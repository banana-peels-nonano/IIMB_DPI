"""
Counterparty Mirror - Gate 7: the proven Anumati journey, started from inside the app.

It calls the verified AA kit exactly as `run_journey.py` does and edits none of it:
  anumati_client.start_consent(mobile, "102", "PERIODIC", ["DEPOSIT"])   -> redirectUrl (Anumati-hosted)
  (the customer approves on Anumati's own page: ACME Bank, the AA's OTP)
  webhook_server.py (:8080 behind the ngrok static domain) writes Anumati's callbacks into captures/
  anumati_client.fetch_data(id, secret)   SINGLE USE; the client saves the raw response before parsing
  decrypt.decrypt_getdata(raw_path)       the supplied crypto jar, on this laptop
  decrypted.json written the same way run_journey --collect writes it (so a fetch of the same data
  reproduces the sealed E8 file byte for byte on the same machine)

What this module adds, and only this:
  - it READS the webhook's capture files, and only those newer than this consent and carrying this
    consent's moduleReference (the CLI takes "the latest file", which is why the runbook needs a clean
    captures folder; this does not);
  - it fetches at most once per consent and never retries (a second fetch returns 410 and loses the data);
  - it reports each step with the time it really happened. Nothing is animated that did not happen.

Never exposed: the client secret, the data-ready id/secret, file paths, the full mobile number.
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess, sys, threading, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

E8_SHA256 = "49248032661E2509D8F98B3ABB4593BCD8F72CB48790DFEE04DF0FA16BB9584D"
MOBILE = re.compile(r"^[6-9]\d{9}$")
CONSENT_ARGS = ("102", "PERIODIC", ["DEPOSIT"])       # the verified configuration (DEMO_RUNBOOK §4.6)
STOP_STATUSES = {"REJECTED", "REVOKED", "EXPIRED", "PAUSED", "FAILED"}
WAIT_LIMIT_S = 20 * 60                                # the data-ready payload itself expires ~15 min after it arrives

# the customer-facing steps, in order; each is reached only by a real event
STEPS = [
    ("requested", "Mirror asked your Account Aggregator for permission", "Anumati · consent request"),
    ("approved", "You approved on Anumati", "Anumati · consent callback"),
    ("data_ready", "Your bank data is ready at the AA, encrypted", "Anumati · data-ready callback"),
    ("fetched", "Mirror collected it once", "this laptop · single-use fetch"),
    ("decrypted", "Decrypted on this laptop", "this laptop · AA crypto library"),
    ("verified", "Checked against the sealed recording", "this laptop · SHA-256"),
    ("learned", "Mirror read your household", "this laptop · Mirror engine"),
]
ACTIVE = {"starting", "requested", "approved", "data_ready", "fetching", "decrypting", "verifying", "learning"}


class LinkError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def utc_stamp() -> str:
    """The webhook's own file-name clock format, so capture files compare as plain strings."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def load_kit(kit_dir: str):
    """Import the verified AA kit without changing it. The .env is found the way run_journey's
    load_dotenv() finds it: walking up from aa-kit (on the primary laptop it sits at the repo root)."""
    kit = Path(kit_dir).resolve(strict=True)
    for name in ("anumati_client.py", "decrypt.py", "webhook_server.py"):
        if not (kit / name).is_file():
            raise SystemExit(f"--aa-kit must be the verified aa-kit folder ({name} not found)")
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise SystemExit("python-dotenv is missing: start Mirror with the aa-kit venv "
                         "(aa-kit\\.venv\\Scripts\\python.exe), which has the AA kit's requirements")
    for d in [kit, *kit.parents]:
        if (d / ".env").is_file():
            load_dotenv(d / ".env")                      # never overrides variables already set
            break
    if str(kit) not in sys.path:
        sys.path.insert(0, str(kit))
    import anumati_client, decrypt                          # noqa: E402  (the verified modules, unchanged)
    return anumati_client, decrypt.decrypt_getdata, kit / "captures", Path(decrypt.JAR)


