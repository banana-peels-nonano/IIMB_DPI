"""
Counterparty Mirror - Batch 1b tests. One test per product or governance promise.
The number in each docstring is the Batch 1b acceptance criterion it proves.

  python -m unittest mirror.test_batch1b -v                 (synthetic only)
  MIRROR_DATA=<path to sealed decrypted.json> python -m unittest mirror.test_batch1b -v
"""
import dataclasses, json, os, unittest
from datetime import date

from mirror.cards import Card, Evidence as E, Question, Deadline, CardInvalid, PAN_RX
from mirror.rules import RULES, RULEBOOK_VERSION, rule_ref, PURPOSE_AA_PROTECT
from mirror.language import gate, render, UnsafeLanguage
from mirror.liquidity import revealed_liquidity
from mirror.corpus import Txn, load
from mirror.evaluate import evaluate, grace_end, reporting_reference_dates

DATA = os.environ.get("MIRROR_DATA")
PROV = {"corpus_sha256": "X", "rulebook_version": RULEBOOK_VERSION, "engine": "t", "as_of": "2026-01-01"}


def good_card(**over):
    """A minimal valid CLOCK card; tests break one rule at a time."""
    kw = dict(
        id="C-1", type="CLOCK", code="LIC_GRACE_CLOCK", member="A", account="XXXX0001", subject="OB-1",
        as_of="2026-01-01", provenance=PROV,
        evidence=(E("o", "O", "RETURN_CHARGE_POSTED", {"charge": 590}, txn_ids=("t1",)),
                  E("r", "R", "GRACE_RULE", {}, rule=rule_ref("LIC_GRACE")),
                  E("i", "I", "LINKED_TO_PAYMENT", {}, based_on=("o",)),
                  E("u", "U", "DUE_DATE", {}, resolved_by="q")),
        claim=("o", "r", "i"),
        deadline=Deadline("2026-02-01", basis=("r",), conditional_on=("u",)),
        question=Question("q", "LIC_RETURN_CONFIRM", ("already_paid",), resolves=("u",)))
    kw.update(over)
    return Card(**kw)


class Rulebook(unittest.TestCase):
    def test_rules_are_versioned_cited_data(self):
        """1. Every rule is data with id, version, citation, source, last-verified date, purpose."""
        need = {"version", "name", "purpose", "output", "applies_to", "trigger_facts", "required_facts",
                "params", "citation", "source", "last_verified", "uncertainty"}
        self.assertEqual(set(RULES), {"LIC_GRACE", "RBI_IRACP_OVERDUE", "CIC_REPORTING_CADENCE"})
        for rid, r in RULES.items():
            self.assertFalse(need - set(r), f"{rid} missing {need - set(r)}")
            self.assertTrue(all(not callable(v) for v in r.values()), f"{rid} contains logic")

    def test_lic_grace_follows_the_published_wording(self):
        """1. 'one month but not less than 30 days' (non-monthly) and 15 days (monthly)."""
        self.assertEqual(grace_end(date(2026, 8, 22), 3), date(2026, 9, 22))   # one month > 30 days
        self.assertEqual(grace_end(date(2026, 2, 1), 3), date(2026, 3, 3))     # 30 days > one month (Feb)
        self.assertEqual(grace_end(date(2026, 8, 7), 1), date(2026, 8, 22))    # monthly: 15 days

    def test_bureau_reporting_dates_follow_the_rule_in_force(self):
        """1. Fortnightly (15th/last) until 30 Jun 2026; 9th/16th/23rd/last from 1 Jul 2026."""
        self.assertEqual(reporting_reference_dates(date(2026, 4, 1), date(2026, 4, 30)),
                         [date(2026, 4, 15), date(2026, 4, 30)])
        self.assertEqual(reporting_reference_dates(date(2026, 7, 1), date(2026, 7, 31)),
                         [date(2026, 7, 9), date(2026, 7, 16), date(2026, 7, 23), date(2026, 7, 31)])


