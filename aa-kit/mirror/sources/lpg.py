"""
Counterparty Mirror - LPG ID Authentication adapter (Perfios Hub), Gate 5.

    rec = simulated(scenario, requested_on=..., household_id=..., account=..., purposes=...)
    rec = live(lpg_id, requested_on=..., purposes=..., holder_confirmed=True, spend_credit=True)

What the oil company's record adds that AA cannot: whether refills were booked
after the household's subsidy credits stopped, whether the subsidy was given up,
and which bank account the subsidy is paid into. AA shows what ARRIVED; this
record shows what the PAYER did.

Two modes, one parser:
  simulated  a schema-true fixture (field names from the Hub documentation),
             run through the SAME parser as a live response. Every record says
             SIMULATED, and the join to the sandbox household is labelled simulated.
  live       off unless MIRROR_HUB_LIVE=1, the person has confirmed it is their
             OWN 17-digit LPG ID, and the caller accepts that a call spends a Hub
             credit (failed calls spend one too). A live record is never joined
             to a sandbox household: it can only be shown on its own.

Failure is never success: any refusal, error, unknown code, unusable body, a
body without a usable last booking date (the one field every branch needs), or
a body that mixes two connections becomes a record with status "failed" or
"refused" and NO household fields.
The evaluator turns that into "we couldn't check" + the question stays open (U).

Minimisation: only the five fields a rule or a sentence actually reads are
kept. Name, address, phone, email, Aadhaar digits, consumer number, IFSC,
distributor details, connection status and refill/subsidy totals are dropped
on arrival; their field NAMES (never values) are listed so the access
log can show what was discarded. The full account number is cut to its last 4.
The LPG ID itself is never stored; a live record keeps only its last 4.
Credentials come from the environment and are never printed or stored.
"""
from __future__ import annotations
import hashlib, json, os, re, urllib.request, urllib.error
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from ..rules import PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG

SOURCE = "PERFIOS_HUB_LPG"
SOURCE_LABEL = "the oil company's LPG record (via Perfios Hub)"
ENDPOINT_PATH = "/ssp/kyc/api/v2/lpg"
TEST_BASE = "https://hub-test.perfios.ai"
ALLOWED_BASES = (TEST_BASE, "https://hub.perfios.ai")     # credentials are never sent anywhere else
LPG_ID_RX = re.compile(r"^[12]\d{16}$")          # documented input pattern
SUCCESS_CODE = "101"                              # [UNVERIFIED] no successful call observed yet
KNOWN_CODES = {"102": "ID_NOT_RECOGNISED"}        # observed on 24 Sep (probe call)
NOT_AVAILABLE = {"", "not applicable", "na", "n/a", "null", "none", "-"}

# field in the Hub response -> our key. Everything else is dropped.
KEEP = {
    "lastbookingdate": "last_booking_date",        # decides every branch
    "subsidizedrefillconsumed": "subsidised_refills",   # shown in the sentence
    "givenupsubsidy": "given_up_subsidy",          # decides the GIVEN_UP branch
    "bankname": "bank_name",                       # shown in the sentence
    "bankaccountno": "account_tail",               # cut to last 4 below; decides ELSEWHERE / SAME
}
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%Y/%m/%d")


# ---------- what is LIVE-capable vs what ran SIMULATED (shown in the app, never blurred) ----------
DISCLOSURE = ("We could not perform a successful live lookup because we do not have a valid consenting LPG ID "
              "for this household; the simulated record demonstrates the exact downstream product flow.")
INTEGRATION = {
    "name": "Perfios Hub — LPG ID Authentication",
    "role": "first-class DPI source: the oil company's own record of the LPG subsidy (payer side)",
    "endpoint": "POST " + ENDPOINT_PATH,
    "hosts": list(ALLOWED_BASES),
    "auth_headers": ["x-secure-id", "x-secure-cred", "x-organization-ID"],   # names only; values from env
    "request": {"consent": "Y", "lpg_id": "17 digits, ^[12]\\d{16}$ (the holder's own)"},
    "live_capability": [
        "live call path built: request, auth from environment, Perfios-host pinning, 30 s timeout",
        "consent gating: both purposes on, holder confirms own ID, credit spend acknowledged",
        "shared parser with simulated mode: success code, field whitelist, last-4 cut, failure codes",
        "failure handling: HTTP error, timeout, non-JSON, unknown code, no booking date, mixed connections",
        "access log entry for every attempt; the ID itself is never stored (live keeps its last 4 digits)",
    ],
    "verified_against_the_hub": [
        "24 Sep 2026: a format-valid, non-existent probe ID through Perfios's Tryout (test mode) returned HTTP 200 "
        "with status-code 102 ('Invalid ID Number or Combination of Inputs') in ~1.7 s",
        "a failed call still spends one Hub credit",
    ],
    "not_yet_verified": [
        "the success status-code (assumed 101) and where the fields sit in a successful body",
        "whether the bank-routing fields are populated (the documented sample shows 'Not Applicable')",
    ],
    "live_lookup_for_this_household": {
        "status": "not performed",
        "reason": "no valid LPG ID from a consenting holder of this household (the sandbox household is synthetic)",
    },
}


