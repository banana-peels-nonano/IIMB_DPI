"""
"Within an amount you set" (--options): the two published tables the options explorer needs that the
rulebook does not hold. Their own version: RULEBOOK_VERSION (and so the store and the Gate 6 digests)
is not touched. Scheme premiums, covers, age limits and the APY taxpayer rule are READ from
rules.STATE_RULES, never copied here.
"""
OPTIONS_RULES_VERSION = "2026-09-28"

# PMJJBY: the first premium for a new subscriber depends on the month of joining (pro-rata by quarter of the
# cover year that starts on 1 June). Renewals are the full annual premium in rules.STATE_RULES.
PMJJBY_FIRST_PREMIUM = {
    "rows": (  # (months of joining, premium in rupees, label)
        ((6, 7, 8), 436, "June–August"),
        ((9, 10, 11), 342, "September–November"),
        ((12, 1, 2), 228, "December–February"),
        ((3, 4, 5), 114, "March–May"),
    ),
    "source": "https://financialservices.gov.in/pmjjby",
    "source_label": "Department of Financial Services, PMJJBY",
    "citation": ("DFS PMJJBY page (updated 5 Jan 2026): premium for new enrolments is Rs 436 (June-August), "
                 "Rs 342 (September-November), Rs 228 (December-February), Rs 114 (March-May). "
                 "PIB 31 May 2022 (PRID 1829772): annual premium revised to Rs 436 from 1 June 2022."),
    "checked": "2026-09-28",
}

# APY: monthly contribution by age at joining for each guaranteed pension level (Rs 1,000 ... 5,000).
# Monthly figures only: bank-published quarterly / half-yearly charts disagree with each other.
APY_PENSION_LEVELS = (1000, 2000, 3000, 4000, 5000)
APY_MONTHLY = {
    18: (42, 84, 126, 168, 210), 19: (46, 92, 138, 183, 228), 20: (50, 100, 150, 198, 248),
    21: (54, 108, 162, 215, 269), 22: (59, 117, 177, 234, 292), 23: (64, 127, 192, 254, 318),
    24: (70, 139, 208, 277, 346), 25: (76, 151, 226, 301, 376), 26: (82, 164, 246, 327, 409),
    27: (90, 178, 268, 356, 446), 28: (97, 194, 292, 388, 485), 29: (106, 212, 318, 423, 529),
    30: (116, 231, 347, 462, 577), 31: (126, 252, 379, 504, 630), 32: (138, 276, 414, 551, 689),
    33: (151, 302, 453, 602, 752), 34: (165, 330, 495, 659, 824), 35: (181, 362, 543, 722, 902),
    36: (198, 396, 594, 792, 990), 37: (218, 436, 654, 870, 1087), 38: (240, 480, 720, 957, 1196),
    39: (264, 528, 792, 1054, 1318), 40: (291, 582, 873, 1164, 1454),
}
APY_TABLE = {
    "source": "https://pfrda.org.in/documents/33652/145099/17.pdf",
    "source_label": "PFRDA, Atal Pension Yojana contribution chart",
    "citation": ("PFRDA 'APY - Benefits and Features': indicative monthly contribution by entry age 18-40 for "
                 "guaranteed pensions of Rs 1,000-5,000 a month from age 60. Scheme continued to 2030-31 "
                 "(Cabinet, 21 Jan 2026) with no change announced to contributions."),
    "checked": "2026-09-28",
}

# the customer's amount: a closed set, like every other answer Mirror accepts
AMOUNTS = (100, 250, 500, 1000, 2500)

# age bands (the only age Mirror ever holds) -> the joining ages they span
BAND_AGES = {"under_18": None, "18_40": (18, 40), "41_50": (41, 50), "51_70": (51, 70), "over_70": None}


def pmjjby_first_premium(month: int) -> tuple:
    for months, inr, label in PMJJBY_FIRST_PREMIUM["rows"]:
        if month in months:
            return inr, label
    raise ValueError("month out of range")


def _check_tables() -> None:
    """Fail at import if a table is malformed: every month once; APY rises with age and with pension."""
    months = sorted(m for ms, _, _ in PMJJBY_FIRST_PREMIUM["rows"] for m in ms)
    assert months == list(range(1, 13)), "PMJJBY table must cover each month once"
    assert sorted(APY_MONTHLY) == list(range(18, 41)), "APY table must cover ages 18-40"
    for age in range(18, 41):
        row = APY_MONTHLY[age]
        assert len(row) == len(APY_PENSION_LEVELS) and list(row) == sorted(row), f"APY row {age}"
        if age > 18:
            assert all(a > b for a, b in zip(row, APY_MONTHLY[age - 1])), f"APY column rises with age ({age})"


_check_tables()
