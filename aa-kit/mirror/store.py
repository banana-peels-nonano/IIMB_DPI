"""
Counterparty Mirror - Batch 1c: durable household state (persistence).

    store = JsonFileStore(r"K:\\IIMB_DPI_state\\mirror")          # outside the repo
    state, events = store.load(corpus, household_id)           # or (initial(), []) the first time
    state, events = advance(state, take_snapshot(...), answers, records)
    store.save(state, events)

What is saved (a CHECKPOINT of the durable part of State, one JSON file per household):
  as_of, since, purposes            where the household is in time, and which purposes are ON
  open cards                        id + first_seen + fingerprint only (cards are re-derived)
  closures                          how and why each card closed (you told us / seen in data / record)
  protect answers (Fact)            answers to account-watch questions
  household facts (FactStatement)   age band, taxpayer, ... - stored as the customer's statements (U)
  corrections                       every change of a household fact, old -> new
  source records (SourceRecord)     the minimised LPG record(s), with mode, status and join label
  access log                        every external lookup and every forgetting
  forgotten                         (purpose, date) pairs: material of that purpose dated on/before
                                    is never re-applied
  last events                       the events of the last refresh, so "since last time" reloads exactly
  purpose history                   ON/OFF switches with dates (no personal values)

What is NOT saved, deliberately:
  raw bank transactions, narrations, balances      the sealed AA corpus stays the only source; the
                                                   snapshot is re-derived from it on every load
  cards' evidence and wording                      re-derived and re-validated on load (no stale text)
  protection status table                          re-derived by the Unlock evaluator
  anything a purpose-switch forgot                 the checkpoint is REWRITTEN on every save (atomic
                                                   replace, no backups), so forgotten material leaves
                                                   the disk with the first save after the switch
  LPG IDs, credentials, the Hub's raw response     never held in state, so never written

Guarantees checked on load (the load REFUSES rather than guess):
  * schema, integrity checksum, corpus SHA-256, rulebook version and engine versions all match;
  * every household fact passes facts.check(); customer answers come back as U statements;
  * every source record is a labelled SIMULATED record joined to THIS household - a live record
    can never be loaded into it - and a failed/refused record carries no fields;
  * every card that was open is re-derived by the engine with the same id and fingerprint.

Tamper-evidence: the checkpoint is sealed with SHA-256 (catches accidental edits and damage). If
MIRROR_STORE_KEY is set in the environment, it is sealed with HMAC-SHA256 instead, so a deliberate
edit cannot be re-sealed without the key. Either way, load() also re-checks every invariant below,
because a seal alone proves nothing about what was sealed.

The app's entry point is refresh(): load (or start) -> advance -> save. Re-opening the app on the
same day with nothing new keeps the saved briefing instead of replacing it with "still open".

The store is deliberately small and swappable: JsonFileStore implements save/load/history/erase;
a production datastore can implement the same four methods.
"""
from __future__ import annotations
import hashlib, hmac, json, os, re, shutil, sys, tempfile, time
from datetime import date
from pathlib import Path

from .evaluate import ENGINE as PROTECT_ENGINE
from .events import State, Closure, Fact, Event, fingerprint, advance, initial, RESOLUTIONS
from .facts import FACTS, FactStatement, Correction, check as check_fact
from .rules import RULEBOOK_VERSION, PURPOSES, PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG
from .snapshot import take_snapshot
from .sources.lpg import SourceRecord, SOURCE as LPG_SOURCE, KEEP as LPG_KEEP
from .unlock import evaluate_unlock, ENGINE as UNLOCK_ENGINE, UNLOCK_CODES

SCHEMA = "mirror.store/1"
RECORD_STATUSES = ("ok", "failed")                 # a refused lookup is only ever an access-log entry
HOUSEHOLD_RX = re.compile(r"^HH-[0-9a-f]{6,64}$")
CLOSURE_BASES = ("you_told_us", "seen_in_data", "rule_implied", "source_record")
REPLACE_RETRIES = 20                               # Windows: an editor/AV scan can hold state.json briefly


class StoreError(Exception):
    """Base class: the store refused to load or save. Nothing is guessed or repaired silently."""


class StoreNotFound(StoreError):
    pass


class StoreCorrupt(StoreError):
    """The file was edited or damaged, or holds something the product must never hold."""


class StoreMismatch(StoreError):
    """The saved state was made from a different corpus, rulebook or engine; it cannot be reproduced."""


# ---------- (de)serialisation ----------
def _d(x: date | None) -> str | None:
    return x.isoformat() if x else None


