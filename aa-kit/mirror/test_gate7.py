"""
Gate 7 acceptance tests: the in-app Anumati journey, run against stand-ins (no network, no secrets).

  MIRROR_DATA=<sealed decrypted.json> python -m unittest mirror.test_gate7 -v

The stand-in client has the verified anumati_client's call shapes (start_consent, fetch_data); the
stand-in webhook writes files exactly as webhook_server.py names them. What is proven here: the app
reacts only to real events for THIS consent, fetches at most once, never retries, keeps the retrieval
credential and the secret out of every response, labels the new corpus honestly, and never changes
what the recorded replay does.
"""
from __future__ import annotations
import hashlib, json, os, shutil, sys, tempfile, threading, time, unittest
from datetime import date
from pathlib import Path
from unittest import mock

from . import serve, aa_link

DATA = os.environ.get("MIRROR_DATA")
TOKEN = "test-token-7"
SECRET = "RETRIEVAL-SECRET-DO-NOT-LEAK"
RID = "retrieval-id-DO-NOT-LEAK"
MOBILE = "9999999999"


class Refusal(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.response = type("R", (), {"status_code": code})()


class FakeKit:
    """anumati_client + decrypt stand-ins with the verified call shapes."""

    def __init__(self, captures: Path, fetch_error: int | None = None):
        self.captures, self.fetch_error = captures, fetch_error
        self.consents, self.fetches = [], []

    def start_consent(self, mobile, purpose_code="102", fetch_type="PERIODIC", fi_types=None):
        self.consents.append((mobile, purpose_code, fetch_type, fi_types))
        return {"moduleReference": "MODREF-000777", "consentHandle": "CH-1", "status": "CONSENT_REQUESTED",
                "redirectUrl": "https://aa.example/consent?handle=CH-1"}

    def fetch_data(self, retrieval_id, secret):
        self.fetches.append((retrieval_id, secret))
        p = self.captures / f"{aa_link.utc_stamp()}_getdata_RAW.json"
        p.write_bytes(b'{"encrypted": "..."}' * 100)            # the real client saves raw BEFORE raising
        if self.fetch_error:
            raise Refusal(self.fetch_error)
        return {}, p

    def decrypt(self, raw_path):
        return json.loads(Path(DATA).read_text(encoding="utf-8"))


def webhook(captures: Path, kind: str, body: dict):
    """What webhook_server.persist writes (the bare payload file the pipeline reads)."""
    time.sleep(0.002)
    (captures / f"{aa_link.utc_stamp()}_{kind}_payload.json").write_bytes(json.dumps(body).encode())


@unittest.skipUnless(DATA, "set MIRROR_DATA to the sealed corpus")
class Gate7(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mirror-g7-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.captures = self.tmp / "captures"
        self.captures.mkdir()
        self.kit = FakeKit(self.captures)

    def make(self, *, poll=None, e8=None, fetch_error=None, link=True):
        self.kit.fetch_error = fetch_error
        m = serve.Mirror(DATA, str(self.tmp / "store"), date(2026, 8, 28))
        m.start_if_needed()
        hub = serve.Hub(m)
        if link:
            kw = {"e8_sha256": e8} if e8 else {}
            hub.link = aa_link.AALink(self.kit, self.kit.decrypt, self.captures, hub.attach_live, poll=poll, **kw)
            hub.entry = "connect"
        app = serve.create_app(hub, 8787, TOKEN)
        self.c = app.test_client()
        return hub

    def get(self, path):
        return self.c.get(path, base_url="http://127.0.0.1:8787")

    def post(self, path, body, token=TOKEN):
        return self.c.post(path, base_url="http://127.0.0.1:8787", json=body, headers={"X-Mirror-Token": token})

    def linux_e8(self):
        """The sha the app computes for the E8 sessions written by run_journey's own write_text on THIS
        platform (on the Windows laptop that is the sealed 4924… value itself)."""
        p = self.tmp / "probe.json"
        p.write_text(json.dumps(json.loads(Path(DATA).read_text(encoding="utf-8")), indent=2))
        return hashlib.sha256(p.read_bytes()).hexdigest().upper()

    def run_journey(self, hub):
        r = self.post("/api/connect/start", {"mobile": MOBILE})
        self.assertEqual(r.status_code, 200, r.get_json())
        webhook(self.captures, "consent-lifecycle", {"moduleReference": "MODREF-000777", "consentHandle": "CH-1",
                                                     "status": "ACTIVE", "timestamp": "t"})
        hub.link.scan()
        webhook(self.captures, "data-ready", {"moduleReference": "MODREF-000777", "consentHandle": "CH-1",
                                              "id": RID, "secret": SECRET, "sessionCount": 7, "expiresAt": "t"})
        hub.link.scan()

    # ---- G7-1 the whole journey, one real event at a time ----
    def test_journey_steps_follow_real_events_and_end_in_a_live_household(self):
        hub = self.make(e8=self.linux_e8())
        self.assertEqual(self.get("/api/payload").get_json(), {"state": "connect"})   # welcome first
        r = self.post("/api/connect/start", {"mobile": MOBILE}).get_json()
        self.assertEqual(r["state"], "requested")
        self.assertEqual(self.kit.consents, [(MOBILE, "102", "PERIODIC", ["DEPOSIT"])])   # the verified config
        self.assertTrue(r["redirect_url"].startswith("https://aa.example/"))
        self.assertEqual([s["done"] for s in r["steps"]], [True] + [False] * 6)
        hub.link.scan()                                          # nothing has arrived: nothing moves
        self.assertEqual(self.get("/api/connect").get_json()["state"], "requested")
        webhook(self.captures, "consent-lifecycle", {"moduleReference": "MODREF-000777", "status": "ACTIVE"})
        hub.link.scan()
        st = self.get("/api/connect").get_json()
        self.assertEqual(st["state"], "approved")
        self.assertIsNone(st["redirect_url"])                    # the single-use link is not offered again
        self.assertEqual(self.kit.fetches, [])
        webhook(self.captures, "data-ready", {"moduleReference": "MODREF-000777", "id": RID, "secret": SECRET,
                                              "sessionCount": 7})
        hub.link.scan()
        st = self.get("/api/connect").get_json()
        self.assertEqual(st["state"], "ready", st)
        self.assertEqual(self.kit.fetches, [(RID, SECRET)])
        self.assertTrue(all(s["done"] and s["at"] for s in st["steps"]))
        self.assertTrue(st["result"]["matches_e8"])
        self.assertIn("same bytes", next(s for s in st["steps"] if s["id"] == "verified")["detail"])
        # the page now shows the household built from the fetched data, in its own store folder
        meta = self.get("/api/meta").get_json()
        self.assertEqual(meta["corpus_source"], "live")
        self.assertTrue(meta["corpus_label"].startswith("FETCHED LIVE · "))
        self.assertEqual(meta["connect"]["entry"], "app")
        live = self.get("/api/payload").get_json()
        rec = hub.recorded.payload()
        self.assertEqual([c["id"] for c in live["now"]["cards"]], [c["id"] for c in rec["now"]["cards"]])
        self.assertEqual(live["generated"]["data_mode"], "replay")   # time is still replayed: the label stays true
        self.assertNotEqual(hub.current.root, hub.recorded.root)
        self.assertTrue(str(hub.current.root).startswith(str(hub.recorded.root / "live")))
        written = sorted(self.captures.glob("LIVE_*/decrypted.json"))
        self.assertEqual(len(written), 1)

    def test_different_bytes_are_called_new_data(self):
        # Genuinely different decrypted content on EVERY platform. (Re-serialising E8 itself is not enough:
        # on Windows write_text emits CRLF and reproduces the sealed file byte for byte.) linkRefNumber is
        # never read by the engine, so the household stays the same while the bytes differ.
        def altered(raw_path):
            sessions = json.loads(Path(DATA).read_text(encoding="utf-8"))
            sessions[0]["linkRefNumber"] = "00000000-0000-0000-0000-000000000000"
            return sessions
        self.kit.decrypt = altered
        hub = self.make()                                      # compared against the real sealed E8 sha
        self.run_journey(hub)
        st = self.get("/api/connect").get_json()
        self.assertEqual(st["state"], "ready")
        written = sorted(self.captures.glob("LIVE_*/decrypted.json"))
        self.assertEqual(len(written), 1)
        sha = hashlib.sha256(written[0].read_bytes()).hexdigest().upper()
        self.assertNotEqual(sha, aa_link.E8_SHA256)           # the fixture really is different data
        self.assertEqual(st["result"]["fingerprint"], f"{sha[:4]}…{sha[-3:]}")   # the app hashed THAT file
        self.assertFalse(st["result"]["matches_e8"])
        self.assertIn("new data", next(s for s in st["steps"] if s["id"] == "verified")["detail"])

    # ---- G7-2 only this consent's callbacks count ----
    def test_stale_and_foreign_callbacks_are_ignored(self):
        hub = self.make()
        webhook(self.captures, "data-ready", {"moduleReference": "MODREF-000777", "id": RID, "secret": SECRET})
        webhook(self.captures, "consent-lifecycle", {"moduleReference": "MODREF-000777", "status": "ACTIVE"})
        self.post("/api/connect/start", {"mobile": MOBILE})
        webhook(self.captures, "data-ready", {"moduleReference": "SOMEONE-ELSE", "id": RID, "secret": SECRET})
        webhook(self.captures, "consent-lifecycle", {"moduleReference": "SOMEONE-ELSE", "status": "ACTIVE"})
        hub.link.scan()
        self.assertEqual(self.get("/api/connect").get_json()["state"], "requested")
        self.assertEqual(self.kit.fetches, [])

    def test_a_half_written_callback_is_read_on_the_next_poll(self):
        hub = self.make()
        self.post("/api/connect/start", {"mobile": MOBILE})
        time.sleep(0.002)
        p = self.captures / f"{aa_link.utc_stamp()}_consent-lifecycle_payload.json"
        p.write_text('{"moduleReference": "MODREF-00')                   # the webhook is mid-write
        hub.link.scan()
        self.assertEqual(self.get("/api/connect").get_json()["state"], "requested")
        p.write_text(json.dumps({"moduleReference": "MODREF-000777", "status": "ACTIVE"}))
        hub.link.scan()
        self.assertEqual(self.get("/api/connect").get_json()["state"], "approved")

    # ---- G7-3 single use, never retried ----
    def test_a_failed_fetch_is_never_retried(self):
        hub = self.make(fetch_error=410)
        self.run_journey(hub)
        st = self.get("/api/connect").get_json()
        self.assertEqual(st["state"], "failed")
        self.assertIn("410", st["error"])
        self.assertIn("never retried", st["error"])
        webhook(self.captures, "data-ready", {"moduleReference": "MODREF-000777", "id": RID, "secret": SECRET})
        hub.link.scan()
        self.assertEqual(len(self.kit.fetches), 1)
        self.assertEqual(self.get("/api/payload").get_json(), {"state": "connect"})   # nothing invented
        self.post("/api/connect/use-recorded", {})
        self.assertEqual(self.get("/api/meta").get_json()["corpus_source"], "recorded")

    def test_a_rejected_consent_fetches_nothing(self):
        hub = self.make()
        self.post("/api/connect/start", {"mobile": MOBILE})
        webhook(self.captures, "consent-lifecycle", {"moduleReference": "MODREF-000777", "status": "REJECTED"})
        hub.link.scan()
        webhook(self.captures, "data-ready", {"moduleReference": "MODREF-000777", "id": RID, "secret": SECRET})
        hub.link.scan()
        st = self.get("/api/connect").get_json()
        self.assertEqual(st["state"], "rejected")
        self.assertEqual(self.kit.fetches, [])

    def test_choosing_the_recording_stops_a_waiting_journey(self):
        hub = self.make()
        self.post("/api/connect/start", {"mobile": MOBILE})
        self.post("/api/connect/use-recorded", {})
        webhook(self.captures, "data-ready", {"moduleReference": "MODREF-000777", "id": RID, "secret": SECRET})
        hub.link.scan()
        self.assertEqual(self.kit.fetches, [])                       # nothing is fetched behind the operator's back
        self.assertEqual(self.get("/api/meta").get_json()["corpus_source"], "recorded")

    def test_a_reset_while_the_request_is_in_flight_drops_its_reply(self):
        hub = self.make()
        release, entered = threading.Event(), threading.Event()
        orig = self.kit.start_consent

        def slow(*a, **k):
            entered.set()
            release.wait(5)
            return orig(*a, **k)
        self.kit.start_consent = slow
        t = threading.Thread(target=lambda: self.post("/api/connect/start", {"mobile": MOBILE}))
        t.start()
        entered.wait(5)
        hub.link.reset()
        release.set()
        t.join(5)
        self.assertEqual(self.get("/api/connect").get_json()["state"], "idle")   # the stale consent is not adopted

    # ---- G7-4 nothing sensitive leaves the server ----
    def test_no_secret_retrieval_id_full_mobile_or_path_in_any_response(self):
        hub = self.make()
        with mock.patch.dict(os.environ, {"ANUMATI_CLIENT_SECRET": "CLIENT-SECRET-XYZ"}):
            self.run_journey(hub)
            hub.link.opener = lambda req, timeout: (_ for _ in ()).throw(OSError("down"))
            bodies = [self.get(p).get_data(as_text=True) for p in
                      ("/api/connect", "/api/meta", "/api/payload", "/api/history", "/api/connect/preflight")]
        for b in bodies:
            for bad in (SECRET, RID, "CLIENT-SECRET-XYZ", MOBILE, str(self.tmp), "getdata_RAW"):
                self.assertNotIn(bad, b)
        self.assertIn("••••••9999", bodies[0])

    # ---- G7-5 input, token and one-at-a-time rules ----
    def test_bad_mobile_missing_token_and_second_start_are_refused(self):
        self.make()
        self.assertEqual(self.post("/api/connect/start", {"mobile": "12345"}).status_code, 400)
        self.assertEqual(self.post("/api/connect/start", {"mobile": 9999999999}).status_code, 400)
        self.assertEqual(self.post("/api/connect/start", {"mobile": MOBILE}, token="wrong").status_code, 403)
        self.assertEqual(self.kit.consents, [])
        self.assertEqual(self.post("/api/connect/start", {"mobile": MOBILE}).status_code, 200)
        self.assertEqual(self.post("/api/connect/start", {"mobile": MOBILE}).status_code, 409)
        self.assertEqual(len(self.kit.consents), 1)
        self.assertEqual(self.post("/api/connect/reset", {}).status_code, 200)
        self.assertEqual(self.get("/api/connect").get_json()["state"], "idle")

    def test_without_the_kit_the_journey_is_off_and_gate6_is_unchanged(self):
        self.make(link=False)
        self.assertEqual(self.get("/api/connect").get_json(), {"enabled": False})
        self.assertEqual(self.post("/api/connect/start", {"mobile": MOBILE}).status_code, 404)
        self.assertIn("now", self.get("/api/payload").get_json())
        self.assertEqual(self.get("/api/meta").get_json()["connect"], {"enabled": False, "entry": "app"})

    # ---- G7-6 the watcher thread, end to end ----
    def test_the_watcher_thread_carries_the_journey_by_itself(self):
        hub = self.make(poll=0.05)
        self.post("/api/connect/start", {"mobile": MOBILE})
        webhook(self.captures, "consent-lifecycle", {"moduleReference": "MODREF-000777", "status": "ACTIVE"})
        webhook(self.captures, "data-ready", {"moduleReference": "MODREF-000777", "id": RID, "secret": SECRET,
                                              "sessionCount": 7})
        deadline = time.time() + 60
        while time.time() < deadline and self.get("/api/connect").get_json()["state"] not in ("ready", "failed"):
            time.sleep(0.1)
        st = self.get("/api/connect").get_json()
        self.assertEqual(st["state"], "ready", st)
        self.assertEqual(len(self.kit.fetches), 1)

    # ---- G7-7 pre-flight is read-only ----
    def test_preflight_reports_without_calling_anumati(self):
        hub = self.make()
        calls = []

        class R:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(self.body).encode()

        def opener(req, timeout):
            calls.append(req.full_url)
            if "127.0.0.1:8080" in req.full_url:
                return R({"ok": True, "mode": "finals-live", "latest": ["x_data-ready_payload.json"]})
            raise OSError("tunnel down")
        hub.link.opener, hub.link.health_url = opener, "https://tunnel.example/health"
        with mock.patch.dict(os.environ, {"ANUMATI_CLIENT_SECRET": "x"}):
            pf = self.get("/api/connect/preflight").get_json()
        by = {c["id"]: c for c in pf["checks"]}
        self.assertFalse(by["webhook"]["ok"])                        # its latest capture is not in OUR folder
        self.assertIn("DIFFERENT", by["webhook"]["detail"])
        (self.captures / "x_data-ready_payload.json").write_text("{}")
        with mock.patch.dict(os.environ, {"ANUMATI_CLIENT_SECRET": "x"}):
            pf = self.get("/api/connect/preflight").get_json()
        by = {c["id"]: c for c in pf["checks"]}
        self.assertIn("java", by)
        self.assertTrue(by["secret"]["ok"])
        self.assertTrue(by["webhook"]["ok"])
        self.assertFalse(by["tunnel"]["ok"])
        self.assertFalse(pf["ready"])
        self.assertNotIn("data-ready_payload", json.dumps(pf))        # capture names are not forwarded
        self.assertEqual(self.kit.consents, [])
        self.assertTrue(all("anumati" not in u for u in calls))

    def test_browser_journey_welcome_to_live_household(self):
        """The page walks the real sequence: welcome -> terms -> approve on the AA -> steps -> household."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed on this machine (optional check)")
        from werkzeug.serving import make_server
        import logging
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        hub = self.make(poll=0.1)
        orig = self.kit.start_consent
        self.kit.start_consent = lambda *a, **k: {**orig(*a, **k), "redirectUrl": "about:blank"}
        srv = make_server("127.0.0.1", 0, None)
        port = srv.server_port
        srv.server_close()
        app = serve.create_app(hub, port, TOKEN)
        srv = make_server("127.0.0.1", port, app)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        errors = []
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(f"http://127.0.0.1:{port}/")
            pg.wait_for_selector("#mobile")
            self.assertTrue(pg.locator(".tabbar").is_hidden())
            pg.fill("#mobile", MOBILE)
            pg.click("text=Continue")
            pg.wait_for_selector("text=What Mirror will ask for")
            pg.click("text=Ask my Account Aggregator")
            pg.wait_for_selector("text=Open Anumati to approve")
            with pg.expect_popup() as pop:
                pg.click("text=Open Anumati to approve")
            pop.value.close()
            self.assertTrue(pg.locator("text=Opened — finish on Anumati").is_disabled())
            webhook(self.captures, "consent-lifecycle", {"moduleReference": "MODREF-000777", "status": "ACTIVE"})
            pg.wait_for_selector("text=Your AA said yes", timeout=15000)
            webhook(self.captures, "data-ready", {"moduleReference": "MODREF-000777", "id": RID, "secret": SECRET,
                                                  "sessionCount": 7})
            pg.wait_for_selector("text=Mirror has read your household", timeout=60000)
            body = pg.inner_text("body")
            for bad in (SECRET, RID, MOBILE, "[object", "undefined", "NaN"):
                self.assertNotIn(bad, body)
            pg.click("text=See what needs attention")
            pg.wait_for_selector(".tabbar:not([hidden])")
            self.assertIn("FETCHED LIVE", pg.inner_text("body").upper())
            b.close()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.kit.fetches), 1)

    def test_load_kit_imports_the_unchanged_modules_and_reads_env_from_above(self):
        root = self.tmp / "repo"
        kit = root / "aa-kit"
        kit.mkdir(parents=True)
        (root / ".env").write_text("ANUMATI_CLIENT_SECRET=from-dotenv\n")
        (kit / "anumati_client.py").write_text("import os\nSEC = os.getenv('ANUMATI_CLIENT_SECRET', '')\n")
        (kit / "decrypt.py").write_text("JAR = 'fiu-crypto-lib.jar'\ndef decrypt_getdata(p):\n    return []\n")
        (kit / "webhook_server.py").write_text("")
        try:
            import dotenv  # noqa: F401
        except ImportError:
            self.skipTest("python-dotenv not installed here (it is in the aa-kit venv)")
        for name in ("anumati_client", "decrypt"):
            sys.modules.pop(name, None)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANUMATI_CLIENT_SECRET", None)
            client, dec, caps, jar = aa_link.load_kit(str(kit))
            self.assertEqual(client.SEC, "from-dotenv")
        self.assertEqual(caps, kit.resolve() / "captures")
        for name in ("anumati_client", "decrypt"):
            sys.modules.pop(name, None)
        sys.path.remove(str(kit.resolve()))
        (kit / "decrypt.py").unlink()
        with self.assertRaises(SystemExit):
            aa_link.load_kit(str(kit))


if __name__ == "__main__":
    unittest.main()
