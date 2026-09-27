"""
Counterparty Mirror - Gate 2 + 3 tests: time axis, briefing, horizon, app contract.
Each test is one product or governance guarantee.

  python -m unittest mirror.test_gate23 -v                   (synthetic only)
  MIRROR_DATA=<sealed decrypted.json> python -m unittest mirror.test_gate23 -v
"""
import json, os, unittest
from datetime import date

from mirror.corpus import load
from mirror.snapshot import take_snapshot
from mirror.events import advance, initial, Answer, AnswerInvalid, fingerprint
from mirror.briefing import since_last_time, MAX_LINES
from mirror.horizon import horizon
from mirror.contract import build_payload, validate_payload, validate_explanation, PayloadInvalid, SCHEMA
from mirror.language import UnsafeLanguage
from mirror.cards import PAN_RX
from mirror.test_mirror import _xml, _write, FILLER

DATA = os.environ.get("MIRROR_DATA")

# a small household: quarterly LIC collected Jan/Apr/Jul, returned 22 Oct (charge 28 Oct),
# re-collected 30 Oct - so a clock opens and is then cured by evidence
LIC = [("q1", "DEBIT", 4600.0, "ACH/LIC OF INDIA/9118815710119", "r1", "2025-01-23"),
       ("q2", "DEBIT", 4600.0, "ACH/LIC OF INDIA/9118815710419", "r2", "2025-04-23"),
       ("q3", "DEBIT", 4600.0, "ACH/LIC OF INDIA/9118815710719", "r3", "2025-07-23"),
       ("c1", "DEBIT", 590.0, "ECSRTNCHGS221019_SR1 (Ref# BANK CHARGES)", "r4", "2025-10-28"),
       ("q4", "DEBIT", 4600.0, "ACH/LIC OF INDIA/9118815711019", "r5", "2025-10-30")]


def lic_household():
    c = load(_write([("XXXX0005", _xml('name="Q ONE" mobile="9000000005"', FILLER + LIC))]))
    return c, c.accounts[0].household_id


def run(c, hh, dates, answers=()):
    st, ev = initial(), []
    for d in dates:
        st, ev = advance(st, take_snapshot(c, hh, d), answers)
    return st, ev


class TimeAxis(unittest.TestCase):
    def test_same_state_gives_no_meaningful_event(self):
        c, hh = lic_household()
        st, _ = run(c, hh, [date(2025, 10, 28)])
        st2, ev = advance(st, take_snapshot(c, hh, date(2025, 10, 28)))
        self.assertTrue(ev)
        self.assertTrue(all(e.status == "CONTINUING" for e in ev), [e.kind for e in ev])

    def test_new_clock_is_NEW(self):
        c, hh = lic_household()
        st, ev = run(c, hh, [date(2025, 10, 27), date(2025, 10, 28)])
        self.assertEqual([(e.kind, e.status) for e in ev], [("CARD_OPENED", "NEW")])

    def test_evidence_cure_resolves_and_does_not_reask(self):
        """Watched -> understood -> noticed it is over: a re-collection after the return closes the clock
        (seen in data), and the same return charge is not re-asked as a new question."""
        c, hh = lic_household()
        st, ev = run(c, hh, [date(2025, 10, 28), date(2025, 11, 2)])
        self.assertEqual([(e.kind, e.status, e.basis) for e in ev],
                         [("CARD_RESOLVED", "RESOLVED", "seen_in_data")])
        self.assertEqual(st.open_cards, ())
        self.assertIn("q4", st.closed[0].evidence_txn_ids)

    def test_customer_answer_resolves_and_bad_answers_are_refused(self):
        c, hh = lic_household()
        st, _ = run(c, hh, [date(2025, 10, 28)])
        card = st.open_cards[0][0]
        with self.assertRaises(AnswerInvalid):
            advance(st, take_snapshot(c, hh, date(2025, 10, 29)), [Answer(card.id, "cancel_policy", date(2025, 10, 29))])
        st2, ev = advance(st, take_snapshot(c, hh, date(2025, 10, 29)),
                          [Answer(card.id, "already_paid", date(2025, 10, 29), fingerprint(card))])
        self.assertEqual([(e.status, e.basis) for e in ev], [("RESOLVED", "you_told_us")])

    def test_answers_dated_in_the_future_are_ignored(self):
        """Replay-safe: an answer given on 5 Nov cannot affect the 29 Oct state."""
        c, hh = lic_household()
        st, _ = run(c, hh, [date(2025, 10, 28)])
        card = st.open_cards[0][0]
        _, ev = advance(st, take_snapshot(c, hh, date(2025, 10, 29)), [Answer(card.id, "already_paid", date(2025, 11, 5))])
        self.assertEqual([e.status for e in ev], ["CONTINUING"])

    def test_time_only_moves_forward(self):
        c, hh = lic_household()
        st, _ = run(c, hh, [date(2025, 10, 28)])
        with self.assertRaises(ValueError):
            advance(st, take_snapshot(c, hh, date(2025, 10, 1)))


