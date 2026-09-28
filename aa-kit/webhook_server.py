"""Anumati callback receiver.
Exposes THREE routes so it works whichever way Anumati provisions us:
  /aa/data-ready   - dedicated data-ready
  /aa/consent      - dedicated consent lifecycle
  /aa/callback     - multiplexing endpoint; classifies by payload shape
Persists the RAW body before any parsing. Never logs secrets.
"""
import json, os, time, hashlib
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify
from customer_api import bp as customer_api

CAP = Path(__file__).parent / "captures"; CAP.mkdir(exist_ok=True)
MODE = os.getenv("MODE", "dev")
app = Flask(__name__)
app.register_blueprint(customer_api)

SENSITIVE = {"x-client-secret", "authorization", "cookie", "x-secure-cred", "x-api-key"}

def safe_headers(h):
    return {k: ("<redacted>" if k.lower() in SENSITIVE else v) for k, v in h.items()}

def classify(body: dict) -> str:
    if not isinstance(body, dict):
        return "unknown"
    if "id" in body and "secret" in body:          # data-ready carries retrieval creds
        return "data-ready"
    if "consentId" in body or ("status" in body and "id" not in body):
        return "consent-lifecycle"
    return "unknown"

def persist(kind: str, raw: bytes, headers) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    digest = hashlib.sha256(raw).hexdigest()[:12]
    name = f"{ts}_{kind}_{digest}.json"
    rec = {
        "received_at_utc": ts,
        "kind": kind,
        "mode": MODE,
        "headers": safe_headers(headers),
        "raw_body_b64_len": len(raw),
        "raw_body_text": raw.decode("utf-8", errors="replace"),
    }
    (CAP / name).write_text(json.dumps(rec, indent=2))
    # also drop the bare payload for the pipeline to consume
    (CAP / f"{ts}_{kind}_payload.json").write_bytes(raw)
    return name

def handle(forced_kind=None):
    raw = request.get_data()                       # RAW FIRST. Parse later.
    try:
        body = json.loads(raw or b"{}")
    except Exception:
        body = None
    kind = forced_kind or classify(body)
    name = persist(kind, raw, request.headers)
    app.logger.info("captured %s -> %s", kind, name)
    return jsonify({"ok": True, "kind": kind}), 200   # 2xx promptly, always

@app.get("/health")
def health():
    caps = sorted(p.name for p in CAP.glob("*_payload.json"))
    return jsonify({"ok": True, "mode": MODE, "captures": len(caps),
                    "latest": caps[-3:], "time": datetime.now(timezone.utc).isoformat()})

@app.post("/aa/data-ready")
def data_ready(): return handle("data-ready")

@app.post("/aa/consent")
def consent(): return handle("consent-lifecycle")

@app.post("/aa/callback")
def callback(): return handle(None)

@app.get("/captures")
def list_caps():
    return jsonify(sorted(p.name for p in CAP.glob("*.json")))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
