"""
Counterparty Mirror - Batch 1c tests: durable state (save -> reload).
Each test is one persistence or governance guarantee.

  python -m unittest mirror.test_batch1c -v                   (synthetic only)
  MIRROR_DATA=<sealed decrypted.json> python -m unittest mirror.test_batch1c -v
"""
import json, os, shutil, tempfile, unittest
from datetime import date

from mirror.corpus import load
from mirror.events import Answer
from mirror.facts import FactStatement
from mirror.contract import build_payload, validate_payload
from mirror.cards import PAN_RX
from mirror.store import JsonFileStore, StoreCorrupt, StoreMismatch, StoreNotFound, StoreError, _sha, refresh
from mirror.rules import PURPOSE_AA_PROTECT, PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG
from mirror.sources import lpg
from mirror.test_mirror import _xml, _write, FILLER

DATA = os.environ.get("MIRROR_DATA")
AA = frozenset({PURPOSE_AA_PROTECT})
GOV = AA | {PURPOSE_GOV_PROTECT}
DPI = GOV | {PURPOSE_DPI_LPG}


def canon(p):
    return json.dumps(p, sort_keys=True, ensure_ascii=False)


def reseal(d):
    """What someone with disk access (but no MIRROR_STORE_KEY) could do: recompute the plain checksum."""
    d["meta"]["seal"] = {"sha256": _sha({"purpose_history": d["purpose_history"], "state": d["state"]})}
    return d


def card(st, code, account=None):
    return next((c for c, _ in st.open_cards if c.code == code and (account is None or c.account == account)), None)


class Session:
    """What the app does on every refresh: load (or start), advance, save."""

    def __init__(self, corpus, household_id, root):
        self.c, self.hh, self.store = corpus, household_id, JsonFileStore(root)

    def refresh(self, as_of, purposes, answers=(), records=()):
        st, ev = refresh(self.store, self.c, self.hh, as_of, purposes, answers, records)
        return st, ev, validate_payload(build_payload(st, ev))

    def reload(self):
        st, ev = self.store.load(self.c, self.hh)
        return st, ev, validate_payload(build_payload(st, ev))

    def file_text(self):
        return (self.store.root / self.hh / "state.json").read_text(encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mirror-store-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)