class Briefing(unittest.TestCase):
    def test_capped_at_five_and_counts_the_rest(self):
        rows = []
        for n in range(7):                                  # 7 payees collected Jan-Jun, then nothing
            for mo in range(1, 7):
                rows.append((f"p{n}{mo}", "DEBIT", 1000.0 + n, f"ACH/PAYEE{'ABCDEFG'[n]} CO/77712{n}0{mo:02d}25",
                             f"rp{n}{mo}", f"2025-{mo:02d}-05"))
        c = load(_write([("XXXX0007", _xml('name="S" mobile="9000000007"', FILLER + rows))]))
        st, ev = run(c, c.accounts[0].household_id, [date(2025, 9, 20)])
        b = since_last_time(st, ev)
        self.assertEqual(len(b.lines), MAX_LINES)
        self.assertEqual(b.more, 2)
        self.assertTrue(all(l.event_ids and l.card_id for l in b.lines))

    def test_deterministic(self):
        c, hh = lic_household()
        a = since_last_time(*run(c, hh, [date(2025, 10, 27), date(2025, 10, 28)]))
        b = since_last_time(*run(c, hh, [date(2025, 10, 27), date(2025, 10, 28)]))
        self.assertEqual(a, b)

    def test_resolved_line_says_how_we_know(self):
        c, hh = lic_household()
        b = since_last_time(*run(c, hh, [date(2025, 10, 28), date(2025, 11, 2)]))
        self.assertEqual(b.lines[0].kind, "RESOLVED")
        self.assertIn("went through on 30 Oct 2025", b.lines[0].text)
        self.assertEqual(b.lines[0].basis, "seen_in_data")


class Contract(unittest.TestCase):
    def payload(self):
        c, hh = lic_household()
        return build_payload(*run(c, hh, [date(2025, 10, 27), date(2025, 10, 28)]))

    def test_payload_validates_and_is_json(self):
        p = validate_payload(self.payload())
        self.assertEqual(json.loads(json.dumps(p, ensure_ascii=False)), p)
        self.assertEqual(set(SCHEMA["required"]) - set(p), set())

    def test_unsafe_text_or_identifier_is_refused(self):
        p = self.payload()
        p["now"]["cards"][0]["title"] = "Your policy has lapsed"
        with self.assertRaises(UnsafeLanguage):
            validate_payload(p)
        p = self.payload()
        p["now"]["cards"][0]["member"] = "ABCDE1234F"
        with self.assertRaises(PayloadInvalid):
            validate_payload(p)
        p = self.payload()
        p["our_household"]["balance"] = 1
        with self.assertRaises(PayloadInvalid):
            validate_payload(p)
        p = self.payload()
        p["what_we_know"]["consent"]["status"] = "ACTIVE"          # no status_source
        with self.assertRaises(PayloadInvalid):
            validate_payload(p)

    def test_ai_boundary_rejects_invented_figures(self):
        view = self.payload()["now"]["cards"][0]
        self.assertTrue(validate_explanation("Your LIC premium of ₹4,600 was returned on 22 Oct.", view))
        with self.assertRaises(UnsafeLanguage):
            validate_explanation("You have ₹20,000 spare, so pay by 25 Nov.", view)