class CardContract(unittest.TestCase):
    def test_valid_card_is_accepted(self):
        self.assertEqual(good_card().type, "CLOCK")

    def test_observed_needs_transactions(self):
        """4. O without transaction ids (and not an absence) cannot exist."""
        with self.assertRaises(CardInvalid):
            good_card(evidence=(E("o", "O", "X", {}),) + good_card().evidence[1:])

    def test_absence_must_be_inside_the_data_window(self):
        """4/13. 'Not collected' is only observed where we actually have data."""
        bad = E("a", "O", "NOT_COLLECTED", {"absence": {"from": "2026-09-01", "to": "2026-09-30",
                                                          "account_data_until": "2026-09-07"}})
        with self.assertRaises(CardInvalid):
            good_card(evidence=good_card().evidence + (bad,))

    def test_rule_must_exist_at_that_version(self):
        """5. R must name a rule@version in the rulebook."""
        ev = list(good_card().evidence)
        ev[1] = E("r", "R", "GRACE_RULE", {}, rule="LIC_GRACE@0")
        with self.assertRaises(CardInvalid):
            good_card(evidence=tuple(ev))

    def test_inference_must_state_its_basis_and_not_rest_on_unknowns(self):
        """6/7. I needs based_on; I may not be built on U."""
        ev = list(good_card().evidence)
        ev[2] = E("i", "I", "LINKED_TO_PAYMENT", {})
        with self.assertRaises(CardInvalid):
            good_card(evidence=tuple(ev))
        ev[2] = E("i", "I", "LINKED_TO_PAYMENT", {}, based_on=("u",))
        with self.assertRaises(CardInvalid):
            good_card(evidence=tuple(ev))

    def test_unknowable_can_never_be_asserted(self):
        """7. The claim may not include U."""
        with self.assertRaises(CardInvalid):
            good_card(claim=("o", "u"))

    def test_unknowable_needs_a_question(self):
        """8. U without a question resolving it cannot exist."""
        with self.assertRaises(CardInvalid):
            good_card(question=None)
        with self.assertRaises(CardInvalid):
            good_card(question=Question("q", "LIC_RETURN_CONFIRM", ("already_paid",), resolves=()))

    def test_deadline_exposes_its_dependency(self):
        """9. With unknowns on the card, a deadline must say which ones it depends on."""
        with self.assertRaises(CardInvalid):
            good_card(deadline=Deadline("2026-02-01", basis=("r",)))
        with self.assertRaises(CardInvalid):
            good_card(deadline=Deadline("2026-02-01", basis=("o",), conditional_on=("u",)))

    def test_no_pan_or_personal_fields_on_a_card(self):
        """17. PAN/DOB/email/address/mobile cannot enter a card."""
        for data in ({"note": "ABCDE1234F"}, {"dob": "1990-01-01"}, {"email": "x"}, {"note": "919876543210"}):
            with self.assertRaises(CardInvalid):
                good_card(evidence=(E("o", "O", "X", data, txn_ids=("t1",)),) + good_card().evidence[1:])


