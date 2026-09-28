"""Additive, local-only customer API for the UX4G Mirror frontend.

This API runs the existing Mirror engine against a generated synthetic corpus.
It never reads Anumati captures, decrypted bank data, or credentials. The AA
consent/webhook routes remain independently available and unchanged.
"""
from __future__ import annotations

import json
import ipaddress
import os
import tempfile
from datetime import date
from pathlib import Path
from threading import RLock

from flask import Blueprint, current_app, jsonify, request

bp = Blueprint("mirror_customer", __name__, url_prefix="/api/customer")
_lock = RLock()
_runtime = None


@bp.before_request
def local_only():
    """The unauthenticated demo API must never cross the local machine boundary."""
    try:
        address = ipaddress.ip_address(request.remote_addr or "")
        host_header = request.host.lower()
        host = (host_header[1:].split("]", 1)[0] if host_header.startswith("[")
                else host_header.split(":", 1)[0])
        if not address.is_loopback or host not in {"localhost", "127.0.0.1", "::1"}:
            return jsonify({"error": "This synthetic demo API is available only from the local machine."}), 403
    except ValueError:
        return jsonify({"error": "This synthetic demo API is available only from the local machine."}), 403
    return None


@bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _state_root() -> Path:
    configured = os.getenv("MIRROR_DEMO_STATE_DIR")
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        base = os.getenv("LOCALAPPDATA") or os.getenv("XDG_STATE_HOME")
        root = (Path(base).expanduser() / "Mirror" / "demo-state" if base else
                Path.home() / ".local" / "state" / "mirror" / "demo-state")
    repository = Path(__file__).resolve().parents[1]
    if root == repository or repository in root.parents:
        raise RuntimeError("MIRROR_DEMO_STATE_DIR must be outside the git repository")
    return root


def _month_start(months_back: int) -> date:
    today = date.today()
    index = today.year * 12 + today.month - 1 - months_back
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def _add_months(day: date, count: int) -> date:
    index = day.year * 12 + day.month - 1 + count
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, 28))


