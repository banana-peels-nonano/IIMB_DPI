"""
Counterparty Mirror - Gate 4 + 5 tests: minimal Unlock + the LPG record (Perfios Hub).
Each test is one product or governance guarantee.

  python -m unittest mirror.test_gate45 -v                   (synthetic only)
  MIRROR_DATA=<sealed decrypted.json> python -m unittest mirror.test_gate45 -v
"""
import json, os, re, unittest
from datetime import date

from mirror.corpus import load
from mirror.snapshot import take_snapshot
from mirror.events import advance, initial, Answer, PurposeNotGranted, JoinRefused
from mirror.facts import FactStatement, FactInvalid, FACTS, AGE_BANDS
from mirror.briefing import since_last_time
from mirror.horizon import horizon
from mirror.contract import build_payload, validate_payload, validate_explanation, PayloadInvalid
from mirror.cards import Card, CardInvalid, Evidence as E, PAN_RX
from mirror.language import gate, render, UnsafeLanguage
from mirror.rules import RULES, STATE_RULES, PURPOSES, PURPOSE_AA_PROTECT, PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG
from mirror.sources import lpg
from mirror.test_mirror import _xml, _write, FILLER

DATA = os.environ.get("MIRROR_DATA")
AA = frozenset({PURPOSE_AA_PROTECT})
GOV = AA | {PURPOSE_GOV_PROTECT}
DPI = GOV | {PURPOSE_DPI_LPG}
ELIGIBILITY = re.compile(r"\b(eligib|qualif|entitled)", re.I)


def one_member(rows, mobile="9000000011", name="R ONE", masked="XXXX0011"):
    c = load(_write([(masked, _xml(f'name="{name}" mobile="{mobile}"', rows))]))
    return c, c.accounts[0].household_id, c.accounts[0].masked


def run(c, hh, steps):
    """steps: [(date, purposes, answers, records)] -> (state, events) after the last step."""
    st, ev = initial(), []
    for d, p, a, r in steps:
        st, ev = advance(st, take_snapshot(c, hh, d, purposes=p), a, r)
    return st, ev


def card(st, code, account=None, scheme=None):
    return next(c for c, _ in st.open_cards if c.code == code and (account is None or c.account == account)
                and (scheme is None or c.subject.endswith(":" + scheme)))


PMSBY_DEBIT = [("p1", "DEBIT", 20.0, "PMSBY RENEWAL PREMIUM FY 25", "rp1", "2025-05-25")]


class Rulebook(unittest.TestCase):
    def test_state_rules_are_versioned_cited_data_in_their_own_book(self):
        need = {"version", "name", "purpose", "output", "applies_to", "trigger_facts", "required_facts",
                "params", "citation", "source", "last_verified", "uncertainty"}
        self.assertEqual(set(RULES), {"LIC_GRACE", "RBI_IRACP_OVERDUE", "CIC_REPORTING_CADENCE"})
        self.assertEqual(set(STATE_RULES), {"PMSBY", "PMJJBY", "APY", "PMUY", "PAHAL_DBTL", "APB_MAPPER"})
        for rid, r in STATE_RULES.items():
            self.assertFalse(need - set(r), f"{rid} missing {need - set(r)}")
            self.assertEqual(r["purpose"], PURPOSE_GOV_PROTECT)
            self.assertTrue(all(not callable(v) for v in r.values()))
            self.assertIsNone(ELIGIBILITY.search(r["name"]))
        self.assertEqual((STATE_RULES["PMSBY"]["params"]["age_min"], STATE_RULES["PMSBY"]["params"]["age_max"]), (18, 70))
        self.assertEqual((STATE_RULES["PMJJBY"]["params"]["age_min"], STATE_RULES["PMJJBY"]["params"]["age_max"]), (18, 50))
        self.assertEqual((STATE_RULES["APY"]["params"]["age_min"], STATE_RULES["APY"]["params"]["age_max"]), (18, 40))

    def test_age_bands_are_cut_at_the_published_limits(self):
        """No band straddles 18/40/50/70, so a band is always wholly inside or outside a rule."""
        from mirror.facts import band_in_range
        for scheme in ("PMSBY", "PMJJBY", "APY"):
            p = STATE_RULES[scheme]["params"]
            for band in AGE_BANDS:
                self.assertIsNotNone(band_in_range(band, p["age_min"], p["age_max"]), (scheme, band))