class Gate(unittest.TestCase):
    def test_banned_claims_raise(self):
        """15/16. Unsupported claims raise; they are never just warned about."""
        for text in ("Your loan is an NPA.", "Your account is in default.", "The policy has lapsed.",
                     "Your credit report shows a late payment.", "You are eligible for PMJJBY.",
                     "Your balance is 4,000.", "Your monthly income is 36,000.", "Your L&T loan",
                     "Your loan is overdue.", "Your deadline is 22 Sep.", "PAN ABCDE1234F",
                     "account 123456789012"):
            with self.assertRaises(UnsafeLanguage, msg=text):
                gate(text)

    def test_safe_conditional_language_passes(self):
        self.assertTrue(gate("If this premium was due on 22 Aug, the grace period ends around 22 Sep."))

    def test_unsafe_data_value_is_caught_at_render_time(self):
        """16. Even a valid card is blocked if its data would produce an unsafe sentence."""
        c = good_card(code="COLLECTION_GAP_QUESTION", type="QUESTION", claim=("o",),
                      evidence=(E("e_hist", "O", "COLLECTION_HISTORY",
                                  {"counterparty": "DEFAULTED LOAN CO", "usual_day": 5, "amount_last": 100.0},
                                  txn_ids=("t1",)),
                                E("e_none", "O", "NOT_COLLECTED", {"periods": ["2026-01"], "absence": {
                                    "from": "2026-01-01", "to": "2026-01-31", "account_data_until": "2026-02-01"}}),
                                E("u", "U", "REASON_FOR_GAP", {}, resolved_by="q"), E("o", "O", "X", {}, txn_ids=("t",))),
                      deadline=None, question=Question("q", "GAP_REASON", ("not_sure",), resolves=("u",)))
        with self.assertRaises(UnsafeLanguage):
            render(c)


class Liquidity(unittest.TestCase):
    def test_range_from_outcomes_only(self):
        """13. A range from debits that went through and one return - no balances involved."""
        t = [Txn("a", 0, date(2026, 1, 1), "DEBIT", 100.0, "x", "", ""),
             Txn("b", 1, date(2026, 1, 2), "CREDIT", 50.0, "y", "", ""),
             Txn("c", 2, date(2026, 1, 5), "DEBIT", 30.0, "z", "", "")]
        r = revealed_liquidity("A", t, at_end_of=date(2026, 1, 6),
                               returned={"date": date(2026, 1, 4), "amount": 70.0, "trace_id": "T"})
        # B0 >= 100 (first debit); before the 4 Jan return the account held B0-50 < 70 -> B0 < 120
        self.assertEqual((r.low, r.high), (20.0, 40.0))
        self.assertEqual(r.evidence_class, "I")
        self.assertNotIn("balance", {f.name for f in dataclasses.fields(Txn)})


