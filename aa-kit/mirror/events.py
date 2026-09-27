"""
Counterparty Mirror - Time axis: household State + meaningful Events.

    state1, events1 = advance(initial(), snapshot_28aug, answers)
    state2, events2 = advance(state1,   snapshot_07sep, answers)

A State is what the household should see at one as_of date: open cards,
closed cards (with how and why they closed), and facts the customer told us.
advance() compares the previous State with a new Snapshot and emits Events
only for MEANINGFUL changes in evaluated state - never one per transaction.

Every event has a status:
  NEW         something appeared            (card opened, commitment started)
  CONTINUING  still true, nothing material changed
  CHANGED     still there, but different    (amount changed, question answered, superseded)
  RESOLVED    watched, and now over         (customer told us / seen in data / rule-implied)
  WITHDRAWN   no longer shown, NOT resolved (evidence changed; we say so, never "resolved")

How a card closes - the 'basis', which the app must show honestly:
  you_told_us   a resolving answer from the customer (a statement, not an observation)
  seen_in_data  a collection for the same payee/amount went through after the return (O)
  rule_implied  the published rule, under the card's stated assumptions, no longer
                implies anything overdue (I)
  source_record the oil company's record (via Perfios Hub) settles it - live or
                SIMULATED, and the app must say which
A card whose evidence simply disappears is WITHDRAWN, never RESOLVED.

Gate 4 + 5 (Unlock and the DPI record) run inside the same transition:
  * answers to Unlock questions become household FACTS (facts.py): the
    customer's statements, class U, scoped to the government-protections purpose;
  * the Unlock evaluator re-reads every rule a fact feeds, in the same pass, and
    one FACT_CONFIRMED / FACT_CORRECTED event carries the combined effect;
  * a DPI record (the LPG record) enters as `records`, is logged in the access
    log whatever its outcome, and can refine or settle the LPG question;
  * switching a purpose off forgets the facts, records and closures it produced.

Replay-safe: every decision uses only the snapshot at as_of and answers dated on
or before as_of. No system clock. Nothing is written to disk (persistence: Batch 1c).
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from datetime import date

from .cards import Card
from .evaluate import _implied_overdue
from .facts import FACTS, FactStatement, apply as apply_facts
from .learn import obligation_key
from .rules import PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG
from .snapshot import Snapshot
from .unlock import evaluate_unlock, cure as unlock_cure, UNLOCK_CODES, REFINES, fact_source_label

# Which answers close a card, and how (product policy, not a published rule).
# None = the answer is recorded as a fact but the card stays open.
RESOLUTIONS = {
    "LIC_RETURN_CONFIRM": {"already_paid": "PAID_PER_CUSTOMER", "not_this_policy": "NOT_THIS_PAYMENT",
                           "it_was_this_premium": None, "due_date_differs": None},
    "LOAN_STATUS_CHECK": {"paid_extra_instalment": "PAID_PER_CUSTOMER",
                          "lender_says_up_to_date": "LENDER_SAYS_UP_TO_DATE", "not_sure_yet": None},
    "RETURN_LINK_CONFIRM": {"something_else": "NOT_THIS_PAYMENT", "yes_that_payment": None, "not_sure": None},
    "GAP_REASON": {"agreed_pause_or_restructure": "PAUSE_AGREED", "paid_another_way": "PAID_ANOTHER_WAY",
                   "it_has_ended": "ENDED", "not_sure": None},
}
CURE_AMOUNT_TOLERANCE = 0.08
STATUSES = ("NEW", "CONTINUING", "CHANGED", "RESOLVED", "WITHDRAWN")


class AnswerInvalid(Exception):
    """An answer that does not match an open card's question options."""


class PurposeNotGranted(Exception):
    """A fact or record arrived for a purpose the customer has not switched on. Nothing is stored."""


class JoinRefused(Exception):
    """A record that may not be joined to this household (e.g. a live record about a real
    person offered to a sandbox household). Nothing is stored."""


@dataclass(frozen=True)
class Answer:
    card_id: str
    option: str
    answered_on: date
    fingerprint: str = ""        # the card version the customer was looking at