class Minimisation(unittest.TestCase):
    def test_only_closed_answer_sets_and_never_a_date_of_birth(self):
        for code, spec in FACTS.items():
            self.assertTrue(spec["values"] and spec["feeds"] and spec["purpose"])
        self.assertIn("date of birth", PURPOSES[PURPOSE_GOV_PROTECT]["never_uses"])
        for sensitive in ("caste", "religion", "disability", "health", "gender"):
            self.assertIn(sensitive, PURPOSES[PURPOSE_GOV_PROTECT]["never_uses"])
        with self.assertRaises(FactInvalid):
            from mirror.facts import check
            check(FactStatement("XXXX0011", "AGE_BAND", "1990-01-01", date(2025, 6, 1)))

    def test_purpose_boundary_nothing_runs_until_switched_on(self):
        c, hh, acc = one_member(FILLER)
        st, ev = run(c, hh, [(date(2025, 12, 1), AA, (), ())])
        self.assertFalse([x for x, _ in st.open_cards if x.provenance.get("purpose") == PURPOSE_GOV_PROTECT])
        p = validate_payload(build_payload(st, ev))
        self.assertFalse(p["our_household"]["protections"]["switched_on"])
        with self.assertRaises(PurposeNotGranted):
            advance(st, take_snapshot(c, hh, date(2025, 12, 2), purposes=AA),
                    [FactStatement(acc, "AGE_BAND", "18_40", date(2025, 12, 2))])


