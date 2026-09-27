"""
Counterparty Mirror - Unlock evaluator (Gate 4) + the LPG record's entry point (Gate 5).

    result = evaluate_unlock(snapshot, facts, records)

The same pattern as the Protect evaluator, over the state's rulebook:

    observed scheme rows (O)  x  STATE_RULES (R)  x  what the customer told us (U, answered)
        -> DOOR | SUPPRESSION | QUESTION        (+ a status per member x scheme)

Scope, deliberately narrow: PMSBY, PMJJBY, APY (doors), PMUY (suppression only),
PAHAL/APB (the LPG subsidy question, which the oil company's record can refine).
No scheme directory, no scores, no "eligible". A door says "worth checking" and
names what we saw, what the published rule says, and what only the bank decides.

Evidence discipline:
  * a scheme debit in a connected account is O (txn ids);
  * NOT seeing one is O only as an ABSENCE inside that account's data window, and
    only if the window is long enough to have shown it (a whole cover year for
    PMSBY/PMJJBY, six months for APY). It is never "not enrolled": every door
    also carries the open or answered unknowable "covered through another account";
  * age band / taxpayer / covered-elsewhere are the customer's answers: U, answered.
    They gate rules; they are never asserted and nothing is inferred from them;
  * the LPG record is O about the oil company's record - with its mode (live or
    SIMULATED) on the evidence and on the card.

One answer, many rules: an AGE_BAND fact is read by every scheme rule that has an
age limit, in the same pass. events.py reports the combined effect as one line.
Runs only under PURPOSE_GOV_PROTECT; the LPG record also needs PURPOSE_DPI_LPG.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta

from .cards import Card, Evidence as E, Question, card_id
from .facts import FACTS, lookup, band_in_range
from .rules import (STATE_RULES, RULEBOOK_VERSION, PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG, rule_ref)
from .snapshot import Snapshot, OMC_PAYERS
from .sources.lpg import SOURCE_LABEL

ENGINE = "mirror-unlock-1"
DOOR_SCHEMES = ("PMSBY", "PMJJBY", "APY")
PROTECTION_FACTS = ("AGE_BAND", "TAXPAYER", "COVERED_ELSEWHERE")
LPG_CODES = ("LPG_SUBSIDY_QUESTION", "LPG_SUBSIDY_ROUTING")
UNLOCK_CODES = ("AGE_BAND_QUESTION", "TAXPAYER_QUESTION", "PROTECTION_DOOR", "PROTECTION_NOT_SHOWN",
                "PMUY_NOT_SHOWN") + LPG_CODES
# which card may replace which, for the same subject, when the evidence gets sharper
REFINES = {"LPG_SUBSIDY_QUESTION": ("LPG_SUBSIDY_ROUTING",), "LPG_SUBSIDY_ROUTING": ("LPG_SUBSIDY_QUESTION",)}
ROUTING_FACT = {"ELSEWHERE": "ROUTED_ACCOUNT_STATUS", "OTHER_MEMBER": "ROUTED_ACCOUNT_STATUS",
                "NOT_SHOWN": "SUBSIDY_ACCOUNT", "SAME": "DISTRIBUTOR_ANSWER", "GIVEN_UP": "SUBSIDY_GIVEN_UP"}
# Product policy (ours, not published): how much data must be in view before "we don't see it" is said.
# PMSBY/PMJJBY renew by auto-debit around the 1 June cover-year start, so the window must hold a whole
# renewal season; APY can be paid half-yearly, so the window must be longer than six months.
RENEWAL_SEASON = ((5, 1), (6, 30))
APY_MIN_WINDOW_DAYS = 190


@dataclass(frozen=True)
class UnlockResult:
    cards: tuple
    status: tuple          # one dict per member x scheme (and one for LPG), for OUR HOUSEHOLD
    resolutions: tuple     # (card_code, subject, basis, reason, record_id) the record settles


# ---------- helpers ----------
def _prov(snap: Snapshot, account: str, simulated: bool = False, **extra) -> dict:
    p = {"source": "AA (ACME-FIP sandbox) + your answers", "account": account,
         "corpus_sha256": snap.corpus_sha256, "rulebook_version": RULEBOOK_VERSION, "engine": ENGINE,
         "as_of": snap.as_of.isoformat(), "purpose": PURPOSE_GOV_PROTECT}
    if simulated:
        p["simulated"] = True
    p.update(extra)
    return p


def _window_covers(m, scheme: str) -> bool:
    """Long enough to have SEEN the scheme if it were paid from this account."""
    lo, hi = m.data_from, m.data_until
    if not lo or not hi or hi < lo:
        return False
    if scheme == "APY":
        return (hi - lo).days >= APY_MIN_WINDOW_DAYS
    (m0, d0), (m1, d1) = RENEWAL_SEASON
    return any(lo <= date(y, m0, d0) and date(y, m1, d1) <= hi for y in range(lo.year, hi.year + 1))


def _absence(m, scheme: str) -> dict:
    return {"scheme": scheme, "accounts": [m.account],
            "absence": {"from": m.data_from.isoformat(), "to": m.data_until.isoformat(),
                        "account_data_until": m.data_until.isoformat()}}


def _answered(eid: str, f, **data) -> E:
    return E(eid, "U", f.code, {"fact": f.code, "account": f.account, "scheme": f.scheme,
                                "answered": f.value, "stated_on": f.stated_on.isoformat(), **data},
             resolved_by=f"fact:{f.id}")


def _open(eid: str, code: str, account: str, scheme=None) -> E:
    return E(eid, "U", code, {"fact": code, "account": account, "scheme": scheme}, resolved_by="q")


def _rule_ev(eid: str, scheme: str) -> E:
    p = STATE_RULES[scheme]["params"]
    return E(eid, "R", "SCHEME_RULE", {"scheme": scheme, "age_min": p.get("age_min"), "age_max": p.get("age_max")},
             rule=rule_ref(scheme))


def _seen_rows(m, scheme: str) -> list:
    return [r for r in m.protections if r["marker"] == scheme and r["direction"] == "DEBIT"]


# ---------- protection status per member x scheme ----------
def _scheme_status(m, scheme: str, facts) -> dict:
    p = STATE_RULES[scheme]["params"]
    base = {"account": m.account, "member": m.display_name.split()[0], "scheme": scheme,
            "rule": rule_ref(scheme), "facts_used": [], "txn_ids": []}
    seen = _seen_rows(m, scheme)
    if seen:
        return {**base, "status": "SEEN", "evidence_class": "O", "txn_ids": [r["txn_id"] for r in seen],
                "last_seen": seen[-1]["date"]}
    if not _window_covers(m, scheme):
        return {**base, "status": "NOT_ENOUGH_DATA", "evidence_class": "O"}
    age = lookup(facts, m.account, "AGE_BAND")
    if age is None:
        return {**base, "status": "NEEDS_AGE", "evidence_class": "U"}
    base["facts_used"].append(age.id)
    inside = band_in_range(age.value, p["age_min"], p["age_max"])
    if inside is not True:
        return {**base, "status": "NOT_APPLICABLE", "reason": "AGE", "evidence_class": "R"}
    if scheme == "APY":
        tax = lookup(facts, m.account, "TAXPAYER")
        if tax is None:
            return {**base, "status": "NEEDS_TAXPAYER", "evidence_class": "U"}
        base["facts_used"].append(tax.id)
        if tax.value == "yes":
            return {**base, "status": "NOT_APPLICABLE", "reason": "TAXPAYER", "evidence_class": "R"}
    cov = lookup(facts, m.account, "COVERED_ELSEWHERE", scheme)
    if cov is not None:
        base["facts_used"].append(cov.id)
        if cov.value == "yes":
            return {**base, "status": "COVERED_ELSEWHERE", "evidence_class": "U"}
    return {**base, "status": "WORTH_CHECKING", "evidence_class": "R"}


# ---------- cards ----------
def _age_question(snap, m, needing: list, statuses: dict) -> Card:
    ev = []
    for s in DOOR_SCHEMES:
        st = statuses[s]
        if st["status"] == "SEEN":
            ev.append(E(f"e_seen_{s}", "O", "SCHEME_DEBIT_SEEN", {"scheme": s}, txn_ids=tuple(st["txn_ids"])))
        elif s in needing:
            ev.append(E(f"e_ns_{s}", "O", "SCHEME_DEBIT_NOT_SEEN", _absence(m, s)))
        if s in needing:
            ev.append(_rule_ev(f"e_rule_{s}", s))
    ev.append(_open("e_age", "AGE_BAND", m.account))
    return Card(
        id=card_id("AGE_BAND_QUESTION", f"{m.account}:AGE_BAND", ""), type="QUESTION", code="AGE_BAND_QUESTION",
        member=m.display_name, account=m.account, subject=f"{m.account}:AGE_BAND", as_of=snap.as_of.isoformat(),
        evidence=tuple(ev), claim=tuple(e.id for e in ev if e.cls in ("O", "R")), provenance=_prov(snap, m.account),
        question=Question("q", "AGE_BAND", tuple(FACTS["AGE_BAND"]["values"]), resolves=("e_age",)))


def _taxpayer_question(snap, m, facts) -> Card:
    age = lookup(facts, m.account, "AGE_BAND")
    ev = (E("e_ns", "O", "SCHEME_DEBIT_NOT_SEEN", _absence(m, "APY")), _rule_ev("e_rule", "APY"),
          _answered("e_age", age), _open("e_tax", "TAXPAYER", m.account))
    return Card(
        id=card_id("TAXPAYER_QUESTION", f"{m.account}:TAXPAYER", ""), type="QUESTION", code="TAXPAYER_QUESTION",
        member=m.display_name, account=m.account, subject=f"{m.account}:TAXPAYER", as_of=snap.as_of.isoformat(),
        evidence=ev, claim=("e_ns", "e_rule"), provenance=_prov(snap, m.account),
        question=Question("q", "TAXPAYER", tuple(FACTS["TAXPAYER"]["values"]), resolves=("e_tax",)))


def _door(snap, m, scheme: str, facts) -> Card:
    ev = [E("e_ns", "O", "SCHEME_DEBIT_NOT_SEEN", _absence(m, scheme)), _rule_ev("e_rule", scheme),
          _answered("e_age", lookup(facts, m.account, "AGE_BAND"))]
    if scheme == "APY":
        ev.append(_answered("e_tax", lookup(facts, m.account, "TAXPAYER")))
    cov = lookup(facts, m.account, "COVERED_ELSEWHERE", scheme)
    ev.append(_answered("e_cov", cov) if cov else _open("e_cov", "COVERED_ELSEWHERE", m.account, scheme))
    return Card(
        id=card_id("PROTECTION_DOOR", f"{m.account}:{scheme}", ""), type="DOOR", code="PROTECTION_DOOR",
        member=m.display_name, account=m.account, subject=f"{m.account}:{scheme}", as_of=snap.as_of.isoformat(),
        evidence=tuple(ev), claim=("e_ns", "e_rule"), provenance=_prov(snap, m.account),
        action="ENROL_THROUGH_BANK",
        question=None if cov else Question("q", "COVERED_ELSEWHERE", tuple(FACTS["COVERED_ELSEWHERE"]["values"]),
                                           resolves=("e_cov",)))


def _not_shown(snap, m, scheme: str, reason: str, facts) -> Card:
    ev = [_rule_ev("e_rule", scheme), _answered("e_age", lookup(facts, m.account, "AGE_BAND"), reason=reason)]
    if reason == "TAXPAYER":
        ev.append(_answered("e_tax", lookup(facts, m.account, "TAXPAYER")))
    return Card(
        id=card_id("PROTECTION_NOT_SHOWN", f"{m.account}:{scheme}", ""), type="SUPPRESSION",
        code="PROTECTION_NOT_SHOWN", member=m.display_name, account=m.account, subject=f"{m.account}:{scheme}",
        as_of=snap.as_of.isoformat(), evidence=tuple(ev), claim=("e_rule",), provenance=_prov(snap, m.account))


# ---------- LPG subsidy (PAHAL) ----------
def lpg_signal(m) -> dict | None:
    """A run of oil-company subsidy credits (APBS/IOC|HPCL|BPCL) and whether it has stopped."""
    rows = [r for r in m.protections if r["marker"] == "APBS" and r["direction"] == "CREDIT" and r.get("payer")]
    p = STATE_RULES["PAHAL_DBTL"]["params"]
    if len(rows) < p["min_credits_seen"] or m.data_until is None:
        return None
    ds = [date.fromisoformat(r["date"]) for r in rows]
    biggest_gap = max((b - a).days for a, b in zip(ds, ds[1:]))
    quiet = (m.data_until - ds[-1]).days
    threshold = max(p["stopped_after_days_min"], p["stopped_after_gap_multiple"] * biggest_gap)
    payer = rows[-1]["payer"]
    return {"payer": payer, "payer_label": OMC_PAYERS[payer], "count": len(rows), "first": ds[0].isoformat(),
            "last": ds[-1].isoformat(), "txn_ids": [r["txn_id"] for r in rows],
            "amount_low": min(r["amount"] for r in rows), "amount_high": max(r["amount"] for r in rows),
            "biggest_gap_days": biggest_gap, "quiet_days": quiet, "stopped": quiet > threshold,
            "threshold_days": threshold}


def _latest_record(records, account):
    mine = [r for r in records if r.account == account]
    return max(mine, key=lambda r: (r.requested_on, r.id)) if mine else None


def _record_ev(eid: str, rec) -> E:
    f = rec.fields
    return E(eid, "O", "LPG_RECORD", {
        "record": {"source": rec.source, "record_id": rec.id, "mode": rec.mode, "request_ref": rec.request_ref,
                   "requested_on": rec.requested_on.isoformat(), "join": rec.join},
        "last_booking_date": f.get("last_booking_date"), "subsidised_refills": f.get("subsidised_refills"),
        "given_up_subsidy": f.get("given_up_subsidy"), "account_tail": f.get("account_tail"),
        "bank_name": f.get("bank_name"), "connection_status": f.get("connection_status")})


def _lpg_cards(snap, m, sig, facts, records, other_tails) -> tuple:
    """-> (cards, status, resolutions)."""
    base_ev = [E("e_credits", "O", "SUBSIDY_CREDITS_SEEN",
                 {k: sig[k] for k in ("payer", "payer_label", "count", "first", "last", "amount_low", "amount_high")},
                 txn_ids=tuple(sig["txn_ids"])),
               E("e_none", "O", "NO_SUBSIDY_CREDIT_SINCE",
                 {"absence": {"from": (date.fromisoformat(sig["last"]) + timedelta(days=1)).isoformat(),
                              "to": m.data_until.isoformat(), "account_data_until": m.data_until.isoformat()},
                  "quiet_days": sig["quiet_days"], "biggest_gap_days": sig["biggest_gap_days"]}),
               E("e_rule", "R", "SUBSIDY_TO_BANK_ACCOUNT", {}, rule=rule_ref("PAHAL_DBTL")),
               E("e_map", "R", "APB_LAST_SEEDED_BANK", {}, rule=rule_ref("APB_MAPPER"))]
    subject, anchor = f"{m.account}:PAHAL", sig["last"]
    status = {"account": m.account, "member": m.display_name.split()[0], "scheme": "PAHAL",
              "rule": rule_ref("PAHAL_DBTL"), "txn_ids": sig["txn_ids"], "facts_used": [], "signal": sig}
    rec = _latest_record(records, m.account)
    lookup_note = None
    if rec is not None and not rec.ok:
        lookup_note = {"status": rec.status, "reason": rec.reason, "on": rec.requested_on.isoformat(),
                       "mode": rec.mode, "record_id": rec.id}
    usable = rec is not None and rec.ok and rec.fields.get("last_booking_date")
    if usable:
        sim = rec.mode == "simulated"
        booked = date.fromisoformat(rec.fields["last_booking_date"])
        if booked <= date.fromisoformat(sig["last"]):
            return (), {**status, "status": "NO_REFILLS_PER_RECORD", "evidence_class": "O", "record": rec.id,
                        "simulated": sim}, \
                ((("LPG_SUBSIDY_QUESTION", "LPG_SUBSIDY_ROUTING"), subject, "source_record",
                  "NO_REFILLS_PER_RECORD", rec.id),)
        f = rec.fields
        tail = f.get("account_tail")
        # last-4 digits only: a match says "same last 4 digits", never "the same account"
        finding = ("GIVEN_UP" if f.get("given_up_subsidy") else "NOT_SHOWN" if not tail
                   else "SAME" if tail == m.account[-4:] else "OTHER_MEMBER" if tail in other_tails
                   else "ELSEWHERE")
        fact_code = ROUTING_FACT[finding]
        ans = lookup(facts, m.account, fact_code)
        if ans is not None:
            return (), {**status, "status": "ANSWERED", "finding": finding, "evidence_class": "U",
                        "facts_used": [ans.id], "record": rec.id, "simulated": sim}, ()
        ev = base_ev + [_record_ev("e_rec", rec),
                        E("e_after", "I", "REFILLS_AFTER_LAST_CREDIT", {"booked": f["last_booking_date"],
                                                                        "last_credit": sig["last"]},
                          based_on=("e_rec", "e_credits")),
                        E("e_find", "I", "ROUTING_FINDING", {"finding": finding, "own_tail": m.account[-4:],
                                                             "other_member": other_tails.get(tail)},
                          based_on=("e_rec", "e_none")),
                        _open("e_q", fact_code, m.account)]
        card = Card(
            id=card_id("LPG_SUBSIDY_ROUTING", subject, anchor), type="QUESTION", code="LPG_SUBSIDY_ROUTING",
            member=m.display_name, account=m.account, subject=subject, as_of=snap.as_of.isoformat(),
            evidence=tuple(ev), claim=("e_credits", "e_none", "e_rec", "e_after", "e_find"),
            provenance=_prov(snap, m.account, simulated=sim, purpose_dpi=PURPOSE_DPI_LPG,
                             join=rec.join, finding=finding),
            action="RESEED_OR_ASK_DISTRIBUTOR",
            question=Question("q", fact_code, tuple(FACTS[fact_code]["values"]), resolves=("e_q",)))
        return (card,), {**status, "status": "RECORD_" + finding, "evidence_class": "O", "record": rec.id,
                         "simulated": sim}, ()
    # no usable record: ask the household
    refills = lookup(facts, m.account, "LPG_REFILLS")
    if refills is not None and refills.value == "no_refills":
        return (), {**status, "status": "ANSWERED", "evidence_class": "U", "facts_used": [refills.id]}, ()
    ev = list(base_ev)
    question = Question("q", "LPG_REFILLS", tuple(FACTS["LPG_REFILLS"]["values"]), resolves=("e_refills",))
    if refills is None:
        ev.append(_open("e_refills", "LPG_REFILLS", m.account))
    else:
        acc = lookup(facts, m.account, "SUBSIDY_ACCOUNT")
        if acc is not None:
            return (), {**status, "status": "ANSWERED", "evidence_class": "U",
                        "facts_used": [refills.id, acc.id]}, ()
        ev += [_answered("e_refills", refills), _open("e_account", "SUBSIDY_ACCOUNT", m.account)]
        question = Question("q", "SUBSIDY_ACCOUNT", tuple(FACTS["SUBSIDY_ACCOUNT"]["values"]), resolves=("e_account",))
    extra = {"purpose_dpi": PURPOSE_DPI_LPG}
    if lookup_note:
        extra["dpi_lookup"] = lookup_note
    card = Card(
        id=card_id("LPG_SUBSIDY_QUESTION", subject, anchor), type="QUESTION", code="LPG_SUBSIDY_QUESTION",
        member=m.display_name, account=m.account, subject=subject, as_of=snap.as_of.isoformat(),
        evidence=tuple(ev), claim=("e_credits", "e_none", "e_rule", "e_map"),
        provenance=_prov(snap, m.account, **extra), action="CHECK_LPG_RECORD", question=question)
    return (card,), {**status, "status": "ASKING" + ("_AFTER_FAILED_LOOKUP" if lookup_note else ""),
                     "evidence_class": "U", "lookup": lookup_note}, ()


def _pmuy(snap, m, sig) -> Card:
    ev = (E("e_credits", "O", "SUBSIDY_CREDITS_SEEN",
            {k: sig[k] for k in ("payer", "payer_label", "count", "first", "last")}, txn_ids=tuple(sig["txn_ids"])),
          E("e_conn", "I", "HOUSEHOLD_HAS_LPG_CONNECTION", {}, based_on=("e_credits",)),
          E("e_rule", "R", "SCHEME_RULE", {"scheme": "PMUY"}, rule=rule_ref("PMUY")))
    return Card(
        id=card_id("PMUY_NOT_SHOWN", f"{snap.household_id}:PMUY", ""), type="SUPPRESSION", code="PMUY_NOT_SHOWN",
        member=m.display_name, account=m.account, subject=f"{snap.household_id}:PMUY", as_of=snap.as_of.isoformat(),
        evidence=ev, claim=("e_credits", "e_conn", "e_rule"), provenance=_prov(snap, m.account))


# ---------- entry point ----------
def evaluate_unlock(snap: Snapshot, facts: tuple = (), records: tuple = ()) -> UnlockResult:
    if PURPOSE_GOV_PROTECT not in snap.purposes:
        return UnlockResult((), (), ())
    if PURPOSE_DPI_LPG not in snap.purposes:
        records = ()
    cards, status, resolutions = [], [], []
    tails = {x.account[-4:]: x.display_name.split()[0] for x in snap.members}
    pmuy_done = False
    for m in snap.members:
        if m.quality != "OK":
            continue
        statuses = {s: _scheme_status(m, s, facts) for s in DOOR_SCHEMES}
        status.extend(statuses.values())
        needing = [s for s, st in statuses.items() if st["status"] == "NEEDS_AGE"]
        if needing:
            cards.append(_age_question(snap, m, needing, statuses))
        for s, st in statuses.items():
            if st["status"] == "NEEDS_TAXPAYER":
                cards.append(_taxpayer_question(snap, m, facts))
            elif st["status"] == "WORTH_CHECKING":
                cards.append(_door(snap, m, s, facts))
            elif st["status"] == "NOT_APPLICABLE":
                cards.append(_not_shown(snap, m, s, st["reason"], facts))
        sig = lpg_signal(m)
        if sig:
            if not pmuy_done:
                cards.append(_pmuy(snap, m, sig))
                status.append({"account": m.account, "member": m.display_name.split()[0], "scheme": "PMUY",
                               "status": "NOT_SHOWN_HAS_LPG", "evidence_class": "I", "rule": rule_ref("PMUY"),
                               "txn_ids": sig["txn_ids"], "facts_used": []})
                pmuy_done = True
            if sig["stopped"]:
                others = {t: who for t, who in tails.items() if t != m.account[-4:]}
                c, st, res = _lpg_cards(snap, m, sig, facts, records, others)
                cards.extend(c)
                status.append(st)
                resolutions.extend(res)
            else:
                status.append({"account": m.account, "member": m.display_name.split()[0], "scheme": "PAHAL",
                               "status": "ARRIVING", "evidence_class": "O", "rule": rule_ref("PAHAL_DBTL"),
                               "txn_ids": sig["txn_ids"], "facts_used": [], "signal": sig})
    return UnlockResult(tuple(cards), tuple(status), tuple(resolutions))


def cure(card: Card, result: UnlockResult):
    """The record settles a vanished LPG card: (basis, reason, evidence refs) or None."""
    for codes, subject, basis, reason, rec_id in result.resolutions:
        if card.code in codes and card.subject == subject:
            return basis, reason, (rec_id,)
    return None


def fact_source_label(mode: str) -> str:
    return f"{SOURCE_LABEL}{' — SIMULATED' if mode == 'simulated' else ''}"