@dataclass(frozen=True)
class Closure:
    card_id: str
    code: str
    subject: str
    account: str
    closed_on: date
    reason: str
    basis: str                   # you_told_us | seen_in_data | rule_implied
    fingerprint: str
    return_txn_ids: tuple        # the charge rows behind the card (to suppress re-asking)
    evidence_txn_ids: tuple      # rows proving the closure (empty when basis is you_told_us)
    summary: dict                # counterparty, amount, deadline - for the Resolved view


@dataclass(frozen=True)
class Fact:
    fact_id: str
    card_id: str
    question_code: str
    option: str
    stated_on: date
    source: str = "customer"


@dataclass(frozen=True)
class Event:
    id: str
    kind: str
    status: str
    as_of: str
    since: str | None
    subject: str
    account: str
    card_id: str | None
    basis: str                   # evidence | rule | you_told_us | seen_in_data | rule_implied | pattern
    evidence_classes: tuple
    txn_ids: tuple
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class State:
    as_of: date | None
    snapshot: Snapshot | None
    since: date | None = None    # the previous refresh this state was compared with
    open_cards: tuple = ()       # (Card, first_seen: date)
    closed: tuple = ()           # Closure
    facts: tuple = ()            # Fact (answers to Protect questions)
    # Gate 4 + 5
    hfacts: tuple = ()           # FactStatement: household facts (age band, taxpayer, ...)
    corrections: tuple = ()      # facts.Correction history
    records: tuple = ()          # sources.lpg.SourceRecord kept for the evaluator
    access_log: tuple = ()       # dicts: every external lookup and every forgetting
    unlock_status: tuple = ()    # per member x scheme status, for OUR HOUSEHOLD
    forgotten: tuple = ()        # (purpose, date): answers/records of that purpose dated on/before are never re-applied

    def open_ids(self) -> set:
        return {c.id for c, _ in self.open_cards}


def initial() -> State:
    return State(None, None, None)


# ---------- helpers ----------
def fingerprint(card: Card) -> str:
    """What makes a card MATERIALLY the same: type, subject, deadline, which kinds of
    evidence it rests on, and its question. Excludes numbers that drift day to day
    (liquidity range, absence window end) so a continuing card stays continuing."""
    parts = [card.type, card.code, card.subject,
             card.deadline.date if card.deadline else "",
             str(card.deadline.data.get("instalments_behind", "")) if card.deadline else "",
             "|".join(sorted(f"{e.cls}:{e.code}" for e in card.evidence)),
             "|".join(card.question.options) if card.question else ""]
    return "F-" + hashlib.sha256("§".join(parts).encode()).hexdigest()[:12]


def _eid(kind: str, subject: str, as_of: date) -> str:
    return "E-" + hashlib.sha256(f"{kind}|{subject}|{as_of.isoformat()}".encode()).hexdigest()[:12]


def _return_txns(card: Card) -> tuple:
    e = next((x for x in card.evidence if x.code == "RETURN_CHARGE_POSTED"), None)
    return tuple(e.txn_ids) if e else ()


def _summary(card: Card) -> dict:
    d = {"code": card.code, "account": card.account}
    for e in card.evidence:
        if e.code == "COLLECTION_HISTORY":
            d.update(counterparty=e.data["counterparty"], amount=e.data["amount_last"])
        if e.code == "EARLIER_COLLECTION":
            d.update(counterparty=e.data["counterparty"], amount=e.data["amount"])
        if e.code == "RETURN_CHARGE_POSTED":
            d.update(return_date=e.data["return_date"], charge=e.data["charge"])
        if e.code == "NOT_COLLECTED" and "periods" in e.data:
            d.update(periods=list(e.data["periods"]))
        if e.code == "SCHEME_RULE" and card.code in ("PROTECTION_DOOR", "PROTECTION_NOT_SHOWN"):
            d.update(scheme=e.data["scheme"])
        if e.code == "SUBSIDY_CREDITS_SEEN":
            d.update(counterparty=e.data["payer_label"], last_credit=e.data["last"])
        if e.code == "LPG_RECORD":
            d.update(record_mode=e.data["record"]["mode"], account_tail=e.data.get("account_tail"))
    if card.deadline:
        d["deadline"] = card.deadline.date
    return d


