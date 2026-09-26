"""
Counterparty Mirror - Learner.

Turns an account's transactions into two kinds of remembered facts:

  OBLIGATION INSTANCES - one per real agreement (a policy, a loan), keyed by
    rail + counterparty + reference root, never by amount alone. Each carries
    cadence, expected day window, amount band, and an expected-period ledger:
    SEEN (with txn ids) / NOT_SEEN / OUTSIDE_DATA_WINDOW.
  INCOME STREAMS - recurring credits. Reuses the verified E7 signature and
    narration-drift merge from hsl/household.py (imported, not copied).

Everything here is Observed (O) except cadence/day-window, which are
patterns over observations (labelled O-pattern). Nothing here is a rule
or a judgement; those live in the evaluator.
"""
from __future__ import annotations
import re, sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import median
from typing import Optional

from .corpus import Account, Txn, mk, unmk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hsl"))
import household as _hsl  # verified E7 engine: signature() and _merge_groups() only

RAILS = ("ACH", "NACH", "ECS", "CMS", "SI")
CHARGE_HINT = re.compile(r"CHG|CHRG|CHGS|CHARGES|JFEE|GST\b|\(REF# BANK CHARGES\)", re.I)
MIN_OCCURRENCES = 3          # a new obligation needs >=3 sightings (spec D.1)
DAY_TOLERANCE = 3            # days after the latest usual day before "not seen"
CADENCES = {1: "MONTHLY", 3: "QUARTERLY", 6: "HALF_YEARLY", 12: "ANNUAL"}