class Synthetic(Base):
    def one(self):
        c = load(_write([("XXXX0011", _xml('name="R ONE" mobile="9000000011"', FILLER))]))
        return c, c.accounts[0].household_id, c.accounts[0].masked

    def test_save_reload_preserves_facts_corrections_purposes_closures_and_first_seen(self):
        c, hh, acc = self.one()
        s = Session(c, hh, self.root)
        st, _, _ = s.refresh(date(2025, 12, 1), GOV)
        q = card(st, "AGE_BAND_QUESTION")
        a = [Answer(q.id, "41_50", date(2025, 12, 2)), FactStatement(acc, "AGE_BAND", "51_70", date(2025, 12, 3))]
        s.refresh(date(2025, 12, 2), GOV, a)
        st, ev, before = s.refresh(date(2025, 12, 3), GOV, a)
        st2, ev2, after = s.reload()
        self.assertEqual([(f.code, f.value) for f in st2.hfacts], [("AGE_BAND", "51_70")])
        self.assertEqual([(x.old_value, x.new_value) for x in st2.corrections], [("41_50", "51_70")])
        self.assertEqual(st2.snapshot.purposes, GOV)
        self.assertEqual(st2.closed, st.closed)
        self.assertEqual(st2.open_cards, st.open_cards)                 # same cards, same first_seen
        self.assertEqual((st2.as_of, st2.since), (st.as_of, st.since))
        self.assertEqual(canon(after), canon(before))

    def test_repeated_reload_never_duplicates_facts_or_corrections(self):
        c, hh, acc = self.one()
        s = Session(c, hh, self.root)
        st, _, _ = s.refresh(date(2025, 12, 1), GOV)
        a = [Answer(card(st, "AGE_BAND_QUESTION").id, "41_50", date(2025, 12, 2)),
             FactStatement(acc, "AGE_BAND", "51_70", date(2025, 12, 3))]
        kinds = []
        for d in range(2, 9):                                   # 7 app sessions, same answer list every time
            _, ev, _ = s.refresh(date(2025, 12, d), GOV, a)
            kinds += [e.kind for e in ev if e.kind.startswith("FACT_")]
            s.reload()
        self.assertEqual(kinds, ["FACT_CONFIRMED", "FACT_CORRECTED"])
        st, _, _ = s.reload()
        self.assertEqual((len(st.hfacts), len(st.corrections)), (1, 1))

    def test_purpose_off_is_durable_and_leaves_the_disk(self):
        c, hh, acc = self.one()
        s = Session(c, hh, self.root)
        st, _, _ = s.refresh(date(2025, 12, 1), GOV)
        a = [Answer(card(st, "AGE_BAND_QUESTION").id, "41_50", date(2025, 12, 2))]
        s.refresh(date(2025, 12, 2), GOV, a)
        self.assertIn("41_50", s.file_text())
        s.refresh(date(2025, 12, 3), AA, a)                      # switched off
        self.assertNotIn("41_50", s.file_text())
        self.assertNotIn("AGE_BAND_QUESTION", s.file_text().split('"access_log"')[0])
        st, _, p = s.reload()
        self.assertEqual((st.hfacts, st.corrections, st.records), ((), (), ()))
        self.assertEqual(st.access_log[-1]["what"], "forgotten")
        st, _, p = s.refresh(date(2025, 12, 4), GOV, a)          # back on, old answer offered again
        self.assertEqual(st.hfacts, ())
        self.assertTrue(card(st, "AGE_BAND_QUESTION"))
        self.assertEqual([x["on"] for x in s.store.purpose_history(hh)], [True, False, True])

    def test_edits_and_forbidden_content_are_refused_on_load(self):
        c, hh, acc = self.one()
        s = Session(c, hh, self.root)
        st, _, _ = s.refresh(date(2025, 12, 1), GOV)
        s.refresh(date(2025, 12, 2), GOV, [Answer(card(st, "AGE_BAND_QUESTION").id, "41_50", date(2025, 12, 2))])
        path = s.store.root / hh / "state.json"
        good = path.read_text(encoding="utf-8")
        path.write_text(good.replace('"41_50"', '"18_40"'), encoding="utf-8")
        with self.assertRaises(StoreCorrupt):                    # hand edit: checksum
            s.reload()
        doc = json.loads(good)                                   # re-sealed edits are still refused
        for mutate in (lambda b: b["household_facts"][0].update(value="1986-07-10"),
                       lambda b: b["household_facts"][0].update(evidence_class="O"),
                       lambda b: b.update(purposes=["AA_PROTECT"])):
            d = json.loads(good)
            mutate(d["state"])
            path.write_text(json.dumps(reseal(d)), encoding="utf-8")
            with self.assertRaises(StoreCorrupt):
                s.reload()
        d = json.loads(good)
        d["meta"]["engines"]["unlock"] = "mirror-unlock-0"
        path.write_text(json.dumps(d), encoding="utf-8")
        with self.assertRaises(StoreMismatch):
            s.reload()
        path.write_text(good, encoding="utf-8")
        other = load(_write([("XXXX0011", _xml('name="R ONE" mobile="9000000011"', FILLER[:-1]))]))
        with self.assertRaises(StoreMismatch):                   # a different corpus can't reproduce it
            s.store.load(other, hh)
        self.assertEqual(doc["meta"]["household_id"], hh)

    def test_an_answer_given_on_the_day_of_the_last_refresh_is_kept_and_speaks(self):
        c, hh, acc = self.one()
        s = Session(c, hh, self.root)
        st, _, _ = s.refresh(date(2025, 12, 1), GOV)
        _, ev, _ = s.refresh(date(2025, 12, 1), GOV, [Answer(card(st, "AGE_BAND_QUESTION").id, "41_50", date(2025, 12, 1))])
        self.assertEqual([e.kind for e in ev if e.kind.startswith("FACT_")], ["FACT_CONFIRMED"])
        st, _, _ = s.reload()
        self.assertEqual([(f.code, f.value) for f in st.hfacts], [("AGE_BAND", "41_50")])

    def test_reopening_on_the_same_day_keeps_the_briefing(self):
        c, hh, acc = self.one()
        s = Session(c, hh, self.root)
        s.refresh(date(2025, 12, 1), AA)
        _, ev, p = s.refresh(date(2025, 12, 2), GOV)
        _, ev2, p2 = s.refresh(date(2025, 12, 2), GOV)                 # the app is opened again
        self.assertEqual([e.id for e in ev2], [e.id for e in ev])
        self.assertEqual(canon(p2), canon(p))
        self.assertTrue(any(l["kind"] == "CHANGE" for l in p2["now"]["since_last_time"]["lines"]))

    def test_keyed_seal_refuses_a_resealed_edit_and_history_holds_no_hash(self):
        c, hh, acc = self.one()
        old = os.environ.get("MIRROR_STORE_KEY")
        os.environ["MIRROR_STORE_KEY"] = "test-key-not-a-secret"
        try:
            s = Session(c, hh, self.root)
            st, _, _ = s.refresh(date(2025, 12, 1), GOV)
            s.refresh(date(2025, 12, 2), GOV, [Answer(card(st, "AGE_BAND_QUESTION").id, "41_50", date(2025, 12, 2))])
            path = s.store.root / hh / "state.json"
            d = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("hmac_sha256", d["meta"]["seal"])
            d["state"]["household_facts"][0]["value"] = "18_40"
            path.write_text(json.dumps(reseal(d)), encoding="utf-8")
            with self.assertRaises(StoreCorrupt):
                s.reload()
        finally:
            os.environ.pop("MIRROR_STORE_KEY") if old is None else os.environ.__setitem__("MIRROR_STORE_KEY", old)
        for line in s.store.history(hh):
            self.assertFalse([k for k in line if "sha" in k])

    def test_torn_history_leftover_temp_files_and_bad_ids_do_not_break_the_store(self):
        c, hh, acc = self.one()
        s = Session(c, hh, self.root)
        s.refresh(date(2025, 12, 1), GOV)
        folder = s.store.root / hh
        with open(folder / "history.jsonl", "a", encoding="utf-8") as f:
            f.write('{"as_of": "2025-12-0')                        # a crash mid-append
        (folder / ".state-crash.tmp").write_text('{"forgotten": "material"}', encoding="utf-8")
        s.refresh(date(2025, 12, 2), GOV)
        self.assertEqual([h["as_of"] for h in s.store.history(hh)], ["2025-12-01", "2025-12-02"])
        self.assertFalse(list(folder.glob(".state-*.tmp")))
        for bad in ("HH-abc ", "HH-a*b", "HH-", "../HH-226db7a65c", None, "HH-ABCDEF"):
            with self.assertRaises(StoreError):
                s.store.exists(bad)

    def test_erase_is_stop_and_forget_for_the_household(self):
        c, hh, acc = self.one()
        s = Session(c, hh, self.root)
        s.refresh(date(2025, 12, 1), GOV)
        self.assertTrue(s.store.erase(hh))
        self.assertFalse((s.store.root / hh).exists())
        with self.assertRaises(StoreNotFound):
            s.reload()

    def test_no_raw_bank_data_and_no_stray_files(self):
        c, hh, acc = self.one()
        s = Session(c, hh, self.root)
        st, _, _ = s.refresh(date(2025, 12, 1), GOV)
        s.refresh(date(2025, 12, 2), GOV, [Answer(card(st, "AGE_BAND_QUESTION").id, "41_50", date(2025, 12, 2))])
        text = s.file_text()
        self.assertNotIn("UPI/123/FOOD", text)                   # the filler narration
        self.assertNotIn("9000000011", text)                     # the holder's mobile
        self.assertEqual(sorted(p.name for p in (s.store.root / hh).iterdir()), ["history.jsonl", "state.json"])
        for line in s.store.history(hh):                         # history carries counts, never answers
            self.assertNotIn("41_50", json.dumps(line))