class AALink:
    """One consent at a time. Thread-safe. `on_data(path, info)` turns the decrypted file into a live
    Mirror (the server does that); it raises if the engine refuses the data."""

    def __init__(self, client, decrypt, captures: Path, on_data, *, poll: float | None = 0.5,
                 health_url: str | None = None, webhook_health: str = "http://127.0.0.1:8080/health",
                 opener=None, e8_sha256: str = E8_SHA256, jar: Path | None = None):
        self.client, self.decrypt, self.captures = client, decrypt, Path(captures)
        self.on_data, self.poll = on_data, poll
        self.health_url, self.webhook_health = health_url, webhook_health
        self.opener = opener or urllib.request.urlopen
        self.e8 = e8_sha256.upper()
        self.jar = Path(jar) if jar else None
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self.gen = 0                                   # bumped by every start/reset: a stale reply is dropped
        self._reset_state()

    # ---- state ----
    def _reset_state(self):
        self.state, self.error, self.steps = "idle", None, {}
        self.started, self.module_ref, self.redirect, self.mobile_tail = None, None, None, None
        self.seen, self.consumed, self.result, self._t0 = set(), False, None, 0.0

    def _step(self, name: str, detail: str):
        self.steps[name] = {"at": datetime.now().strftime("%H:%M:%S"), "detail": detail}

    def _fail(self, state: str, message: str):
        self.state, self.error = state, message

    def status_unlocked(self) -> dict:
        return self.status()

    def status(self) -> dict:
        with self.lock:
            steps = [{"id": sid, "label": label, "source": source, "done": sid in self.steps,
                      **({"at": self.steps[sid]["at"], "detail": self.steps[sid]["detail"]} if sid in self.steps else {})}
                     for sid, label, source in STEPS]
            waited = int(time.time() - self._t0) if self.state in ACTIVE and self.started else 0
            return {"enabled": True, "state": self.state, "error": self.error, "steps": steps,
                    "mobile": f"••••••{self.mobile_tail}" if self.mobile_tail else None,
                    "consent_ref": f"…{self.module_ref[-6:]}" if self.module_ref else None,
                    # single-use link: offered only until the approval arrives
                    "redirect_url": self.redirect if self.state == "requested" else None,
                    "waited_s": waited, "result": self.result}

    # ---- the journey ----
    def start(self, mobile) -> dict:
        if not isinstance(mobile, str) or not MOBILE.fullmatch(mobile.strip()):
            raise LinkError(400, "enter a 10-digit Indian mobile number")
        mobile = mobile.strip()
        with self.lock:
            if self.state in ACTIVE:
                raise LinkError(409, "a consent is already in progress; the operator can reset it")
            self._reset_state()
            self.gen += 1
            gen = self.gen
            self.state, self.started, self._t0 = "starting", utc_stamp(), time.time()
            self.mobile_tail = mobile[-4:]
        try:
            r = self.client.start_consent(mobile, *CONSENT_ARGS)       # network: Anumati UAT (not metered)
        except Exception as err:                                        # message only; never headers or secrets
            code = getattr(getattr(err, "response", None), "status_code", None)
            with self.lock:
                if gen == self.gen:
                    self._fail("failed", f"Anumati did not accept the consent request ({code or type(err).__name__})")
            return self.status()
        with self.lock:
            if gen != self.gen:                        # reset while the request was in flight: not ours any more
                return self.status()
            self.module_ref = r.get("moduleReference") if isinstance(r, dict) else None
            self.redirect = r.get("redirectUrl") if isinstance(r, dict) else None
            if not self.module_ref or not self.redirect:
                self._fail("failed", "Anumati's reply had no consent link")
                return self.status()
            self.state = "requested"
            self._step("requested", f"status {r.get('status', 'CONSENT_REQUESTED')}")
        if self.poll:
            self._stop = threading.Event()             # a fresh stop flag per consent: an old watcher stays stopped
            self._thread = threading.Thread(target=self._watch, args=(self._stop,), name="aa-link", daemon=True)
            self._thread.start()
        return self.status()

    def reset(self) -> dict:
        with self.lock:
            if self.state in {"fetching", "decrypting", "verifying", "learning"}:
                raise LinkError(409, "the single-use fetch is running; wait for it to finish")
            self._stop.set()
            self.gen += 1
            self._reset_state()
        return self.status()

    def _watch(self, stop: threading.Event):
        while not stop.is_set():
            with self.lock:
                if self.state not in ACTIVE:
                    return
                if time.time() - self._t0 > WAIT_LIMIT_S and self.state in {"requested", "approved"}:
                    self._fail("failed", "Anumati's data did not arrive within 20 minutes; start a new consent")
                    return
            try:
                self.scan()
            except Exception as err:                     # a bad file must not kill the watcher silently
                with self.lock:
                    self._fail("failed", f"could not read a callback ({type(err).__name__})")
                return
            stop.wait(self.poll)

    def _mine(self, p: Path):
        """A capture belongs to this consent only if it arrived after it started and names it."""
        if p.name in self.seen or p.name.split("_", 1)[0] < self.started:
            return None
        try:
            body = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None                    # the webhook may still be writing it: read it on the next poll
        self.seen.add(p.name)                          # read once, whoever it belongs to
        if not isinstance(body, dict) or body.get("moduleReference") != self.module_ref:
            return None
        return body

    def scan(self):
        """Read the webhook's new capture files for this consent (the watcher calls this; tests may too)."""
        with self.lock:
            if self.state not in {"requested", "approved", "data_ready"} or not self.captures.is_dir():
                return
            for p in sorted(self.captures.glob("*_consent-lifecycle_payload.json")):
                body = self._mine(p)
                if body is None:
                    continue
                st = str(body.get("status", "")).upper()
                if st == "ACTIVE" and "approved" not in self.steps:
                    self._step("approved", "consent ACTIVE")
                    if self.state == "requested":
                        self.state = "approved"
                elif st in STOP_STATUSES:
                    self._fail("rejected", f"Anumati reported the consent as {st}; nothing was fetched")
                    return
            ready = None
            for p in sorted(self.captures.glob("*_data-ready_payload.json")):
                body = self._mine(p)
                if body is not None and not self.consumed:
                    ready = body
                    break
            if ready is None:
                return
            if "approved" not in self.steps:             # data-ready implies an approved consent
                self._step("approved", "inferred from the data-ready callback")
            n = ready.get("sessionCount")
            self._step("data_ready", f"{n} account sessions" if isinstance(n, int) else "data ready")
            self.state, self.consumed = "fetching", True     # consumed BEFORE the call: never fetched twice
        self._collect(ready)

    def _collect(self, ready: dict):
        rid, secret = ready.get("id"), ready.get("secret")
        ready.clear()                                        # the retrieval credential is not kept around
        try:
            _, raw_path = self.client.fetch_data(rid, secret)   # SINGLE USE; raw saved by the client first
        except Exception as err:
            code = getattr(getattr(err, "response", None), "status_code", None)
            with self.lock:
                if code is None and isinstance(err, ValueError):    # 200, but the reply would not parse
                    self._fail("failed", "the fetch returned data Mirror could not read; the raw response is saved. "
                                         "Do not fetch again; use the sealed recording.")
                else:
                    self._fail("failed", f"the single-use fetch failed ({code or type(err).__name__}). "
                                         f"It is never retried: start a new consent, or use the sealed recording.")
            return
        finally:
            rid = secret = None
        try:
            self._after_fetch(Path(raw_path))
        except OSError as err:
            with self.lock:
                self._fail("failed", f"the data was fetched and the raw response is saved, but writing it failed "
                                     f"({type(err).__name__}). Do not fetch again; use the sealed recording.")

    def _after_fetch(self, raw_path: Path):
        with self.lock:
            self._step("fetched", f"{raw_path.stat().st_size:,} bytes, saved before reading")
            self.state = "decrypting"
        try:
            out = self.decrypt(raw_path)
        except Exception as err:
            with self.lock:
                self._fail("failed", f"decryption failed ({type(err).__name__}). The raw response is saved; "
                                     f"do not fetch again. Use the sealed recording.")
            return
        dest = self.captures / f"LIVE_{self.started.split('.')[0]}" / "decrypted.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(out, indent=2))           # exactly what run_journey --collect writes
        sha = hashlib.sha256(dest.read_bytes()).hexdigest().upper()
        same = sha == self.e8
        info = {"fetched_at": datetime.now().strftime("%d %b %Y %H:%M"), "sha256": sha, "matches_e8": same,
                "sessions": len(out) if isinstance(out, list) else None}
        with self.lock:
            self._step("decrypted", f"{info['sessions']} account sessions")
            self._step("verified", "the same bytes as the sealed E8 recording" if same else
                       f"new data: fingerprint {sha[:4]}…{sha[-3:]} differs from the sealed recording")
            self.state = "learning"
        try:
            self.on_data(dest, info)
        except SystemExit as err:                             # Mirror's own refusal: detail to the operator only
            print(f"[mirror] the live data was refused: {err}", file=sys.stderr)
            with self.lock:
                self._fail("failed", "Mirror could not use this data (the engine refused it). Use the sealed recording.")
            return
        except Exception as err:
            with self.lock:
                self._fail("failed", f"Mirror could not use this data ({type(err).__name__})")
            return
        with self.lock:
            self._step("learned", "household read and checked")
            self.state = "ready"
            self.result = {"fetched_at": info["fetched_at"], "matches_e8": same,
                           "fingerprint": f"{sha[:4]}…{sha[-3:]}"}

    # ---- operator pre-flight (read-only; no call to Anumati) ----
    def _get(self, url: str, headers: dict | None = None, timeout: float = 4.0):
        req = urllib.request.Request(url, headers=headers or {})
        with self.opener(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _java_check(self) -> dict:
        label = "Java 21 or newer is available for the AA crypto library"
        if shutil.which("java") is None:
            return {"id": "java", "label": label, "ok": False, "detail": "java not found"}
        try:
            out = subprocess.run(["java", "-version"], capture_output=True, text=True, timeout=10)
            m = re.search(r'version "(\d+)', out.stderr + out.stdout)
            major = int(m.group(1)) if m else None
        except Exception:
            major = None
        if major is None:
            return {"id": "java", "label": label, "ok": None, "detail": "java found; version not read"}
        return {"id": "java", "label": label, "ok": major >= 21, "detail": f"Java {major}"}

    def preflight(self) -> dict:
        checks = [{"id": "secret", "label": "Anumati client secret is set on this laptop",
                   "ok": bool(os.getenv("ANUMATI_CLIENT_SECRET")), "detail": "read from .env; never shown"},
                  self._java_check()]
        if self.jar is not None:
            checks.append({"id": "jar", "label": "The AA crypto library is in place", "ok": self.jar.is_file(),
                           "detail": "fiu-crypto-lib.jar found" if self.jar.is_file() else "fiu-crypto-lib.jar missing"})
        try:
            h = self._get(self.webhook_health)
            latest = [n for n in (h.get("latest") or []) if isinstance(n, str)]
            same = all((self.captures / n).exists() for n in latest) if latest else None
            checks.append({"id": "webhook", "label": "The AA webhook is running on this laptop",
                           "ok": bool(h.get("ok")) and same is not False,
                           "detail": (f"mode {h.get('mode')}; " +
                                      ("writes to the folder Mirror reads" if same else
                                       "it writes to a DIFFERENT captures folder" if same is False else
                                       "no callbacks yet, folder not confirmed"))})
        except Exception as err:
            checks.append({"id": "webhook", "label": "The AA webhook is running on this laptop", "ok": False,
                           "detail": f"not reachable ({type(err).__name__}): start webhook_server.py"})
        if self.health_url:
            try:
                h = self._get(self.health_url, {"ngrok-skip-browser-warning": "1"}, timeout=6.0)
                checks.append({"id": "tunnel", "label": "Anumati can reach the webhook (tunnel)",
                               "ok": bool(h.get("ok")), "detail": "the provisioned static domain answered"})
            except Exception as err:
                checks.append({"id": "tunnel", "label": "Anumati can reach the webhook (tunnel)", "ok": False,
                               "detail": f"no answer ({type(err).__name__}): start ngrok with --url"})
        else:
            checks.append({"id": "tunnel", "label": "Anumati can reach the webhook (tunnel)", "ok": None,
                           "detail": "not checked: start Mirror with --callback-health <https://…/health>"})
        return {"checks": checks, "ready": all(c["ok"] is not False for c in checks)}
