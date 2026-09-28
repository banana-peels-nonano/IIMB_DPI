"""
--demo-login acceptance tests: the phone-entry screen opens a sandbox household (DEMO / SANDBOX, not authentication).

    MIRROR_DATA=<sealed decrypted.json> python -m unittest mirror.test_demo_login -v

What is proven here:
  * without --demo-login nothing changes (no /api/login, meta unchanged, Gate 6 and Gate 7 entries as before);
  * the directory maps three demo numbers to three different households, derived from account endings in the
    corpus; NAVEEN's second mobile is not reachable and nothing is merged; the directory refuses to start if broken;
  * no response carries a holder mobile, a PAN, a household id, a hash or the typed number;
  * 9999999998 / 9999999997 open only the SEALED RECORDING and can never start an AA consent (even by calling
    /api/connect/start directly, and even after a live fetch this session);
  * 9999999999 takes the verified Gate 7 journey when the AA kit is on, and the sealed SELA household when it is off;
  * signing out shows nothing of any household; each household keeps its own answers and 'Stop and forget'.
The AA journey runs against the same stand-in kit as test_gate7 (no network, no secrets).
"""
import json, os, re, shutil, tempfile, unittest
from datetime import date
from pathlib import Path

from . import serve, aa_link
from .language import gate
from .rules import PURPOSE_GOV_PROTECT as GOV
from .test_gate7 import FakeKit