@unittest.skipUnless(DATA, "set MIRROR_DATA to the sealed decrypted.json")
class OnCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = load(DATA)
        cls.john, cls.kiran = cls.c.account("9741"), cls.c.account("9648")
        cls.all_ids = {t.txn_id for a in cls.c.accounts for t in a.txns}

    def run_(self, acc, d):
        return evaluate(self.c, acc, d)

    def test_john_lic_conditional_clock(self):
        """2/9. John 28 Aug: one LIC grace CLOCK, deadline 22 Sep, conditional on due date and payment."""
        cards = self.run_(self.john, date(2026, 8, 28))
        self.assertEqual([c.code for c in cards], ["LIC_GRACE_CLOCK"])
        c = cards[0]
        self.assertEqual(c.deadline.date, "2026-09-22")
        self.assertEqual({c.ev(u).code for u in c.deadline.conditional_on}, {"DUE_DATE", "PAID_ANOTHER_WAY"})
        self.assertTrue(c.subject.endswith("-3M"), "must be the quarterly instance, not the monthly one")

    def test_john_590_charge_links_only_after_it_posts(self):
        """2. The 590 charge is on the card from 28 Aug; on 27 Aug there is nothing to say."""
        self.assertEqual(self.run_(self.john, date(2026, 8, 27)), [])
        c = self.run_(self.john, date(2026, 8, 28))[0]
        ret = c.ev("e_ret")
        self.assertEqual((ret.data["charge"], ret.data["return_date"]), (590.0, "2026-08-22"))
        self.assertEqual(c.ev("e_link").cls, "I")

    def test_john_revealed_liquidity(self):
        """10. End of 7 Sep: 14,749-18,605 (accepted range)."""
        c = self.run_(self.john, date(2026, 9, 7))[0]
        liq = c.ev("e_liq").data
        self.assertEqual(liq["point"], "end of 2026-09-07")
        self.assertAlmostEqual(liq["low"], 14749.20, places=2)
        self.assertAlmostEqual(liq["high"], 18604.84, places=2)
        self.assertEqual(c.ev("e_liq").cls, "I")

    def test_kiran_weak_link_is_only_a_question(self):
        """11. 1 Dec: the return is asked about; no clock, nothing asserted about the loan."""
        cards = self.run_(self.kiran, date(2025, 12, 1))
        self.assertEqual([(c.type, c.code) for c in cards], [("QUESTION", "RETURN_LINK_QUESTION")])
        self.assertEqual(cards[0].claim, ("e_ret",))

    def test_kiran_loan_clock_is_rules_implied_and_conditional(self):
        """9. 21 Apr: RBI-rule clock stated under assumptions, which are U and asked about."""
        c = self.run_(self.kiran, date(2026, 4, 21))[0]
        self.assertEqual(c.code, "LOAN_OVERDUE_CLOCK")
        self.assertEqual(c.deadline.data["passed_30_days_on"], ["2026-01-20", "2026-02-20", "2026-04-20"])
        self.assertEqual(c.deadline.date, "2026-04-30")
        self.assertEqual({c.ev(u).cls for u in c.deadline.conditional_on}, {"U"})
        self.assertAlmostEqual(c.ev("e_liq").data["low"], 25709.97, places=2)

    def test_may_to_july_is_a_question_not_a_lender_status(self):
        """12. 28 Aug: the May-Jul absence is asked about; no loan clock is computed across it."""
        cards = self.run_(self.kiran, date(2026, 8, 28))
        self.assertTrue(cards)
        self.assertTrue(all(c.type == "QUESTION" for c in cards))
        ind = [c for c in cards if "INDUSIND" in c.subject][0]
        self.assertEqual(ind.ev("e_none").data["periods"], ["2026-05", "2026-06", "2026-07"])

    def test_every_card_is_traceable(self):
        """3/4/5. Provenance on every card; every O txn id exists in the corpus; R at a real version."""
        for acc, d in ((self.john, date(2026, 9, 7)), (self.kiran, date(2025, 12, 1)),
                       (self.kiran, date(2026, 4, 21)), (self.kiran, date(2026, 8, 28))):
            for c in self.run_(acc, d):
                self.assertEqual(c.provenance["corpus_sha256"], self.c.sha256)
                for e in c.evidence:
                    self.assertIn(e.cls, "ORIU")
                    self.assertTrue(set(e.txn_ids) <= self.all_ids)
                render(c)                                     # 15: every real card passes the gate

    def test_quiet_and_refused_households(self):
        """Kumar has nothing to flag; Naveen's padded data produces nothing; no consent -> nothing."""
        self.assertEqual(self.run_(self.c.account("9950"), date(2026, 9, 22)), [])
        self.assertEqual(self.run_(self.c.account("9960"), date(2026, 9, 22)), [])
        self.assertEqual(evaluate(self.c, self.john, date(2026, 9, 7), purposes=frozenset()), [])

    def test_no_pan_income_or_balance_in_any_output(self):
        """14/17. Serialised cards and rendered text carry no PAN. (Income and balance claims
        cannot appear either: every rendered text here passed gate(), which bans them.)"""
        blobs = []
        for acc, d in ((self.john, date(2026, 9, 7)), (self.kiran, date(2026, 4, 21))):
            for c in self.run_(acc, d):
                blobs.append(json.dumps(dataclasses.asdict(c)))
                blobs.extend(render(c))
        blob = "\n".join(blobs)
        self.assertFalse(PAN_RX.search(blob), "a PAN-shaped string reached derived output")

    def test_deterministic_and_stable_ids(self):
        """Same inputs -> identical cards; the same situation keeps its id across replay dates."""
        a = self.run_(self.john, date(2026, 9, 7))
        self.assertEqual(a, self.run_(self.john, date(2026, 9, 7)))
        self.assertEqual(a[0].id, self.run_(self.john, date(2026, 8, 28))[0].id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
