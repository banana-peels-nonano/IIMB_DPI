"""
Counterparty Mirror - Rulebook (DATA ONLY).

This file holds what institutions have PUBLISHED, in a form the evaluator can
read. It contains no decisions. If a rule changes, edit its entry, bump its
version and last_verified date; every card produced afterwards names the new
version.

Three kinds of entries, deliberately kept apart:
  RULES                 - published by a regulator/insurer. Cited. Evidence class R.
  CONTRACT_PARAMETERS   - terms of a household's own contract that the bank data
                          cannot show. They have a stated default, but the
                          default is NEVER evidence: class U until the customer
                          or the institution confirms it.
  PRODUCT_POLICIES      - how WE choose to behave (e.g. ask instead of assert).
                          Not evidence of anything about the household.

Purpose tags: a rule runs only if its purpose is covered by the consent the
customer gave. All three Protect rules sit under the AA consent's purpose.
"""

RULEBOOK_VERSION = "2026-09-26"

PURPOSE_AA_PROTECT = "AA_PROTECT"   # AA consent, purpose code 102, FI type DEPOSIT

RULES = {
    "LIC_GRACE": {
        "version": "1",
        "name": "LIC premium grace period",
        "purpose": PURPOSE_AA_PROTECT,
        "output": "CLOCK",
        "applies_to": "LIC of India policies under LIC's standard policy conditions",
        "trigger_facts": ["a collection to 'LIC OF INDIA' was returned or not collected in an expected period"],
        "required_facts": ["premium mode (from the observed cadence)",
                           "premium due date (not in bank data: U until confirmed)"],
        "params": {
            "non_monthly": {"months": 1, "min_days": 30},   # yearly / half-yearly / quarterly
            "monthly_days": 15,
        },
        "citation": ("LIC of India, Policy Conditions: 'A grace period of one month but not "
                     "less than 30 days is allowed where the mode of payment is yearly, "
                     "half-yearly or quarterly and 15 days for monthly payments.'"),
        "source": "https://licindia.in/policy-conditions",
        "last_verified": "2026-09-26",
        "uncertainty": [
            "The policy document governs; a specific policy may state different terms.",
            "The grace period runs from the premium due date, which bank data does not show "
            "(LIC's conditions page does not state the start date; policy documents count "
            "from the due date).",
            "Whether the premium was paid another way (branch, online) is not visible to us.",
        ],
    },
    "RBI_IRACP_OVERDUE": {
        "version": "2025-11-28",
        "name": "RBI overdue classification by day-end process",
        "purpose": PURPOSE_AA_PROTECT,
        "output": "CLOCK",
        "applies_to": "loans from commercial banks",
        "trigger_facts": ["a loan instalment collection was returned"],
        "required_facts": ["instalment due date (observed collection day is a proxy: I)",
                           "how the lender applies payments (contract parameter: U)",
                           "whether anything was paid another way (U)"],
        "params": {
            "overdue": "an amount not paid on the due date fixed by the lender is overdue",
            "classified_at": "day-end process of the relevant date",
            # days continuously overdue at which a tag is applied at day-end
            # (RBI illustration: overdue 31 Mar 2021 -> SMA-1 on 30 Apr 2021)
            "sma_1_after_days": 30,
            "sma_2_after_days": 60,
            "third_stage_after_days": 90,   # stored for completeness; never rendered as a label
            "upgrade": "only when the entire arrears of interest and principal are paid",
        },
        "citation": ("RBI (Commercial Banks - Income Recognition, Asset Classification and "
                     "Provisioning) Directions, 2025, RBI/DOR/2025-26/164, 28 Nov 2025; "
                     "illustration from RBI/2021-2022/125, 12 Nov 2021: overdue on 31 Mar 2021 "
                     "-> SMA-1 at day-end 30 Apr 2021, SMA-2 at day-end 30 May 2021."),
        "source": "https://rbi.org.in (Directions RBI/DOR/2025-26/164; circular RBI/2021-2022/125)",
        "last_verified": "2026-09-26",
        "uncertainty": [
            "Applies to commercial banks; NBFC loans follow parallel RBI directions not encoded here.",
            "The lender's actual account status is not visible to us; we compute what the "
            "published rule implies under stated assumptions.",
            "An agreed restructuring, moratorium or other arrangement changes the outcome.",
        ],
    },
    "CIC_REPORTING_CADENCE": {
        "version": "2",
        "name": "When lenders report to credit bureaus",
        "purpose": PURPOSE_AA_PROTECT,
        "output": "CONTEXT",
        "applies_to": "banks and NBFCs reporting to credit information companies",
        "trigger_facts": ["a rules-implied overdue state exists on a loan"],
        "required_facts": ["date"],
        "params": {
            # dated schedule: the evaluator picks the entry in force on the date
            "schedule": [
                {"effective_from": "2025-01-01", "effective_to": "2026-06-30",
                 "reference_days": [15, "last"],
                 "citation": "RBI/2024-25/60, DoR.FIN.REC.No.32/20.16.056/2024-25, 8 Aug 2024 "
                             "(fortnightly, as on 15th and last day; submit within 7 days)"},
                {"effective_from": "2026-07-01", "effective_to": None,
                 "reference_days": [9, 16, 23, "last"],
                 "citation": "RBI/DOR/2025-26/110 (commercial banks) and RBI/DOR/2025-26/117 "
                             "(NBFCs), 4 Dec 2025: as on 9th, 16th, 23rd and last day; "
                             "incremental within 4 days, full file by the 5th"},
            ],
        },
        "citation": "RBI credit information reporting directions (see schedule entries)",
        "source": "https://rbi.org.in",
        "last_verified": "2026-09-26",
        "uncertainty": ["What a lender actually reported is not visible to us."],
    },
}

CONTRACT_PARAMETERS = {
    "PAYMENT_ALLOCATION_ORDER": {
        "default": "oldest_first",
        "why_default": "common lender practice; not a published rule",
        "evidence_class_until_confirmed": "U",
        "confirmed_by": ["customer (from the lender's answer)", "lender"],
    },
    "PREMIUM_DUE_DATE": {
        "default": "the date the collection was presented",
        "why_default": "collections are usually presented on or near the due date",
        "evidence_class_until_confirmed": "U",
        "confirmed_by": ["customer (from the policy document)", "insurer"],
    },
}

PRODUCT_POLICIES = {
    "ASK_ON_UNEXPLAINED_GAP": ("An expected collection with no debit AND no return charge "
                               "is asked about, never interpreted as a lender status."),
    "ASK_ON_WEAK_LINK": "A return linked only weakly to a payment produces a question, never a clock.",
    "NO_STATE_ACROSS_GAP": ("A rules-implied loan state is not computed across an unexplained gap; "
                            "the gap is asked about first."),
}


def rule_ref(rule_id: str) -> str:
    """The exact string an R evidence item must carry, e.g. 'LIC_GRACE@1'."""
    return f"{rule_id}@{RULES[rule_id]['version']}"


def known_rule_refs() -> set:
    return {rule_ref(r) for r in RULES}