class Unlock(unittest.TestCase):
    def test_one_age_band_re_evaluates_every_rule_in_one_pass(self):
        c, hh, acc = one_member(FILLER)
        st, _ = run(c, hh, [(date(2025, 12, 1), GOV, (), ())])
        q = card(st, "AGE_BAND_QUESTION")
        self.assertEqual(set(q.question.options), set(AGE_BANDS))
        st, ev = advance(st, take_snapshot(c, hh, date(2025, 12, 2), purposes=GOV),
                         [Answer(q.id, "18_40", date(2025, 12, 2))])
        facts = [e for e in ev if e.kind == "FACT_CONFIRMED"]
        self.assertEqual(len(facts), 1)
        eff = {x["scheme"]: x["status"] for x in facts[0].data["effects"]}
        self.assertEqual(eff, {"PMSBY": "WORTH_CHECKING", "PMJJBY": "WORTH_CHECKING", "APY": "NEEDS_TAXPAYER"})
        opened = {e.data["summary"]["code"] for e in ev if e.kind == "CARD_OPENED"}
        self.assertEqual(opened, {"PROTECTION_DOOR", "TAXPAYER_QUESTION"})
        self.assertTrue(all(e.data.get("caused_by_fact") == facts[0].id for e in ev if e.kind == "CARD_OPENED"))
        lines = since_last_time(st, ev).lines
        self.assertEqual(len([l for l in lines if l.kind == "CHANGE"]), 1)
        self.assertIn("PMSBY and PMJJBY are worth checking", lines[0].text)

    def test_taxpayer_is_asked_only_when_its_answer_matters(self):
        c, hh, acc = one_member(FILLER)
        st, _ = run(c, hh, [(date(2025, 12, 1), GOV, (), ())])
        q = card(st, "AGE_BAND_QUESTION")
        st, _ = advance(st, take_snapshot(c, hh, date(2025, 12, 2), purposes=GOV),
                        [Answer(q.id, "41_50", date(2025, 12, 2))])
        self.assertFalse([x for x, _ in st.open_cards if x.code == "TAXPAYER_QUESTION"])
        apy = next(s for s in st.unlock_status if s["scheme"] == "APY")
        self.assertEqual((apy["status"], apy["reason"]), ("NOT_APPLICABLE", "AGE"))

    def test_not_seen_is_never_not_enrolled(self):
        c, hh, acc = one_member(FILLER)
        st, _ = run(c, hh, [(date(2025, 12, 1), GOV, (), ())])
        st, _ = advance(st, take_snapshot(c, hh, date(2025, 12, 2), purposes=GOV),
                        [Answer(card(st, "AGE_BAND_QUESTION").id, "41_50", date(2025, 12, 2))])
        door = card(st, "PROTECTION_DOOR")
        self.assertIn("COVERED_ELSEWHERE", [e.code for e in door.evidence if e.cls == "U"])
        ns = door.ev("e_ns").data["absence"]
        self.assertLessEqual(ns["to"], ns["account_data_until"])
        self.assertEqual(door.ev("e_ns").data["accounts"], [acc])
        for bad in ("John is not enrolled in PMJJBY.", "Kiran isn't covered.", "They don't have cover.",
                    "You are eligible for PMJJBY.", "You should enrol in APY."):
            with self.assertRaises(UnsafeLanguage):
                gate(bad)
        with self.assertRaises(CardInvalid):               # a door without the 'another account' unknowable
            Card(id="C-x", type="DOOR", code="PROTECTION_DOOR", member="R", account=acc, subject="s", as_of="2025-12-02",
                 evidence=(door.ev("e_ns"), door.ev("e_rule")), claim=("e_ns", "e_rule"), provenance=door.provenance)

    def test_answers_stay_U_are_never_claimed_and_nothing_is_inferred_from_them(self):
        c, hh, acc = one_member(FILLER)
        st, _ = run(c, hh, [(date(2025, 12, 1), GOV, (), ())])
        st, _ = advance(st, take_snapshot(c, hh, date(2025, 12, 2), purposes=GOV),
                        [Answer(card(st, "AGE_BAND_QUESTION").id, "41_50", date(2025, 12, 2))])
        door = card(st, "PROTECTION_DOOR")
        age = door.ev("e_age")
        self.assertTrue(age.cls == "U" and age.answered)
        self.assertNotIn("e_age", door.claim)
        with self.assertRaises(CardInvalid):
            Card(**{**door.__dict__, "claim": door.claim + ("e_age",)})
        with self.assertRaises(CardInvalid):
            Card(**{**door.__dict__, "evidence": door.evidence + (E("e_inf", "I", "X", {}, based_on=("e_age",)),),
                    "claim": door.claim})

    def test_no_eligibility_language_on_any_unlock_surface(self):
        c, hh, acc = one_member(FILLER + PMSBY_DEBIT)
        st, _ = run(c, hh, [(date(2025, 12, 1), GOV, (), ())])
        st, ev = advance(st, take_snapshot(c, hh, date(2025, 12, 2), purposes=GOV),
                         [Answer(card(st, "AGE_BAND_QUESTION").id, "18_40", date(2025, 12, 2))])
        blob = json.dumps(validate_payload(build_payload(st, ev)), ensure_ascii=False)
        self.assertIsNone(ELIGIBILITY.search(blob.replace("ELIGIBILITY", "")))
        for x, _ in st.open_cards:
            text, trail = render(x)
            self.assertIsNone(ELIGIBILITY.search(text))

    def test_correction_re_evaluates_withdraws_not_resolves_and_is_kept(self):
        c, hh, acc = one_member(FILLER)
        st, _ = run(c, hh, [(date(2025, 12, 1), GOV, (), ())])
        st, _ = advance(st, take_snapshot(c, hh, date(2025, 12, 2), purposes=GOV),
                        [Answer(card(st, "AGE_BAND_QUESTION").id, "41_50", date(2025, 12, 2))])
        door = card(st, "PROTECTION_DOOR", scheme="PMJJBY")
        st, ev = advance(st, take_snapshot(c, hh, date(2025, 12, 3), purposes=GOV),
                         [FactStatement(acc, "AGE_BAND", "51_70", date(2025, 12, 3))])
        self.assertEqual([e.kind for e in ev if e.kind.startswith("FACT_")], ["FACT_CORRECTED"])
        gone = [e for e in ev if e.card_id == door.id]
        self.assertEqual([(e.status, e.data["reason"]) for e in gone], [("WITHDRAWN", "FACT_CHANGED")])
        self.assertEqual([(x.old_value, x.new_value) for x in st.corrections], [("41_50", "51_70")])
        p = validate_payload(build_payload(st, ev))
        self.assertEqual(p["what_we_know"]["corrections"][0]["after"], "51–70")
        self.assertTrue(since_last_time(st, ev).lines[0].text.startswith("Updated: you told us R is 51–70"))

    def test_covered_elsewhere_closes_the_door_as_you_told_us(self):
        c, hh, acc = one_member(FILLER)
        st, _ = run(c, hh, [(date(2025, 12, 1), GOV, (), ())])
        st, _ = advance(st, take_snapshot(c, hh, date(2025, 12, 2), purposes=GOV),
                        [Answer(card(st, "AGE_BAND_QUESTION").id, "41_50", date(2025, 12, 2))])
        door = card(st, "PROTECTION_DOOR", scheme="PMJJBY")
        st, ev = advance(st, take_snapshot(c, hh, date(2025, 12, 3), purposes=GOV),
                         [Answer(door.id, "yes", date(2025, 12, 3))])
        self.assertIn(("RESOLVED", "you_told_us"), [(e.status, e.basis) for e in ev if e.card_id == door.id])
        self.assertEqual(next(s for s in st.unlock_status if s["scheme"] == "PMJJBY")["status"], "COVERED_ELSEWHERE")

    def test_switching_off_forgets_and_old_answers_never_return(self):
        c, hh, acc = one_member(FILLER)
        st, _ = run(c, hh, [(date(2025, 12, 1), GOV, (), ())])
        answers = [Answer(card(st, "AGE_BAND_QUESTION").id, "41_50", date(2025, 12, 2))]
        st, _ = advance(st, take_snapshot(c, hh, date(2025, 12, 2), purposes=GOV), answers)
        st, ev = advance(st, take_snapshot(c, hh, date(2025, 12, 3), purposes=AA), answers)
        self.assertEqual((st.hfacts, st.unlock_status), ((), ()))
        self.assertFalse([cl for cl in st.closed if cl.code.startswith(("AGE_", "PROTECTION"))])
        self.assertEqual(st.access_log[-1]["what"], "forgotten")
        self.assertTrue(all(e.data["reason"] == "PURPOSE_OFF" for e in ev if e.kind == "CARD_WITHDRAWN"))
        st, _ = advance(st, take_snapshot(c, hh, date(2025, 12, 4), purposes=GOV), answers)
        self.assertEqual(st.hfacts, ())                          # the old answer is not re-applied
        self.assertTrue([x for x, _ in st.open_cards if x.code == "AGE_BAND_QUESTION"])

    def test_short_data_window_makes_no_absence_claim(self):
        rows = [(f"s{m}{d}", "DEBIT", 100.0 + d, "UPI/1/FOOD/x@y", f"rs{m}{d}", f"2025-0{m}-{d:02d}")
                for m in (7, 8, 9) for d in (1, 4, 7, 10, 13, 16, 19, 22, 25)]      # 27 rows, Jul-Sep only
        c, hh, acc = one_member(rows)
        st, _ = run(c, hh, [(date(2025, 9, 20), GOV, (), ())])
        self.assertEqual({s["status"] for s in st.unlock_status}, {"NOT_ENOUGH_DATA"})
        self.assertFalse([x for x, _ in st.open_cards if x.code in ("AGE_BAND_QUESTION", "PROTECTION_DOOR")])

    def test_a_window_that_only_touches_1_june_is_not_enough(self):
        rows = [(f"j{i}", "DEBIT", 100.0 + i, "UPI/1/FOOD/x@y", f"rj{i}", f"2025-{5 + (i >= 3):02d}-{d:02d}")
                for i, d in enumerate((29, 30, 31, 1, 2, 3, 5, 6, 8, 9, 10, 12, 13, 15, 16, 17, 18, 19, 19, 19, 19))]
        c, hh, acc = one_member(rows)
        st, _ = run(c, hh, [(date(2025, 6, 20), GOV, (), ())])
        self.assertEqual({s["status"] for s in st.unlock_status}, {"NOT_ENOUGH_DATA"})

    def test_replayed_statements_never_invent_corrections(self):
        c, hh, acc = one_member(FILLER)
        said = [FactStatement(acc, "AGE_BAND", "41_50", date(2025, 12, 2)),
                FactStatement(acc, "AGE_BAND", "51_70", date(2025, 12, 3))]
        st, _ = run(c, hh, [(date(2025, 12, 1), GOV, said, ()), (date(2025, 12, 2), GOV, said, ()),
                            (date(2025, 12, 3), GOV, said, ()), (date(2025, 12, 4), GOV, said, ()),
                            (date(2025, 12, 5), GOV, said, ())])
        self.assertEqual([(x.old_value, x.new_value) for x in st.corrections], [("41_50", "51_70")])
        self.assertEqual([f.value for f in st.hfacts], ["51_70"])

    def test_a_cover_seen_in_the_account_renews_on_the_horizon(self):
        c, hh, acc = one_member(FILLER + PMSBY_DEBIT)
        st, ev = run(c, hh, [(date(2026, 5, 10), GOV, (), ())])
        seen = next(s for s in st.unlock_status if s["scheme"] == "PMSBY")
        self.assertEqual((seen["status"], seen["txn_ids"]), ("SEEN", ["p1"]))
        ren = [i for i in horizon(st)["items"] if i["kind"] == "RENEWAL"]
        self.assertEqual([(i["scheme"], i["date_from"], i["evidence_class"]) for i in ren], [("PMSBY", "2026-06-01", "R")])
        self.assertEqual(ren[0]["conditional_on"], ["still enrolled through this account"])
        validate_payload(build_payload(st, ev))


