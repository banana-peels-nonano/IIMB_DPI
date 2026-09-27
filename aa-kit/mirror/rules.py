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

Gate 4 adds STATE_RULES: rules the STATE has published for its own protection
schemes (PMSBY, PMJJBY, APY, PMUY) and for how its subsidies travel (PAHAL,
the Aadhaar Payment Bridge mapper). Same schema, same evidence class (R), same
citation discipline - one rulebook, two books. They run only under their own
purpose, which the customer switches on separately from the AA consent.
"""

RULEBOOK_VERSION = "2026-09-27"

PURPOSE_AA_PROTECT = "AA_PROTECT"   # AA consent, purpose code 102, FI type DEPOSIT
PURPOSE_GOV_PROTECT = "GOV_PROTECT"  # separate toggle: "Check government protections for my household"
PURPOSE_DPI_LPG = "DPI_LPG_CHECK"    # separate, per-lookup: "Check my LPG record with the oil company"

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


# ---------------------------------------------------------------------------
# STATE_RULES (Gate 4). Published by the Government of India for its own schemes.
# Primary sources are the Department of Financial Services (DFS) scheme pages and
# PIB; where only a secondary copy of a notification was reachable, the entry says so.
# ---------------------------------------------------------------------------
STATE_RULES = {
    "PMSBY": {
        "version": "1",
        "name": "Pradhan Mantri Suraksha Bima Yojana (accident cover)",
        "purpose": PURPOSE_GOV_PROTECT,
        "output": "DOOR",
        "applies_to": "people with a bank account",
        "trigger_facts": ["no PMSBY premium debit seen in a connected account across a full cover year"],
        "required_facts": ["age band (customer)", "already covered through another account (customer)"],
        "params": {"age_min": 18, "age_max": 70, "premium_inr": 20,
                   "cover_inr": {"death_or_permanent_total_disability": 200000, "partial_disability": 100000},
                   "cover_year_starts": "06-01", "cover_year_ends": "05-31",
                   "payment": "auto-debit from the subscriber's bank account"},
        "citation": ("DFS, PMSBY (updated 05.02.2026): 'people in the age group of 18 to 70 years having a "
                     "bank account'; 'Annual premium is Rs 20 per year'; cover period '1st June to 31st May'; "
                     "'Rs. 2 Lakh payable on death or permanent total disability and Rs. 1 Lakh on partial "
                     "disability'; premium paid 'through auto-debit'. PIB, 9 May 2026 (same age range and premium)."),
        "source": "https://financialservices.gov.in/pradhan-mantri-suraksha-bima-yojana-pmsby",
        "last_verified": "2026-09-27",
        "uncertainty": [
            "Only the bank or insurer decides an enrolment; we never state that someone can or cannot join.",
            "Premiums are revised from time to time; an older debit can show an older premium.",
            "A debit we cannot see (another bank, the post office) is invisible to us.",
        ],
    },
    "PMJJBY": {
        "version": "1",
        "name": "Pradhan Mantri Jeevan Jyoti Bima Yojana (life cover)",
        "purpose": PURPOSE_GOV_PROTECT,
        "output": "DOOR",
        "applies_to": "individual account holders of participating banks / post office",
        "trigger_facts": ["no PMJJBY premium debit seen in a connected account across a full cover year"],
        "required_facts": ["age band (customer)", "already covered through another account (customer)"],
        "params": {"age_min": 18, "age_max": 50, "cover_until_age": 55, "premium_inr": 436,
                   "cover_inr": 200000, "cover_year_starts": "06-01", "cover_year_ends": "05-31",
                   "first_days_without_non_accident_cover": 30, "accounts_allowed": 1},
        "citation": ("DFS, PMJJBY (updated 05.01.2026): account holders 'in the age group of 18 to 50 years'; "
                     "'Rs.436/- per annum'; 'Rs.2 lakh is payable on a subscriber's death due to any cause'; "
                     "cover '1st June to 31st May'; ends 'On attaining age 55 years'; no cover for death "
                     "(other than accident) 'during the first 30 days from the date of enrolment'; "
                     "'through one bank / Post office account only'."),
        "source": "https://financialservices.gov.in/pmjjby",
        "last_verified": "2026-09-27",
        "uncertainty": [
            "Only the bank or insurer decides an enrolment; we never state that someone can or cannot join.",
            "Cover also ends if the account is closed or has too little money at renewal (DFS).",
        ],
    },
    "APY": {
        "version": "1",
        "name": "Atal Pension Yojana (pension)",
        "purpose": PURPOSE_GOV_PROTECT,
        "output": "DOOR",
        "applies_to": "savings account holders",
        "trigger_facts": ["no APY contribution debit seen in a connected account"],
        "required_facts": ["age band (customer)", "income-tax payer, now or ever (customer)",
                           "already enrolled through another account (customer)"],
        "params": {"age_min": 18, "age_max": 40, "excludes_income_tax_payers_from": "2022-10-01",
                   "contribution_modes": ["monthly", "quarterly", "half-yearly"],
                   "late_charge": "Rs 1 per month for every Rs 100 of a delayed monthly contribution",
                   "pension_options_inr": [1000, 2000, 3000, 4000, 5000], "pension_from_age": 60},
        "citation": ("DFS, APY (updated 05.01.2026): 'The age of the subscriber should be between 18 and 40 "
                     "years'; contributions 'monthly / quarterly / half yearly ... through auto debit'; "
                     "Rs. 1 per month per Rs. 100 for delayed monthly contributions; pension Rs 1,000-5,000 a "
                     "month at 60. PIB, 9 May 2026 (PRID 2259251): APY is for bank account holders who are non-income-tax "
                     "payers. MoF notification of 10 Aug 2022 (reported copies; the gazette text itself was "
                     "not reachable): from 1 Oct 2022 'any citizen who is or has been an income-tax payer' "
                     "may not join."),
        "source": "https://financialservices.gov.in/atal-pension-yojana",
        "last_verified": "2026-09-27",
        "uncertainty": [
            "The 2022 taxpayer notification was read through secondary copies; reports differ on what "
            "happens to people who joined earlier (not relevant to a new joining check).",
            "Only the bank decides an enrolment; we never state that someone can or cannot join.",
        ],
    },
    "PMUY": {
        "version": "1",
        "name": "Pradhan Mantri Ujjwala Yojana (new LPG connection)",
        "purpose": PURPOSE_GOV_PROTECT,
        "output": "SUPPRESSION",
        "applies_to": "households without an LPG connection",
        "trigger_facts": ["LPG subsidy credits seen in a connected account"],
        "required_facts": [],
        "params": {"requires_no_lpg_connection_in_household": True},
        "citation": ("PMUY, Ujjwala 2.0 conditions: 'There should be no other LPG connection from any Oil "
                     "Marketing Company (OMC) within the same household' (other conditions: an adult woman "
                     "applicant; a deprivation declaration)."),
        "source": "https://www.pmuy.gov.in/ujjwala2.html",
        "last_verified": "2026-09-27",
        "uncertainty": ["We use only the 'no existing connection' condition, and only to explain why we "
                        "do not show the scheme. We never collect or infer the other conditions."],
    },
    "PAHAL_DBTL": {
        "version": "1",
        "name": "PAHAL: LPG subsidy paid into the consumer's bank account",
        "purpose": PURPOSE_GOV_PROTECT,
        "output": "QUESTION",
        "applies_to": "LPG consumers who joined PAHAL (DBTL)",
        "trigger_facts": ["a run of LPG subsidy credits that stops"],
        "required_facts": ["whether refills were booked since (customer or oil company record)",
                           "which bank account the subsidy is paid into (oil company record)"],
        "params": {"min_credits_seen": 3, "stopped_after_days_min": 60, "stopped_after_gap_multiple": 2},
        "citation": ("PIB, launch of PAHAL (DBTL), 1 Jan 2015: consumers buy cylinders at market price and "
                     "'subsidy will be transferred into their bank account'; joining is by giving the Aadhaar "
                     "number to the distributor and the bank, or bank details / the 17-digit LPG ID."),
        "source": "https://www.pib.gov.in/newsite/printrelease.aspx?relid=114245",
        "last_verified": "2026-09-27",
        "uncertainty": ["Subsidy per cylinder changes over time and can be zero; a stop in credits has "
                        "innocent explanations (no refills, no subsidy due)."],
    },
    "APB_MAPPER": {
        "version": "1",
        "name": "Aadhaar Payment Bridge: which account government transfers go to",
        "purpose": PURPOSE_GOV_PROTECT,
        "output": "CONTEXT",
        "applies_to": "government transfers routed by Aadhaar number (APBS)",
        "trigger_facts": ["APBS credits in a connected account"],
        "required_facts": [],
        "params": {"routes_to": "the bank where the Aadhaar number was given last"},
        "citation": ("Aadhaar Payment Bridge FAQ (UCO Bank, a participating bank): 'The customer Aadhaar "
                     "number will get mapped in NPCI mapper to the bank in which he/she has given the "
                     "Aadhaar number at the last.'"),
        "source": "https://www.uco.bank.in/documents/d/guest/faq-apb",
        "last_verified": "2026-09-27",
        "uncertainty": ["A bank's FAQ, not an NPCI circular; NPCI's own FAQ page was not reachable."],
    },
}

# Purposes as data: what each one lets us use, and what it never uses. The app shows
# these words; the evaluator refuses to run a rule whose purpose is not switched on.
PURPOSES = {
    PURPOSE_AA_PROTECT: {
        "label": "Watch our bank accounts for things that need attention",
        "granted_through": "Account Aggregator consent (purpose code 102)",
        "uses": ["transactions from the accounts you connect"],
        "never_uses": ["balances as evidence", "PAN", "date of birth", "address"],
        "withdraw": "revoke the consent in your AA app, or 'Stop & forget' here",
    },
    PURPOSE_GOV_PROTECT: {
        "label": "Check government protections for our household",
        "granted_through": "a separate switch in this app (not part of the AA consent)",
        "uses": ["scheme debits and subsidy credits we already found in your connected accounts",
                 "an age band you tell us (never a date of birth)",
                 "whether someone pays income tax (asked only if a scheme needs it)",
                 "whether someone is already covered through another account"],
        "never_uses": ["date of birth", "caste", "religion", "disability", "health", "gender",
                       "education", "location", "your income as a figure"],
        "withdraw": "turn the switch off: the answers it used are forgotten",
    },
    PURPOSE_DPI_LPG: {
        "label": "Check our LPG record with the oil company (through Perfios Hub)",
        "granted_through": "a separate, per-lookup consent with your own 17-digit LPG ID",
        "uses": ["your LPG ID, sent once to the oil company's record through Perfios Hub"],
        "never_uses": ["the name, address, phone, email or Aadhaar digits the record returns - we drop them"],
        "withdraw": "turn it off: the record and the ID are forgotten",
    },
}


def _book(rule_id: str) -> dict:
    return RULES.get(rule_id) or STATE_RULES[rule_id]


def rule(rule_id: str) -> dict:
    """Look a rule up in either book."""
    return _book(rule_id)


def rule_ref(rule_id: str) -> str:
    """The exact string an R evidence item must carry, e.g. 'LIC_GRACE@1'."""
    return f"{rule_id}@{_book(rule_id)['version']}"


def known_rule_refs() -> set:
    return {rule_ref(r) for r in list(RULES) + list(STATE_RULES)}
