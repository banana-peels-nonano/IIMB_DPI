"""Anumati FIU module client. Secrets come from env only - never hard-coded, never logged."""
import os, json, uuid, time
from datetime import datetime, timezone
from pathlib import Path
import requests

BASE = os.getenv("ANUMATI_BASE_URL", "https://fiu-module-uat.anumati.co.in").rstrip("/")
CID  = os.getenv("ANUMATI_CLIENT_ID", "")
SEC  = os.getenv("ANUMATI_CLIENT_SECRET", "")
CAP  = Path(__file__).parent / "captures"; CAP.mkdir(exist_ok=True)

def _h(idem=False):
    h = {"X-Client-Id": CID, "X-Client-Secret": SEC, "Content-Type": "application/json"}
    if idem: h["X-Idempotency-Key"] = str(uuid.uuid4())
    return h

def _redact(h): return {k: ("<redacted>" if k == "X-Client-Secret" else v) for k, v in h.items()}

def _save(tag, payload):
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    p = CAP / f"{ts}_{tag}.json"
    p.write_bytes(payload if isinstance(payload, bytes) else json.dumps(payload, indent=2).encode())
    return p

def start_consent(mobile: str, purpose_code="102", fetch_type="PERIODIC",
                  fi_types=None, data_from=None, data_to=None, expiry=None):
    from datetime import datetime, timedelta, timezone
    _now = datetime.now(timezone.utc)
    # dataRange must not end in the future; keep the window inside 12 months and
    # consent validity inside 1 year, per the fair-use templates.
    data_to   = data_to   or _now.strftime("%Y-%m-%dT00:00:00Z")
    data_from = data_from or (_now - timedelta(days=364)).strftime("%Y-%m-%dT00:00:00Z")
    expiry    = expiry    or (_now + timedelta(days=350)).strftime("%Y-%m-%dT00:00:00Z")
    """Purpose/fetch-type pairing is enforced by the fair-use templates:
       101,102,104 -> PERIODIC ; 103,105 -> ONETIME."""
    body = {
        "customer": {"mobileNumber": mobile},
        "consent": {
            "purposeCode": purpose_code,
            "purposeText": "Personal finance management",
            "fiTypes": fi_types or ["DEPOSIT"],
            "fetchType": fetch_type,
            "dataRange": {"from": data_from, "to": data_to},
            "dataLife": {"unit": "MONTH", "value": 12},
            "frequency": {"unit": "MONTH", "value": 1},
            "consentExpiry": expiry,
        },
    }
    h = _h(idem=True)
    r = requests.post(f"{BASE}/module/initiate/consent", headers=h, json=body, timeout=60)
    _save("consent_request", {"url": f"{BASE}/module/initiate/consent",
                              "headers": _redact(h), "body": body})
    _save("consent_response", r.content)          # RAW first
    r.raise_for_status()
    return r.json()

def fetch_data(retrieval_id: str, secret: str):
    """SINGLE USE. The raw response is written to disk BEFORE any parsing."""
    h = _h()
    r = requests.post(f"{BASE}/module/fi/fetch", headers=h,
                      json={"id": retrieval_id, "secret": secret}, timeout=120)
    path = _save("getdata_RAW", r.content)        # <-- persist before parse, always
    print(f"[fetch] raw response saved to {path} ({len(r.content)} bytes) status={r.status_code}")
    r.raise_for_status()
    return r.json(), path

def initiate_fetch(module_reference: str, key_material: dict):
    h = _h()
    r = requests.post(f"{BASE}/module/initiate/fetch", headers=h,
                      json={"moduleReference": module_reference, "KeyMaterial": key_material},
                      timeout=60)
    _save("initiate_fetch_response", r.content)
    r.raise_for_status()
    return r.json()