def _classes(card: Card) -> tuple:
    return tuple(sorted({e.cls for e in card.evidence}))


def _ev(kind, status, snap, prev_as_of, card=None, subject=None, account=None, basis="evidence",
        classes=(), txn_ids=(), **data) -> Event:
    subj = subject or (card.subject if card else "")
    return Event(_eid(kind, f"{subj}|{card.id if card else ''}", snap.as_of), kind, status,
                 snap.as_of.isoformat(), prev_as_of.isoformat() if prev_as_of else None, subj,
                 account or (card.account if card else ""), card.id if card else None, basis,
                 tuple(classes) or (_classes(card) if card else ()), tuple(txn_ids),
                 {"summary": _summary(card), **data} if card else dict(data))


def _cure(card: Card, snap: Snapshot) -> tuple | None:
    """Positive evidence that a clock is over. Returns (basis, reason, txn_ids) or None."""
    m = next((x for x in snap.members if x.account == card.account), None)
    if m is None or m.quality != "OK":
        return None
    ob = next((o for o in m.obligations if o.id == card.subject), None)
    ret = next((e for e in card.evidence if e.code == "RETURN_CHARGE_POSTED"), None)
    if ob is None or ret is None:
        return None
    ret_date = date.fromisoformat(ret.data["return_date"])
    if card.code == "LIC_GRACE_CLOCK":
        amount = next(e.data["amount"] for e in card.evidence if e.code == "PRESENTED_AMOUNT")
        deadline = date.fromisoformat(card.deadline.date)
        key = (ob.rail, ob.counterparty, ob.ref_root)
        hits = [t for t in m.txns if t.kind == "DEBIT" and ret_date < t.d <= deadline
                and obligation_key(t.narration) == key
                and abs(t.amount - amount) <= CURE_AMOUNT_TOLERANCE * amount]
        if hits:
            return "seen_in_data", "COLLECTED_AFTER_RETURN", tuple(t.txn_id for t in hits)
    if card.code == "LOAN_OVERDUE_CLOCK":
        state = _implied_overdue(ob, ob.day_window[0], snap.as_of)
        gaps = [o for o in ob.occurrences if o.status == "NOT_SEEN"
                and o.period > ret.data["return_date"][:7]
                and not any(t.linked_obligation == ob.id and (t.event_date or "")[:7] == o.period
                            for t in m.traces)]
        if state["instalments_behind"] == 0 and not gaps:
            after = tuple(i for o in ob.occurrences if o.status == "SEEN" and o.period >= ret.data["return_date"][:7]
                          for i in o.txn_ids)
            return "rule_implied", "NOTHING_IMPLIED_OVERDUE", after
    return None


# ---------- Gate 4 + 5 helpers ----------
def _log_entry(rec) -> dict:
    return {"id": rec.id, "on": rec.requested_on.isoformat(), "what": "lookup", "source": rec.source,
            "source_label": fact_source_label(rec.mode), "purpose": rec.purpose, "mode": rec.mode,
            "outcome": rec.status, "reason": rec.reason, "account": rec.account,
            "fields_kept": sorted(k for k, v in rec.fields.items() if v is not None),
            "fields_dropped": list(rec.dropped), "request_ref": rec.request_ref, "join": rec.join}


def _forget_entry(on: date, purpose: str, n_facts: int, n_records: int, n_closures: int) -> dict:
    return {"id": "AL-" + hashlib.sha256(f"forget|{purpose}|{on}".encode()).hexdigest()[:10],
            "on": on.isoformat(), "what": "forgotten", "source": "this app", "purpose": purpose,
            "mode": "n/a", "outcome": "done", "reason": "PURPOSE_SWITCHED_OFF",
            "forgot": {"answers": n_facts, "records": n_records, "closed_items": n_closures}}


def _effects(status: tuple, prev_status: tuple, fact: FactStatement) -> list:
    feeds = [fact.scheme] if fact.scheme else FACTS[fact.code]["feeds"]
    before = {(s["account"], s["scheme"]): s["status"] for s in prev_status}
    out = []
    for st in status:
        if st["account"] == fact.account and st["scheme"] in feeds:
            out.append({"scheme": st["scheme"], "status": st["status"], "reason": st.get("reason"),
                        "before": before.get((st["account"], st["scheme"]))})
    return out


