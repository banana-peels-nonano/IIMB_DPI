"""
Payslip-Passbook reconciliation engine.
Design rule: this module NEVER outputs a diagnosis. It outputs observations,
a confidence, and a suggested verification step. Accusatory states do not exist.
"""
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import List, Optional, Dict

CEILING_OLD, CEILING_NEW, EE_RATE = 15000, 25000, 0.12
EPFO_RATE = 0.0825

# ---------- inputs ----------
@dataclass
class Credit:
    d: date
    amount: float
    narration: str = ""

@dataclass
class Employment:
    """Hub PAN-flow fields. All Optional: absence is a real state."""
    uan: Optional[str] = None
    is_employed: Optional[bool] = None
    is_recent: Optional[bool] = None          # PF filing activity in recent TWO months
    date_of_joining: Optional[date] = None
    date_of_exit: Optional[date] = None
    current_employer: Optional[str] = None
    settled: Optional[bool] = None
    as_of: Optional[date] = None              # when the Hub was queried

# ---------- outputs ----------
@dataclass
class Finding:
    state: str
    observations: List[str] = field(default_factory=list)
    confidence: str = "low"
    caveats: List[str] = field(default_factory=list)
    suggested_check: Optional[str] = None
    delta: Optional[float] = None

# ---------- salary shift ----------
SALARY_HINTS = ("salary", "sal ", "neft", "payroll", "wages", "imps")

def monthly_totals(credits: List[Credit], salary_only: bool = True) -> Dict[tuple, float]:
    out: Dict[tuple, float] = {}
    for c in credits:
        if salary_only and c.narration and not any(h in c.narration.lower() for h in SALARY_HINTS):
            continue
        out[(c.d.year, c.d.month)] = out.get((c.d.year, c.d.month), 0.0) + c.amount
    return out

def detect_salary_shift(credits: List[Credit], boundary: date, months: int = 3, min_n: int = 2):
    """Median of MONTHLY TOTALS either side of a boundary.
    Monthly totals (not single txns) so split/partial payments don't create false shifts."""
    tot = monthly_totals(credits)
    def key(y, m): return (y, m)
    before, after = [], []
    for (y, m), v in tot.items():
        # exclude the boundary month itself: it is usually partial/mixed
        if (y, m) == (boundary.year, boundary.month):
            continue
        if (y, m) < key(boundary.year, boundary.month):
            before.append(((y, m), v))
        else:
            after.append(((y, m), v))
    before = [v for _, v in sorted(before)[-months:]]
    after = [v for _, v in sorted(after)[:months]]
    if len(before) < min_n or len(after) < min_n:
        return None, len(before), len(after), None
    mb, ma = median(before), median(after)
    variability = (max(before) - min(before)) / mb if mb else 0
    return mb - ma, len(before), len(after), variability

# ---------- expected contribution delta ----------
def expected_ee_delta(monthly_wage: float) -> float:
    """Employee-share increase from the ceiling change. NOT universal: it is
    12% of the wage between the old and new ceiling, capped."""
    if monthly_wage <= CEILING_OLD:
        return 0.0
    return EE_RATE * (min(monthly_wage, CEILING_NEW) - CEILING_OLD)

def compound_monthly(amount: float, years: int, rate: float = EPFO_RATE) -> float:
    n, r = years * 12, rate / 12
    return sum(amount * (1 + r) ** (n - i) for i in range(n))

# ---------- reconciliation ----------
def reconcile(credits: List[Credit], emp: Employment, boundary: date,
              expected_delta: Optional[float] = None) -> Finding:
    delta, nb, na, variability = detect_salary_shift(credits, boundary)

    if delta is None:
        return Finding("INSUFFICIENT_DATA",
            [f"Only {nb} full month(s) before and {na} after the reference date."],
            "low", ["Cannot compare periods without at least two full months either side."],
            "Reconnect after another full salary cycle.")

    caveats: List[str] = []
    if variability and variability > 0.15:
        caveats.append(f"Pay varies month to month (spread {variability:.0%} of median) — a shift of this size may be ordinary variation.")

    # employment transition inside the window invalidates a like-for-like comparison
    if emp.date_of_exit and abs((emp.date_of_exit - boundary).days) < 120:
        caveats.append("An employment change is recorded near the reference date — the two periods may not be comparable.")
    if emp.date_of_joining and abs((emp.date_of_joining - boundary).days) < 120:
        caveats.append("Employment started near the reference date — the earlier period may be a partial record.")

    fell = delta > 0
    obs = [f"Net monthly credit changed by Rs{abs(delta):,.0f} ({'lower' if fell else 'higher'}) after {boundary.isoformat()}."]

    # not enrolled at all
    if not emp.uan or emp.is_employed is False:
        return Finding("NO_STATUTORY_RECORD",
            obs + ["No active EPF record was found against this identity."],
            "low",
            caveats + ["Absence of a record is not proof of non-enrolment; records can lag or be held under different identifiers."],
            "Check your UAN on the EPFO member portal, or ask your employer whether you are enrolled.",
            delta)

    if emp.is_recent is None:
        return Finding("FILING_STATUS_UNKNOWN", obs + ["Filing status was not returned."], "low",
                       caveats, "Check your EPF passbook directly.", delta)

    if emp.is_recent:
        state = "CONSISTENT" if fell else "NO_CONCERN"
        obs.append("Statutory records show PF filing activity within the last two months.")
        conf = "moderate" if not caveats else "low"
        return Finding(state, obs, conf,
            caveats + ["Filing activity does not confirm the amount filed, or that funds were received."],
            "Your passbook should show the matching credit. Worth confirming the amount.", delta)

    # is_recent False -- the sensitive branch. Deliberately NOT an accusation.
    obs.append("Statutory records show no PF filing activity recorded in the last two months.")
    caveats = caveats + [
        "Filing records can lag by several weeks; a recent filing may not appear yet.",
        "This does not establish whether any amount was deducted from your pay, nor whether your employer has or has not paid.",
    ]
    conf = "low" if (caveats and (variability or 0) > 0.15) else "moderate"
    return Finding("NEEDS_VERIFICATION", obs, conf, caveats,
        "Open your EPF passbook on the EPFO member portal and check the last two months. If a contribution is genuinely missing, EPFiGMS is the free grievance route.",
        delta)
