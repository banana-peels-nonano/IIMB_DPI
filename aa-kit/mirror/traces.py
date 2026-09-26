"""
Counterparty Mirror - Trace linker.

A failure trace is a bank charge line that records that something went wrong
(a returned ECS/NACH presentation, a declined card payment, a minimum-balance
shortfall). Charges are the only reliable evidence of failure in the data:
the returned presentation itself never appears as a transaction.

Linking a return to a specific obligation is INFERENCE (I), never observation.
It is linked only when exactly one known obligation fits the presentation
date; otherwise the candidates are kept and a question is required. The
customer confirms the link the first time (spec D.5) - that is the evaluator's
job, not this module's.
"""
from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from datetime import timedelta
from .corpus import Account, add_months, estimate_label_offset
from .learn import obligation_key

RX_ECS_RETURN = re.compile(r"ECSRTNCHGS?(\d{2})(\d{2})(\d{2})_?(SR\d+)?", re.I)
RX_CARD_DECLINE = re.compile(r"(POS|ATM)DEC CHG/(\d{2})-(\d{2})-(\d{4})", re.I)
RX_MAB = re.compile(r"MABCHGS", re.I)
RX_ROUTINE = re.compile(r"SMSCHGS|DRCARD JFEE", re.I)
LINK_DAY_TOLERANCE = 2
RETURN_TO_CHARGE_MAX_DAYS = 7


@dataclass
class Trace:
    id: str
    account: str
    kind: str                     # ECS_RETURN | CARD_DECLINE | MIN_BALANCE | ROUTINE_CHARGE
    total_charge: float
    txn_ids: list
    posted: str                   # first posting date of the charge line(s)
    label_date_source: Optional[str] = None   # date written in the narration (source calendar)
    event_date: Optional[str] = None          # label date mapped to posting calendar
    linked_obligation: Optional[str] = None
    link_class: Optional[str] = None          # "I" when linked
    link_confidence: Optional[str] = None     # strong | none
    candidates: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def classify_charges(acc: Account, txns: list) -> list:
    """Group charge lines into traces. GST lines and split charges that share
    the same service-request number are one trace."""
    ecs = defaultdict(list)
    out = []
    for t in txns:
        if t.kind != "DEBIT":
            continue
        n = t.narration.upper()
        m = RX_ECS_RETURN.search(n)
        if m:
            key = m.group(4) or f"{m.group(1)}{m.group(2)}{m.group(3)}"
            ecs[key].append((t, m))
            continue
        m = RX_CARD_DECLINE.search(n)
        if m:
            out.append(Trace(f"TR-{t.txn_id}", acc.masked, "CARD_DECLINE", t.amount, [t.txn_id],
                             t.d.isoformat(), f"{m.group(4)}-{m.group(3)}-{m.group(2)}",
                             notes=["card payment declined" if m.group(1) == "POS" else "ATM withdrawal declined"]))
            continue
        if RX_MAB.search(n):
            out.append(Trace(f"TR-{t.txn_id}", acc.masked, "MIN_BALANCE", t.amount, [t.txn_id],
                             t.d.isoformat()))
            continue
        if RX_ROUTINE.search(n):
            out.append(Trace(f"TR-{t.txn_id}", acc.masked, "ROUTINE_CHARGE", t.amount, [t.txn_id],
                             t.d.isoformat()))
    for key, rows in ecs.items():
        rows.sort(key=lambda r: (r[0].d, r[0].seq))
        t0, m = rows[0]
        dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        out.append(Trace(f"TR-{t0.txn_id}", acc.masked, "ECS_RETURN",
                         round(sum(r[0].amount for r in rows), 2), [r[0].txn_id for r in rows],
                         t0.d.isoformat(), f"20{yy:02d}-{mm:02d}-{dd:02d}"))
    return sorted(out, key=lambda x: x.posted)


def link_returns(acc: Account, traces: list, obligations: list, txns: list = ()) -> list:
    """Map each ECS return to the one obligation that was due that day and did
    not go through.

    The return date is anchored on the charge's own posting date: the latest
    date on or before posting whose day equals the day in the narration, at
    most RETURN_TO_CHARGE_MAX_DAYS earlier. That works identically in
    production. The label-calendar offset (estimated only from data visible
    at this replay point - no look-ahead) is a cross-check, reported either way."""
    off = estimate_label_offset(txns)[0] if txns else acc.label_offset_months
    for tr in traces:
        if tr.kind != "ECS_RETURN":
            continue
        src = date.fromisoformat(tr.label_date_source)
        ev = _anchor(date.fromisoformat(tr.posted), src.day)
        if ev is None:
            tr.notes.append("the return's own date could not be placed near the charge; not linked")
            tr.link_confidence = "none"
            continue
        tr.event_date = ev.isoformat()
        if off is not None and add_months(src, off).replace(day=1) != ev.replace(day=1):
            tr.notes.append("the narration's month does not match this account's calendar; not linked")
            tr.link_confidence = "none"
            continue
        if off:
            tr.notes.append(f"narration date {src.isoformat()} is in the source system's calendar; "
                            f"this sandbox account is shifted by {off} months (checked)")
        period = f"{ev.year:04d}-{ev.month:02d}"
        fits = []
        for ob in obligations:
            if ob.account != acc.masked or ob.rail not in ("ACH", "NACH", "ECS"):
                continue
            lo, hi = ob.day_window
            if not (lo - LINK_DAY_TOLERANCE <= ev.day <= hi + LINK_DAY_TOLERANCE):
                continue
            occ = next((o for o in ob.occurrences if o.period == period), None)
            if occ is None or occ.status == "SEEN":
                continue  # not due that period, or it went through
            fits.append(ob.id)
        tr.candidates = fits
        if len(fits) == 1:
            tr.linked_obligation, tr.link_class, tr.link_confidence = fits[0], "I", "strong"
        elif not fits and _weak_candidate(tr, ev, txns):
            pass
        else:
            tr.link_confidence = "none"
            tr.notes.append("no single obligation fits this return; ask the customer"
                            if not fits else f"{len(fits)} obligations fit; ask the customer")
    return traces


def _anchor(posted: date, day: int):
    for back in range(0, RETURN_TO_CHARGE_MAX_DAYS + 1):
        d = posted - timedelta(days=back)
        if d.day == day:
            return d
    return None


def _weak_candidate(tr: Trace, ev: date, txns: list) -> bool:
    """Early in a consent (few months of history) a mandate may have been
    seen only once or twice - too few to be a learned obligation. If exactly
    one rail mandate was collected on this day of the month before, and not in
    the return's month, it is a WEAK candidate: shown only as a question."""
    period = (ev.year, ev.month)
    keys = {}
    for t in txns:
        if t.kind != "DEBIT" or t.d > ev:
            continue
        k = obligation_key(t.narration)
        if not k or k[0] not in ("ACH", "NACH", "ECS"):
            continue
        if abs(t.d.day - ev.day) > LINK_DAY_TOLERANCE:
            continue
        keys.setdefault(k, []).append(t)
    keys = {k: ts for k, ts in keys.items() if all((t.d.year, t.d.month) != period for t in ts)}
    if len(keys) != 1:
        return False
    (rail, name, root), ts = next(iter(keys.items()))
    tr.candidates = [f"UNLEARNED:{rail}/{name}/{root}"]
    tr.link_class, tr.link_confidence = "I", "weak"
    tr.notes.append(f"matches a {rail} collection by '{name}' seen {len(ts)} time(s) before "
                    f"on the same day of the month; too few sightings to be sure - ask")
    return True