def _p(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _closure_out(c: Closure) -> dict:
    return {"card_id": c.card_id, "code": c.code, "subject": c.subject, "account": c.account,
            "closed_on": _d(c.closed_on), "reason": c.reason, "basis": c.basis, "fingerprint": c.fingerprint,
            "return_txn_ids": list(c.return_txn_ids), "evidence_txn_ids": list(c.evidence_txn_ids),
            "summary": c.summary}


def _closure_in(d: dict) -> Closure:
    return Closure(d["card_id"], d["code"], d["subject"], d["account"], _p(d["closed_on"]), d["reason"],
                   d["basis"], d["fingerprint"], tuple(d["return_txn_ids"]), tuple(d["evidence_txn_ids"]),
                   d["summary"])


def _fact_out(f: Fact) -> dict:
    return {"fact_id": f.fact_id, "card_id": f.card_id, "question_code": f.question_code, "option": f.option,
            "stated_on": _d(f.stated_on), "source": f.source}


def _fact_in(d: dict) -> Fact:
    f = Fact(d["fact_id"], d["card_id"], d["question_code"], d["option"], _p(d["stated_on"]), d["source"])
    if RESOLUTIONS.get(f.question_code, {}).get(f.option, "x") is not None or f.source != "customer" or \
            f.fact_id != "FACT-" + hashlib.sha256(f"{f.card_id}|{f.option}".encode()).hexdigest()[:10]:
        raise StoreCorrupt(f"account-watch answer {f.fact_id} is not a recordable answer")
    return f


def _hfact_out(f: FactStatement) -> dict:
    return {"account": f.account, "code": f.code, "value": f.value, "stated_on": _d(f.stated_on),
            "scheme": f.scheme, "via_card": f.via_card, "evidence_class": "U", "source": "customer"}


def _hfact_in(d: dict) -> FactStatement:
    if d.get("evidence_class") != "U" or d.get("source") != "customer":
        raise StoreCorrupt("a household fact must be stored as the customer's statement (class U)")
    f = FactStatement(d["account"], d["code"], d["value"], _p(d["stated_on"]), d["scheme"], d["via_card"])
    try:
        return check_fact(f)
    except Exception as err:                      # FactInvalid: an edited or unknown answer
        raise StoreCorrupt(f"household fact refused: {err}") from None


def _corr_out(c: Correction) -> dict:
    return {"fact_id": c.fact_id, "code": c.code, "account": c.account, "scheme": c.scheme,
            "old_value": c.old_value, "new_value": c.new_value, "stated_on": _d(c.stated_on)}


def _corr_in(d: dict) -> Correction:
    return Correction(d["fact_id"], d["code"], d["account"], d["scheme"], d["old_value"], d["new_value"],
                      _p(d["stated_on"]))


def _rec_out(r: SourceRecord) -> dict:
    return {"id": r.id, "source": r.source, "mode": r.mode, "status": r.status, "reason": r.reason,
            "requested_on": _d(r.requested_on), "purpose": r.purpose, "household_id": r.household_id,
            "account": r.account, "join": r.join, "fields": r.fields, "dropped": list(r.dropped),
            "request_ref": r.request_ref, "lpg_id_tail": r.lpg_id_tail, "notes": list(r.notes)}


def _rec_in(d: dict, household_id: str) -> SourceRecord:
    r = SourceRecord(d["id"], d["source"], d["mode"], d["status"], d["reason"], _p(d["requested_on"]),
                     d["purpose"], d["household_id"], d["account"], d["join"], dict(d["fields"]),
                     tuple(d["dropped"]), d["request_ref"], d["lpg_id_tail"], tuple(d["notes"]))
    def bad(why):
        raise StoreCorrupt(f"source record {r.id}: {why}")
    if r.status not in RECORD_STATUSES:
        bad(f"status {r.status!r} is never held in state")
    if r.status != "ok" and r.fields:
        bad(f"a {r.status} lookup cannot carry household fields")
    if r.mode != "simulated" or r.join != "simulated" or r.household_id != household_id:
        bad(f"only a labelled SIMULATED record for this household may be held in its state "
            f"(got mode={r.mode}, join={r.join}); live records are never joined")
    if r.source != LPG_SOURCE or r.purpose != PURPOSE_DPI_LPG or r.lpg_id_tail is not None \
            or not r.request_ref.startswith("SIM-LPG-") or any("live" in n.lower() for n in r.notes):
        bad("carries marks of a live lookup")
    expected = {"SR-" + hashlib.sha256(f"{LPG_SOURCE}|simulated|{r.request_ref}|{r.requested_on}".encode()).hexdigest()[:10],
                "SR-" + hashlib.sha256(f"{LPG_SOURCE}|simulated|timeout|{r.requested_on}".encode()).hexdigest()[:10]}
    if r.id not in expected:
        bad("its id does not match its own contents")
    if set(r.fields) - set(LPG_KEEP.values()):
        bad(f"fields outside the minimisation whitelist {sorted(set(r.fields) - set(LPG_KEEP.values()))}")
    tail = r.fields.get("account_tail")
    if tail is not None and not re.fullmatch(r"\d{4}", str(tail)):
        bad("an account number longer than its last 4 digits")
    return r


def _event_out(e: Event) -> dict:
    return {"id": e.id, "kind": e.kind, "status": e.status, "as_of": e.as_of, "since": e.since,
            "subject": e.subject, "account": e.account, "card_id": e.card_id, "basis": e.basis,
            "evidence_classes": list(e.evidence_classes), "txn_ids": list(e.txn_ids), "data": e.data}


def _event_in(d: dict) -> Event:
    return Event(d["id"], d["kind"], d["status"], d["as_of"], d["since"], d["subject"], d["account"],
                 d["card_id"], d["basis"], tuple(d["evidence_classes"]), tuple(d["txn_ids"]), d["data"])


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _sha(obj) -> str:
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()


def _seal(sealed: dict) -> dict:
    key = os.environ.get("MIRROR_STORE_KEY")
    if key:
        return {"hmac_sha256": hmac.new(key.encode(), _canon(sealed).encode("utf-8"), hashlib.sha256).hexdigest()}
    return {"sha256": _sha(sealed)}


def _check_seal(meta: dict, sealed: dict) -> None:
    key = os.environ.get("MIRROR_STORE_KEY")
    seal = meta.get("seal", {})
    if "hmac_sha256" in seal:
        if not key:
            raise StoreCorrupt("this state is sealed with a key; set MIRROR_STORE_KEY to load it")
        good = hmac.new(key.encode(), _canon(sealed).encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, seal["hmac_sha256"]):
            raise StoreCorrupt("state.json was changed outside the app (keyed seal does not match)")
    elif seal.get("sha256") != _sha(sealed):
        raise StoreCorrupt("state.json was changed outside the app (integrity checksum does not match)")
    elif key:
        raise StoreCorrupt("MIRROR_STORE_KEY is set but this state was saved without it; refusing to trust it")


def _scrub(events: list, state: State) -> list:
    """When a purpose was switched off in this refresh, the events about cards it produced (and that
    are no longer open) lose their summaries before they reach the disk: those summaries can quote
    forgotten material (a record's account digits, an answer). Nothing customer-facing reads them:
    the briefing never shows purpose-off withdrawals, and the contract's event list omits summaries."""
    if not any(e.kind == "PURPOSE_REVOKED" for e in events):
        return [_event_out(e) for e in events]
    still_open = {c.id for c, _ in state.open_cards}
    out = []
    for e in events:
        d = _event_out(e)
        code = e.data.get("summary", {}).get("code")
        if code in UNLOCK_CODES and e.card_id not in still_open:
            d["data"] = {k: v for k, v in e.data.items() if k in ("reason", "superseded_by", "waiting_on")}
            d["data"]["summary"] = {"code": code, "scrubbed": "purpose switched off"}
        out.append(d)
    return out


def state_body(state: State, events: list) -> dict:
    """The durable part of a State, as plain JSON. Pure: no clock, no randomness."""
    snap = state.snapshot
    return {
        "as_of": _d(state.as_of), "since": _d(state.since), "purposes": sorted(snap.purposes),
        "open_cards": [{"id": c.id, "code": c.code, "first_seen": _d(first), "fingerprint": fingerprint(c)}
                       for c, first in state.open_cards],
        "closed": [_closure_out(c) for c in state.closed],
        "protect_answers": [_fact_out(f) for f in state.facts],
        "household_facts": [_hfact_out(f) for f in state.hfacts],
        "corrections": [_corr_out(c) for c in state.corrections],
        "records": [_rec_out(r) for r in state.records],
        "access_log": [dict(e) for e in state.access_log],
        "forgotten": [[p, _d(d)] for p, d in state.forgotten],
        "last_events": _scrub(events, state),
    }


def _purpose_changes(events: list) -> list:
    return [{"purpose": e.subject, "on": e.kind == "PURPOSE_GRANTED", "on_date": e.as_of}
            for e in events if e.kind in ("PURPOSE_GRANTED", "PURPOSE_REVOKED")]


# ---------- the store ----------
class JsonFileStore:
    """One folder per household: state.json (checkpoint, rewritten atomically) and history.jsonl
    (append-only counts and dates - never answers, never a hash of the body). Keep the root OUTSIDE
    the git repository."""

    def __init__(self, root):
        self.root = Path(root)

    def _dir(self, household_id) -> Path:
        if not isinstance(household_id, str) or not HOUSEHOLD_RX.match(household_id):
            raise StoreError(f"not a household id: {household_id!r}")
        return self.root / household_id

    def exists(self, household_id: str) -> bool:
        return (self._dir(household_id) / "state.json").is_file()

    # --- write ---
    def save(self, state: State, events: list) -> dict:
        snap = state.snapshot
        folder = self._dir(snap.household_id)
        folder.mkdir(parents=True, exist_ok=True)
        self._sweep(folder)
        previous = self._read(snap.household_id) if self.exists(snap.household_id) else None
        if previous and previous["meta"]["household_id"] != snap.household_id:
            raise StoreCorrupt("the folder holds another household's state; refusing to overwrite it")
        history = list(previous["purpose_history"]) if previous else []
        for change in _purpose_changes(events):
            if change not in history:
                history.append(change)
        body = state_body(state, events)
        sealed = {"purpose_history": history, "state": body}
        meta = {"schema": SCHEMA, "household_id": snap.household_id, "corpus_sha256": snap.corpus_sha256,
                "rulebook_version": RULEBOOK_VERSION, "engines": {"protect": PROTECT_ENGINE, "unlock": UNLOCK_ENGINE},
                "seal": _seal(sealed)}
        self._atomic_write(folder / "state.json", _canon({"meta": meta, **sealed}) + "\n")
        line = {"as_of": body["as_of"], "since": body["since"], "purposes": body["purposes"],
                "open_cards": len(body["open_cards"]), "closed": len(body["closed"]),
                "household_facts": len(body["household_facts"]), "corrections": len(body["corrections"]),
                "records": len(body["records"]), "access_log": len(body["access_log"]),
                "purpose_changes": _purpose_changes(events), "event_kinds": sorted({e.kind for e in events})}
        hist = self.history(snap.household_id)
        if not hist or hist[-1] != line:
            path = folder / "history.jsonl"
            torn = path.is_file() and path.stat().st_size and not path.read_bytes().endswith(b"\n")
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(("\n" if torn else "") + _canon(line) + "\n")   # never glue onto a torn line
                f.flush()
                os.fsync(f.fileno())
        return meta

    @staticmethod
    def _sweep(folder: Path) -> None:
        for leftover in folder.glob(".state-*.tmp"):        # from a process killed mid-save
            leftover.unlink(missing_ok=True)

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(REPLACE_RETRIES):
                try:
                    os.replace(tmp, path)          # the old checkpoint is gone; no backups are kept
                    break
                except PermissionError:
                    if attempt == REPLACE_RETRIES - 1:
                        raise StoreError(f"could not replace {path.name}: the file is held open by another "
                                         f"program; nothing was changed") from None
                    time.sleep(0.05 * (attempt + 1))
            if sys.platform != "win32":            # make the rename itself durable (POSIX)
                dfd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    # --- read ---
    def _read(self, household_id: str) -> dict:
        path = self._dir(household_id) / "state.json"
        if not path.is_file():
            raise StoreNotFound(f"no saved state for {household_id}")
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as err:
            raise StoreCorrupt(f"state.json is not valid JSON: {err}") from None
        meta = doc.get("meta", {})
        if meta.get("schema") != SCHEMA:
            raise StoreMismatch(f"unknown store schema {meta.get('schema')!r}")
        _check_seal(meta, {"purpose_history": doc.get("purpose_history"), "state": doc.get("state")})
        return doc

    def history(self, household_id: str) -> list:
        """Every save's counts. A line torn by a crash is skipped, never fatal."""
        path = self._dir(household_id) / "history.jsonl"
        out = []
        if path.is_file():
            for raw in path.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(raw))
                except ValueError:
                    continue
        return out

    def load(self, corpus, household_id: str) -> tuple:
        """-> (State, last events), re-derived from the sealed corpus and checked against the checkpoint."""
        doc = self._read(household_id)
        self._sweep(self._dir(household_id))
        meta, b = doc["meta"], doc["state"]
        if meta["household_id"] != household_id:
            raise StoreCorrupt("state.json belongs to another household")
        if meta["corpus_sha256"] != corpus.sha256:
            raise StoreMismatch("saved with a different AA corpus; its state cannot be reproduced from this one")
        if meta["rulebook_version"] != RULEBOOK_VERSION:
            raise StoreMismatch(f"saved under rulebook {meta['rulebook_version']}, running {RULEBOOK_VERSION}")
        if meta["engines"] != {"protect": PROTECT_ENGINE, "unlock": UNLOCK_ENGINE}:
            raise StoreMismatch(f"saved by engines {meta['engines']}; cannot reproduce with the running engines")
        purposes = frozenset(b["purposes"])
        if not purposes <= set(PURPOSES):
            raise StoreCorrupt(f"unknown purpose(s) {sorted(purposes - set(PURPOSES))}")
        as_of = _p(b["as_of"])
        forgotten = tuple((p, _p(d)) for p, d in b["forgotten"])
        if any(p not in PURPOSES or d > as_of for p, d in forgotten):
            raise StoreCorrupt("the forgetting record is not valid")
        hfacts = tuple(_hfact_in(x) for x in b["household_facts"])
        records = tuple(_rec_in(x, household_id) for x in b["records"])
        for f in hfacts:                          # a switched-off purpose's answers must not be on disk
            if FACTS[f.code]["purpose"] not in purposes:
                raise StoreCorrupt(f"an answer for a switched-off purpose is stored ({f.code})")
            if f.stated_on > as_of:
                raise StoreCorrupt(f"an answer dated after the state's date is stored ({f.code})")
        corrections = tuple(_corr_in(x) for x in b["corrections"])
        held = {f.id: f for f in hfacts}
        for c in corrections:
            f = held.get(c.fact_id)
            if f is None or (c.account, c.code, c.scheme) != f.key or \
                    {c.old_value, c.new_value} - set(FACTS[c.code]["values"]):
                raise StoreCorrupt(f"correction {c.fact_id} does not belong to a held answer")
        if records and not {PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG} <= purposes:
            raise StoreCorrupt("a source record is stored while the LPG check is switched off")
        if any(r.requested_on > as_of for r in records):
            raise StoreCorrupt("a source record dated after the state's date is stored")
        for cl in b["closed"]:
            if cl["basis"] not in CLOSURE_BASES:
                raise StoreCorrupt(f"closure {cl['card_id']} has an unknown basis")
            if (cl["code"] in UNLOCK_CODES and PURPOSE_GOV_PROTECT not in purposes) or \
               ((cl["code"] == "LPG_SUBSIDY_ROUTING" or cl["basis"] == "source_record")
                    and PURPOSE_DPI_LPG not in purposes):
                raise StoreCorrupt(f"a closure produced under a switched-off purpose is stored ({cl['code']})")
        snap = take_snapshot(corpus, household_id, as_of, purposes=purposes)
        ures = evaluate_unlock(snap, hfacts, records)
        derived = {c.id: c for c in tuple(snap.cards) + ures.cards}
        open_cards = []
        for oc in b["open_cards"]:
            card = derived.get(oc["id"])
            if card is None or fingerprint(card) != oc["fingerprint"]:
                raise StoreMismatch(f"open card {oc['id']} ({oc['code']}) is not reproduced by this engine")
            open_cards.append((card, _p(oc["first_seen"])))
        state = State(as_of, snap, _p(b["since"]), tuple(open_cards),
                      tuple(_closure_in(x) for x in b["closed"]), tuple(_fact_in(x) for x in b["protect_answers"]),
                      hfacts, corrections, records, tuple(dict(x) for x in b["access_log"]), ures.status, forgotten)
        return state, [_event_in(x) for x in b["last_events"]]

    def purpose_history(self, household_id: str) -> list:
        return list(self._read(household_id)["purpose_history"])

    # --- stop & forget everything for a household (AA consent revoked, or the customer asks) ---
    def erase(self, household_id: str) -> bool:
        folder = self._dir(household_id)
        if not folder.exists():
            return False
        shutil.rmtree(folder)
        return True


def _durable(body: dict) -> dict:
    return {k: v for k, v in body.items() if k not in ("since", "last_events")}


def refresh(store: JsonFileStore, corpus, household_id: str, as_of: date, purposes, answers=(), records=()):
    """The app's one entry point: load (or start) -> advance -> save -> (State, events).
    Re-opening on the same day with nothing new keeps the saved state and its briefing."""
    if store.exists(household_id):
        prev, prev_events = store.load(corpus, household_id)
    else:
        prev, prev_events = initial(), []
    state, events = advance(prev, take_snapshot(corpus, household_id, as_of, purposes=purposes), answers, records)
    if prev.as_of == as_of and _durable(state_body(state, events)) == _durable(state_body(prev, prev_events)):
        return prev, prev_events                         # nothing new today: keep what the customer saw
    store.save(state, events)
    return state, events
