"""
--households acceptance tests: the operator's household switcher (a demo control, not customer access).

    MIRROR_DATA=<sealed decrypted.json> python -m unittest mirror.test_households -v

What is proven here:
  * without --households nothing changes: no new endpoints, meta unchanged, the SELA household as before;
  * the switcher lists exactly the households the corpus holds (nothing invented, nothing dropped,
    NAVEEN's two mobile-derived households never merged) and every word passes the language gate;
  * each household gets its own validated payload, its own saved state, its own answers and its own
    'Stop and forget' - an answer or an erase in one household never touches another, across restarts;
  * the same guards as every other POST apply, and the switcher stays off the AA journey screens;
  * on a live-fetched corpus the switcher works inside that corpus, labelled FETCHED LIVE.
No test makes a network call. Every store lives in a temporary folder.
"""
import hashlib, json, os, re, shutil, tempfile, unittest
from datetime import date
from pathlib import Path

from . import serve
from .language import gate
from .rules import PURPOSE_GOV_PROTECT as GOV

DATA = os.environ.get("MIRROR_DATA")
PORT = 8787
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = "test-token-households"


def digest(p) -> str:
    return hashlib.sha256(json.dumps(p, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


@unittest.skipUnless(DATA, "set MIRROR_DATA to the sealed corpus")
class Households(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        corpus = serve.load(DATA)
        cls.all_households = set(corpus.households())
        by_tail = {a.masked[-4:]: a.household_id for a in corpus.accounts}
        cls.SELA, cls.KUMAR = by_tail["9741"], by_tail["9950"]
        cls.NAVEEN_A, cls.NAVEEN_B = by_tail["9960"], by_tail["9334"]

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mirror-hh-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.environ.pop("MIRROR_HUB_LIVE", None)

    # ---- helpers ----
    def make(self, households=True, store=None):
        m = serve.Mirror(DATA, str(store or self.tmp / "store"), date(2026, 8, 28))
        m.start_if_needed()
        hub = serve.Hub(m)
        if households:
            hub.enable_households()
        return hub, serve.create_app(hub, PORT, TOKEN).test_client()

    def get(self, c, path, **kw):
        return c.get(path, base_url=BASE, **kw)

    def post(self, c, path, body, token=TOKEN, **kw):
        headers = {"X-Mirror-Token": token} if token else {}
        return c.post(path, base_url=BASE, json=body, headers=headers, **kw)

    def ok(self, resp):
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True)[:300])
        return resp.get_json()

    def select(self, c, hh):
        return self.ok(self.post(c, "/api/households/select", {"household": hh}))

    def payload(self, c):
        return self.ok(self.get(c, "/api/payload"))

    @staticmethod
    def card(p, code, tail=None):
        return next(x for x in p["now"]["cards"] if x["code"] == code and (tail is None or x["account"].endswith(tail)))

    # ---- 1. without the flag, nothing changes ----
    def test_without_the_flag_nothing_changes(self):
        hub, c = self.make(households=False)
        self.assertEqual(self.get(c, "/api/households").status_code, 404)
        self.assertEqual(self.post(c, "/api/households/select", {"household": self.KUMAR}).status_code, 404)
        meta = self.ok(self.get(c, "/api/meta"))
        self.assertNotIn("households_enabled", meta)
        self.assertNotIn("household", meta)
        self.assertEqual(meta["stops"], [{"date": d, "hint": h} for d, h in serve.REPLAY_STOPS])
        self.assertEqual(hub.current.hh, self.SELA)
        self.assertEqual(self.payload(c)["generated"]["household_id"], self.SELA)
        with self.assertRaises(serve.Refused):
            hub.households()

    def test_naming_the_sela_household_explicitly_gives_the_same_bytes(self):
        a = serve.Mirror(DATA, str(self.tmp / "a"), date(2026, 8, 28))
        b = serve.Mirror(DATA, str(self.tmp / "b"), date(2026, 8, 28), household=self.SELA)
        for m in (a, b):
            m.start_if_needed()
        self.assertEqual(digest(a.payload()), digest(b.payload()))
        with self.assertRaises(ValueError):
            serve.Mirror(DATA, str(self.tmp / "c"), date(2026, 8, 28), household="HH-0000000000")

    # ---- 2. the list: exactly what the corpus holds ----
    def test_lists_the_corpus_households_without_inventing_or_merging(self):
        _, c = self.make()
        hs = self.ok(self.get(c, "/api/households"))
        self.assertEqual([g["title"] for g in hs["groups"]],
                         ["SELA household", "KUMAR NAGARAJ household", "NAVEEN KUMAR household"])
        ids = [x["id"] for g in hs["groups"] for x in g["households"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), self.all_households)                    # nothing invented, nothing dropped
        naveen = hs["groups"][2]
        self.assertEqual({x["id"] for x in naveen["households"]}, {self.NAVEEN_A, self.NAVEEN_B})   # never merged
        self.assertIn("never merged", naveen["note"])
        sela = hs["groups"][0]["households"][0]
        self.assertEqual(sela["members"], ["John Sela Sr", "Kiran Sela Jr"])
        tails = [a["account"] for g in hs["groups"] for x in g["households"] for a in x["accounts"]]
        self.assertEqual(len(tails), len(set(tails)))                      # every account in one household only
        self.assertEqual(hs["unassigned_accounts"], ["…9335"])
        self.assertTrue(all(not a["read"] and "templated" in (a["not_read_reason"] or "") or a["account"] == "…9333"
                            for x in naveen["households"] for a in x["accounts"]))
        self.assertEqual(hs["current"], self.SELA)
        self.assertIn("each household consents for itself", hs["caveat"])
        self.assertIn("not a login", hs["caveat"])
        for s in strings(hs):
            gate(s)                                                         # evidence-language guard
        body = json.dumps(hs, ensure_ascii=False)
        self.assertIsNone(re.search(r"\d{9,}", body), "no unmasked account or mobile number")
        self.assertNotIn("DRWPG", body)                                     # PAN is never read, never shown

    # ---- 3. each household: its own validated payload ----
    def test_each_situation_has_its_own_validated_payload(self):
        hub, c = self.make()
        self.select(c, self.KUMAR)
        p = self.payload(c)
        self.assertEqual(p["generated"]["household_id"], self.KUMAR)
        self.assertEqual([m["display_name"] for m in p["our_household"]["members"]], ["Kumar Nagaraj"])
        self.assertEqual(p["now"]["cards"], [])
        self.assertTrue(p["now"]["since_last_time"]["lines"][0]["text"].startswith("Nothing needs you"))
        meta = self.ok(self.get(c, "/api/meta"))
        self.assertEqual(meta["household"], {"id": self.KUMAR, "label": "KUMAR NAGARAJ household"})
        self.assertTrue(all(s["hint"] == "" for s in meta["stops"]))       # SELA's story hints are not reused
        for hh in (self.NAVEEN_A, self.NAVEEN_B):
            self.select(c, hh)
            p = self.payload(c)
            self.assertEqual(p["generated"]["household_id"], hh)
            self.assertEqual(p["now"]["cards"], [])
            self.assertTrue(all(m["status"] == "not_used" and m["not_used_reason"] for m in p["our_household"]["members"]))
        self.select(c, self.SELA)
        self.assertIs(hub.current, hub.recorded)                           # one Mirror per household folder
        meta = self.ok(self.get(c, "/api/meta"))
        self.assertEqual(meta["stops"], [{"date": d, "hint": h} for d, h in serve.REPLAY_STOPS])
        self.assertEqual(self.card(self.payload(c), "LIC_GRACE_CLOCK")["member"], "John")

    # ---- 4. answers stay in their household ----
    def test_answers_are_isolated_between_households(self):
        hub, c = self.make()
        self.select(c, self.KUMAR)
        self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        q = self.card(self.payload(c), "AGE_BAND_QUESTION")
        self.ok(self.post(c, "/api/answers", {"answers": [{"card_id": q["id"], "option": "18_40"}]}))
        kumar = self.payload(c)
        self.assertEqual([(f["member"], f["value"]) for f in kumar["what_we_know"]["household_facts"]], [("Kumar", "18_40")])

        self.select(c, self.SELA)
        sela = self.payload(c)
        self.assertEqual(sela["what_we_know"]["household_facts"], [])
        self.assertNotIn(GOV, self.ok(self.get(c, "/api/meta"))["purposes_on"])
        self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        q = self.card(self.payload(c), "AGE_BAND_QUESTION", "9741")
        self.ok(self.post(c, "/api/answers", {"answers": [{"card_id": q["id"], "option": "41_50"}]}))

        self.select(c, self.KUMAR)
        kumar2 = self.payload(c)
        self.assertEqual([(f["member"], f["value"]) for f in kumar2["what_we_know"]["household_facts"]], [("Kumar", "18_40")])
        self.select(c, self.SELA)
        facts = self.payload(c)["what_we_know"]["household_facts"]
        self.assertEqual([(f["member"], f["value"]) for f in facts], [("John", "41_50")])
        # on disk: one folder per household, each holding only its own answers
        root = self.tmp / "store"
        k_state = (root / self.KUMAR / "state.json").read_text(encoding="utf-8")
        s_state = (root / self.SELA / "state.json").read_text(encoding="utf-8")
        self.assertIn("9950", k_state)
        self.assertNotIn("9741", k_state)
        self.assertNotIn("9950", s_state)
        self.assertFalse((root / self.NAVEEN_A).exists())                 # never shown, never started

    # ---- 5. 'Stop and forget' stays in its household ----
    def test_forgetting_is_isolated_between_households(self):
        hub, c = self.make()
        self.select(c, self.KUMAR)
        self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        self.assertEqual(self.ok(self.post(c, "/api/erase", {})), {"state": "forgotten"})
        self.assertEqual(self.payload(c), {"state": "forgotten"})
        root = self.tmp / "store"
        self.assertFalse((root / self.KUMAR / "state.json").exists())
        self.assertTrue((root / f".forgotten-{self.KUMAR}").exists())

        self.select(c, self.SELA)                                          # SELA untouched
        self.assertEqual(self.payload(c)["generated"]["household_id"], self.SELA)
        self.select(c, self.NAVEEN_A)
        self.assertEqual(self.payload(c)["generated"]["household_id"], self.NAVEEN_A)

        self.select(c, self.SELA)                                          # and the other way round
        self.ok(self.post(c, "/api/erase", {}))
        self.select(c, self.NAVEEN_A)
        self.assertEqual(self.payload(c)["generated"]["household_id"], self.NAVEEN_A)
        self.select(c, self.KUMAR)
        self.assertEqual(self.payload(c), {"state": "forgotten"})          # still forgotten, not revived

        # the operator's restart clears only the household being shown
        self.ok(self.post(c, "/api/replay/restart", {"as_of": "2026-08-28"}))
        self.assertEqual(self.payload(c)["generated"]["household_id"], self.KUMAR)
        self.assertEqual(self.payload(c)["what_we_know"]["household_facts"], [])
        self.assertTrue((root / f".forgotten-{self.SELA}").exists())

    # ---- 6. each household's state survives a restart of the server ----
    def test_each_household_state_survives_a_restart(self):
        hub, c = self.make()
        self.select(c, self.KUMAR)
        self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        q = self.card(self.payload(c), "AGE_BAND_QUESTION")
        self.ok(self.post(c, "/api/answers", {"answers": [{"card_id": q["id"], "option": "18_40"}]}))
        before = digest(self.payload(c))

        hub2, c2 = self.make()                                             # a new process on the same --store
        self.assertEqual(self.payload(c2)["what_we_know"]["household_facts"], [])
        self.select(c2, self.KUMAR)
        self.assertEqual(digest(self.payload(c2)), before)

    # ---- 7. guards ----
    def test_the_usual_guards_apply(self):
        hub, c = self.make()
        self.assertEqual(self.post(c, "/api/households/select", {"household": self.KUMAR}, token=None).status_code, 403)
        self.assertEqual(self.post(c, "/api/households/select", {"household": self.KUMAR}, token="wrong").status_code, 403)
        r = c.post("/api/households/select", base_url=BASE, data="household=x", headers={"X-Mirror-Token": TOKEN},
                   content_type="application/x-www-form-urlencoded")
        self.assertEqual(r.status_code, 415)
        self.assertEqual(c.get("/api/households", base_url="http://evil.example").status_code, 403)
        for bad in ("HH-0000000000", 7, None, "", "../store"):
            self.assertEqual(self.post(c, "/api/households/select", {"household": bad}).status_code, 400)
        self.assertEqual(hub.current.hh, self.SELA)

    def test_refused_on_the_aa_journey_screens(self):
        hub, c = self.make()
        hub.entry = "connect"                                              # Gate 7 welcome / journey showing
        r = self.post(c, "/api/households/select", {"household": self.KUMAR})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(hub.current.hh, self.SELA)

    # ---- 8. a live-fetched corpus ----
    def test_switching_inside_a_live_fetched_corpus(self):
        hub, c = self.make()
        live_file = self.tmp / "captures" / "LIVE_test" / "decrypted.json"
        live_file.parent.mkdir(parents=True)
        shutil.copyfile(DATA, live_file)
        hub.attach_live(live_file, {"fetched_at": "28 Sep 2026 06:31", "matches_e8": True})
        live_sela = hub.current
        self.assertEqual(live_sela.source["kind"], "live")
        hs = self.ok(self.get(c, "/api/households"))
        self.assertEqual(hs["source"], "live")

        self.select(c, self.KUMAR)
        self.assertEqual(hub.current.source["kind"], "live")
        self.assertEqual(hub.current.root, live_sela.root)                 # the live store, not the recorded one
        meta = self.ok(self.get(c, "/api/meta"))
        self.assertEqual(meta["corpus_source"], "live")
        self.assertTrue(meta["corpus_label"].startswith("FETCHED LIVE"))
        self.assertFalse((self.tmp / "store" / self.KUMAR).exists())      # the recorded store is untouched

        self.select(c, self.SELA)
        self.assertIs(hub.current, live_sela)                              # back to the same live household
        self.ok(self.post(c, "/api/connect/use-recorded", {}))             # Gate 7 fallback: the sealed SELA recording
        self.assertIs(hub.current, hub.recorded)


if __name__ == "__main__":
    unittest.main()