class LiveLookupRefused(Exception):
    """Raised before any network call when live mode's preconditions are not met."""


@dataclass(frozen=True)
class SourceRecord:
    id: str
    source: str
    mode: str                     # live | simulated
    status: str                   # ok | failed | refused
    reason: str                   # "" when ok; a code when not
    requested_on: date
    purpose: str
    household_id: str | None      # None = cannot be joined to any household (live, standalone)
    account: str | None           # the member account the customer said this connection belongs to
    join: str                     # "simulated" | "customer_confirmed" | "none"
    fields: dict = field(default_factory=dict)       # minimised, only when status == ok
    dropped: tuple = ()           # names of fields discarded on arrival
    request_ref: str = ""         # the Hub's request id, or the fixture id
    lpg_id_tail: str | None = None
    notes: tuple = ()

    @property
    def ok(self) -> bool:
        return self.status == "ok"


# ---------- parsing (shared by live and simulated) ----------
def _walk(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                yield from _walk(v)
            else:
                yield k, v
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _parse_date(v) -> str | None:
    s = str(v or "").strip()
    iso = re.match(r"\d{4}-\d{2}-\d{2}", s)                 # also "2026-08-12T00:00:00", "2026-08-12 10:22"
    if iso:
        s = iso.group(0)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s[:11].strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _clean(key: str, v):
    s = str(v).strip() if v is not None else ""
    if s.lower() in NOT_AVAILABLE:
        return None
    if key == "last_booking_date":
        return _parse_date(s)
    if key in ("subsidised_refills", "total_refills"):
        return int(float(s)) if re.fullmatch(r"\d+(\.0+)?", s) else None
    if key == "subsidy_availed":
        return float(s) if re.fullmatch(r"\d+(\.\d+)?", s) else None
    if key == "given_up_subsidy":
        return {"yes": True, "no": False}.get(s.lower())
    if key == "account_tail":
        digits = re.sub(r"\D", "", s)
        return digits[-4:] if len(digits) >= 4 else None
    return s


def parse_response(raw: dict, *, mode: str, requested_on: date, purpose: str, household_id, account,
                   join: str, lpg_id_tail=None, fixture_id: str = "") -> SourceRecord:
    code = str(raw.get("status-code", raw.get("statusCode", "")))
    ref = str(raw.get("request_id", "")) or fixture_id
    rid = "SR-" + hashlib.sha256(f"{SOURCE}|{mode}|{ref}|{requested_on}".encode()).hexdigest()[:10]
    base = dict(id=rid, source=SOURCE, mode=mode, requested_on=requested_on, purpose=purpose,
                household_id=household_id, account=account, join=join, request_ref=ref,
                lpg_id_tail=lpg_id_tail)
    result = raw.get("result")
    if code != SUCCESS_CODE or not isinstance(result, dict) or not result:
        reason = KNOWN_CODES.get(code, f"SOURCE_CODE_{code or 'MISSING'}")
        return SourceRecord(status="failed", reason=reason, **base)
    kept, dropped, clash = {}, set(), False
    for k, v in _walk(result):
        ours = KEEP.get(str(k).lower())
        if ours is None:
            dropped.add(str(k))
            continue
        value = _clean(ours, v)
        clash = clash or (ours in kept and kept[ours] != value)
        kept[ours] = value
    dropped = tuple(sorted(dropped))
    if clash:                                            # e.g. two connections in one body: never mix them
        return SourceRecord(status="failed", reason="AMBIGUOUS_RECORD", dropped=dropped, **base)
    if kept.get("last_booking_date") is None:            # every branch needs it: without it nothing is usable
        return SourceRecord(status="failed", reason="NO_USABLE_FIELDS", dropped=dropped, **base)
    notes = ("the record does not show which bank account the subsidy goes to",) \
        if kept.get("account_tail") is None else ()
    return SourceRecord(status="ok", reason="", fields=kept, dropped=dropped, notes=notes, **base)


def _refused(reason, *, mode, requested_on, purpose, household_id, account, join) -> SourceRecord:
    rid = "SR-" + hashlib.sha256(f"{SOURCE}|{mode}|refused|{reason}|{requested_on}".encode()).hexdigest()[:10]
    return SourceRecord(rid, SOURCE, mode, "refused", reason, requested_on, purpose, household_id, account, join)


def _purpose_ok(purposes) -> bool:
    return PURPOSE_GOV_PROTECT in purposes and PURPOSE_DPI_LPG in purposes


# ---------- simulated mode ----------
# Field names follow the Hub documentation for LPG ID Authentication. Values are invented
# for the SELA sandbox story and marked; "<dropped>" placeholders stand where the real
# response carries personal data, so the minimiser is exercised on every run.
_PII = {"ConsumerName": "<dropped>", "ConsumerAddress": "<dropped>", "ConsumerEmail": "<dropped>",
        "ConsumerMobile": "<dropped>", "AadhaarNo": "<dropped>", "ConsumerNo": "<dropped>",
        "DistributorAddress": "<dropped>", "IFSCCode": "<dropped>", "DistributorCode": "<dropped>"}
SCENARIOS = {
    "rerouted": {"status-code": "101", "request_id": "SIM-LPG-REROUTED", "result": {
        **_PII, "status": "ACTIVE", "DistributorName": "Sample Gas Agency (simulated)",
        "LastBookingDate": "2026-08-12", "SubsidizedRefillConsumed": "3", "TotalRefillConsumed": "3",
        "ApproximateSubsidyAvailed": "484.44", "GivenUpSubsidy": "No",
        "BankName": "Sample Bank (simulated)", "BankAccountNo": "XXXXXXXX4471"}},
    "no_refills": {"status-code": "101", "request_id": "SIM-LPG-NOREFILLS", "result": {
        **_PII, "status": "ACTIVE", "DistributorName": "Sample Gas Agency (simulated)",
        "LastBookingDate": "2026-05-20", "SubsidizedRefillConsumed": "2", "TotalRefillConsumed": "2",
        "ApproximateSubsidyAvailed": "322.96", "GivenUpSubsidy": "No",
        "BankName": "Sample Bank (simulated)", "BankAccountNo": "XXXXXXXX9648"}},
    "routing_not_shown": {"status-code": "101", "request_id": "SIM-LPG-NOROUTING", "result": {
        # mirrors the documented sample's limitation: routing fields come back "Not Applicable"
        **_PII, "status": "ACTIVE", "LastBookingDate": "2026-08-12", "SubsidizedRefillConsumed": "3",
        "TotalRefillConsumed": "", "ApproximateSubsidyAvailed": "0.0", "GivenUpSubsidy": "No",
        "BankName": "Not Applicable", "BankAccountNo": "Not Applicable"}},
    "given_up": {"status-code": "101", "request_id": "SIM-LPG-GIVENUP", "result": {
        **_PII, "status": "ACTIVE", "LastBookingDate": "2026-08-12", "SubsidizedRefillConsumed": "0",
        "TotalRefillConsumed": "3", "ApproximateSubsidyAvailed": "0.0", "GivenUpSubsidy": "Yes",
        "BankName": "Not Applicable", "BankAccountNo": "Not Applicable"}},
    "invalid_id": {"status-code": "102", "request_id": "SIM-LPG-INVALID", "result": {}},
    "unusable": {"status-code": "101", "request_id": "SIM-LPG-UNUSABLE", "result": {**_PII}},
    "timeout": None,
}


def simulated(scenario: str, *, requested_on: date, household_id: str, account: str, purposes) -> SourceRecord:
    """A labelled, schema-true fixture for the sandbox household. No identifier is used or needed."""
    kw = dict(mode="simulated", requested_on=requested_on, purpose=PURPOSE_DPI_LPG,
              household_id=household_id, account=account, join="simulated")
    if not _purpose_ok(purposes):
        return _refused("PURPOSE_NOT_GRANTED", **kw)
    if scenario not in SCENARIOS:
        raise KeyError(f"unknown simulated scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
    raw = SCENARIOS[scenario]
    if raw is None:
        rid = "SR-" + hashlib.sha256(f"{SOURCE}|simulated|timeout|{requested_on}".encode()).hexdigest()[:10]
        return SourceRecord(rid, SOURCE, "simulated", "failed", "TIMEOUT", requested_on, PURPOSE_DPI_LPG,
                            household_id, account, "simulated", request_ref="SIM-LPG-TIMEOUT")
    return parse_response(json.loads(json.dumps(raw)), fixture_id=raw["request_id"], **kw)


# ---------- live mode ----------
def live(lpg_id: str, *, requested_on: date, purposes, holder_confirmed: bool, spend_credit: bool,
         base_url: str = TEST_BASE, timeout_s: int = 30, _opener=urllib.request.urlopen) -> SourceRecord:
    """One real lookup on the holder's OWN LPG ID. Every precondition is checked before any network
    call. The result cannot be joined to a household (household_id=None, join='none')."""
    kw = dict(mode="live", requested_on=requested_on, purpose=PURPOSE_DPI_LPG, household_id=None,
              account=None, join="none")
    if os.environ.get("MIRROR_HUB_LIVE") != "1":
        raise LiveLookupRefused("live mode is off (set MIRROR_HUB_LIVE=1 for one deliberate call)")
    if not _purpose_ok(purposes):
        raise LiveLookupRefused("the LPG check purpose is not switched on")
    if not holder_confirmed:
        raise LiveLookupRefused("the holder must confirm this is their own LPG ID and that they consent")
    if not spend_credit:
        raise LiveLookupRefused("a live call spends a Hub credit, even when it fails; pass spend_credit=True")
    if not LPG_ID_RX.match(lpg_id or ""):
        raise LiveLookupRefused("not a 17-digit LPG ID starting with 1 or 2; no call made")
    if base_url not in ALLOWED_BASES:
        raise LiveLookupRefused("credentials are only ever sent to Perfios Hub's own hosts")
    creds = {h: os.environ.get(e) for h, e in (("x-secure-id", "PERFIOS_SECURE_ID"),
                                               ("x-secure-cred", "PERFIOS_SECURE_CRED"),
                                               ("x-organization-ID", "PERFIOS_ORG_ID"))}
    if not all(creds.values()):
        raise LiveLookupRefused("Hub credentials are not in the environment; they are never read from files")
    tail = lpg_id[-4:]
    req = urllib.request.Request(base_url + ENDPOINT_PATH, method="POST",
                                 data=json.dumps({"consent": "Y", "lpg_id": lpg_id}).encode(),
                                 headers={"Content-Type": "application/json", **creds})
    try:
        with _opener(req, timeout=timeout_s) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return _failed_live(f"HTTP_{e.code}", tail, **kw)
    except (urllib.error.URLError, TimeoutError, OSError):
        return _failed_live("UNREACHABLE_OR_TIMEOUT", tail, **kw)
    except ValueError:
        return _failed_live("NOT_JSON", tail, **kw)
    if not isinstance(raw, dict):
        return _failed_live("NOT_JSON_OBJECT", tail, **kw)
    rec = parse_response(raw, lpg_id_tail=tail, **kw)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return SourceRecord(**{**rec.__dict__, "notes": rec.notes + (f"live call at {stamp}",)})


def _failed_live(reason, tail, **kw) -> SourceRecord:
    rid = "SR-" + hashlib.sha256(f"{SOURCE}|live|{reason}|{kw['requested_on']}|{tail}".encode()).hexdigest()[:10]
    return SourceRecord(rid, SOURCE, "live", "failed", reason, kw["requested_on"], kw["purpose"], None, None,
                        "none", lpg_id_tail=tail)


def standalone_view(rec: SourceRecord) -> dict:
    """How a live record may be shown: on its own, never merged into a household."""
    return {"source": SOURCE_LABEL, "mode": rec.mode, "status": rec.status, "reason": rec.reason,
            "lpg_id": f"…{rec.lpg_id_tail}" if rec.lpg_id_tail else None, "fields": rec.fields,
            "dropped_on_arrival": list(rec.dropped), "request_ref": rec.request_ref,
            "joined_to_household": False, "notes": list(rec.notes)}


if __name__ == "__main__":
    import argparse, getpass
    ap = argparse.ArgumentParser(description="LPG adapter. Default: print every simulated scenario. "
                                             "--live makes ONE real call on the holder's own LPG ID.")
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    from ..rules import PURPOSE_AA_PROTECT
    purposes = {PURPOSE_AA_PROTECT, PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG}
    if not a.live:
        for name in SCENARIOS:
            r = simulated(name, requested_on=date(2026, 9, 9), household_id="HH-demo", account="XXXXXXXX9648",
                          purposes=purposes)
            print(f"{name:<18} {r.status:<7} {r.reason:<22} kept={r.fields} dropped={list(r.dropped)}")
    else:
        print("ONE live call. It spends a Hub credit even if it fails. Use only YOUR OWN LPG ID.")
        ok = input("Type 'my own ID, I consent' to continue: ").strip() == "my own ID, I consent"
        lpg = getpass.getpass("LPG ID (hidden, never stored): ").strip()
        rec = live(lpg, requested_on=date.today(), purposes=purposes, holder_confirmed=ok, spend_credit=ok)
        print(json.dumps(standalone_view(rec), indent=2, ensure_ascii=False))