@unittest.skipUnless(DATA, "set MIRROR_DATA to the sealed decrypted.json")
class OnCorpus(Base):
    @classmethod
    def setUpClass(cls):
        cls.c = load(DATA)
        cls.hh = cls.c.account("9741").household_id
        cls.john, cls.kiran = cls.c.account("9741").masked, cls.c.account("9648").masked
        cls.narr = {t.narration for a in cls.c.accounts for t in a.txns if len(t.narration) > 12}

    def rec(self, scenario, on, purposes=DPI):
        return lpg.simulated(scenario, requested_on=on, household_id=self.hh, account=self.kiran, purposes=purposes)

    def test_the_whole_story_reloads_to_the_same_contract_at_every_step(self):
        s = Session(self.c, self.hh, self.root)
        a, r = [], []
        steps = [(date(2026, 9, 7), AA), (date(2026, 9, 8), GOV), (date(2026, 9, 9), GOV), (date(2026, 9, 10), GOV),
                 (date(2026, 9, 11), DPI), (date(2026, 9, 12), DPI), (date(2026, 9, 13), DPI), (date(2026, 9, 14), GOV),
                 (date(2026, 9, 15), AA)]
        for d, p in steps:
            if d == date(2026, 9, 9):
                st, _, _ = s.reload()
                a += [Answer(card(st, "AGE_BAND_QUESTION", self.john).id, "41_50", d),
                      Answer(card(st, "AGE_BAND_QUESTION", self.kiran).id, "18_40", d)]
            if d == date(2026, 9, 10):
                a.append(Answer(card(s.reload()[0], "TAXPAYER_QUESTION", self.kiran).id, "no", d))
            if d == date(2026, 9, 11):
                r.append(self.rec("rerouted", d))
            if d == date(2026, 9, 12):
                a.append(Answer(card(s.reload()[0], "LPG_SUBSIDY_ROUTING").id, "old_not_in_use", d))
            if d == date(2026, 9, 13):
                a.append(FactStatement(self.john, "AGE_BAND", "51_70", d))
            _, _, before = s.refresh(d, p, a, r)
            _, _, after = s.reload()
            self.assertEqual(canon(after), canon(before), f"contract changed across reload on {d}")
            text = s.file_text()
            self.assertFalse(PAN_RX.search(text))
            self.assertFalse([n for n in self.narr if n in text], "raw narrations must never be stored")
        st, _, _ = s.reload()
        self.assertEqual((st.hfacts, st.records), ((), ()))
        self.assertNotIn("4471", s.file_text())
        self.assertEqual([x["what"] for x in st.access_log], ["lookup", "forgotten", "forgotten"])
        self.assertEqual((st.access_log[0]["request_ref"], st.access_log[0]["fields_kept"]), ("", []))
        self.assertNotIn("SIM-LPG-", s.file_text())                   # not even the fixture's name survives

    def test_simulated_provenance_and_disclosure_survive_reload(self):
        s = Session(self.c, self.hh, self.root)
        s.refresh(date(2026, 9, 8), GOV)
        s.refresh(date(2026, 9, 9), DPI, (), [self.rec("rerouted", date(2026, 9, 9))])
        st, _, p = s.reload()
        self.assertEqual([(x.mode, x.join, x.status) for x in st.records], [("simulated", "simulated", "ok")])
        view = next(v for v in p["now"]["cards"] if v["code"] == "LPG_SUBSIDY_ROUTING")
        self.assertIn("SIMULATED", view["title"])
        dpi = p["what_we_know"]["dpi_integrations"][0]
        self.assertEqual((dpi["live_lookup_for_this_household"]["status"], dpi["disclosure"]),
                         ("not performed", lpg.DISCLOSURE))
        path = s.store.root / self.hh / "state.json"                # a live record can't be smuggled in
        d = json.loads(path.read_text(encoding="utf-8"))
        good = json.dumps(d)
        for mutate in (lambda r: r.update(mode="live", join="customer_confirmed"),
                       lambda r: r.update(lpg_id_tail="4321"),                    # marks of a live lookup
                       lambda r: r.update(request_ref="5c0f81d6-68b9-44bc-8c41-b97c9693cdce"),
                       lambda r: r["fields"].update(pan="ABCDE1234F"),            # outside the whitelist
                       lambda r: r["fields"].update(account_tail="123456789012")):
            d = json.loads(good)
            mutate(d["state"]["records"][0])
            path.write_text(json.dumps(reseal(d)), encoding="utf-8")
            with self.assertRaises(StoreCorrupt):
                s.reload()

    def test_failed_and_refused_lookups_stay_failures_after_reload(self):
        s = Session(self.c, self.hh, self.root)
        s.refresh(date(2026, 9, 8), GOV)
        refused = self.rec("rerouted", date(2026, 9, 9), purposes=GOV)          # LPG check not on: no call
        s.refresh(date(2026, 9, 9), GOV, (), [refused])
        failed = self.rec("invalid_id", date(2026, 9, 10))
        s.refresh(date(2026, 9, 10), DPI, (), [refused, failed])
        for _ in range(2):
            st, _, p = s.reload()
            self.assertEqual([(x.status, x.reason, x.fields) for x in st.records],
                             [("failed", "ID_NOT_RECOGNISED", {})])
            self.assertEqual([x["outcome"] for x in st.access_log], ["refused", "failed"])
            q = card(st, "LPG_SUBSIDY_QUESTION")
            self.assertEqual(q.provenance["dpi_lookup"]["reason"], "ID_NOT_RECOGNISED")
            self.assertFalse(p["now"]["resolved"])
            self.assertFalse([v for v in p["now"]["cards"] if v["code"] == "LPG_SUBSIDY_ROUTING"])
        path = s.store.root / self.hh / "state.json"
        d = json.loads(path.read_text(encoding="utf-8"))
        d["state"]["records"][0]["fields"] = {"last_booking_date": "2026-05-01"}  # a failure dressed as data
        path.write_text(json.dumps(reseal(d)), encoding="utf-8")
        with self.assertRaises(StoreCorrupt):
            s.reload()

    def test_the_lpg_check_off_alone_is_durable(self):
        s = Session(self.c, self.hh, self.root)
        s.refresh(date(2026, 9, 8), GOV)
        r = [self.rec("rerouted", date(2026, 9, 9))]
        st, _, _ = s.refresh(date(2026, 9, 9), DPI, (), r)
        a = [Answer(card(st, "LPG_SUBSIDY_ROUTING").id, "old_not_in_use", date(2026, 9, 10))]
        s.refresh(date(2026, 9, 10), DPI, a, r)
        s.refresh(date(2026, 9, 11), GOV, a, r)
        text = s.file_text()
        self.assertNotIn("4471", text)
        self.assertNotIn("Sample Bank", text)
        st, _, _ = s.refresh(date(2026, 9, 12), DPI, a, r)          # back on; old record and answer offered
        self.assertEqual((st.records, [f for f in st.hfacts if f.code == "ROUTED_ACCOUNT_STATUS"]), ((), []))
        self.assertTrue(card(st, "LPG_SUBSIDY_QUESTION"))

    def test_gate_23_story_survives_a_reload_mid_way(self):
        s = Session(self.c, self.hh, self.root)
        s.refresh(date(2026, 8, 28), AA)
        st, _, _ = s.reload()
        lic = card(st, "LIC_GRACE_CLOCK")
        _, ev, _ = s.refresh(date(2026, 9, 7), AA)
        self.assertEqual([(e.kind, e.card_id) for e in ev if e.card_id == lic.id], [("CARD_CONTINUING", lic.id)])
        self.assertEqual({c.id: f for c, f in s.reload()[0].open_cards}[lic.id], date(2026, 8, 28))  # first_seen kept
        a = [Answer(lic.id, "already_paid", date(2026, 9, 9))]
        _, ev, _ = s.refresh(date(2026, 9, 9), AA, a)
        self.assertIn(("RESOLVED", "you_told_us"), [(e.status, e.basis) for e in ev if e.card_id == lic.id])
        _, ev, p = s.refresh(date(2026, 9, 12), AA, a)
        self.assertFalse([e for e in ev if e.card_id == lic.id])
        self.assertTrue(p["now"]["since_last_time"]["silent"])                      # "Nothing needs you."


if __name__ == "__main__":
    unittest.main(verbosity=2)