# ---------- the transition ----------
def advance(prev: State, snap: Snapshot, answers=(), records=()) -> tuple:
    """Previous State + new Snapshot (+ customer answers and DPI records dated <= snap.as_of)
    -> (State, Events). `answers` may hold card Answers and direct FactStatements (corrections)."""
    if prev.as_of is not None and snap.as_of < prev.as_of:
        raise ValueError("time only moves forward: snapshot is older than the previous state")
    prev_as_of = prev.as_of
    purposes = snap.purposes
    gov_on, dpi_on = PURPOSE_GOV_PROTECT in purposes, PURPOSE_DPI_LPG in purposes
    prev_purposes = prev.snapshot.purposes if prev.snapshot is not None else frozenset()
    card_answers = sorted((a for a in answers if isinstance(a, Answer) and a.answered_on <= snap.as_of),
                          key=lambda a: (a.answered_on, a.card_id))
    statements = sorted((a for a in answers if isinstance(a, FactStatement) and a.stated_on <= snap.as_of),
                        key=lambda f: (f.stated_on, f.key))
    fresh = lambda d: prev_as_of is None or d > prev_as_of

    prev_open = {c.id: (c, since) for c, since in prev.open_cards}
    closed = {cl.card_id: cl for cl in prev.closed}
    facts = {f.fact_id: f for f in prev.facts}
    hfacts, corrections, kept = prev.hfacts, list(prev.corrections), list(prev.records)
    access_log, forgotten = list(prev.access_log), list(prev.forgotten)
    known_cards = {c.id: c for c in snap.cards}
    known_cards.update({cid: c for cid, (c, _) in prev_open.items() if cid not in known_cards})

    events, open_now = [], []

    # purposes: switching one on is an event; switching one off FORGETS what it produced
    for purpose in (PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG):
        if purpose in purposes and purpose not in prev_purposes:
            events.append(_ev("PURPOSE_GRANTED", "NEW", snap, prev_as_of, subject=purpose, basis="consent"))
    for purpose in (PURPOSE_DPI_LPG, PURPOSE_GOV_PROTECT):          # narrower purpose forgets first
        if purpose in prev_purposes and purpose not in purposes:
            # GOV off forgets everything Unlock produced; DPI off forgets what the record produced
            if purpose == PURPOSE_GOV_PROTECT:
                drop_fact = lambda f: True
                drop_closure = lambda cl: cl.code in UNLOCK_CODES
            else:
                drop_fact = lambda f: FACTS[f.code]["purpose"] == PURPOSE_DPI_LPG
                drop_closure = lambda cl: cl.code == "LPG_SUBSIDY_ROUTING" or cl.basis == "source_record"
            n_f = len([f for f in hfacts if drop_fact(f)])
            hfacts = tuple(f for f in hfacts if not drop_fact(f))
            corrections = [c for c in corrections if any(f.id == c.fact_id for f in hfacts)]
            gone = [cid for cid, cl in closed.items() if drop_closure(cl)]
            for cid in gone:
                del closed[cid]
            n_r = len(kept)
            kept = []
            # the access log keeps THAT a lookup happened (date, source, mode, outcome, whose account),
            # but loses what it returned: the reference and the names of the fields kept are redacted
            access_log = [({**e, "request_ref": "", "fields_kept": [], "redacted": "purpose switched off"}
                           if e.get("what") == "lookup" and e.get("purpose") == PURPOSE_DPI_LPG else e)
                          for e in access_log]
            forgotten.append((purpose, snap.as_of))
            access_log.append(_forget_entry(snap.as_of, purpose, n_f, n_r, len(gone)))
            events.append(_ev("PURPOSE_REVOKED", "CHANGED", snap, prev_as_of, subject=purpose, basis="consent",
                              forgot_answers=n_f, forgot_records=n_r, forgot_closed_items=len(gone)))

    def was_forgotten(purpose: str, when: date) -> bool:
        return any(when <= d and (p == purpose or p == PURPOSE_GOV_PROTECT) for p, d in forgotten)

    # DPI records: accepted only under both purposes and only for this household; always logged
    kept_ids = {r.id for r in kept} | {e["id"] for e in access_log}      # a replayed lookup is never logged twice
    for rec in sorted((r for r in records if r.requested_on <= snap.as_of), key=lambda r: (r.requested_on, r.id)):
        if rec.id in kept_ids or was_forgotten(PURPOSE_DPI_LPG, rec.requested_on):
            continue
        if rec.status != "refused":
            if not (gov_on and dpi_on):
                raise PurposeNotGranted(f"{rec.source}: the LPG check purpose is not switched on")
            # In this build only a labelled SIMULATED record may be joined to a household. A live record
            # (a real person's own LPG ID) is shown on its own, never merged into the sandbox household.
            if rec.mode != "simulated" or rec.join != "simulated" or rec.household_id != snap.household_id:
                raise JoinRefused(f"{rec.source}: only a labelled simulated record for this household can be joined "
                                  f"here; got mode={rec.mode}, join={rec.join}, household={rec.household_id}")
            kept.append(rec)
        kept_ids.add(rec.id)
        access_log.append(_log_entry(rec))
        kind = {"ok": "SOURCE_CHECKED", "failed": "SOURCE_CHECK_FAILED", "refused": "SOURCE_CHECK_REFUSED"}
        events.append(_ev(kind[rec.status], "NEW", snap, prev_as_of, subject=rec.id, account=rec.account or "",
                          basis="source_record", classes=("O",) if rec.ok else (),
                          mode=rec.mode, reason=rec.reason, record_id=rec.id))   # once: replays are skipped above

    # answers first: they may close cards (Protect) or become household facts (Unlock)
    pending = []                                            # (FactStatement, card, answer)
    for a in card_answers:
        card = known_cards.get(a.card_id)
        usable = card is not None and card.question is not None and a.option in card.question.options
        if not fresh(a.answered_on) and (a.card_id in closed or not usable):
            continue                                        # replayed answer, already reflected in state
        if not usable:
            raise AnswerInvalid(f"{a.card_id}: '{a.option}' is not an option on an open card")
        if card.question.code in FACTS:
            if was_forgotten(FACTS[card.question.code]["purpose"], a.answered_on):
                continue                                    # forgotten answers are never re-applied
            if FACTS[card.question.code]["purpose"] not in purposes:
                raise PurposeNotGranted(f"{card.question.code}: its purpose is switched off")
            u = next(e for e in card.evidence if e.id in card.question.resolves)
            pending.append((FactStatement(u.data["account"], u.data["fact"], a.option, a.answered_on,
                                          u.data.get("scheme"), via_card=card.id), card, a))
            continue
        reason = RESOLUTIONS[card.question.code][a.option]
        if reason is None:
            fid = "FACT-" + hashlib.sha256(f"{a.card_id}|{a.option}".encode()).hexdigest()[:10]
            if fid not in facts:
                facts[fid] = Fact(fid, a.card_id, card.question.code, a.option, a.answered_on)
                events.append(_ev("QUESTION_ANSWERED", "CHANGED", snap, prev_as_of, card,
                                  basis="you_told_us", option=a.option))
        elif a.card_id not in closed:
            closed[a.card_id] = Closure(card.id, card.code, card.subject, card.account, a.answered_on,
                                        reason, "you_told_us", a.fingerprint or fingerprint(card),
                                        _return_txns(card), (), _summary(card))
            events.append(_ev("CARD_RESOLVED", "RESOLVED", snap, prev_as_of, card,
                              basis="you_told_us", reason=reason, option=a.option))
    for f in statements:
        spec = FACTS.get(f.code)
        if spec is None:
            raise AnswerInvalid(f"unknown fact {f.code!r}")
        if was_forgotten(spec["purpose"], f.stated_on):
            continue                                        # forgotten: never re-applied (facts.apply drops
                                                            # repeats and stale statements)
        if spec["purpose"] not in purposes:
            raise PurposeNotGranted(f"{f.code}: its purpose is not switched on")
        pending.append((f, None, None))
    pending.sort(key=lambda x: (x[0].stated_on, x[0].key))
    hfacts, new_corr, applied = apply_facts(hfacts, [p[0] for p in pending])
    corrections += list(new_corr)
    corrected_ids = {c.fact_id: c for c in new_corr}

    # the Unlock evaluator re-reads every rule each fact feeds - in this same pass
    ures = evaluate_unlock(snap, hfacts, tuple(kept))
    current = tuple(snap.cards) + ures.cards
    current_ids = {c.id for c in current}
    for c in ures.cards:
        known_cards.setdefault(c.id, c)

    # a fact-question card that the answer made unnecessary is closed: "you told us"
    for f, card, a in pending:
        if card is not None and card.id not in current_ids and card.id not in closed:
            summary = {**_summary(card), "fact": f.code, "value": f.value, "scheme": f.scheme}
            closed[card.id] = Closure(card.id, card.code, card.subject, card.account, a.answered_on, "ANSWERED",
                                      "you_told_us", a.fingerprint or fingerprint(card), (), (), summary)
            events.append(_ev("CARD_RESOLVED", "RESOLVED", snap, prev_as_of, card, basis="you_told_us",
                              reason="ANSWERED", fact=f.code, value=f.value, summary=summary))

    # one event per fact that changed state now, carrying its combined effect across rules
    fact_events = {}
    for f in applied:                                       # applied = changed state now, whatever its date
        corr = corrected_ids.get(f.id)
        e = _ev("FACT_CORRECTED" if corr else "FACT_CONFIRMED", "CHANGED", snap, prev_as_of,
                subject=f.id, account=f.account, basis="you_told_us", classes=("U",),
                code=f.code, value=f.value, scheme=f.scheme, old_value=corr.old_value if corr else None,
                feeds=[f.scheme] if f.scheme else list(FACTS[f.code]["feeds"]),
                effects=_effects(ures.status, prev.unlock_status, f), via_card=f.via_card)
        events.append(e)
        fact_events.setdefault(f.account, e.id)

    def caused(card):
        return fact_events.get(card.account) if card.code in UNLOCK_CODES else None

    # cards that vanished from the evaluation: close them first if the data (or a record) shows a cure,
    # so the same return charge is not re-asked about as a "new" question below
    for cid, (card, since) in prev_open.items():
        if cid in current_ids or cid in closed:
            continue
        cure = _cure(card, snap) or unlock_cure(card, ures)
        if cure:
            basis, reason, rows = cure
            summary = _summary(card)
            if basis == "source_record":
                rec = next(r for r in kept if r.id == rows[0])
                summary.update(record_mode=rec.mode, last_booking_date=rec.fields.get("last_booking_date"),
                               record_id=rec.id)
            closed[cid] = Closure(cid, card.code, card.subject, card.account, snap.as_of, reason, basis,
                                  fingerprint(card), _return_txns(card), rows, summary)
            events.append(_ev("CARD_RESOLVED", "RESOLVED", snap, prev_as_of, card, basis=basis,
                              txn_ids=rows if basis != "source_record" else (), reason=reason,
                              record_id=rows[0] if basis == "source_record" else None, summary=summary))

    closed_return_rows = {t for cl in closed.values() for t in cl.return_txn_ids}

    for card in current:
        fp = fingerprint(card)
        cause = caused(card)
        extra = {"caused_by_fact": cause} if cause else {}
        if card.id in closed:
            if closed[card.id].fingerprint == fp:
                continue                                   # stays closed: nothing new
            del closed[card.id]                            # materially new evidence: reopen
            events.append(_ev("CARD_REOPENED", "NEW", snap, prev_as_of, card, basis="evidence", **extra))
            open_now.append((card, snap.as_of))
            continue
        rt = set(_return_txns(card))
        if rt and rt <= closed_return_rows:
            continue                                       # same underlying return, already closed
        cure = _cure(card, snap)
        if cure:
            basis, reason, rows = cure
            closed[card.id] = Closure(card.id, card.code, card.subject, card.account, snap.as_of,
                                      reason, basis, fp, _return_txns(card), rows, _summary(card))
            events.append(_ev("CARD_RESOLVED", "RESOLVED", snap, prev_as_of, card, basis=basis,
                              txn_ids=rows, reason=reason))
            continue
        if card.id in prev_open:
            before, since = prev_open[card.id]
            changed = fingerprint(before) != fp
            events.append(_ev("CARD_CHANGED" if changed else "CARD_CONTINUING",
                              "CHANGED" if changed else "CONTINUING", snap, prev_as_of, card, **extra))
            open_now.append((card, since))
        else:
            events.append(_ev("CARD_OPENED", "NEW", snap, prev_as_of, card, **extra))
            open_now.append((card, snap.as_of))

    # cards that were open, are not open now, and were not cured: superseded or withdrawn
    open_ids = {c.id for c, _ in open_now}
    for cid, (card, since) in prev_open.items():
        if cid in open_ids or cid in closed:
            continue
        rt = set(_return_txns(card))
        successor = next((c for c, _ in open_now
                          if (rt and rt <= set(_return_txns(c)))
                          or (c.subject == card.subject and c.code in REFINES.get(card.code, ()))), None)
        if successor:
            events.append(_ev("CARD_SUPERSEDED", "CHANGED", snap, prev_as_of, card,
                              superseded_by=successor.id))
            continue
        waiting = next((c for c, _ in open_now if c.subject == card.subject
                        and c.code == "COLLECTION_GAP_QUESTION"), None)
        if card.code in UNLOCK_CODES and not gov_on:
            reason = "PURPOSE_OFF"
        elif caused(card):
            reason = "FACT_CHANGED"
        else:
            reason = "WAITING_ON_ANSWER" if waiting else "EVIDENCE_CHANGED"
        cause = caused(card)
        events.append(_ev("CARD_WITHDRAWN", "WITHDRAWN", snap, prev_as_of, card, reason=reason,
                          waiting_on=waiting.id if waiting else None,
                          **({"caused_by_fact": cause} if cause else {})))

    # commitments and regular credits: newly recognised / amount changed (baseline on first look).
    # 'Recognised' not 'started': a pattern becomes learnable after 3 sightings; it may be older.
    if prev.snapshot is not None:
        before = {o.id: o for m in prev.snapshot.members for o in m.obligations}
        before_rows = {t for m in prev.snapshot.members for s in m.income for t in s.txn_ids}
        for m in snap.members:
            for o in m.obligations:
                last = [x for x in o.occurrences if x.status == "SEEN"][-1]
                if o.id not in before:
                    events.append(_ev("COMMITMENT_RECOGNISED", "NEW", snap, prev_as_of, subject=o.id,
                                      account=o.account, basis="pattern", classes=("O",),
                                      txn_ids=o.seen_txn_ids, counterparty=o.counterparty,
                                      amount=last.amount, usual_day=o.day_window[0], cadence=o.cadence))
                    continue
                old = [x for x in before[o.id].occurrences if x.status == "SEEN"][-1]
                if old.amount and abs(last.amount - old.amount) > 0.01 * old.amount:
                    events.append(_ev("COMMITMENT_AMOUNT_CHANGED", "CHANGED", snap, prev_as_of, subject=o.id,
                                      account=o.account, basis="evidence", classes=("O",),
                                      txn_ids=tuple(last.txn_ids), counterparty=o.counterparty,
                                      old_amount=old.amount, new_amount=last.amount))
            for s in m.income:
                if not set(s.txn_ids) & before_rows:   # same stream = shared transactions
                    events.append(_ev("REGULAR_CREDIT_RECOGNISED", "NEW", snap, prev_as_of, subject=s.id,
                                      account=s.account, basis="pattern", classes=("O",),
                                      txn_ids=tuple(s.txn_ids[-3:]), signature=s.signature))

    state = State(snap.as_of, snap, prev_as_of, tuple(sorted(open_now, key=lambda x: x[0].id)),
                  tuple(sorted(closed.values(), key=lambda c: (c.closed_on, c.card_id))),
                  tuple(sorted(facts.values(), key=lambda f: f.fact_id)),
                  hfacts, tuple(corrections), tuple(kept), tuple(access_log), ures.status, tuple(forgotten))
    return state, sorted(events, key=lambda e: (STATUSES.index(e.status), e.kind, e.id))
