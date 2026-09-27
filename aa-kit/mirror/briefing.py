"""
Counterparty Mirror - "Since last time": the household's personal briefing.

    briefing = since_last_time(state, events)

Turns the meaningful Events between two refreshes into at most FIVE lines, in
this priority order:
  1 ATTENTION  clocks that are open (new, changed or still running)
  2 RESOLVED   things the household can stop worrying about
  3 CHANGE     commitment started / amount changed / card superseded / reading paused
  4 DOOR       a protection worth checking (Gate 4) - unless a fact just opened it,
               in which case it is folded into that fact's CHANGE line
  5 QUESTION   new questions only (open questions are not repeated every time)
  6 FACT       answers the household gave that we now remember
  7 LEARNED    a regular collection or credit we can now recognise
Gate 4 + 5 CHANGE lines: one answer and everything it changed across the rules
("Noted: John is 41–50. PMJJBY is worth checking; APY isn't shown ..."),
a purpose switched on or off, and a DPI lookup that failed or was refused.
Then, if there is room, one ROUTINE line about everything NOT already on a card
("4 of 4 other expected collections went through"). On the first look it says
what we are now watching. If nothing needs attention the briefing says so -
silence is a result.

Every line is built from structured events with fixed templates, passes the
language gate, and carries the event ids and card id it came from. No LLM.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta

from .events import Event, State
from .language import gate, inr, dt, months, ordinal, OPTION_LABELS, scheme_copy, LOOKUP_REASON
from .rules import PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG
from .unlock import PROTECTION_FACTS

MAX_LINES = 5
PRIORITY = {"ATTENTION": 1, "RESOLVED": 2, "CHANGE": 3, "DOOR": 4, "QUESTION": 5, "FACT": 6, "LEARNED": 7,
            "ROUTINE": 8}
NOUN = {"LIC_GRACE_CLOCK": "premium", "LOAN_OVERDUE_CLOCK": "instalment"}
CLOCK_NAME = {"LIC_GRACE_CLOCK": "grace-period clock", "LOAN_OVERDUE_CLOCK": "overdue clock"}


@dataclass(frozen=True)
class Line:
    id: str
    kind: str                     # ATTENTION | RESOLVED | CHANGE | DOOR | QUESTION | FACT | LEARNED | ROUTINE
    text: str
    member: str | None
    card_id: str | None
    event_ids: tuple
    basis: str                    # evidence | rule | you_told_us | seen_in_data | rule_implied | pattern
    evidence_classes: tuple
    action: dict | None = None    # {"type": "OPEN_CARD" | "ANSWER_QUESTION", "card_id": ...}


@dataclass(frozen=True)
class Briefing:
    as_of: str
    since: str | None
    lines: tuple
    more: int                     # meaningful items that did not fit in five lines
    silent: bool
    provenance: dict = field(default_factory=dict)


def _who(state: State, account: str) -> str:
    m = next((x for x in state.snapshot.members if x.account == account), None)
    return m.display_name.split()[0] if m else "This account"


def _card(state: State, card_id: str):
    return next((c for c, _ in state.open_cards if c.id == card_id), None)


def _attention(state: State, e: Event) -> tuple | None:
    card = _card(state, e.card_id)
    if card is None or card.type != "CLOCK":
        return None
    s, who = e.data["summary"], _who(state, e.account)
    deadline = date.fromisoformat(card.deadline.date)
    left = (deadline - state.as_of).days
    if card.code == "LIC_GRACE_CLOCK":
        if e.status == "NEW":
            text = (f"{who}: a {inr(s['amount'])} {s['counterparty']} premium was returned on {dt(s['return_date'])}. "
                    f"If it was due that day, the grace period ends around {dt(card.deadline.date)}.")
        elif left >= 0:
            text = (f"{who}: still open — the {s['counterparty']} grace period ends around {dt(card.deadline.date)} "
                    f"if the premium was due on {dt(s['return_date'])} ({left} days left).")
        else:
            text = (f"{who}: still open — if the {s['counterparty']} premium was due on {dt(s['return_date'])}, "
                    f"the grace period would have ended around {dt(card.deadline.date)}.")
    else:
        behind = card.deadline.data["instalments_behind"]
        text = (f"{who}: a {inr(s['amount'])} collection by {s['counterparty']} was returned on {dt(s['return_date'])}. "
                f"If payments go to the oldest instalment first, the loan could still be {behind} "
                f"instalment{'s' if behind != 1 else ''} behind; lenders' next report date is {dt(card.deadline.date)}.")
    return text, {"type": "OPEN_CARD", "card_id": card.id}


def _resolved(state: State, e: Event) -> str:
    return resolved_text(state, e.account, e.data["summary"], e.data["reason"], e.txn_ids)


def resolved_text(state: State, account: str, s: dict, r: str, txn_ids=()) -> str:
    """One wording for a closure, used by the briefing AND the Resolved list."""
    who = _who(state, account)
    cp = s.get("counterparty", "this payment")
    name = CLOCK_NAME.get(s["code"], "card")
    if r == "PAID_PER_CUSTOMER":
        return f"Resolved: you told us {who}'s {cp} {NOUN.get(s['code'], 'payment')} was paid. The {name} is closed."
    if r == "LENDER_SAYS_UP_TO_DATE":
        return f"Resolved: you told us {cp} says {who}'s loan is up to date. The {name} is closed."
    if r == "NOT_THIS_PAYMENT":
        return f"Closed: you told us the payment returned on {dt(s['return_date'])} was not the {cp} one."
    if r == "PAUSE_AGREED":
        return f"Noted: you told us a pause or restructuring was agreed with {cp}."
    if r == "PAID_ANOTHER_WAY":
        return f"Noted: you told us {cp} was paid another way."
    if r == "ENDED":
        return f"Noted: you told us the {cp} collections have ended."
    if r == "COLLECTED_AFTER_RETURN":
        m = next(x for x in state.snapshot.members if x.account == account)
        when = min(t.d for t in m.txns if t.txn_id in txn_ids)
        return (f"Resolved: a {inr(s['amount'])} collection by {cp} went through on {dt(when.isoformat())}. "
                f"The {name} is closed.")
    if r == "NOTHING_IMPLIED_OVERDUE":
        return (f"Looks resolved: {cp}'s collections have caught up. Under RBI's day-end rule, with payments "
                f"applied to the oldest instalment first, nothing would be overdue now.")
    if r == "NO_REFILLS_PER_RECORD":
        sim = " (SIMULATED record)" if s.get("record_mode") == "simulated" else ""
        return (f"Resolved{sim}: the oil company's record shows {who}'s last refill was booked on "
                f"{dt(s['last_booking_date'])}, before the last subsidy credit on {dt(s['last_credit'])}, "
                f"so no subsidy was due since.")
    if r == "ANSWERED":
        return answered_text(who, s)
    raise ValueError(f"no template for resolution {r}")


RESEED = ("To move the subsidy to an account you use, give your Aadhaar number to that bank for DBT "
          "seeding (or use NPCI's BASE service) — transfers go to the bank where it was given last.")
ANSWERED_TEXT = {
    ("LPG_REFILLS", "no_refills"): "Closed: you told us no refills were booked since {last}, so no subsidy was due.",
    ("SUBSIDY_ACCOUNT", "another_account"): "Noted: you told us the subsidy may go to another account. " + RESEED,
    ("SUBSIDY_ACCOUNT", "one_i_connected"): ("Noted: you told us the subsidy should come to an account you "
                                             "connected. If refills continue and nothing arrives, ask your distributor."),
    ("SUBSIDY_ACCOUNT", "not_sure"): ("Noted: you're not sure which account gets the subsidy. Your bank can tell you "
                                      "where your Aadhaar number is linked for government transfers."),
    ("ROUTED_ACCOUNT_STATUS", "mine_in_use"): ("Noted: the account ending {tail} is yours and in use. Connect it (or, "
                                               "if it's already connected, we'll watch it) to see the subsidy arrive."),
    ("ROUTED_ACCOUNT_STATUS", "old_not_in_use"): "Noted: the account ending {tail} is old or not in use. " + RESEED,
    ("ROUTED_ACCOUNT_STATUS", "not_mine"): ("Noted: the account ending {tail} isn't yours. Ask your distributor to "
                                            "correct the bank details on the LPG record, then " + RESEED[0].lower()
                                            + RESEED[1:]),
    ("SUBSIDY_GIVEN_UP", "chose_to"): "Closed: you told us the subsidy was given up by choice.",
    ("SUBSIDY_GIVEN_UP", "did_not"): ("Noted: you didn't choose to give up the subsidy. Your distributor can explain "
                                      "how to restart it."),
    ("SUBSIDY_GIVEN_UP", "not_sure"): "Noted: you're not sure. Your distributor can say whether it was given up.",
    ("DISTRIBUTOR_ANSWER", "says_none_due"): "Closed: you told us the distributor says no subsidy was due.",
    ("DISTRIBUTOR_ANSWER", "says_paid"): ("Noted: the distributor says it was paid, but none arrived in your connected "
                                          "accounts. Your bank can tell you where your Aadhaar number is linked."),
    ("DISTRIBUTOR_ANSWER", "not_asked"): "Noted: you haven't asked yet. The distributor can say whether it was paid.",
}


def answered_text(who: str, s: dict) -> str:
    key = (s["fact"], s["value"])
    sim = "(SIMULATED record) " if s.get("record_mode") == "simulated" else ""
    if key in ANSWERED_TEXT:
        text = ANSWERED_TEXT[key].format(last=dt(s["last_credit"]) if s.get("last_credit") else "then",
                                         tail=s.get("account_tail") or "")
        return (text.replace(": ", ": " + sim, 1) if sim else text)
    label = OPTION_LABELS[s["value"]]
    scheme = f" ({s['scheme']})" if s.get("scheme") else ""
    return f"Noted: you told us {who}: {label}{scheme}."


# ---------- Gate 4: one fact, many rules ----------
def _effect_phrase(who: str, ef: dict) -> str:
    sc = ef["scheme"]
    st = ef["status"]
    if st == "WORTH_CHECKING":
        return f"{sc} is worth checking"
    if st == "NOT_APPLICABLE" and ef.get("reason") == "TAXPAYER":
        return f"{sc} isn't shown (it is closed to income-tax payers)"
    if st == "NOT_APPLICABLE":
        return f"{sc} isn't shown (its age range is {scheme_copy(sc)['ages']})"
    if st == "NEEDS_TAXPAYER":
        return f"{sc} needs one more answer (on the card)"
    if st == "SEEN":
        return f"{sc} is already in {who}'s account"
    if st == "COVERED_ELSEWHERE":
        return f"{sc} is through another account, you said"
    if st == "NOT_ENOUGH_DATA":
        return f"{sc} can't be checked from the data we have"
    return f"{sc}: {st.lower().replace('_', ' ')}"


def fact_text(state: State, e: Event) -> str:
    who = _who(state, e.account)
    d = e.data
    label = OPTION_LABELS[d["value"]]
    if d["code"] == "AGE_BAND":
        head = f"{who} is {label}"
    elif d["code"] == "TAXPAYER":
        head = {"yes": f"{who} is or has been an income-tax payer", "no": f"{who} has never been an income-tax payer",
                "not_sure": f"you're not sure whether {who} has paid income tax"}[d["value"]]
    elif d["code"] == "COVERED_ELSEWHERE":
        head = {"yes": f"{who} already has {d['scheme']} through another account",
                "no": f"{who} doesn't have {d['scheme']} through another account",
                "not_sure": f"you're not sure whether {who} has {d['scheme']} through another account"}[d["value"]]
    elif d["code"] == "LPG_REFILLS":
        head = {"still_booking": "refills are still being booked", "not_sure": "you're not sure about refills",
                "no_refills": "no refills were booked"}[d["value"]]
    else:
        head = f"{who}: {label}"
    if e.kind == "FACT_CORRECTED":
        lead = f"Updated: you told us {head} (before: {OPTION_LABELS[d['old_value']]})."
    else:
        lead = f"Noted: you told us {head}."
    shown = [ef for ef in d.get("effects", []) if d["code"] != "COVERED_ELSEWHERE" or ef["scheme"] == d["scheme"]]
    worth = [ef["scheme"] for ef in shown if ef["status"] == "WORTH_CHECKING"]
    effects = ([f"{' and '.join(worth)} {'are' if len(worth) > 1 else 'is'} worth checking"] if worth else []) + \
        [_effect_phrase(who, ef) for ef in shown if ef["status"] != "WORTH_CHECKING"]
    if d["code"] == "LPG_REFILLS" and d["value"] != "no_refills":
        effects = ["so the subsidy may be going to another account — one more question on the card"]
    return lead + (" " + "; ".join(effects)[0].upper() + "; ".join(effects)[1:] + "." if effects else "")


PURPOSE_TEXT = {
    ("PURPOSE_GRANTED", PURPOSE_GOV_PROTECT): (
        "You switched on 'Check government protections'. We'll look at PMSBY, PMJJBY and APY for each of you and "
        "at LPG subsidy credits — using what's already in your connected accounts and a few short answers."),
    ("PURPOSE_GRANTED", PURPOSE_DPI_LPG): (
        "You switched on the LPG record check. We ask the oil company's record once, through Perfios Hub, and keep "
        "only what the check needs."),
    ("PURPOSE_REVOKED", PURPOSE_GOV_PROTECT): (
        "You switched off 'Check government protections'. We've forgotten the {n} answer{s} it used and stopped "
        "those checks."),
    ("PURPOSE_REVOKED", PURPOSE_DPI_LPG): "You switched off the LPG record check. We've forgotten the record.",
}
SOURCE_REASON = LOOKUP_REASON


def _source_text(state: State, e: Event) -> str | None:
    if e.kind == "SOURCE_CHECKED":
        return None                                  # the card it changed says what the record showed
    who = _who(state, e.account) if e.account else "We"
    sim = " (simulated)" if e.data["mode"] == "simulated" else ""
    why = SOURCE_REASON.get(e.data["reason"], "the record returned an error")
    if e.kind == "SOURCE_CHECK_REFUSED":
        return f"{who}: we didn't check the oil company's LPG record{sim} — {why}."
    return (f"{who}: we tried to check the oil company's LPG record{sim} but couldn't — {why}. "
            f"Nothing has changed; the question stays open.")


def _change(state: State, e: Event) -> str | None:
    who = _who(state, e.account)
    if e.kind == "COMMITMENT_AMOUNT_CHANGED":
        return f"{who}: {e.data['counterparty']} now collects {inr(e.data['new_amount'])} (was {inr(e.data['old_amount'])})."
    if e.kind == "CARD_SUPERSEDED":
        if "return_date" not in e.data["summary"]:
            return None                            # e.g. the LPG question refined by the record: the new card speaks
        succ = _card(state, e.data["superseded_by"])
        cp = next((x.data["counterparty"] for x in succ.evidence if x.code == "COLLECTION_HISTORY"), "a regular")
        return f"{who}: update — the payment returned on {dt(e.data['summary']['return_date'])} now matches the {cp} collection."
    if e.kind == "CARD_WITHDRAWN" and e.data.get("reason") == "WAITING_ON_ANSWER":
        return (f"{who}: we've paused our reading of the {e.data['summary']['counterparty']} loan until you "
                f"tell us about the missing collections.")
    return None                    # other withdrawals stay in the audit trail, not the briefing


def _learned(state: State, e: Event) -> str | None:
    who = _who(state, e.account)
    if e.kind == "COMMITMENT_RECOGNISED":
        return (f"{who}: we now recognise a regular collection — {e.data['counterparty']} takes about "
                f"{inr(e.data['amount'])} around the {ordinal(e.data['usual_day'])} ({e.data['cadence'].lower()}).")
    if e.kind == "REGULAR_CREDIT_RECOGNISED":
        return f"{who}: we now recognise a regular monthly credit ('{e.data['signature']}')."
    return None


ROUTING_LINE = {
    "ELSEWHERE": "says the subsidy goes to an account ending {tail} that you haven't connected. Is it yours?",
    "NOT_SHOWN": "shows refills after the last subsidy credit but not which account gets the subsidy. Do you know?",
    "GIVEN_UP": "says the subsidy on this connection was given up. Was that your choice?",
    "SAME": "names an account ending {tail} (the same last 4 digits as your connected account), but no subsidy "
            "has arrived there since. What does your distributor say?",
    "OTHER_MEMBER": "names an account ending {tail}, the same last 4 digits as another member's connected account. "
                    "Is it yours?",
}


def _question(state: State, e: Event) -> tuple | None:
    card = _card(state, e.card_id)
    if card is None or card.type != "QUESTION":
        return None
    s, who = e.data["summary"], _who(state, e.account)
    if card.code == "AGE_BAND_QUESTION":
        schemes = [x.data["scheme"] for x in card.evidence if x.code == "SCHEME_RULE"]
        text = (f"{who}: which age band is {who} in? It settles the checks for "
                f"{' and '.join(schemes) if len(schemes) < 3 else ', '.join(schemes[:-1]) + ' and ' + schemes[-1]}.")
    elif card.code == "TAXPAYER_QUESTION":
        text = f"{who}: one more question for APY — has {who} ever been an income-tax payer?"
    elif card.code == "LPG_SUBSIDY_QUESTION":
        text = (f"{who}: LPG subsidy credits from {s['counterparty']} stopped after {dt(s['last_credit'])}. "
                f"Have refills been booked since?")
    elif card.code == "LPG_SUBSIDY_ROUTING":
        sim = " (SIMULATED)" if s.get("record_mode") == "simulated" else ""
        text = (f"{who}: the oil company's record{sim} "
                + ROUTING_LINE[card.provenance["finding"]].format(tail=s.get("account_tail") or ""))
    elif card.code == "COLLECTION_GAP_QUESTION":
        text = f"{who}: {s['counterparty']} didn't collect in {months(s['periods'])} and there was no return charge. Do you know why?"
    elif "counterparty" in s:
        text = f"{who}: a payment was returned on {dt(s['return_date'])} — was it the {s['counterparty']} collection?"
    else:
        text = f"{who}: a payment was returned on {dt(s['return_date'])}. Which payment was it?"
    return text, {"type": "ANSWER_QUESTION", "card_id": card.id}


FACT_TEXT = {
    "it_was_this_premium": "Noted: you confirmed the returned payment was {who}'s {cp} premium.",
    "due_date_differs": "Noted: {who}'s {cp} due date is different — we'll ask you for it.",
    "yes_that_payment": "Noted: you confirmed the returned payment was the {cp} collection.",
    "not_sure": "Noted: you're not sure yet — we'll keep watching {cp}.",
    "not_sure_yet": "Noted: you're not sure yet — we'll keep watching {cp}.",
}


def routine_tally(state: State, since: date | None) -> dict:
    """Expected collections in the window that went through - EXCLUDING anything already on
    an open or recently closed card (those are covered by their own lines) - and regular
    credits that arrived."""
    start = since or (state.as_of - timedelta(days=30))
    on_cards = {c.subject for c, _ in state.open_cards} | {cl.subject for cl in state.closed}
    seen = expected = excluded = 0
    arrivals = []
    for m in state.snapshot.members:
        if m.quality != "OK":
            continue
        by_id = {t.txn_id: t for t in m.txns}
        for ob in m.obligations:
            if ob.id in on_cards:
                excluded += 1
                continue
            for o in ob.occurrences:
                if o.status not in ("SEEN", "NOT_SEEN"):
                    continue
                y, mo = int(o.period[:4]), int(o.period[5:7])
                day = o.day if o.status == "SEEN" else ob.day_window[0]
                d = date(y, mo, min(day, 28))
                if start < d <= min(state.as_of, m.data_until):
                    expected += 1
                    seen += o.status == "SEEN"
        for s in m.income:
            hits = [by_id[i].d for i in s.txn_ids if i in by_id and start < by_id[i].d <= state.as_of]
            if hits:
                arrivals.append((m.display_name.split()[0], s.signature, max(hits)))
    return {"from": start.isoformat(), "to": state.as_of.isoformat(), "expected": expected,
            "went_through": seen, "excluded_on_cards": excluded, "credit_arrivals": arrivals}


def _routine_text(t: dict) -> str | None:
    parts = []
    if t["expected"]:
        other = "other " if t["excluded_on_cards"] else ""
        parts.append(f"{t['went_through']} of {t['expected']} {other}expected collection"
                     f"{'s' if t['expected'] != 1 else ''} went through")
    for who, sig, when in t["credit_arrivals"][:1]:
        parts.append(f"{who}'s regular '{sig}' credit arrived on {dt(when.isoformat())}")
    return (", and ".join(parts) + ".") if parts else None


def _first_look(state: State) -> str:
    ok = [m for m in state.snapshot.members if m.quality == "OK"]
    n_c = sum(len(m.obligations) for m in ok)
    n_i = sum(len(m.income) for m in ok)
    return (f"First look: we're now watching {n_c} regular collection{'s' if n_c != 1 else ''} and "
            f"{n_i} regular credit{'s' if n_i != 1 else ''} across {len(ok)} account{'s' if len(ok) != 1 else ''}.")


def since_last_time(state: State, events: list) -> Briefing:
    since = state.since
    candidates = []                                   # (kind, sort_key, text, event, action)
    closed_by_answer = {e.card_id for e in events if e.kind == "CARD_RESOLVED" and e.data.get("reason") == "ANSWERED"}
    for e in events:
        if e.kind in ("CARD_OPENED", "CARD_REOPENED", "CARD_CHANGED", "CARD_CONTINUING"):
            a = _attention(state, e)
            if a:
                card = _card(state, e.card_id)
                candidates.append(("ATTENTION", card.deadline.date, a[0], e, a[1]))
                continue
            if e.data.get("caused_by_fact"):
                continue                                   # said once, in that fact's CHANGE line
            if e.kind in ("CARD_OPENED", "CARD_REOPENED"):
                card = _card(state, e.card_id)
                if card is not None and card.type == "DOOR":
                    sc = e.data["summary"]["scheme"]
                    candidates.append(("DOOR", e.card_id, f"{_who(state, e.account)}: {sc} "
                                       f"({scheme_copy(sc)['kind'].lower()}) is worth checking.", e,
                                       {"type": "OPEN_CARD", "card_id": e.card_id}))
                    continue
                q = _question(state, e)
                if q:
                    candidates.append(("QUESTION", e.card_id, q[0], e, q[1]))
        elif e.kind == "CARD_RESOLVED":
            if e.data.get("reason") == "ANSWERED" and e.data.get("fact") in PROTECTION_FACTS:
                continue                                   # the FACT line says it, with its effects
            candidates.append(("RESOLVED", e.card_id, _resolved(state, e), e, None))
        elif e.kind in ("FACT_CONFIRMED", "FACT_CORRECTED"):
            if e.data["code"] not in PROTECTION_FACTS and e.data.get("via_card") in closed_by_answer:
                continue                                   # the RESOLVED line says it
            candidates.append(("CHANGE", e.subject, fact_text(state, e), e, None))
        elif e.kind in ("PURPOSE_GRANTED", "PURPOSE_REVOKED"):
            n = e.data.get("forgot_answers", 0)
            candidates.append(("CHANGE", e.subject, PURPOSE_TEXT[(e.kind, e.subject)].format(
                n=n, s="" if n == 1 else "s"), e, None))
        elif e.kind.startswith("SOURCE_CHECK"):
            t = _source_text(state, e)
            if t:
                candidates.append(("CHANGE", e.subject, t, e, None))
        elif e.kind == "CARD_WITHDRAWN" and e.data.get("reason") in ("PURPOSE_OFF", "FACT_CHANGED"):
            continue                                       # folded into the purpose / fact line
        elif e.kind == "QUESTION_ANSWERED":
            s = e.data["summary"]
            candidates.append(("FACT", e.card_id, FACT_TEXT[e.data["option"]].format(
                who=_who(state, e.account), cp=s.get("counterparty", "this payment")), e, None))
        elif e.kind in ("COMMITMENT_RECOGNISED", "REGULAR_CREDIT_RECOGNISED"):
            candidates.append(("LEARNED", e.subject, _learned(state, e), e, None))
        else:
            t = _change(state, e)
            if t:
                candidates.append(("CHANGE", e.subject, t, e, None))

    candidates.sort(key=lambda c: (PRIORITY[c[0]], str(c[1]), c[3].id))
    chosen, more = candidates[:MAX_LINES], max(0, len(candidates) - MAX_LINES)
    lines = [Line(f"L{i}", kind, gate(text), _who(state, e.account), e.card_id, (e.id,), e.basis,
                  e.evidence_classes, action)
             for i, (kind, _, text, e, action) in enumerate(chosen, start=1)]

    tally = routine_tally(state, since)
    routine = _routine_text(tally) if since else _first_look(state)
    silent = not lines
    if silent:
        text = "Nothing needs you." + (f" {routine[0].upper()}{routine[1:]}" if routine else "")
        lines.append(Line("L1", "ROUTINE", gate(text), None, None, (), "evidence", ("O",)))
    elif routine and len(lines) < MAX_LINES:
        text = f"Everything else: {routine}" if since else routine
        lines.append(Line(f"L{len(lines) + 1}", "ROUTINE", gate(text), None, None, (), "evidence", ("O",)))

    snap = state.snapshot
    return Briefing(state.as_of.isoformat(), since.isoformat() if since else None, tuple(lines), more,
                    silent, {"corpus_sha256": snap.corpus_sha256, "rulebook_version": snap.rulebook_version,
                             "engine": snap.engine, "event_ids": [e.id for e in events],
                             "routine_window": {k: tally[k] for k in ("from", "to", "expected", "went_through")}})