DATA = os.environ.get("MIRROR_DATA")
PORT = 8787
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = "test-token-demo-login"
SELA_NO, NAGARAJ_NO, NAVEEN_NO = "9999999999", "9999999998", "9999999997"


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
class DemoLogin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        corpus = serve.load(DATA)
        by_tail = {a.masked[-4:]: a.household_id for a in corpus.accounts}
        cls.SELA, cls.KUMAR = by_tail["9741"], by_tail["9950"]
        cls.NAVEEN_A, cls.NAVEEN_B = by_tail["9960"], by_tail["9334"]
        cls.all_ids = set(corpus.households())

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mirror-dl-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.captures = self.tmp / "captures"
        self.captures.mkdir()
        self.kit = FakeKit(self.captures)
        os.environ.pop("MIRROR_HUB_LIVE", None)

    # ---- helpers ----
    def make(self, demo=True, link=False, store=None):
        m = serve.Mirror(DATA, str(store or self.tmp / "store"), date(2026, 8, 28))
        m.start_if_needed()
        hub = serve.Hub(m)
        if link:
            hub.link = aa_link.AALink(self.kit, self.kit.decrypt, self.captures, hub.attach_live, poll=None)
            hub.entry = "connect"
        if demo:
            hub.enable_demo_login()
        return hub, serve.create_app(hub, PORT, TOKEN).test_client()

    def get(self, c, path, **kw):
        return c.get(path, base_url=BASE, **kw)

    def post(self, c, path, body, token=TOKEN, **kw):
        headers = {"X-Mirror-Token": token} if token else {}
        return c.post(path, base_url=BASE, json=body, headers=headers, **kw)

    def ok(self, resp):
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True)[:300])
        return resp.get_json()

    def login(self, c, number):
        return self.ok(self.post(c, "/api/login", {"mobile": number}))

    def logout(self, c):
        return self.ok(self.post(c, "/api/logout", {}))

    def payload(self, c):
        return self.ok(self.get(c, "/api/payload"))

    @staticmethod
    def card(p, code, tail=None):
        return next(x for x in p["now"]["cards"] if x["code"] == code and (tail is None or x["account"].endswith(tail)))

    @staticmethod
    def no_fingerprint(meta):
        """The corpus SHA-256 (an existing Gate 6 meta field) is a data fingerprint, not a person's identifier."""
        return {k: v for k, v in meta.items() if k != "corpus_sha256"}

    def assert_no_identifiers(self, text):
        self.assertIsNone(re.search(r"\d{9,}", text), "no mobile or unmasked number")
        self.assertNotIn("HH-", text)
        self.assertNotIn("DRWPG", text)                                    # PAN is never read, never shown

    # ---- 1. flag off: nothing changes ----
    def test_without_the_flag_nothing_changes(self):
        hub, c = self.make(demo=False)
        self.assertEqual(self.post(c, "/api/login", {"mobile": NAGARAJ_NO}).status_code, 404)
        self.assertEqual(self.post(c, "/api/logout", {}).status_code, 404)
        meta = self.ok(self.get(c, "/api/meta"))
        self.assertNotIn("demo_login", meta)
        self.assertNotIn("household", meta)
        self.assertEqual(meta["connect"]["entry"], "app")
        self.assertEqual(self.payload(c)["generated"]["household_id"], self.SELA)
        hub7, c7 = self.make(demo=False, link=True, store=self.tmp / "s7")
        self.assertEqual(self.payload(c7), {"state": "connect"})         # the Gate 7 welcome, as before
        r = self.post(c7, "/api/connect/start", {"mobile": NAGARAJ_NO})  # without the flag, Gate 7 is unchanged
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.kit.consents), 1)

    # ---- 2. the directory ----
    def test_directory_maps_three_numbers_to_three_households_without_merging(self):
        hub, _ = self.make()
        targets = {n: hh for n, (hh, _) in hub._logins.items()}
        self.assertEqual(targets, {SELA_NO: self.SELA, NAGARAJ_NO: self.KUMAR, NAVEEN_NO: self.NAVEEN_A})
        self.assertNotIn(self.NAVEEN_B, targets.values())                 # not merged, not listed
        self.assertTrue(set(targets.values()) <= self.all_ids)            # nothing invented
        self.assertEqual([n for n, (_, aa) in hub._logins.items() if aa], [SELA_NO])
        for row in serve.DEMO_LOGINS:                                     # the directory holds no mobile or hash
            self.assertEqual(set(row), {"number", "account", "aa"})
            self.assertRegex(row["account"], r"^\d{4}$")

    def test_a_broken_directory_refuses_to_start(self):
        for bad in (({"number": SELA_NO, "account": "9741", "aa": True}, {"number": NAGARAJ_NO, "account": "9648", "aa": False}),
                    ({"number": SELA_NO, "account": "0000", "aa": True},),
                    ({"number": SELA_NO, "account": "9950", "aa": True},)):
            with self.subTest(bad=bad):
                m = serve.Mirror(DATA, str(self.tmp / "b"), date(2026, 8, 28))
                hub = serve.Hub(m)
                orig = serve.DEMO_LOGINS
                serve.DEMO_LOGINS = bad
                try:
                    with self.assertRaises(SystemExit):
                        hub.enable_demo_login()
                finally:
                    serve.DEMO_LOGINS = orig

    # ---- 3. signed out: nothing of any household ----
    def test_signed_out_serves_nothing_of_any_household(self):
        hub, c = self.make()
        self.assertEqual(self.payload(c), {"state": "login"})
        self.assertEqual(self.ok(self.get(c, "/api/history")), {"state": "login"})
        self.assertEqual(self.post(c, "/api/answers", {"answers": [{"card_id": "x", "option": "y"}]}).status_code, 409)
        self.assertEqual(self.post(c, "/api/erase", {}).status_code, 409)
        meta = self.ok(self.get(c, "/api/meta"))
        self.assertEqual(meta["connect"]["entry"], "login")
        self.assertEqual(meta["demo_login"]["signed_in"], False)
        self.assertNotIn("household", meta)
        self.assertIn("not authentication", meta["demo_login"]["note"])
        self.assertIn("each household would consent for itself", meta["demo_login"]["note"])

    # ---- 4. the three numbers, recorded mode ----
    def test_each_number_opens_its_recorded_household(self):
        hub, c = self.make()
        res = self.login(c, NAGARAJ_NO)
        self.assertEqual(res, {"route": "app", "label": "KUMAR NAGARAJ household"})
        p = self.payload(c)
        self.assertEqual(p["generated"]["household_id"], self.KUMAR)
        self.assertEqual(p["now"]["cards"], [])
        self.assertTrue(p["now"]["since_last_time"]["lines"][0]["text"].startswith("Nothing needs you"))
        meta = self.ok(self.get(c, "/api/meta"))
        self.assertEqual(meta["household"], {"label": "KUMAR NAGARAJ household"})    # a label, never an id
        self.assertEqual(meta["corpus_source"], "recorded")
        self.assert_no_identifiers(json.dumps(res) + json.dumps(self.no_fingerprint(meta)))

        self.logout(c)
        self.login(c, NAVEEN_NO)
        p = self.payload(c)
        self.assertEqual(p["generated"]["household_id"], self.NAVEEN_A)
        self.assertTrue(all(m["status"] == "not_used" and "templated" in m["not_used_reason"]
                            for m in p["our_household"]["members"]))

        self.logout(c)
        self.assertEqual(self.login(c, SELA_NO), {"route": "app", "label": "SELA household"})   # no AA kit: recorded
        self.assertIs(hub.current, hub.recorded)
        self.assertEqual(self.card(self.payload(c), "LIC_GRACE_CLOCK")["member"], "John")
        self.assertEqual(self.ok(self.get(c, "/api/meta"))["stops"], [{"date": d, "hint": h} for d, h in serve.REPLAY_STOPS])

    def test_unknown_or_malformed_numbers_are_refused_without_listing_any(self):
        hub, c = self.make()
        r = self.post(c, "/api/login", {"mobile": "9876543210"})
        self.assertEqual(r.status_code, 404)
        body = r.get_data(as_text=True)
        self.assertNotIn("99999", body)
        self.assertIn("demo", body)
        for bad in ("12345", "0999999999", 9999999998, None, "", "+919999999998"):
            self.assertEqual(self.post(c, "/api/login", {"mobile": bad}).status_code, 400, bad)
        self.assertEqual(self.post(c, "/api/login", {"mobile": NAGARAJ_NO}, token=None).status_code, 403)
        r = c.post("/api/login", base_url=BASE, data="mobile=9999999998", headers={"X-Mirror-Token": TOKEN},
                   content_type="application/x-www-form-urlencoded")
        self.assertEqual(r.status_code, 415)
        self.assertEqual(self.payload(c), {"state": "login"})               # still signed out
        for s in (serve.DEMO_LOGIN_NOTE, serve.DEMO_LOGIN_UNKNOWN, serve.DEMO_LOGIN_NO_AA):
            gate(s)

    # ---- 5. the AA journey: only 9999999999 ----
    def test_only_the_aa_test_customer_can_start_an_aa_consent(self):
        hub, c = self.make(link=True)
        self.assertEqual(self.payload(c), {"state": "login"})
        for n in (NAGARAJ_NO, NAVEEN_NO):
            self.assertEqual(self.login(c, n)["route"], "app")
            self.assertEqual(self.ok(self.get(c, "/api/meta"))["corpus_source"], "recorded")
            r = self.post(c, "/api/connect/start", {"mobile": n})              # even called directly
            self.assertEqual(r.status_code, 403)
            self.logout(c)
        r = self.post(c, "/api/connect/start", {"mobile": "9876543210"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.kit.consents, [])                               # no AA call was ever made

        self.assertEqual(self.login(c, SELA_NO), {"route": "aa"})             # the verified Gate 7 path
        self.assertEqual(self.payload(c), {"state": "connect"})
        self.assertEqual(self.kit.consents, [])                               # nothing until 'Ask my Account Aggregator'
        st = self.ok(self.post(c, "/api/connect/start", {"mobile": SELA_NO}))
        self.assertEqual(st["state"], "requested")
        self.assertEqual(self.kit.consents[0][0], SELA_NO)
        self.logout(c)                                                         # a waiting journey stops
        self.assertEqual(self.ok(self.get(c, "/api/connect"))["state"], "idle")
        self.assertEqual(self.payload(c), {"state": "login"})

    def test_other_numbers_stay_recorded_after_a_live_fetch(self):
        hub, c = self.make(link=True)
        self.login(c, SELA_NO)
        live = self.tmp / "captures" / "LIVE_test" / "decrypted.json"
        live.parent.mkdir(parents=True)
        shutil.copyfile(DATA, live)
        hub.attach_live(live, {"fetched_at": "28 Sep 2026 06:31", "matches_e8": True})
        self.assertEqual(self.ok(self.get(c, "/api/meta"))["corpus_source"], "live")
        live_root = hub.current.root
        self.logout(c)
        self.login(c, NAGARAJ_NO)
        meta = self.ok(self.get(c, "/api/meta"))
        self.assertEqual(meta["corpus_source"], "recorded")                   # never FETCHED LIVE for this number
        self.assertTrue(meta["corpus_label"].startswith("RECORDED"))
        self.assertNotEqual(hub.current.root, live_root)
        self.assertFalse((live_root / self.KUMAR).exists())
        self.logout(c)                                                         # SELA again: the live household, no new consent
        consents = len(self.kit.consents)
        self.assertEqual(self.login(c, SELA_NO), {"route": "app", "label": "SELA household"})
        self.assertEqual(self.ok(self.get(c, "/api/meta"))["corpus_source"], "live")
        self.assertEqual(hub.current.root, live_root)
        self.assertEqual(len(self.kit.consents), consents)

    # ---- 6. isolation of answers and 'Stop and forget' across sign-ins ----
    def test_answers_and_forgetting_stay_in_their_household(self):
        hub, c = self.make()
        self.login(c, NAGARAJ_NO)
        self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        q = self.card(self.payload(c), "AGE_BAND_QUESTION")
        self.ok(self.post(c, "/api/answers", {"answers": [{"card_id": q["id"], "option": "18_40"}]}))
        self.logout(c)

        self.login(c, SELA_NO)
        self.assertEqual(self.payload(c)["what_we_know"]["household_facts"], [])
        self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        q = self.card(self.payload(c), "AGE_BAND_QUESTION", "9741")
        self.ok(self.post(c, "/api/answers", {"answers": [{"card_id": q["id"], "option": "41_50"}]}))
        self.logout(c)

        self.login(c, NAGARAJ_NO)
        facts = self.payload(c)["what_we_know"]["household_facts"]
        self.assertEqual([(f["member"], f["value"]) for f in facts], [("Kumar", "18_40")])
        self.assertEqual(self.ok(self.post(c, "/api/erase", {})), {"state": "forgotten"})
        self.logout(c)

        self.login(c, SELA_NO)
        facts = self.payload(c)["what_we_know"]["household_facts"]
        self.assertEqual([(f["member"], f["value"]) for f in facts], [("John", "41_50")])
        self.logout(c)
        self.login(c, NAVEEN_NO)
        self.assertEqual(self.payload(c)["generated"]["household_id"], self.NAVEEN_A)
        self.logout(c)
        self.login(c, NAGARAJ_NO)
        self.assertEqual(self.payload(c), {"state": "forgotten"})               # still forgotten, only here
        root = self.tmp / "store"
        self.assertTrue((root / f".forgotten-{self.KUMAR}").exists())
        self.assertFalse((root / f".forgotten-{self.SELA}").exists())

        hub2, c2 = self.make()                                                   # a restart on the same --store
        self.login(c2, SELA_NO)
        facts = self.payload(c2)["what_we_know"]["household_facts"]
        self.assertEqual([(f["member"], f["value"]) for f in facts], [("John", "41_50")])

    def test_every_word_served_passes_the_language_gate_and_carries_no_identifiers(self):
        hub, c = self.make()
        texts = [json.dumps(self.no_fingerprint(self.ok(self.get(c, "/api/meta"))))]
        for n in (SELA_NO, NAGARAJ_NO, NAVEEN_NO):
            texts.append(json.dumps(self.login(c, n)))
            meta = self.ok(self.get(c, "/api/meta"))
            texts.append(json.dumps(self.no_fingerprint(meta)))
            for s in strings(meta.get("demo_login", {})):
                gate(s)
            self.logout(c)
        texts.append(self.post(c, "/api/login", {"mobile": "9876543210"}).get_data(as_text=True))
        for t in texts:
            self.assertIsNone(re.search(r"\d{9,}", t))
            self.assertNotIn("HH-", t)


if __name__ == "__main__":
    unittest.main()
