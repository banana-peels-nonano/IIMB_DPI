"""
Gate 6 acceptance tests (G6-1 ... G6-8). G6-9 = the existing suites still pass (run separately).

    set MIRROR_DATA=<path to the sealed decrypted.json>
    python -m unittest mirror.test_gate6 -v

No test makes a network call (G6-2 and G6-6 block sockets to prove it). Every store lives in a
temporary folder outside any git repository.
"""
import hashlib, json, os, re, shutil, socket, tempfile, unittest, urllib.request
from datetime import date
from pathlib import Path
from unittest import mock

from . import serve
from .rules import PURPOSE_GOV_PROTECT as GOV, PURPOSE_DPI_LPG as DPI

DATA = os.environ.get("MIRROR_DATA")
PORT = 8787
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = "test-launch-token"
SESSION1_DIGEST = "1a7295f67390cd5ae25442d5e36645b32eda9e04804d6329d2f66bd7ae992c0a"
SESSION3_DIGEST = "f525cb58854f94316f59f8779868697c2ed53ed73efa099b33ea193f8d7aff96"


def digest(p) -> str:
    return hashlib.sha256(json.dumps(p, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@unittest.skipUnless(DATA, "set MIRROR_DATA to the sealed corpus")
class Gate6(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mirror-g6-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("MIRROR_HUB_LIVE", None)

    def make(self, start=serve.DEFAULT_START, store=None, started=True):
        m = serve.Mirror(DATA, str(store or self.tmp / "store"), start)
        if started:
            m.start_if_needed()                  # what `python -m mirror.serve` does at start-up
        return m, serve.create_app(m, PORT, TOKEN).test_client()

    def get(self, c, path, **kw):
        return c.get(path, base_url=BASE, **kw)

    def post(self, c, path, body, token=TOKEN, **kw):
        headers = {"X-Mirror-Token": token} if token else {}
        return c.post(path, base_url=BASE, json=body, headers=headers, **kw)

    def ok(self, resp):
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True)[:300])
        return resp.get_json()

    @staticmethod
    def card(p, code, account_tail=None):
        return next(c for c in p["now"]["cards"] if c["code"] == code
                    and (account_tail is None or c["account"].endswith(account_tail)))

    # ---- G6-1: a thin wrapper - the API reproduces the verified sessions byte for byte ----
    def test_g6_1_api_reproduces_the_batch1c_contract_digests(self):
        m, c = self.make(start=date(2026, 9, 8), started=False)
        self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True, "as_of": "2026-09-08"}))
        p = self.ok(self.get(c, "/api/payload"))
        self.ok(self.post(c, "/api/answers", {"as_of": "2026-09-09", "answers": [
            {"card_id": self.card(p, "AGE_BAND_QUESTION", "9741")["id"], "option": "41_50"},
            {"card_id": self.card(p, "AGE_BAND_QUESTION", "9648")["id"], "option": "18_40"}]}))
        p = self.ok(self.get(c, "/api/payload"))
        self.ok(self.post(c, "/api/answers", {"as_of": "2026-09-10", "answers": [
            {"card_id": self.card(p, "TAXPAYER_QUESTION", "9648")["id"], "option": "no"}]}))
        self.ok(self.post(c, "/api/lpg-check", {"mode": "simulated", "scenario": "rerouted",
                                                "consent_to_purpose": True, "as_of": "2026-09-11"}))
        p = self.ok(self.get(c, "/api/payload"))
        self.ok(self.post(c, "/api/answers", {"as_of": "2026-09-12", "answers": [
            {"card_id": self.card(p, "LPG_SUBSIDY_ROUTING")["id"], "option": "old_not_in_use"}]}))
        john = self.card(p, "LIC_GRACE_CLOCK")["account"]
        self.ok(self.post(c, "/api/facts", {"account": john, "code": "AGE_BAND", "scheme": None,
                                            "value": "51_70", "as_of": "2026-09-13"}))
        self.assertEqual(digest(self.ok(self.get(c, "/api/payload"))), SESSION1_DIGEST)
        # a new process on the same store sees the same contract (session 2's reload)
        _, c2 = self.make(start=date(2026, 9, 8), store=self.tmp / "store")
        self.assertEqual(digest(self.ok(self.get(c2, "/api/payload"))), SESSION1_DIGEST)   # start-up added nothing
        self.ok(self.post(c2, "/api/clock", {"as_of": "2026-09-14"}))
        self.ok(self.post(c2, "/api/purposes", {"purpose": GOV, "on": False, "as_of": "2026-09-15"}))
        self.assertEqual(digest(self.ok(self.get(c2, "/api/payload"))), SESSION3_DIGEST)

    # ---- G6-2: works with the network unplugged; the page loads nothing from outside ----
    def test_g6_2_offline_page_and_views(self):
        def no_network(*a, **k):
            raise AssertionError("network access attempted")
        with mock.patch.object(socket.socket, "connect", no_network), \
                mock.patch.object(socket, "create_connection", no_network), \
                mock.patch.object(socket, "getaddrinfo", no_network):
            _, c = self.make()
            page = self.get(c, "/")
            self.assertEqual(page.status_code, 200)
            html = page.get_data(as_text=True)
            assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
            self.assertTrue(assets)
            for a in assets:
                self.assertEqual(self.get(c, a).status_code, 200, a)
            p = self.ok(self.get(c, "/api/payload"))
            for view in ("now", "ahead", "our_household", "what_we_know"):
                self.assertIn(view, p)
            self.ok(self.get(c, "/api/meta"))
            self.ok(self.get(c, "/api/vocab"))
        for f in serve.WEB.rglob("*"):
            if f.suffix in (".html", ".css", ".js"):
                # the SVG namespace name is an identifier the browser never fetches
                text = f.read_text(encoding="utf-8").replace("http://www.w3.org/2000/svg", "")
                self.assertNotRegex(text, r"https?://|(?:src|href)=\"//|@import\s+url\(\s*['\"]?//",
                                    f"{f.name} references something outside this laptop")

    # ---- G6-3: fail closed ----
    def test_g6_3_a_payload_that_fails_validation_is_never_sent(self):
        real = serve.build_payload

        def tampered(state, events, consent=None):
            p = real(state, events, consent)
            p["our_household"]["balance"] = 12345
            return p
        _, c = self.make()
        with mock.patch.object(serve, "build_payload", tampered):
            r = self.get(c, "/api/payload")
            self.assertEqual(r.status_code, 500)
            text = r.get_data(as_text=True)
            self.assertNotIn('"now"', text)
            self.assertNotIn("12345", text)

    # ---- G6-4: answers stay U; re-sending changes nothing ----
    def test_g6_4_answers_stay_u_and_resending_adds_no_correction(self):
        _, c = self.make(start=date(2026, 9, 8))
        p = self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        q = self.card(p, "AGE_BAND_QUESTION", "9741")
        p = self.ok(self.post(c, "/api/answers", {"card_id": q["id"], "option": "41_50", "as_of": "2026-09-09"}))
        fact = next(f for f in p["what_we_know"]["household_facts"] if f["account"] == q["account"])
        self.assertEqual((fact["evidence_class"], fact["badge"]), ("U", "You told us"))
        answered = [w for card in p["now"]["cards"] for w in card["why"] if w.get("answered")]
        self.assertTrue(answered)
        self.assertTrue(all(w["class"] == "U" and w["badge"] == "You told us" and w["fact_id"] == fact["id"]
                            for w in answered if w.get("fact_id") == fact["id"]))
        n = len(p["what_we_know"]["corrections"])
        p = self.ok(self.post(c, "/api/facts", {"account": q["account"], "code": "AGE_BAND", "scheme": None,
                                                "value": "41_50"}))
        self.assertEqual(len(p["what_we_know"]["corrections"]), n)
        # the answered question is closed: answering it again is refused, not re-applied
        r = self.post(c, "/api/answers", {"card_id": q["id"], "option": "41_50"})
        self.assertEqual(r.status_code, 400)
        # only closed values are accepted
        self.assertEqual(self.post(c, "/api/facts", {"account": q["account"], "code": "AGE_BAND", "scheme": None,
                                                     "value": "1984-02-03"}).status_code, 400)

    # ---- G6-5: switching a purpose off is durable, and leaves the disk ----
    def test_g6_5_purpose_off_is_durable_across_a_restart(self):
        store = self.tmp / "store"
        _, c = self.make(start=date(2026, 9, 8), store=store)
        p = self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        q = self.card(p, "AGE_BAND_QUESTION", "9741")
        self.ok(self.post(c, "/api/answers", {"card_id": q["id"], "option": "41_50", "as_of": "2026-09-09"}))
        self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": False, "as_of": "2026-09-10"}))
        _, c2 = self.make(start=date(2026, 9, 8), store=store)          # "restart the server"
        p = self.ok(self.get(c2, "/api/payload"))
        self.assertEqual(p["what_we_know"]["household_facts"], [])
        self.assertFalse(p["our_household"]["protections"]["switched_on"])
        on_disk = "".join(f.read_text(encoding="utf-8") for f in store.rglob("state.json"))
        self.assertNotIn('"41_50"', on_disk)
        hist = self.ok(self.get(c2, "/api/history"))
        self.assertEqual([h["on"] for h in hist["purpose_history"]], [True, False])

    # ---- G6-6: live LPG is closed by default; simulated always says so ----
    def test_g6_6_live_lpg_is_closed_and_simulated_is_labelled(self):
        def no_network(*a, **k):
            raise AssertionError("network access attempted")
        _, c = self.make(start=date(2026, 9, 8))
        self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        with mock.patch.object(socket, "getaddrinfo", no_network), \
                mock.patch.object(socket.socket, "connect", no_network):
            r = self.post(c, "/api/lpg-check", {"mode": "live", "lpg_id": "1" * 17, "holder_confirmed": True,
                                                "spend_credit": True})
            self.assertEqual(r.status_code, 403)
            self.assertIn("off", r.get_json()["error"])
            os.environ["MIRROR_HUB_LIVE"] = "1"
            r = self.post(c, "/api/lpg-check", {"mode": "live", "lpg_id": "1" * 17})    # no confirmation
            self.assertEqual(r.status_code, 403)
            self.assertIn("before any call", r.get_json()["error"])
            os.environ.pop("MIRROR_HUB_LIVE")
            # the separate OK is required before a simulated check too
            self.assertEqual(self.post(c, "/api/lpg-check", {"mode": "simulated"}).status_code, 409)
            p = self.ok(self.post(c, "/api/lpg-check", {"mode": "simulated", "scenario": "rerouted",
                                                        "consent_to_purpose": True}))
        self.assertIn(DPI, p["generated"]["purposes_on"])
        dpi = p["what_we_know"]["dpi_integrations"][0]
        self.assertEqual(dpi["disclosure"], serve.lpg.DISCLOSURE)
        self.assertEqual(dpi["live_lookup_for_this_household"]["status"], "not performed")
        routing = self.card(p, "LPG_SUBSIDY_ROUTING")
        self.assertTrue(routing["simulated"] and "SIMULATED" in routing["title"])
        self.assertTrue(all(e["mode"] == "simulated" for e in p["what_we_know"]["access_log"]
                            if e.get("what") == "lookup"))

    # ---- G6-7: no secrets, raw data or identifiers in any response or static file ----
    def test_g6_7_no_secrets_or_raw_data_leave_the_server(self):
        secret_values = {"PERFIOS_SECURE_ID": "sid-TESTVALUE-1", "PERFIOS_SECURE_CRED": "cred-TESTVALUE-2",
                         "PERFIOS_ORG_ID": "org-TESTVALUE-3", "MIRROR_STORE_KEY": "store-key-TESTVALUE-4"}
        os.environ.update(secret_values)
        _, c = self.make(start=date(2026, 9, 8))
        texts = []
        p = self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        texts.append(json.dumps(p, ensure_ascii=False))
        p = self.ok(self.post(c, "/api/lpg-check", {"mode": "simulated", "scenario": "rerouted",
                                                    "consent_to_purpose": True, "as_of": "2026-09-11"}))
        texts.append(json.dumps(p, ensure_ascii=False))
        for path in ("/api/meta", "/api/vocab", "/api/history", "/", "/api/payload"):
            texts.append(self.get(c, path).get_data(as_text=True))
        texts += [f.read_text(encoding="utf-8") for f in serve.WEB.rglob("*") if f.suffix in (".html", ".css", ".js")]
        blob = "\n".join(texts)
        for name, value in secret_values.items():
            self.assertNotIn(value, blob)
            self.assertNotIn(name, blob)
        for key in ("CLIENT_SECRET", "NGROK_AUTHTOKEN", ".env"):
            self.assertNotIn(key, blob)
        corpus = serve.load(DATA)
        narrations = {t.narration for a in corpus.accounts for t in a.txns if len(t.narration) >= 16}
        self.assertTrue(narrations)
        self.assertEqual([n for n in narrations if n in blob], [])
        self.assertNotRegex(blob, r'"balance"|(?<!\d)[12]\d{16}(?!\d)')
        self.assertNotIn(str(self.tmp), blob)                       # no file-system paths either

    # ---- G6-8: local guards ----
    def test_g6_8_foreign_host_and_missing_token_are_refused(self):
        _, c = self.make()
        self.assertEqual(c.get("/api/payload", base_url="http://evil.example:8787").status_code, 403)
        self.assertEqual(c.get("/", base_url="http://192.168.1.5:8787").status_code, 403)
        self.assertEqual(self.post(c, "/api/erase", {}, token=None).status_code, 403)
        self.assertEqual(self.post(c, "/api/erase", {}, token="wrong").status_code, 403)
        r = c.post("/api/purposes", base_url=BASE, data="purpose=GOV_PROTECT&on=true",
                   headers={"X-Mirror-Token": TOKEN, "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 415)
        page = self.get(c, "/")
        self.assertIn(TOKEN, page.get_data(as_text=True))
        self.assertNotIn("Access-Control-Allow-Origin", page.headers)
        self.assertIn("default-src 'self'", page.headers["Content-Security-Policy"])

    # ---- replay honesty and control ----
    def test_replay_only_moves_forward_and_the_aa_watch_is_not_an_app_switch(self):
        _, c = self.make()
        self.ok(self.get(c, "/api/payload"))
        self.assertEqual(self.post(c, "/api/clock", {"as_of": "2026-08-01"}).status_code, 409)
        self.assertEqual(self.post(c, "/api/clock", {"as_of": "2026-12-01"}).status_code, 400)
        p = self.ok(self.post(c, "/api/clock", {"as_of": "2026-09-07"}))
        self.assertEqual(p["generated"]["as_of"], "2026-09-07")
        self.assertEqual(self.post(c, "/api/purposes", {"purpose": "AA_PROTECT", "on": False}).status_code, 400)
        self.assertEqual(self.post(c, "/api/purposes", {"purpose": DPI, "on": True}).status_code, 409)

    def test_stop_and_forget_erases_and_needs_no_extra_step(self):
        store = self.tmp / "store"
        _, c = self.make(store=store)
        self.ok(self.get(c, "/api/payload"))
        self.assertTrue(any(store.rglob("state.json")))
        self.assertEqual(self.ok(self.post(c, "/api/erase", {})), {"state": "forgotten"})
        self.assertFalse(any(store.rglob("state.json")))
        self.assertEqual(self.ok(self.get(c, "/api/payload")), {"state": "forgotten"})
        p = self.ok(self.post(c, "/api/replay/restart", {"as_of": "2026-08-28"}))
        self.assertEqual(p["generated"]["as_of"], "2026-08-28")

    def test_vocab_and_notification_preview_are_safe(self):
        v = serve._vocab()
        preview = v["notification_preview"]["text"]
        self.assertNotRegex(preview, r"\d|₹|https?:|www\.")
        corpus = serve.load(DATA)
        for a in corpus.accounts:
            for part in (a.member or "").replace(".", " ").split():
                if len(part) > 3:
                    self.assertNotIn(part.title(), preview)
        self.assertEqual([q["id"] for q in v["ask_mirror"]][:5], ["why", "know", "who", "wrong", "stop"])
        codes = {"RETURN_CHARGE_POSTED", "LINKED_TO_PAYMENT", "GRACE_RULE", "DUE_DATE", "AGE_BAND", "LPG_RECORD"}
        self.assertTrue(codes <= set(v["evidence_labels"]))

    def test_store_inside_git_and_live_mode_are_refused(self):
        repo = self.tmp / "repo"
        (repo / ".git").mkdir(parents=True)
        with self.assertRaises(SystemExit):
            serve.Mirror(DATA, str(repo / "state"))
        with self.assertRaises(SystemExit):
            serve.Mirror(DATA, str(self.tmp / "s"), mode="live")

    # ---- review follow-ups ----
    def test_get_is_read_only_and_stop_and_forget_survives_a_restart(self):
        store = self.tmp / "store"
        _, c = self.make(store=store, started=False)
        self.assertEqual(self.ok(self.get(c, "/api/payload")), {"state": "not_started"})
        self.assertFalse(any(store.rglob("state.json")), "a GET must never create state")
        m, c = self.make(store=store)
        self.ok(self.get(c, "/api/payload"))
        self.ok(self.post(c, "/api/erase", {}))
        m2, c2 = self.make(store=store)                                   # server restarted after forgetting
        self.assertTrue(m2.stopped)
        self.assertEqual(self.ok(self.get(c2, "/api/payload")), {"state": "forgotten"})
        self.assertEqual(self.ok(self.post(c2, "/api/clock", {"as_of": "2026-09-01"})), {"state": "forgotten"})
        self.assertFalse(any(store.rglob("state.json")), "nothing may recreate a forgotten household")
        self.assertTrue(self.ok(self.get(c2, "/api/meta"))["stopped"])
        p = self.ok(self.post(c2, "/api/replay/restart", {"as_of": "2026-08-28"}))
        self.assertEqual(p["generated"]["as_of"], "2026-08-28")

    def test_the_lpg_purpose_needs_its_own_ok_everywhere(self):
        _, c = self.make(start=date(2026, 9, 8))
        self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        self.assertEqual(self.post(c, "/api/purposes", {"purpose": DPI, "on": True}).status_code, 409)
        p = self.ok(self.post(c, "/api/purposes", {"purpose": DPI, "on": True, "consent_to_purpose": True}))
        self.assertIn(DPI, p["generated"]["purposes_on"])

    def test_malformed_and_duplicate_answers_are_refused_as_json(self):
        _, c = self.make(start=date(2026, 9, 8))
        p = self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        q = self.card(p, "AGE_BAND_QUESTION", "9648")
        for bad in ({"card_id": ["x"], "option": "18_40"}, {"card_id": q["id"], "option": {"a": 1}},
                    {"answers": [{"card_id": q["id"], "option": "18_40"}, {"card_id": q["id"], "option": "41_50"}]}):
            r = self.post(c, "/api/answers", bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn("error", r.get_json())
        self.assertEqual(self.post(c, "/api/lpg-check", {"mode": "simulated", "scenario": ["x"]}).status_code, 400)
        self.assertEqual(self.post(c, "/api/facts", {"account": 1, "code": "AGE_BAND", "value": "18_40"}).status_code, 400)
        self.assertEqual(self.ok(self.get(c, "/api/payload"))["what_we_know"]["corrections"], [])

    def test_fail_closed_on_a_post_and_on_unsafe_language(self):
        from .language import UnsafeLanguage
        _, c = self.make(start=date(2026, 9, 8))

        def unsafe(state, events, consent=None):
            raise UnsafeLanguage("test: a banned claim")
        with mock.patch.object(serve, "build_payload", unsafe):
            r = self.post(c, "/api/purposes", {"purpose": GOV, "on": True})
            self.assertEqual(r.status_code, 500)
            self.assertNotIn('"now"', r.get_data(as_text=True))

    def test_every_live_call_is_logged_without_the_id_and_never_joined(self):
        import urllib.error
        m, c = self.make(start=date(2026, 9, 8))
        self.ok(self.post(c, "/api/purposes", {"purpose": GOV, "on": True}))
        self.ok(self.post(c, "/api/purposes", {"purpose": DPI, "on": True, "consent_to_purpose": True}))
        os.environ.update({"MIRROR_HUB_LIVE": "1", "PERFIOS_SECURE_ID": "sid-TEST", "PERFIOS_SECURE_CRED": "cred-TEST",
                           "PERFIOS_ORG_ID": "org-TEST"})

        def down(*a, **k):
            raise urllib.error.URLError("no network in tests")
        m.opener = down
        lpg_id = "1" + "2345678901234567"
        r = self.post(c, "/api/lpg-check", {"mode": "live", "lpg_id": lpg_id, "holder_confirmed": True,
                                            "spend_credit": True})
        res = self.ok(r)
        self.assertFalse(res["joined_to_household"])
        self.assertEqual(res["standalone_live_record"]["status"], "failed")
        hist = self.ok(self.get(c, "/api/history"))
        self.assertEqual(len(hist["standalone_live_lookups"]), 1)
        e = hist["standalone_live_lookups"][0]
        self.assertEqual((e["mode"], e["outcome"], e["lpg_id_last4"], e["joined_to_household"]), ("live", "failed", "4567", False))
        p = self.ok(self.get(c, "/api/payload"))
        self.assertEqual([x for x in p["what_we_know"]["access_log"] if x.get("mode") == "live"], [])
        self.assertEqual(p["what_we_know"]["dpi_integrations"][0]["live_lookup_for_this_household"]["status"], "not performed")
        on_disk = "".join(f.read_text(encoding="utf-8") for f in self.tmp.rglob("*") if f.is_file())
        self.assertNotIn(lpg_id, on_disk + json.dumps(res) + json.dumps(hist))

    def test_the_pages_fixed_words_pass_the_language_gate(self):
        from .language import gate
        js = (serve.WEB / "app.js").read_text(encoding="utf-8")
        js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        js = "\n".join(l.split("//")[0] if "'//" not in l and '"//' not in l else l for l in js.splitlines())
        lits = re.findall(r"'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`", js)
        texts = [a or re.sub(r"\$\{[^}]*\}", " ", b) for a, b in lits]
        self.assertGreater(len(texts), 100)
        for t in texts:
            gate(t)

    def test_design_system_type_floor_and_hindi_accent(self):
        """Type comes from the scale (rem, never under 12 px); Hindi is a tagged accent, never the interface."""
        css = (serve.WEB / "styles.css").read_text(encoding="utf-8") if hasattr(serve, "WEB") else \
            (Path(serve.__file__).parent / "web" / "styles.css").read_text(encoding="utf-8")
        sizes = re.findall(r"font-size:\s*([^;}]+)", css)
        self.assertTrue(sizes)
        for v in sizes:
            v = v.strip()
            if v.startswith("var(--fs-"):
                continue
            m = re.fullmatch(r"([\d.]+)(px|rem)", v)
            self.assertIsNotNone(m, f"font-size must use the scale: {v}")
            px = float(m.group(1)) * (16 if m.group(2) == "rem" else 1)
            self.assertGreaterEqual(px, 12, f"text under the 12 px floor: {v}")
        for tok in re.findall(r"--fs-(\d+):\s*([\d.]+)rem", css):
            self.assertEqual(float(tok[1]) * 16, float(tok[0]), f"--fs-{tok[0]} does not match its name")
        js = (Path(serve.__file__).parent / "web" / "app.js").read_text(encoding="utf-8")
        deva = re.findall(r"'([^']*[\u0900-\u097F][^']*)'", js)
        self.assertTrue(1 <= len(deva) <= 8, f"Hindi is an accent, not a translation layer ({len(deva)} phrases)")
        self.assertIn("lang: 'hi'", js)

    def test_browser_smoke_every_view_and_lpg_scenario(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed on this machine (optional check)")
        from werkzeug.serving import make_server
        import logging, threading
        logging.getLogger("werkzeug").setLevel(logging.WARNING)       # no request lines in the test output
        m = serve.Mirror(DATA, str(self.tmp / "store"), date(2026, 8, 28))
        m.start_if_needed()
        srv = make_server("127.0.0.1", 0, None)
        port = srv.server_port
        srv.server_close()
        app = serve.create_app(m, port, TOKEN)
        srv = make_server("127.0.0.1", port, app)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{port}"
        c = app.test_client()
        post = lambda path, body: c.post(path, base_url=base, json=body, headers={"X-Mirror-Token": TOKEN})
        errors = []
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

            def sweep(label):
                pg.goto(base + "/")
                pg.wait_for_timeout(600)
                for i in range(4):
                    pg.click(f".tab >> nth={i}")
                    pg.wait_for_timeout(350)
                    body = pg.inner_text("body")
                    for bad in ("[object", "undefined", "NaN"):
                        self.assertNotIn(bad, body, f"{label}, view {i}")
                    self.assertEqual(pg.locator("#view h1").count(), 1, f"{label}, view {i}: one h1")
                    self.assertEqual(pg.locator("#view [lang=hi]").count(),
                                     pg.locator("#view .hi").count(), f"{label}, view {i}: Hindi is tagged")
                    self.assertLessEqual(pg.locator("#view .hi").count(), 2, f"{label}, view {i}: Hindi stays an accent")
                pg.click("#fab")
                for i in range(6):
                    pg.click(f".ask-chips button >> nth={i}")
                    pg.wait_for_timeout(120)
                    self.assertNotIn("[object", pg.inner_text(".sheet"), f"{label}, ask {i}")
            sweep("start")
            self.assertEqual(post("/api/purposes", {"purpose": GOV, "on": True}).status_code, 200)
            for day, scenario in zip(range(1, 8), sorted(serve.lpg.SCENARIOS)):
                r = post("/api/lpg-check", {"mode": "simulated", "scenario": scenario, "consent_to_purpose": True,
                                            "as_of": f"2026-09-0{day}"})
                self.assertEqual(r.status_code, 200, scenario)
                sweep(scenario)
            post("/api/purposes", {"purpose": GOV, "on": False, "as_of": "2026-09-09"})
            sweep("forgotten purpose")
            pg.goto(base + "/")
            pg.wait_for_timeout(600)
            pg.click(".tab >> nth=3")
            pg.wait_for_timeout(300)
            know = pg.inner_text("body")
            self.assertIn("Removed:", know)                 # a forgetting row reads as words, not keys
            self.assertNotIn("PURPOSE_SWITCHED_OFF", know)
            # a logged live call (fixture line, as the server writes it) shows apart from the household
            m.root.mkdir(parents=True, exist_ok=True)
            m.live_log.write_text(json.dumps({"on": "2026-09-09", "what": "live lookup", "source": serve.lpg.SOURCE,
                                              "source_label": serve.lpg.SOURCE_LABEL, "mode": "live",
                                              "outcome": "failed", "reason": "INVALID_ID", "lpg_id_last4": "4567",
                                              "joined_to_household": False}) + "\n", encoding="utf-8")
            pg.goto(base + "/")
            pg.wait_for_timeout(600)
            pg.click(".tab >> nth=3")
            pg.wait_for_timeout(300)
            know = pg.inner_text("body")
            self.assertIn("never part of this household", know)
            self.assertIn("we couldn't check", know)
            post("/api/erase", {})
            pg.goto(base + "/")
            pg.wait_for_timeout(500)
            self.assertIn("Forgotten", pg.inner_text("body"))
            # no saved state and no tombstone: a start screen, never a blank or a guess
            m.tombstone.unlink()
            pg.goto(base + "/")
            pg.wait_for_timeout(500)
            self.assertIn("Not started", pg.inner_text("body"))
            pg.click("text=Start the replay")
            pg.wait_for_timeout(1500)
            self.assertIn("Now", pg.inner_text(".tabbar"))
            self.assertNotIn("Not started", pg.inner_text("#view"))
            b.close()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