@unittest.skipUnless(DATA, "set MIRROR_DATA to the sealed decrypted.json")
class OnCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = load(DATA)
        cls.john = cls.c.account("9741")
        cls.hh = cls.john.household_id
        cls.ids = {t.txn_id for a in cls.c.accounts for t in a.txns}
        cls.narr = {t.narration for a in cls.c.accounts for t in a.txns if len(t.narration) > 12}

    def test_john_lifecycle(self):
        c, hh, j = self.c, self.hh, self.john.masked
        st, ev = run(c, hh, [date(2026, 8, 27)])
        self.assertFalse([e for e in ev if e.account == j])
        st, ev = advance(st, take_snapshot(c, hh, date(2026, 8, 28)))
        opened = [e for e in ev if e.account == j]
        self.assertEqual([(e.kind, e.status) for e in opened], [("CARD_OPENED", "NEW")])
        cid = opened[0].card_id
        st, ev = advance(st, take_snapshot(c, hh, date(2026, 9, 7)))
        self.assertEqual([(e.card_id, e.status) for e in ev if e.account == j], [(cid, "CONTINUING")])
        card = next(x for x, _ in st.open_cards if x.id == cid)
        ans = [Answer(cid, "already_paid", date(2026, 9, 9), fingerprint(card))]
        st, ev = advance(st, take_snapshot(c, hh, date(2026, 9, 9)), ans)
        self.assertEqual([(e.status, e.basis) for e in ev if e.account == j], [("RESOLVED", "you_told_us")])
        st, ev = advance(st, take_snapshot(c, hh, date(2026, 9, 12)), ans)
        self.assertFalse([e for e in ev if e.account == j])

    def test_vanished_is_withdrawn_not_resolved(self):
        """Kiran's loan clock disappears when collections stop - that is WITHDRAWN, waiting on her answer."""
        st, ev = run(self.c, self.hh, [date(2026, 4, 21), date(2026, 6, 5)])
        kinds = {(e.kind, e.status, e.data.get("reason")) for e in ev if "INDUSIND" in e.subject}
        self.assertIn(("CARD_WITHDRAWN", "WITHDRAWN", "WAITING_ON_ANSWER"), kinds)
        self.assertFalse([e for e in ev if e.status == "RESOLVED"])

    def test_question_superseded_by_clock(self):
        st, ev = run(self.c, self.hh, [date(2025, 12, 1), date(2026, 4, 21)])
        sup = [e for e in ev if e.kind == "CARD_SUPERSEDED"]
        self.assertEqual(len(sup), 1)
        self.assertTrue(any(c.id == sup[0].data["superseded_by"] for c, _ in st.open_cards))

    def test_horizon_pressure_is_inferred_and_conditional(self):
        h = horizon(run(self.c, self.hh, [date(2026, 8, 9)])[0])
        p = [x for x in h["pressure_points"] if x["member"] == "John"][0]
        self.assertEqual((p["date"], p["severity"], p["evidence_class"]), ("2026-08-23", "COULD_BE_TIGHT", "I"))
        self.assertIn("nothing else comes in or goes out of this account before then", p["conditions"])

    def test_horizon_only_evidence_supported_items(self):
        for d in (date(2026, 8, 9), date(2026, 8, 28), date(2026, 9, 9)):
            h = horizon(run(self.c, self.hh, [d])[0])
            for i in h["items"]:
                self.assertIn(i["evidence_class"], ("I", "R"))
                self.assertNotIn("balance", json.dumps(i).lower())
                if i["kind"] == "COLLECTION":
                    self.assertGreaterEqual(i["seen_count"], 3)
                    self.assertTrue(set(i["based_on_txn_ids"]) <= self.ids)
                if i["kind"] == "REGULAR_CREDIT_DAYS":
                    self.assertNotIn("amount", i)

    def test_irregular_credits_are_never_projected(self):
        h = horizon(run(self.c, self.hh, [date(2026, 8, 28)])[0])
        self.assertFalse([i for i in h["items"] if i["kind"] == "REGULAR_CREDIT_DAYS" and i["member"] == "Kiran"])
        self.assertTrue([n for n in h["not_projected"] if n["member"] == "Kiran" and n["what"] == "credits"])
        self.assertTrue([n for n in h["not_projected"] if n["what"] == "BAJAJ AUTO C D"])

    def test_payload_is_safe_traceable_and_deterministic(self):
        st, ev = run(self.c, self.hh, [date(2026, 8, 27), date(2026, 8, 28)])
        p = validate_payload(build_payload(st, ev))
        self.assertEqual(p, validate_payload(build_payload(st, ev)))
        blob = json.dumps(p, ensure_ascii=False)
        self.assertFalse(PAN_RX.search(blob))
        self.assertFalse([n for n in self.narr if n in blob], "raw narrations must not reach the app")
        for e in p["events"]:
            self.assertTrue(set(e["txn_ids"]) <= self.ids)
        self.assertEqual(p["now"]["since_last_time"]["provenance"]["corpus_sha256"], self.c.sha256)
        for v in p["now"]["cards"]:
            self.assertTrue(v["why"] and v["fingerprint"])

    def test_quiet_household_gets_a_silent_briefing(self):
        kumar = self.c.account("9950").household_id
        b = since_last_time(*run(self.c, kumar, [date(2026, 9, 1), date(2026, 9, 22)]))
        self.assertTrue(b.silent)
        self.assertTrue(b.lines[0].text.startswith("Nothing needs you."))


if __name__ == "__main__":
    unittest.main(verbosity=2)