def _synthetic_corpus_file() -> Path:
    """Create reproducible synthetic AA-shaped data outside the git checkout."""
    root = _state_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "synthetic-corpus.json"
    if path.is_file():
        return path

    def session(masked: str, name: str, mobile: str, transactions: list[tuple]) -> dict:
        rows = "".join(
            '<Transaction txnId="{}" type="{}" amount="{}" narration="{}" reference="{}" '
            'mode="OTHERS" transactionTimestamp="{}T10:00:00" valueDate="{}T00:00:00"/>'.format(
                txn_id, kind, amount, narration, ref, day, day)
            for txn_id, kind, amount, narration, ref, day in transactions
        )
        xml = ('<?xml version="1.0" encoding="UTF-8"?><Account '
               'xmlns="http://api.rebit.org.in/FISchema/deposit"><Profile><Holders><Holder '
               f'name="{name}" mobile="{mobile}"/></Holders></Profile><Summary '
               f'accountSubType="SAVINGS"/><Transactions>{rows}</Transactions></Account>')
        return {"fipId": "SYNTHETIC-FIP", "maskedAccNumber": masked,
                "linkRefNumber": "local-demo", "data": xml}

    from calendar import monthrange

    first = _month_start(23)
    today = date.today()
    primary, secondary = [], []
    for offset in range(24):
        month = _add_months(first, offset)
        last_day = min(7, monthrange(month.year, month.month)[1])
        stamp = f"{month.year:04d}-{month.month:02d}-{last_day:02d}"
        primary.append((f"demo-flow-{offset:02d}", "DEBIT", "100.00", "UPI/123/FOOD/demo",
                        f"DEMO-FLOW-{offset:02d}", stamp))
        secondary.append((f"demo-house-{offset:02d}", "DEBIT", "75.00", "UPI/123/GROCERY/demo",
                          f"DEMO-HOUSE-{offset:02d}", stamp))

    # Recurring entries deliberately stop before the current month so the real
    # evaluator can demonstrate its ordinary timeline and conditional rules.
    for offset in range(18):
        month = _add_months(first, offset)
        if month >= today.replace(day=1):
            break
        day = f"{month.year:04d}-{month.month:02d}-20"
        primary.append((f"demo-lic-{offset:02d}", "DEBIT", "1526.00",
                        "ACH/LIC OF INDIA/DEMO0001", f"DEMO-LIC-{offset:02d}", day))
        primary.append((f"demo-credit-{offset:02d}", "CREDIT", "32000.00",
                        "BY SAL DEMO EMPLOYER", f"DEMO-CREDIT-{offset:02d}",
                        f"{month.year:04d}-{month.month:02d}-01"))
        secondary.append((f"demo-loan-{offset:02d}", "DEBIT", "4999.00",
                          "CMS/000573987107/BAJAJ_AUTO C D", f"DEMO-LOAN-{offset:02d}", day))

    payload = [session("XXXXXX9741", "Asha Sample", "9000000001", primary),
               session("XXXXXX9648", "Ravi Sample", "9000000001", secondary)]
    fd, temp_name = tempfile.mkstemp(prefix=".corpus-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return path


def _engine():
    global _runtime
    if _runtime is None:
        from mirror.corpus import load
        from mirror.rules import PURPOSE_AA_PROTECT
        from mirror.store import JsonFileStore

        corpus = load(str(_synthetic_corpus_file()))
        household_ids = list(corpus.households())
        if len(household_ids) != 1:
            raise RuntimeError("The local demo corpus did not resolve to one household")
        _runtime = {"corpus": corpus, "household": household_ids[0],
                    "store": JsonFileStore(_state_root() / "households"),
                    "base_purposes": frozenset({PURPOSE_AA_PROTECT})}
    return _runtime


def _read_state(runtime):
    from mirror.store import refresh

    store, corpus, household = runtime["store"], runtime["corpus"], runtime["household"]
    today = date.today()
    if store.exists(household):
        state, events = store.load(corpus, household)
        as_of = max(today, state.as_of or today)
        state, events = refresh(store, corpus, household, as_of,
                                state.snapshot.purposes if state.snapshot else runtime["base_purposes"])
    else:
        state, events = refresh(store, corpus, household, today, runtime["base_purposes"])
    return state, events


def _payload():
    from mirror.contract import build_payload, validate_payload

    runtime = _engine()
    state, events = _read_state(runtime)
    result = build_payload(state, events)
    # The shared engine contract defaults to its historical Anumati replay
    # description. This local-only adapter supplies synthetic data, so replace
    # those source/consent disclosures before validating the customer payload.
    result["generated"]["data_mode"] = "synthetic replay"
    known = result["what_we_know"]
    consent = known["consent"]
    consent.update({"rail": "Local synthetic dataset", "purpose_code": "", "purpose_text":
                    "No AA consent is requested or active in this local demo", "fi_types": [],
                    "fetch_type": "", "frequency": "", "data_life": "", "data_range": "",
                    "expiry": "", "status": None, "status_source": None,
                    "terms_source": "Local synthetic demo configuration"})
    for purpose in known["purposes"]:
        if purpose["purpose"] == "AA_PROTECT":
            purpose["status_source"] = "Fixed synthetic replay input; no AA consent is active"
            purpose["granted_through"] = "This local demo's fixed synthetic dataset, not an AA consent"
    known["sources"] = [{"name": "Local synthetic dataset", "fi_type": "DEPOSIT",
                         "mode": "synthetic replay", "corpus_sha256": result["generated"]["corpus_sha256"],
                         "accounts": [{"account": member["account"], "member": member["display_name"].split()[0],
                                       "data_from": member["data_from"], "data_until": member["data_until"],
                                       "used": member["status"] == "watched"}
                                      for member in result["our_household"]["members"]]}]
    known["limits"] = ["This local view uses generated synthetic account activity, not a bank record."
                       if "This is a replay of a recorded sandbox fetch" in limit else limit
                       for limit in known["limits"]]
    result = validate_payload(result)
    return result, state, runtime


def _error(message: str, status: int):
    return jsonify({"error": message}), status


@bp.get("/session")
def session_status():
    return jsonify({"mode": "local-demo", "authenticated": False,
                    "data_source": "synthetic Mirror engine replay",
                    "aa_connected": False, "consent_status": "not_started"})


@bp.get("/contract")
def contract():
    try:
        with _lock:
            result, _, _ = _payload()
        return jsonify(result)
    except Exception:
        current_app.logger.exception("Local Mirror contract could not be generated")
        return _error("The local Mirror engine could not prepare this view. Check backend configuration and state.", 503)


@bp.post("/answers")
def answer():
    from mirror.contract import build_payload, validate_payload
    from mirror.events import Answer, advance, fingerprint
    from mirror.snapshot import take_snapshot

    body = request.get_json(silent=True) or {}
    card_id, option = body.get("cardId"), body.get("optionId")
    if not isinstance(card_id, str) or not isinstance(option, str):
        return _error("Choose an available answer option.", 400)
    try:
        with _lock:
            payload, state, runtime = _payload()
            card_view = next((c for c in payload["now"]["cards"] if c["id"] == card_id), None)
            if not card_view or not card_view.get("question"):
                return _error("That question is no longer open. Refresh the page and try again.", 409)
            card = next((c for c, _ in state.open_cards if c.id == card_id), None)
            if not card or option not in card.question.options:
                return _error("That answer is not available for this question.", 400)
            as_of = max(date.today(), state.as_of or date.today())
            snap = take_snapshot(runtime["corpus"], runtime["household"], as_of,
                                 purposes=state.snapshot.purposes)
            new_state, events = advance(state, snap, [Answer(card_id, option, as_of,
                                                              fingerprint=card_view["fingerprint"])])
            runtime["store"].save(new_state, events)
            return jsonify(validate_payload(build_payload(new_state, events)))
    except Exception:
        current_app.logger.exception("Mirror answer could not be saved")
        return _error("We could not complete that answer. Reload the view to check its current status.", 400)


@bp.post("/purpose")
def purpose():
    from mirror.rules import PURPOSE_GOV_PROTECT
    from mirror.store import refresh

    body = request.get_json(silent=True) or {}
    purpose_id, enabled = body.get("purposeId"), body.get("enabled")
    if purpose_id != PURPOSE_GOV_PROTECT or not isinstance(enabled, bool):
        return _error("This local demo only supports the government-protection purpose switch. AA and LPG consent need their own journeys.", 400)
    try:
        with _lock:
            _, state, runtime = _payload()
            purposes = set(state.snapshot.purposes)
            (purposes.add if enabled else purposes.discard)(PURPOSE_GOV_PROTECT)
            as_of = max(date.today(), state.as_of or date.today())
            updated, events = refresh(runtime["store"], runtime["corpus"], runtime["household"],
                                      as_of, frozenset(purposes))
            from mirror.contract import build_payload, validate_payload
            return jsonify(validate_payload(build_payload(updated, events)))
    except Exception:
        current_app.logger.exception("Mirror purpose could not be updated")
        return _error("We could not complete this purpose change. Reload the view to check its current status.", 400)


@bp.post("/forget")
def forget():
    try:
        with _lock:
            runtime = _engine()
            erased = runtime["store"].erase(runtime["household"])
        return jsonify({"forgotten": True, "state_removed": erased,
                        "message": "Local demo answers, corrections, and access history were removed."})
    except Exception:
        current_app.logger.exception("Mirror local state could not be forgotten")
        return _error("We could not remove the saved local state.", 503)


@bp.post("/facts/correct")
def correct_fact():
    from mirror.contract import build_payload, validate_payload
    from mirror.facts import FactStatement
    from mirror.snapshot import take_snapshot
    from mirror.events import advance

    body = request.get_json(silent=True) or {}
    fact_id, value = body.get("factId"), body.get("value")
    if not isinstance(fact_id, str) or not isinstance(value, str):
        return _error("Choose one of the listed answers.", 400)
    try:
        with _lock:
            _, state, runtime = _payload()
            held = next((f for f in state.hfacts if f.id == fact_id), None)
            if held is None:
                return _error("That fact is no longer available to correct. Refresh and try again.", 409)
            statement = FactStatement(held.account, held.code, value, max(date.today(), state.as_of or date.today()),
                                     held.scheme)
            snap = take_snapshot(runtime["corpus"], runtime["household"], statement.stated_on,
                                 purposes=state.snapshot.purposes)
            updated, events = advance(state, snap, [statement])
            runtime["store"].save(updated, events)
            return jsonify(validate_payload(build_payload(updated, events)))
    except Exception:
        current_app.logger.exception("Mirror fact correction could not be saved")
        return _error("We could not complete that correction. Reload the view to check its current status.", 400)
