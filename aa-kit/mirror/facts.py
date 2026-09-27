"""
Counterparty Mirror - Household facts the customer tells us (Gate 4).

A household fact is a short, bounded answer - an age BAND, a yes/no - that a
published rule needs and bank data cannot show. It is:

  * asked only when its answer opens or closes something (the evaluator decides
    when; this file only says what may be asked and what each answer feeds);
  * stored as the customer's statement - evidence class U, "you told us" -
    never promoted to an observation, never used to build an inference;
  * scoped to one purpose (government protections, or the LPG check - the
    three questions that exist only because of the oil company's record), and
    forgotten when that purpose is switched off;
  * correctable: a later statement replaces an earlier one, the old value is
    kept in the correction history, and every rule that used it is re-run.

The value sets are closed. There is no free text, no date of birth, and nothing
outside what PURPOSES in rules.py says each purpose may use.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from datetime import date

from .rules import PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG

# Age bands are cut exactly at the published limits (18, 40, 50, 70), so a band is
# always wholly inside or wholly outside each scheme's range - never "partly".
AGE_BANDS = {"under_18": (0, 17), "18_40": (18, 40), "41_50": (41, 50), "51_70": (51, 70), "over_70": (71, 150)}

FACTS = {
    "AGE_BAND": {
        "scope": "member", "purpose": PURPOSE_GOV_PROTECT,
        "values": {"under_18": "Under 18", "18_40": "18–40", "41_50": "41–50", "51_70": "51–70",
                   "over_70": "Over 70"},
        "feeds": ["PMSBY", "PMJJBY", "APY"],
        "why": "government protections have age limits; a band is enough - we never ask for a date of birth",
    },
    "TAXPAYER": {
        "scope": "member", "purpose": PURPOSE_GOV_PROTECT,
        "values": {"yes": "Yes", "no": "No", "not_sure": "Not sure"},
        "feeds": ["APY"],
        "why": "APY is closed to anyone who is or has been an income-tax payer; asked only if the age band fits",
    },
    "COVERED_ELSEWHERE": {
        "scope": "member_scheme", "purpose": PURPOSE_GOV_PROTECT,
        "values": {"yes": "Yes, through another account", "no": "No", "not_sure": "Not sure"},
        "feeds": ["PMSBY", "PMJJBY", "APY"],
        "why": "we only see the accounts you connect; cover through another bank is invisible to us",
    },
    "LPG_REFILLS": {
        "scope": "member", "purpose": PURPOSE_GOV_PROTECT,
        "values": {"no_refills": "No refills since then", "still_booking": "Yes, still booking refills",
                   "not_sure": "Not sure"},
        "feeds": ["PAHAL_DBTL"],
        "why": "no refills means no subsidy was due - the innocent explanation",
    },
    "SUBSIDY_ACCOUNT": {
        "scope": "member", "purpose": PURPOSE_GOV_PROTECT,
        "values": {"one_i_connected": "One of the accounts I connected", "another_account": "Another account",
                   "not_sure": "Not sure"},
        "feeds": ["PAHAL_DBTL", "APB_MAPPER"],
        "why": "government transfers go to the bank where the Aadhaar number was given last",
    },
    "ROUTED_ACCOUNT_STATUS": {
        "scope": "member", "purpose": PURPOSE_DPI_LPG,
        "values": {"mine_in_use": "It's mine and I use it", "old_not_in_use": "It's old / I don't use it",
                   "not_mine": "It isn't mine"},
        "feeds": ["APB_MAPPER"],
        "why": "only you know whether the account the record names is one you still use",
    },
    "DISTRIBUTOR_ANSWER": {
        "scope": "member", "purpose": PURPOSE_DPI_LPG,
        "values": {"says_paid": "They say it was paid", "says_none_due": "They say none was due",
                   "not_asked": "I haven't asked yet"},
        "feeds": ["PAHAL_DBTL"],
        "why": "the record points to your own account; only the distributor knows why nothing arrived",
    },
    "SUBSIDY_GIVEN_UP": {
        "scope": "member", "purpose": PURPOSE_DPI_LPG,
        "values": {"chose_to": "Yes, we chose to", "did_not": "No, we didn't", "not_sure": "Not sure"},
        "feeds": ["PAHAL_DBTL"],
        "why": "the oil company's record can mark a subsidy as given up; only you know if that was your choice",
    },
}


class FactInvalid(Exception):
    """A statement with an unknown fact code, value or scope. Nothing is stored."""


@dataclass(frozen=True)
class FactStatement:
    account: str                 # masked account of the member the fact is about
    code: str
    value: str
    stated_on: date
    scheme: str | None = None    # only for member_scheme facts
    via_card: str | None = None  # the card whose question it answered, if any

    @property
    def key(self) -> tuple:
        return (self.account, self.code, self.scheme)

    @property
    def id(self) -> str:
        return "HF-" + hashlib.sha256("|".join(map(str, self.key)).encode()).hexdigest()[:10]

    def label(self) -> str:
        return FACTS[self.code]["values"][self.value]


@dataclass(frozen=True)
class Correction:
    fact_id: str
    code: str
    account: str
    scheme: str | None
    old_value: str
    new_value: str
    stated_on: date


def check(s: FactStatement) -> FactStatement:
    spec = FACTS.get(s.code)
    if spec is None:
        raise FactInvalid(f"unknown fact {s.code!r}")
    if s.value not in spec["values"]:
        raise FactInvalid(f"{s.code}: {s.value!r} is not one of {sorted(spec['values'])}")
    if (spec["scope"] == "member_scheme") != (s.scheme is not None):
        raise FactInvalid(f"{s.code}: scheme must be given exactly when the fact is per scheme")
    return s


def apply(current: tuple, statements: list) -> tuple:
    """(current facts, new statements in date order) -> (facts, corrections, fresh).
    A statement with the same key replaces the earlier one; if the value differs,
    the change is kept as a Correction. Same key + same value is a no-op."""
    by_key = {f.key: f for f in current}
    corrections, fresh = [], []
    for s in statements:
        check(s)
        old = by_key.get(s.key)
        if old is not None and old.value == s.value:
            continue
        if old is not None:
            corrections.append(Correction(s.id, s.code, s.account, s.scheme, old.value, s.value, s.stated_on))
        by_key[s.key] = s
        fresh.append(s)
    return tuple(sorted(by_key.values(), key=lambda f: f.key)), tuple(corrections), tuple(fresh)


def lookup(facts: tuple, account: str, code: str, scheme: str | None = None) -> FactStatement | None:
    return next((f for f in facts if f.key == (account, code, scheme)), None)


def band_in_range(band: str, lo: int, hi: int) -> bool | None:
    """True if the whole band is inside [lo, hi], False if wholly outside, None if it straddles."""
    b_lo, b_hi = AGE_BANDS[band]
    if lo <= b_lo and b_hi <= hi:
        return True
    if b_hi < lo or b_lo > hi:
        return False
    return None