class LpgAdapter(unittest.TestCase):
    def test_minimisation_keeps_only_what_the_rule_needs(self):
        r = lpg.simulated("rerouted", requested_on=date(2026, 9, 9), household_id="HH-x", account="XXXX9648",
                          purposes=DPI)
        self.assertEqual(set(r.fields) - set(lpg.KEEP.values()), set())
        self.assertEqual(r.fields["account_tail"], "4471")
        self.assertIn("ConsumerName", r.dropped)
        self.assertNotIn("<dropped>", json.dumps(r.fields))
        self.assertEqual((r.mode, r.join), ("simulated", "simulated"))

    def test_failure_is_never_success(self):
        for scenario, reason in (("invalid_id", "ID_NOT_RECOGNISED"), ("timeout", "TIMEOUT"),
                                 ("unusable", "NO_USABLE_FIELDS")):
            r = lpg.simulated(scenario, requested_on=date(2026, 9, 9), household_id="HH-x", account="A", purposes=DPI)
            self.assertEqual((r.status, r.reason, r.fields), ("failed", reason, {}))
        r = lpg.simulated("rerouted", requested_on=date(2026, 9, 9), household_id="HH-x", account="A", purposes=GOV)
        self.assertEqual((r.status, r.reason), ("refused", "PURPOSE_NOT_GRANTED"))

    def test_unusable_mixed_or_non_object_replies_fail(self):
        kw = dict(mode="simulated", requested_on=date(2026, 9, 9), purpose=PURPOSE_DPI_LPG, household_id="HH-x",
                  account="A", join="simulated")
        r = lpg.parse_response({"status-code": "101", "result": {"status": "ACTIVE"}}, **kw)
        self.assertEqual((r.status, r.reason, r.fields), ("failed", "NO_USABLE_FIELDS", {}))
        two = {"status-code": "101", "result": {"connections": [{"LastBookingDate": "2026-08-01"},
                                                                 {"LastBookingDate": "2026-05-01"}]}}
        r = lpg.parse_response(two, **kw)
        self.assertEqual((r.status, r.reason), ("failed", "AMBIGUOUS_RECORD"))

    def test_live_mode_refuses_before_any_network_call(self):
        def boom(*a, **k):
            raise AssertionError("network must not be touched")
        os.environ.pop("MIRROR_HUB_LIVE", None)
        with self.assertRaises(lpg.LiveLookupRefused):
            lpg.live("12345678901234567", requested_on=date(2026, 9, 9), purposes=DPI, holder_confirmed=True,
                     spend_credit=True, _opener=boom)
        os.environ["MIRROR_HUB_LIVE"] = "1"
        try:
            for kw in ({"holder_confirmed": False, "spend_credit": True}, {"holder_confirmed": True, "spend_credit": False}):
                with self.assertRaises(lpg.LiveLookupRefused):
                    lpg.live("12345678901234567", requested_on=date(2026, 9, 9), purposes=DPI, _opener=boom, **kw)
            with self.assertRaises(lpg.LiveLookupRefused):
                lpg.live("ABCDE1234F", requested_on=date(2026, 9, 9), purposes=DPI, holder_confirmed=True,
                         spend_credit=True, _opener=boom)
            with self.assertRaises(lpg.LiveLookupRefused):     # credentials never leave Perfios Hub's hosts
                lpg.live("12345678901234567", requested_on=date(2026, 9, 9), purposes=DPI, holder_confirmed=True,
                         spend_credit=True, base_url="http://elsewhere.example", _opener=boom)
        finally:
            os.environ.pop("MIRROR_HUB_LIVE", None)

    def test_a_live_record_is_never_joined_to_a_household(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps({"status-code": "102", "request_id": "r", "result": {}}).encode()
        env = {"MIRROR_HUB_LIVE": "1", "PERFIOS_SECURE_ID": "t", "PERFIOS_SECURE_CRED": "t", "PERFIOS_ORG_ID": "t"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            r = lpg.live("12345678901234567", requested_on=date(2026, 9, 9), purposes=DPI, holder_confirmed=True,
                         spend_credit=True, _opener=lambda req, timeout: Resp())
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertEqual((r.status, r.reason, r.join, r.household_id, r.lpg_id_tail),
                         ("failed", "ID_NOT_RECOGNISED", "none", None, "4567"))
        self.assertNotIn("12345678901234567", json.dumps(lpg.standalone_view(r)))
        c, hh, acc = one_member(FILLER)
        ok = lpg.SourceRecord("SR-live", lpg.SOURCE, "live", "ok", "", date(2025, 12, 1), PURPOSE_DPI_LPG, None,
                              None, "none", {"last_booking_date": "2025-11-01"})
        with self.assertRaises(JoinRefused):
            advance(initial(), take_snapshot(c, hh, date(2025, 12, 1), purposes=DPI), (), [ok])
        relabelled = lpg.SourceRecord("SR-live2", lpg.SOURCE, "live", "ok", "", date(2025, 12, 1), PURPOSE_DPI_LPG,
                                      hh, acc, "customer_confirmed", {"last_booking_date": "2025-11-01"})
        with self.assertRaises(JoinRefused):                    # a live record is refused whatever its join label
            advance(initial(), take_snapshot(c, hh, date(2025, 12, 1), purposes=DPI), (), [relabelled])


@unittest.skipUnless(DATA, "set MIRROR_DATA to the sealed decrypted.json")
class OnCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = load(DATA)
        cls.hh = cls.c.account("9741").household_id
        cls.john, cls.kiran = cls.c.account("9741").masked, cls.c.account("9648").masked
        cls.narr = {t.narration for a in cls.c.accounts for t in a.txns if len(t.narration) > 12}

    def gov(self, d=date(2026, 9, 8), p=GOV):
        return run(self.c, self.hh, [(d, p, (), ())])

    def rec(self, scenario, on=date(2026, 9, 9)):
        return lpg.simulated(scenario, requested_on=on, household_id=self.hh, account=self.kiran, purposes=DPI)

    def test_participation_is_observed_and_pmuy_is_explained_not_shown(self):
        st, ev = self.gov()
        john = {s["scheme"]: s for s in st.unlock_status if s["account"] == self.john}
        self.assertEqual((john["PMSBY"]["status"], john["PMSBY"]["evidence_class"]), ("SEEN", "O"))
        pmuy = card(st, "PMUY_NOT_SHOWN")
        self.assertEqual(pmuy.type, "SUPPRESSION")
        self.assertEqual(pmuy.ev("e_conn").cls, "I")
        self.assertEqual(len(pmuy.ev("e_credits").txn_ids), 11)
        p = validate_payload(build_payload(st, ev))
        self.assertNotIn(pmuy.id, [v["id"] for v in p["now"]["cards"]])
        self.assertIn(pmuy.id, [v["id"] for v in p["our_household"]["protections"]["not_shown"]])

    def test_john_and_kiran_one_answer_each_changes_several_rules(self):
        st, _ = self.gov()
        a = [Answer(card(st, "AGE_BAND_QUESTION", self.john).id, "41_50", date(2026, 9, 9)),
             Answer(card(st, "AGE_BAND_QUESTION", self.kiran).id, "18_40", date(2026, 9, 9))]
        st, ev = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=GOV), a)
        eff = {e.account: {x["scheme"]: x["status"] for x in e.data["effects"]}
               for e in ev if e.kind == "FACT_CONFIRMED"}
        self.assertEqual(eff[self.john], {"PMSBY": "SEEN", "PMJJBY": "WORTH_CHECKING", "APY": "NOT_APPLICABLE"})
        self.assertEqual(eff[self.kiran], {"PMSBY": "WORTH_CHECKING", "PMJJBY": "WORTH_CHECKING", "APY": "NEEDS_TAXPAYER"})

    def test_lpg_question_then_record_refines_it_labelled_simulated(self):
        st, _ = self.gov()
        q = card(st, "LPG_SUBSIDY_QUESTION")
        self.assertEqual(q.ev("e_credits").data["last"], "2026-05-28")
        st, ev = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=DPI), (), [self.rec("rerouted")])
        self.assertIn(("CARD_SUPERSEDED", q.id), [(e.kind, e.card_id) for e in ev])
        r = card(st, "LPG_SUBSIDY_ROUTING")
        self.assertTrue(r.provenance["simulated"])
        p = validate_payload(build_payload(st, ev))
        view = next(v for v in p["now"]["cards"] if v["id"] == r.id)
        self.assertIn("SIMULATED", view["title"])
        self.assertTrue(any(w.get("simulated") for w in view["why"]))
        self.assertEqual(p["what_we_know"]["access_log"][-1]["mode"], "simulated")
        self.assertIn("SIMULATED", " ".join(l.text for l in since_last_time(st, ev).lines))
        bad = json.loads(json.dumps(p))
        next(v for v in bad["now"]["cards"] if v["id"] == r.id)["title"] = "Where your LPG subsidy goes"
        with self.assertRaises(PayloadInvalid):
            validate_payload(bad)

    def test_live_capability_and_simulated_execution_are_never_blurred(self):
        st, _ = self.gov()
        st, ev = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=DPI), (), [self.rec("rerouted")])
        p = validate_payload(build_payload(st, ev))
        d = p["what_we_know"]["dpi_integrations"][0]
        self.assertEqual(d["live_lookup_for_this_household"]["status"], "not performed")
        self.assertEqual((d["responses_used_here"], d["disclosure"]), (["simulated"], lpg.DISCLOSURE))
        self.assertTrue(d["live_capability"])
        view = next(v for v in p["now"]["cards"] if v["code"] == "LPG_SUBSIDY_ROUTING")
        self.assertIn("couldn't do a live lookup", " ".join(view["body"]))
        fake = json.loads(json.dumps(p))
        fake["what_we_know"]["dpi_integrations"][0]["live_lookup_for_this_household"] = {"status": "succeeded"}
        with self.assertRaises(PayloadInvalid):                  # a live success can't be claimed without one
            validate_payload(fake)
        hidden = json.loads(json.dumps(p))
        hidden["what_we_know"]["dpi_integrations"][0]["disclosure"] = None
        with self.assertRaises(PayloadInvalid):
            validate_payload(hidden)

    def test_failed_lookup_keeps_the_question_open_and_is_logged(self):
        st, _ = self.gov()
        q = card(st, "LPG_SUBSIDY_QUESTION")
        st, ev = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=DPI), (), [self.rec("invalid_id")])
        still = card(st, "LPG_SUBSIDY_QUESTION")
        self.assertEqual(still.id, q.id)
        self.assertEqual(still.provenance["dpi_lookup"]["reason"], "ID_NOT_RECOGNISED")
        self.assertTrue([e for e in still.evidence if e.cls == "U" and not e.answered])
        self.assertFalse([e for e in ev if e.status == "RESOLVED"])
        self.assertEqual([e.kind for e in ev if e.kind.startswith("SOURCE")], ["SOURCE_CHECK_FAILED"])
        log = st.access_log[-1]
        self.assertEqual((log["outcome"], log["fields_kept"]), ("failed", []))

    def test_record_settles_the_innocent_branch_as_source_record(self):
        st, _ = self.gov()
        st, ev = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=DPI), (), [self.rec("no_refills")])
        res = [e for e in ev if e.status == "RESOLVED"]
        self.assertEqual([(e.basis, e.data["reason"]) for e in res], [("source_record", "NO_REFILLS_PER_RECORD")])
        p = validate_payload(build_payload(st, ev))
        self.assertIn("SIMULATED", p["now"]["resolved"][0]["basis_label"])

    def test_record_without_purpose_or_for_another_household_is_refused(self):
        st, _ = self.gov()
        with self.assertRaises(PurposeNotGranted):
            advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=GOV), (), [self.rec("rerouted")])
        other = lpg.simulated("rerouted", requested_on=date(2026, 9, 9), household_id="HH-other",
                              account=self.kiran, purposes=DPI)
        with self.assertRaises(JoinRefused):
            advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=DPI), (), [other])

    def test_switching_off_only_the_lpg_check_forgets_what_the_record_produced(self):
        st, _ = self.gov()
        r = [self.rec("rerouted")]
        st, _ = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=DPI), (), r)
        a = [Answer(card(st, "LPG_SUBSIDY_ROUTING").id, "old_not_in_use", date(2026, 9, 10))]
        st, _ = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 10), purposes=DPI), a, r)
        st, ev = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 11), purposes=GOV), a, r)
        blob = json.dumps(validate_payload(build_payload(st, ev)), ensure_ascii=False)
        self.assertNotIn("4471", blob)
        self.assertFalse([f for f in st.hfacts if f.code == "ROUTED_ACCOUNT_STATUS"])
        self.assertTrue(card(st, "LPG_SUBSIDY_QUESTION"))           # back to asking the household

    def test_switching_off_a_purpose_never_drops_unrelated_answers(self):
        st, _ = run(self.c, self.hh, [(date(2026, 9, 8), DPI, (), ())])
        gap = card(st, "COLLECTION_GAP_QUESTION", self.kiran)
        st, ev = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=GOV),
                         [Answer(gap.id, "not_sure", date(2026, 9, 9))])
        self.assertIn("QUESTION_ANSWERED", [e.kind for e in ev])

    def test_a_simulated_record_stays_labelled_after_it_is_answered(self):
        st, _ = self.gov()
        r = [self.rec("rerouted")]
        st, _ = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=DPI), (), r)
        a = [Answer(card(st, "LPG_SUBSIDY_ROUTING").id, "old_not_in_use", date(2026, 9, 10))]
        st, ev = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 10), purposes=DPI), a, r)
        p = validate_payload(build_payload(st, ev))
        res = p["now"]["resolved"][0]
        self.assertTrue(res["simulated"] and "SIMULATED" in res["title"] and "SIMULATED" in res["text"])
        row = next(x for m in p["our_household"]["protections"]["members"] for x in m["schemes"]
                   if x["scheme"] == "PAHAL")
        self.assertIn("SIMULATED", row["badge"])
        self.assertIn("SIMULATED", " ".join(l.text for l in since_last_time(st, ev).lines))

    def test_last_four_digits_matching_another_member_is_never_called_the_same_account(self):
        st, _ = self.gov()
        raw = json.loads(json.dumps(lpg.SCENARIOS["rerouted"]))
        raw["result"]["BankAccountNo"] = "XXXXXXXX" + self.john[-4:]
        other = lpg.parse_response(raw, mode="simulated", requested_on=date(2026, 9, 9), purpose=PURPOSE_DPI_LPG,
                                   household_id=self.hh, account=self.kiran, join="simulated", fixture_id="T")
        st, ev = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=DPI), (), [other])
        r = card(st, "LPG_SUBSIDY_ROUTING")
        self.assertEqual(r.provenance["finding"], "OTHER_MEMBER")
        text, _ = render(r)
        self.assertIn("same last 4 digits as John's connected account", text)

    def test_payload_is_safe_deterministic_and_traceable_across_the_journey(self):
        st, _ = self.gov()
        a = [Answer(card(st, "AGE_BAND_QUESTION", self.kiran).id, "18_40", date(2026, 9, 9))]
        r = [self.rec("rerouted", date(2026, 9, 10))]
        for d, p in ((date(2026, 9, 9), GOV), (date(2026, 9, 10), DPI)):
            st, ev = advance(st, take_snapshot(self.c, self.hh, d, purposes=p), a, r)
            pay = validate_payload(build_payload(st, ev))
            self.assertEqual(pay, validate_payload(build_payload(st, ev)))
            blob = json.dumps(pay, ensure_ascii=False)
            self.assertFalse(PAN_RX.search(blob))
            self.assertFalse([n for n in self.narr if n in blob])
            self.assertNotIn("<dropped>", blob)
            self.assertIsNone(ELIGIBILITY.search(blob))
            for line in pay["now"]["since_last_time"]["lines"]:
                self.assertTrue(line["kind"] == "ROUTINE" or line["event_ids"])

    def test_ai_boundary_holds_on_a_door(self):
        st, _ = self.gov()
        st, ev = advance(st, take_snapshot(self.c, self.hh, date(2026, 9, 9), purposes=GOV),
                         [Answer(card(st, "AGE_BAND_QUESTION", self.john).id, "41_50", date(2026, 9, 9))])
        door = next(v for v in validate_payload(build_payload(st, ev))["now"]["cards"] if v["type"] == "DOOR")
        self.assertTrue(validate_explanation("PMJJBY costs ₹436 a year for ₹2,00,000 of life cover.", door))
        with self.assertRaises(UnsafeLanguage):
            validate_explanation("PMJJBY costs ₹330 a year.", door)
        with self.assertRaises(UnsafeLanguage):
            validate_explanation("John is eligible for PMJJBY.", door)


if __name__ == "__main__":
    unittest.main(verbosity=2)