# ---------- keys ----------
def obligation_key(narration: str) -> Optional[tuple]:
    """(rail, counterparty, ref_root) for rail-collected debits, or a
    (None, counterparty, ref) key for self-labelled standing debits such as
    'LTGURXX42921 DEC19 Manish Kum'. Returns None for ordinary spends."""
    n = (narration or "").upper().strip()
    if CHARGE_HINT.search(n):
        return None
    parts = [p.strip() for p in n.split("/")]
    if parts[0] in RAILS and len(parts) >= 3:
        rail = parts[0]
        name = next((p for p in parts[1:] if p and not any(c.isdigit() for c in p)), "")
        if not name:  # CMS/000573987107/BAJAJ_AUTO_C D__580DPFFC021540
            name = re.sub(r"_+\S*\d\S*", "", parts[-1]).replace("_", " ").strip()
            ref = re.search(r"([A-Z0-9]*\d[A-Z0-9]*)$", parts[-1])
            return rail, name, ref.group(1) if ref else ""
        ref = parts[-1]
        root = ref[:-4] if ref.isdigit() and len(ref) >= 9 else ref
        return rail, name, root
    toks = n.split()
    if toks and re.fullmatch(r"[A-Z]{3,}\d{3,}", toks[0]):
        # a loan/agreement code followed by a period label: only a key if a
        # period label is actually present, else it is just a reference.
        if re.search(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b", n):
            return None, toks[0], toks[0]
    return None


# ---------- facts ----------
@dataclass
class Occurrence:
    period: str               # YYYY-MM of the expected period
    status: str               # SEEN | NOT_SEEN | OUTSIDE_DATA_WINDOW | NOT_YET_DUE
    txn_ids: list = field(default_factory=list)
    amount: Optional[float] = None
    day: Optional[int] = None


@dataclass
class Obligation:
    id: str
    account: str
    member: Optional[str]
    rail: Optional[str]
    counterparty: str         # as labelled in the narration - never "resolved" to a brand
    ref_root: str
    cadence: str
    cadence_months: int
    day_window: tuple         # (earliest, latest) observed day; 28 = clamped month-end
    amount_band: tuple
    first_seen: str
    last_seen: str
    occurrences: list
    evidence_class: str = "O"
    notes: list = field(default_factory=list)

    @property
    def seen_txn_ids(self):
        return [i for o in self.occurrences for i in o.txn_ids]


@dataclass
class IncomeStream:
    id: str
    account: str
    member: Optional[str]
    signature: str
    months: list
    day_window: tuple
    amount_band: tuple
    regular: bool             # same cadence, tight day window, no gaps
    last_seen: str
    txn_ids: list
    evidence_class: str = "O"
    notes: list = field(default_factory=list)


def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _cadence(months_idx: list) -> Optional[int]:
    if len(months_idx) < 2:
        return None
    gaps = sorted(b - a for a, b in zip(months_idx, months_idx[1:]))
    g = int(median(gaps))
    # a gap that is a multiple of the base cadence is a miss, not a new cadence
    base = min(gaps)
    if base in CADENCES and all(x % base == 0 for x in gaps):
        return base
    return g if g in CADENCES else None


def _split_by_amount(ts: list, tol: float = 0.08) -> list:
    """Same counterparty+ref root but clearly different fixed amounts are
    different instances (e.g. two policies on one mandate)."""
    out = []
    for t in sorted(ts, key=lambda x: x.amount):
        for c in out:
            m = median(x.amount for x in c)
            if abs(t.amount - m) <= max(1.0, tol * m):
                c.append(t)
                break
        else:
            out.append([t])
    return out


def learn_obligations(acc: Account, txns: list, as_of: date) -> list:
    if acc.quality != "OK":
        return []
    groups = defaultdict(list)
    for t in txns:
        if t.kind != "DEBIT":
            continue
        k = obligation_key(t.narration)
        if k:
            groups[k].append(t)
    out = []
    for (rail, name, root), ts in groups.items():
        for cl in _split_by_amount(ts):
            by_month = defaultdict(list)
            for t in cl:
                by_month[mk(t.d.year, t.d.month)].append(t)
            if len(by_month) < MIN_OCCURRENCES:
                continue
            idx = sorted(by_month)
            cad = _cadence(idx)
            if cad is None:
                continue
            days = [t.d.day for t in cl]
            dw = (min(days), max(days))
            ob_id = f"OB-{acc.masked[-4:]}-{re.sub(r'[^A-Z0-9]', '', (name or root))[:10]}-{(root or '')[-6:]}-{cad}M"
            occ = _ledger(idx, by_month, cad, dw, acc.window, as_of)
            amts = [t.amount for t in cl]
            ob = Obligation(ob_id, acc.masked, acc.member, rail, name or root, root,
                            CADENCES[cad], cad, dw, (min(amts), max(amts)),
                            _ym(min(t.d for t in cl)), _ym(max(t.d for t in cl)), occ)
            if dw[1] == 28:
                ob.notes.append("day 28 in this sandbox can mean any day from the 28th to month-end")
            out.append(ob)
    return sorted(out, key=lambda o: (o.account, o.day_window[0]))


def _ledger(idx, by_month, cad, dw, window, as_of) -> list:
    """Expected periods from the first sighting to as_of, at the cadence."""
    first_day, last_day = window
    occ, k = [], idx[0]
    last_data = min(last_day, as_of) if last_day else as_of
    while True:
        y, m = unmk(k)
        due_latest = date(y, m, min(28, dw[1]))
        if date(y, m, 1) > as_of:
            break
        ts = by_month.get(k, [])
        if ts:
            occ.append(Occurrence(f"{y:04d}-{m:02d}", "SEEN", [t.txn_id for t in ts],
                                  sum(t.amount for t in ts), ts[0].d.day))
        else:
            # can we see this period at all?
            from datetime import timedelta
            due_check = due_latest + timedelta(days=DAY_TOLERANCE)
            if due_check > last_data:
                status = "NOT_YET_DUE" if due_check > as_of else "OUTSIDE_DATA_WINDOW"
            else:
                status = "NOT_SEEN"
            occ.append(Occurrence(f"{y:04d}-{m:02d}", status))
        k += cad
    return occ


_GLUED_MONTH = re.compile(r"\b([A-Z]{3,}?)(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEPT?|OCT|NOV|DEC)\b")


def _unglue(narration: str) -> str:
    """'SAL FORMAY' -> 'SAL FOR MAY' so the E7 signature drops the month."""
    return _GLUED_MONTH.sub(r"\1 \2", (narration or "").upper())


def learn_income(acc: Account, txns: list, as_of: date, min_months: int = 3) -> tuple:
    """Returns (regular income streams, count of other recurring credit
    sources). Only REGULAR streams are income; everything else is inflow and
    is never called income (spec: inflow != income)."""
    if acc.quality != "OK":
        return [], 0
    g = defaultdict(list)
    for t in txns:
        if t.kind == "CREDIT" and t.amount >= 100:
            g[("CREDIT", _hsl.signature(_unglue(t.narration)))].append(t)
    merged = _hsl._merge_groups(dict(g))
    out, other = [], 0
    for (_, sig), ts in merged.items():
        if not sig or sig in ("UPI", "IMPS", "NEFT", "MMT IMPS"):
            continue  # generic rail tokens are not a payer (spec D.1 guard)
        months = sorted({t.ym for t in ts})
        if len(months) < min_months:
            continue
        idx = [mk(int(m[:4]), int(m[5:])) for m in months]
        gaps = [b - a for a, b in zip(idx, idx[1:])]
        days = [t.d.day for t in ts]
        amts = [t.amount for t in ts]
        regular = (all(x == 1 for x in gaps) and max(days) - min(days) <= 7
                   and len(ts) == len(months))
        sid = f"IN-{acc.masked[-4:]}-{re.sub(r'[^A-Z]', '', sig)[:10]}"
        s = IncomeStream(sid, acc.masked, acc.member, sig, months, (min(days), max(days)),
                         (min(amts), max(amts)), regular, months[-1],
                         [t.txn_id for t in ts])
        if not regular:
            other += 1
            continue
        if max(days) == 28:
            s.notes.append("day 28 in this sandbox can mean any day from the 28th to month-end")
        out.append(s)
    return sorted(out, key=lambda s: -median(s.amount_band)), other
