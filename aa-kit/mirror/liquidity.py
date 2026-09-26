"""
Counterparty Mirror - Revealed liquidity.

WHAT IT IS: a range for how much money an account could have had at a stated
point, inferred ONLY from what payments did:
  * every debit that went through     -> the account could cover it
                                          (balance after it was >= 0)  -> LOWER bound
  * a collection that was returned    -> the account could not cover it
                                          (balance just before it < amount) -> UPPER bound
Money in and out between those points is fully observed, so both bounds move
forward exactly; the width of the range never changes.

WHAT IT IS NOT: not a balance, not net worth, not a complete cash position.
It never reads the bank's reported balance fields (the loader does not even
load them). It knows nothing about cash, other accounts, or what the money is
"for". Inflow is not income.

Evidence class: I (inferred), always. The upper bound additionally rests on a
linked return (itself I) and on the amount presented (I), so it is only used
when that link is strong.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional

ASSUMPTIONS = (
    "no overdraft: a debit only goes through if the account can cover it",
    "a returned collection means the account could not cover the amount presented",
    "the returned collection was presented before that day's other transactions",
    "the amount presented equals the last amount collected for that payment",
)
NOT_CONSIDERED = ("the bank's reported balance", "cash", "other accounts", "future income")


@dataclass(frozen=True)
class LiquidityRange:
    account: str
    point: str                      # "end of 2026-09-07" or "just after txn <id>"
    low: float
    high: Optional[float]           # None when there is no usable upper bound
    lower_bound_txn: str            # the debit that pins the lower bound
    upper_bound_trace: Optional[str]
    presented_amount: Optional[float]
    assumptions: tuple
    not_considered: tuple = NOT_CONSIDERED
    evidence_class: str = "I"
    note: str = ""


def _signed(t) -> float:
    return t.amount if t.kind == "CREDIT" else -t.amount


def revealed_liquidity(account: str, txns: list, *, at_end_of: Optional[date] = None,
                       after_txn: Optional[str] = None, returned: Optional[dict] = None
                       ) -> Optional[LiquidityRange]:
    """txns: the account's transactions visible at the replay point, in (date, file order).
    Exactly one of at_end_of / after_txn chooses the point.
    returned: {"date": date, "amount": float, "trace_id": str} for a STRONGLY linked return,
              or None (then only the lower bound is known)."""
    if (at_end_of is None) == (after_txn is None):
        raise ValueError("choose exactly one point: at_end_of or after_txn")
    debits = [t for t in txns if t.kind == "DEBIT"]
    if not debits:
        return None

    # 1. bounds on the unseen opening balance B0
    running, lo_b0, lo_txn, before_return = 0.0, float("-inf"), None, None
    for t in txns:
        if returned and before_return is None and t.d >= returned["date"]:
            before_return = running
        running += _signed(t)
        if t.kind == "DEBIT" and -running > lo_b0:
            lo_b0, lo_txn = -running, t.txn_id
    hi_b0, note = None, ""
    if returned:
        if before_return is None:          # return is after every visible transaction
            before_return = running
        hi_b0 = returned["amount"] - before_return
        if hi_b0 <= lo_b0:
            hi_b0, note = None, "the return contradicts the debits that went through; upper bound dropped"

    # 2. net money in/out up to the chosen point
    net, found = 0.0, False
    for t in txns:
        if at_end_of is not None and t.d > at_end_of:
            break
        net += _signed(t)
        if after_txn is not None and t.txn_id == after_txn:
            found = True
            break
    if after_txn is not None and not found:
        raise ValueError(f"transaction {after_txn} is not visible at this point")
    point = f"end of {at_end_of.isoformat()}" if at_end_of else f"just after txn {after_txn}"

    return LiquidityRange(
        account=account, point=point,
        low=round(lo_b0 + net, 2),
        high=round(hi_b0 + net, 2) if hi_b0 is not None else None,
        lower_bound_txn=lo_txn,
        upper_bound_trace=returned["trace_id"] if (returned and hi_b0 is not None) else None,
        presented_amount=returned["amount"] if returned else None,
        assumptions=ASSUMPTIONS if returned else ASSUMPTIONS[:1],
        note=note)
