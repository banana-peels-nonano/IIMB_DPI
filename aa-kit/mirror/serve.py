"""
Counterparty Mirror - Gate 6: the local app server (one household, one process, this laptop only).

    python -m mirror.serve --data <decrypted.json> --store <folder OUTSIDE the repo> [--start 2026-08-28]
    then open http://127.0.0.1:8787

What it is: a thin wrapper. Every request is ONE store.refresh() (the verified Batch 1c entry point),
then build_payload() -> validate_payload(). The browser only ever receives validated mirror.app/1.0
JSON (or a refusal). It renders; it decides nothing. If a payload fails validation, the server sends an
error, never the payload (fail closed).

Endpoints (all JSON; POSTs need the per-launch token injected into the page):
  GET  /api/payload     the current validated payload (first call: one refresh at the start date)
  GET  /api/meta        mode, replay date, replay stops, what is live-capable (no paths, no secrets)
  GET  /api/vocab       fixed display words (gated at start-up): evidence labels, Ask Mirror, preview
  GET  /api/history     purpose ON/OFF history (dates only) and the access log, as in the payload
  POST /api/answers     {answers:[{card_id, option}], as_of?}           closed options of an open card
  POST /api/facts       {account, code, value, scheme?, as_of?}          a correction, closed values only
  POST /api/purposes    {purpose, on, as_of?}                            switch off = forget (engine)
  POST /api/lpg-check   {mode:"simulated", scenario, consent_to_purpose?, as_of?}
                        {mode:"live", ...} is refused unless started with MIRROR_HUB_LIVE=1 AND the
                        holder confirms; a live record is shown on its own, never joined or stored
  POST /api/erase       stop and forget: the household's saved state is deleted (no extra verification)
  POST /api/clock       {as_of}  REPLAY ONLY: the next refresh, on a later date of the recorded data
  POST /api/replay/restart {as_of}  REPLAY ONLY, operator: erase and start the replay again

`as_of` on a POST is a replay-only convenience that moves the replay date and applies the change in
the SAME refresh (so an API session reproduces the demo sessions byte for byte).

Local hardening: binds 127.0.0.1 only; Host header must be 127.0.0.1/localhost (blocks DNS rebinding);
POSTs need the launch token and a JSON body (blocks other pages posting to localhost); no CORS;
request bodies are never logged; one lock serialises every read and write; debug is off.

Gate 7 (optional, --aa-kit <folder>): the customer starts the proven Anumati journey from the app.
  GET  /api/connect            the journey's state: each step with the time it really happened
  GET  /api/connect/preflight  operator: secret set? java? webhook up? tunnel answering? (no Anumati call)
  POST /api/connect/start      {mobile}  -> anumati_client.start_consent (the AA kit, unchanged)
  POST /api/connect/reset      operator: back to the welcome screen (refused during the single-use fetch)
  POST /api/connect/use-recorded   operator: show the sealed E8 recording instead
The approval, the bank choice and the OTP happen on Anumati's own page, never in Mirror. Callbacks
still arrive only at webhook_server.py; aa_link.py reads what it writes. The fetched data becomes a
new household state in its own store folder, labelled FETCHED LIVE; time is still replayed, because
the sandbox data ends in September (so generated.data_mode stays "replay", and it is true).

Households (optional, --households): an OPERATOR / DEMO control. It is not customer login, not
access control and not multi-tenancy. The sandbox's one test consent returned accounts for several
holders; the engine already separates them by holder mobile (never PAN) and the store already keeps
one folder per household. With the flag, the operator can show each household in the corpus being
shown (recorded or fetched live), each with its own saved answers and its own "Stop and forget":
  GET  /api/households          the households in the corpus being shown, grouped by holder name
  POST /api/households/select   {household}  show that household (refused on the AA journey screens)
Households are never merged: one holder under two mobiles stays two households. In real use each
household consents for itself and sees only its own. Without the flag none of this exists and the
app shows the SELA household exactly as before.

Demo login (optional, --demo-login): the phone-entry screen opens a sandbox household. DEMO / SANDBOX
only - not authentication, not a Mirror login. A fixed three-row directory maps demo numbers to the
household holding one account; it holds no holder mobile, no hash and no household id:
  9999999999 -> account ...9741 (SELA). It is Anumati's UAT test customer: with --aa-kit it takes the
                verified Gate 7 journey unchanged; without it, the sealed recording. After a live fetch this
                session, signing back in with it reopens that household (no new consent).
  9999999998 -> account ...9950, 9999999997 -> account ...9960: the sealed recording only. These never
                start an AA consent (the server refuses /api/connect/start for them).
  POST /api/login  {mobile}   -> {route: "aa" | "app"}   (unknown numbers are refused; nothing is stored)
  POST /api/logout            operator: back to the phone screen; every household keeps its saved state
Only the number that consented ever sees FETCHED LIVE data. In real use each customer would identify
through their own Account Aggregator and each household would consent for itself.
--households (operator API only, no page UI): GET /api/households and POST /api/households/select.

Options (optional, --options): "Within an amount you set", the answer to Ask Mirror's "Which scheme or
policy should we take?". A deterministic, neutral options explorer (options.py): no LLM, no network,
nothing stored. POST /api/options {member, amount} -> options/1.0, validated fail-closed. The amount is
a closed set, compared one by one with each published option's single debit; never summed, subtracted,
divided or saved. Without --options the fixed Ask Mirror reply is unchanged.

Not built: a Mirror login of its own, deployment, customer access to more than one household.
`--mode live` is refused: mirror.app/1.0 labels every payload as a replay of a recorded fetch
(generated.data_mode, the sources list and a LIMITS line). A live-fetched corpus is still replayed in
time, so that label stays true; only the corpus provenance changes, and the page shows it.
"""
from __future__ import annotations
import argparse, hmac, json, logging, os, re, secrets, sys, threading
from datetime import date, datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, Response

from .corpus import load
from .contract import (build_payload, validate_payload, PayloadInvalid, CONTRACT_VERSION, BADGE, BADGE_ANSWERED,
                       BADGE_RECORD, BASIS_LABEL, U_TEXT)
from .events import Answer, AnswerInvalid, PurposeNotGranted, JoinRefused
from .facts import FactStatement, FACTS, FactInvalid
from .language import gate, UnsafeLanguage
from .rules import PURPOSE_AA_PROTECT, PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG, PURPOSES
from .sources import lpg
from .store import JsonFileStore, refresh, StoreError
from .snapshot import display_name
from . import aa_link
from .options import (build_options, validate_options, OptionsRefused, REPLY as OPTIONS_REPLY,
                      BUTTON as OPTIONS_BUTTON, LINK as OPTIONS_LINK, STEP1 as OPTIONS_STEP1)

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
WEB = Path(__file__).resolve().parent / "web"
E8_SHA256 = "49248032661E2509D8F98B3ABB4593BCD8F72CB48790DFEE04DF0FA16BB9584D"
REPLAY_END = date(2026, 9, 23)                 # the recorded consent window ends here
DEFAULT_START = date(2026, 8, 28)
# Operator hints for the replay panel (never shown as customer text). Dates of the recorded data.
REPLAY_STOPS = [
    ("2026-04-21", "Kiran: a returned IndusInd collection, paid every month since"),
    ("2026-08-09", "Kiran's collections pause; AHEAD shows a tight day for John"),
    ("2026-08-28", "John: a ₹590 return charge posts"),
    ("2026-09-07", "Ten days later: John's last data day"),
    ("2026-09-12", "A few days on"),
]
SWITCHABLE = (PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG)

# ---- fixed display words: served to the page, every string passes the language gate at start-up ----
EVIDENCE_LABELS = {
    # O - what the bank data shows (or a defined absence in it)
    "RETURN_CHARGE_POSTED": "A return charge in the bank data",
    "COLLECTION_HISTORY": "Earlier collections of this payment",
    "EARLIER_COLLECTION": "An earlier collection by the same payee",
    "NOT_COLLECTED": "No collection where one usually appears",
    "NO_RETURN_CHARGE": "No return charge in that period either",
    "SUBSIDY_CREDITS_SEEN": "Subsidy credits in the bank data",
    "NO_SUBSIDY_CREDIT_SINCE": "No subsidy credit since then",
    "SCHEME_DEBIT_SEEN": "Scheme premium debits in the bank data",
    "SCHEME_DEBIT_NOT_SEEN": "No scheme premium debit in this account",
    "LPG_RECORD": "The oil company's LPG record",
    # I - our reading
    "LINKED_TO_PAYMENT": "Which payment the charge belongs to",
    "PRESENTED_AMOUNT": "The amount that was probably presented",
    "REVEALED_LIQUIDITY": "What the payments that went through suggest this account could cover",
    "LOOKS_LIKE_LOAN_INSTALMENT": "That these collections look like a loan instalment",
    "DUE_DAY_FROM_COLLECTIONS": "The usual collection day, read from past collections",
    "POSSIBLE_MATCH": "A possible matching payment",
    "HOUSEHOLD_HAS_LPG_CONNECTION": "That the household has had an LPG connection",
    "REFILLS_AFTER_LAST_CREDIT": "Refills booked after the last subsidy credit",
    "ROUTING_FINDING": "Which account the record names for the subsidy",
    # R - published rules (the payload also carries each rule's own name and citation)
    "GRACE_RULE": "The insurer's grace period",
    "OVERDUE_RULE": "RBI's overdue rule",
    "BUREAU_REPORTING_DATES": "When lenders report to credit bureaus",
    "SCHEME_RULE": "The scheme's published rules",
    "SUBSIDY_TO_BANK_ACCOUNT": "How the LPG subsidy is paid",
    "APB_LAST_SEEDED_BANK": "Which bank government transfers go to",
    # U - only the customer or the counterparty can know (the engine's own wording for account-watch unknowns)
    **{k: v[0].upper() + v[1:] for k, v in U_TEXT.items() if k not in FACTS},
    # U - household facts (short labels; the engine's longer "why" stays in the payload)
    "AGE_BAND": "Which age band applies",
    "TAXPAYER": "Whether this member has ever paid income tax",
    "COVERED_ELSEWHERE": "Whether there is cover through another account",
    "LPG_REFILLS": "Whether refills were booked",
    "SUBSIDY_ACCOUNT": "Which account the subsidy should reach",
    "ROUTED_ACCOUNT_STATUS": "Whether the account the record names is yours and in use",
    "DISTRIBUTOR_ANSWER": "What the distributor says",
    "SUBSIDY_GIVEN_UP": "Whether giving up the subsidy was your choice",
}
CHAIN_GROUPS = [  # the order a card's evidence is revealed in: bank data -> our reading -> rule -> unknowns
    {"class": "O", "heading": BADGE["O"]},
    {"class": "I", "heading": BADGE["I"]},
    {"class": "R", "heading": BADGE["R"]},
    {"class": "U", "heading": BADGE["U"]},
]
KIND_LABELS = {"CLOCK": "Needs attention", "DOOR": "Worth checking", "QUESTION": "A question for you",
               "SUPPRESSION": "Checked, not shown"}
ASK_MIRROR = [  # S2: five fixed questions; answers are assembled ONLY from payload fields
    {"id": "why", "label": "Why am I seeing this?"},
    {"id": "know", "label": "What do you know about us?"},
    {"id": "who", "label": "Who looked at our data?"},
    {"id": "wrong", "label": "This is wrong"},
    {"id": "stop", "label": "Stop and forget"},
    {"id": "advice", "label": "Which scheme or policy should we take?",
     "fixed_reply": "Mirror doesn't recommend products. Here is what we saw and where you can check it."},
]
NOTIFICATION_PREVIEW = {  # S1: the text an alert WOULD carry. Never sent. No digits, amounts, names or links.
    # The messaging decision's draft said "1 new update"; its own acceptance rule forbids any digit.
    "text": "Mirror: there is a new update for your household. Open the Mirror app to see it. "
            "We never send amounts or account details by message.",
    "badge": "SIMULATED · NOT SENT",
    "does_not_contain": ["amounts", "names", "account digits", "what changed", "links"],
}
MODE_LABELS = {"recorded_e8": "RECORDED E8 · 23 Sep 2026", "recorded": "RECORDED AA FETCH",
               "replay": "REPLAY", "simulated_lpg": "SIMULATED LPG"}


def _vocab() -> dict:
    v = {"contract": CONTRACT_VERSION, "badges": {**BADGE, "U_answered": BADGE_ANSWERED,
                                                   "O_record_live": BADGE_RECORD["live"],
                                                   "O_record_simulated": BADGE_RECORD["simulated"]},
         "basis_labels": BASIS_LABEL, "evidence_labels": EVIDENCE_LABELS, "chain_groups": CHAIN_GROUPS,
         "kind_labels": KIND_LABELS, "ask_mirror": ASK_MIRROR, "notification_preview": NOTIFICATION_PREVIEW,
         "mode_labels": MODE_LABELS, "lpg_disclosure": lpg.DISCLOSURE}

    def walk(x):
        if isinstance(x, dict):
            for y in x.values():
                walk(y)
        elif isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, str):
            gate(x)
    walk(v)
    return v


def inside_git(p: Path) -> bool:
    return any((q / ".git").exists() for q in [p, *p.parents])


class Refused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ---- --households (operator / demo control): which households a corpus holds, named from its holders ----
HOUSEHOLDS_CAVEAT = gate(
    "A demo control for the operator: not a customer feature and not a login. The sandbox's one test consent "
    "returned accounts for several holders; Mirror separates them into households by holder mobile, never PAN. "
    "Each keeps its own saved answers and its own 'Stop and forget'. In real use, each household consents for "
    "itself and sees only its own.")
HOUSEHOLDS_SAME_NAME = gate(
    "Same holder name under different mobile numbers. Mirror joins a household by holder mobile only, so these "
    "stay separate households and are never merged.")


# ---- --demo-login: DEMO / SANDBOX phone entry. Not authentication. No holder mobile, hash or household id here ----
DEMO_LOGINS = (
    {"number": "9999999999", "account": "9741", "aa": True},    # Anumati's UAT test customer; its consent returned SELA's accounts
    {"number": "9999999998", "account": "9950", "aa": False},   # sealed recording only; never an AA call
    {"number": "9999999997", "account": "9960", "aa": False},   # sealed recording only; never an AA call
)
DEMO_LOGIN_NOTE = gate(
    "Demo login for the sandbox. It is not authentication: real Mirror would identify you through your Account "
    "Aggregator, and each household would consent for itself.")
DEMO_LOGIN_UNKNOWN = gate("This demo login only knows the sandbox demo numbers. It is not a real sign-in.")
DEMO_LOGIN_NO_AA = gate("In the demo login, only the sandbox's AA test customer starts an AA consent.")
MOBILE_RX = re.compile(r"[6-9]\d{9}")


def _group_title(names: tuple) -> str:
    if len(names) > 1:
        common = set(names[0].split())
        for n in names[1:]:
            common &= set(n.split())
        common -= {"Sr", "Jr"}
        if len(common) == 1:
            return f"{common.pop().upper()} household"
    return f"{' & '.join(n.upper() for n in names)} household"


def household_groups(corpus) -> list:
    """The corpus's households for the operator's switcher, grouped by holder name for display only.
    Every household keeps its own id, saved state and 'Stop and forget'; nothing is merged or invented."""
    by_names = {}
    for hh, accs in corpus.households().items():
        by_names.setdefault(tuple(sorted({display_name(a.member) for a in accs})), []).append((hh, accs))
    groups = []
    for names, items in by_names.items():
        title = _group_title(names)
        items.sort(key=lambda x: (-sum(len(a.txns) for a in x[1]), x[0]))
        entries = []
        for hh, accs in items:
            accs = sorted(accs, key=lambda a: a.masked[-4:])
            tails = [f"…{a.masked[-4:]}" for a in accs]
            read = [a for a in accs if a.quality == "OK"]
            entries.append({
                "id": hh,
                "label": title if len(items) == 1 else f"{title} ({', '.join(tails)})",
                "members": sorted({display_name(a.member) for a in accs}),
                "accounts": [{"account": t, "member": display_name(a.member), "read": a.quality == "OK",
                              "not_read_reason": gate(a.quality_reason) if a.quality != "OK" and a.quality_reason
                              else None} for t, a in zip(tails, accs)],
                "summary": gate(f"Mirror reads {len(read)} of {len(accs)} account{'s' if len(accs) > 1 else ''}"
                                if read else "Mirror infers nothing from this data (reasons below)"),
            })
        groups.append({"title": title, "households": entries,
                       "note": HOUSEHOLDS_SAME_NAME if len(items) > 1 else None,
                       "_rank": (-max(sum(1 for acc in e["accounts"] if acc["read"]) for e in entries), -len(names), title)})
    groups.sort(key=lambda g: g.pop("_rank"))
    return groups


class Mirror:
    """One household, one store, one lock. Holds no answers of its own: the store is the memory."""

    def __init__(self, data: str, store: str, start: date = DEFAULT_START, mode: str = "replay",
                 source: dict | None = None, household: str | None = None):
        if mode != "replay":
            raise SystemExit("--mode live is not available in Gate 6: mirror.app/1.0 labels every payload as a "
                             "replay of a recorded fetch, so a live corpus would be mislabelled (Gate 7).")
        root = Path(store).resolve()
        if inside_git(root):
            raise SystemExit(f"refusing: {root} is inside a git repository; saved answers must never be committed")
        if not (date(2025, 9, 24) <= start <= REPLAY_END):
            raise SystemExit("--start must be a date inside the recorded consent window")
        self.corpus = load(data)
        if household is None:                            # Gate 6/7 default: the SELA household, unchanged
            members = [a for a in self.corpus.accounts if a.masked.endswith("9741")]
            if not members:
                raise SystemExit("the SELA household (account …9741) is not in this corpus")
            self.hh = members[0].household_id
        else:                                            # --households: the operator chose another household
            if household not in self.corpus.households():
                raise ValueError("that household is not in this corpus")
            self.hh = household
        self.first_start = start                         # the launch date (restart() may move self.start)
        self.root = root
        self.store = JsonFileStore(root)
        self.start, self.mode = start, mode
        self.source = source or {"kind": "recorded"}         # "live": fetched through the app this session
        self.lock = threading.Lock()
        self.vocab = _vocab()
        self.opener = None                       # tests inject a fake network opener for the live path
        # "Stop and forget" is durable: a tombstone survives restarts; only the operator's restart clears it
        self.tombstone = root / f".forgotten-{self.hh}"
        self.live_log = root / "standalone-live-lookups.jsonl"

    @property
    def stopped(self) -> bool:
        return self.tombstone.exists()

    # ---- state ----
    def start_if_needed(self) -> None:
        """The first refresh happens here (server start or operator restart), never on a GET."""
        if not self.stopped and not self.store.exists(self.hh):
            refresh(self.store, self.corpus, self.hh, self.start, frozenset({PURPOSE_AA_PROTECT}))

    def _saved(self):
        return self.store.load(self.corpus, self.hh) if self.store.exists(self.hh) else (None, None)

    def _current(self):
        st, _ = self._saved()
        if st is None:
            return self.start, frozenset({PURPOSE_AA_PROTECT})
        return st.as_of, frozenset(st.snapshot.purposes)

    def _payload(self, st, ev) -> dict:
        return validate_payload(build_payload(st, ev))

    def payload(self) -> dict:
        """Read-only: never creates or changes state."""
        if self.stopped:
            raise Refused(410, "forgotten")
        st, ev = self._saved()
        if st is None:
            raise Refused(412, "not started")
        return self._payload(st, ev)

    def _when(self, body: dict) -> date:
        as_of, _ = self._current()
        if body.get("as_of") in (None, ""):
            return as_of
        try:
            when = date.fromisoformat(str(body["as_of"]))
        except ValueError:
            raise Refused(400, "as_of must be YYYY-MM-DD")
        if when < as_of:
            raise Refused(409, "time only moves forward in the replay")
        if when > REPLAY_END:
            raise Refused(400, "that date is after the recorded consent window")
        return when

    def _refresh(self, when: date, purposes, answers=(), records=()) -> dict:
        if self.stopped:
            raise Refused(410, "forgotten")
        try:
            st, ev = refresh(self.store, self.corpus, self.hh, when, frozenset(purposes), answers, records)
        except (AnswerInvalid, FactInvalid) as err:
            raise Refused(400, f"not accepted: {err}")
        except (PurposeNotGranted, JoinRefused) as err:
            raise Refused(403, f"not accepted: {err}")
        return self._payload(st, ev)

    def _open_payload(self) -> dict:
        """The current payload for validating a customer action (the first POST may start the state)."""
        if self.stopped:
            raise Refused(410, "forgotten")
        st, ev = self._saved()
        if st is None:
            return None
        return self._payload(st, ev)

    # ---- customer actions ----
    def answers(self, body: dict) -> dict:
        items = body.get("answers")
        if items is None and "card_id" in body:
            items = [{"card_id": body.get("card_id"), "option": body.get("option")}]
        if not isinstance(items, list) or not items or len(items) > 10:
            raise Refused(400, "send one to ten answers")
        when = self._when(body)
        _, purposes = self._current()
        current = self._open_payload()
        if current is None:
            raise Refused(409, "there are no open questions yet")
        open_q = {c["id"]: c for c in current["now"]["cards"] if c.get("question")}
        out, seen = [], set()
        for a in items:
            if not isinstance(a, dict) or not isinstance(a.get("card_id"), str) or not isinstance(a.get("option"), str):
                raise Refused(400, "each answer is {card_id, option} as text")
            if a["card_id"] in seen:
                raise Refused(400, "one answer per card in a request")
            seen.add(a["card_id"])
            card = open_q.get(a["card_id"])
            if card is None:
                raise Refused(400, "that card has no open question")
            if a["option"] not in {o["id"] for o in card["question"]["options"]}:
                raise Refused(400, "that is not one of the card's options")
            out.append(Answer(card["id"], a["option"], when, card["fingerprint"]))
        return self._refresh(when, purposes, out)

    def fact(self, body: dict) -> dict:
        if not all(isinstance(body.get(k), str) for k in ("account", "code", "value")) or \
                not (body.get("scheme") is None or isinstance(body.get("scheme"), str)):
            raise Refused(400, "send {account, code, value, scheme} as text (scheme may be null)")
        when = self._when(body)
        _, purposes = self._current()
        current = self._open_payload()
        facts = current["what_we_know"]["household_facts"] if current else []
        held = next((f for f in facts if f["account"] == body["account"] and f["fact"] == body["code"]
                     and f["scheme"] == body.get("scheme")), None)
        if held is None:
            raise Refused(400, "only a fact you already told us can be corrected here")
        if body["value"] not in {o["id"] for o in held["options"]}:
            raise Refused(400, "that is not one of the fact's options")
        f = FactStatement(held["account"], held["fact"], body["value"], when, held["scheme"])
        return self._refresh(when, purposes, [f])

    def purpose(self, body: dict) -> dict:
        pid, on = body.get("purpose"), body.get("on")
        if pid == PURPOSE_AA_PROTECT:
            raise Refused(400, "the bank-data watch follows your AA consent; change it at the AA, "
                               "or use 'Stop and forget'")
        if pid not in SWITCHABLE or not isinstance(on, bool):
            raise Refused(400, "send {purpose, on:true|false}")
        when = self._when(body)
        _, purposes = self._current()
        new = set(purposes)
        if on:
            if pid == PURPOSE_DPI_LPG and PURPOSE_GOV_PROTECT not in new:
                raise Refused(409, "switch on 'Check government protections' first")
            if pid == PURPOSE_DPI_LPG and pid not in new and body.get("consent_to_purpose") is not True:
                raise Refused(409, "the LPG record check needs its own separate OK")
            new.add(pid)
        else:
            new.discard(pid)
            if pid == PURPOSE_GOV_PROTECT:
                new.discard(PURPOSE_DPI_LPG)       # the narrower purpose goes with it
        return self._refresh(when, new)

    def lpg_check(self, body: dict) -> dict:
        mode = body.get("mode")
        if mode == "live":
            return self._lpg_live(body)
        if mode != "simulated":
            raise Refused(400, "mode is 'simulated' (or 'live', which is off unless enabled at start-up)")
        scenario = body.get("scenario", "rerouted")
        if not isinstance(scenario, str) or scenario not in lpg.SCENARIOS:
            raise Refused(400, f"unknown scenario; choose from {sorted(lpg.SCENARIOS)}")
        when = self._when(body)
        _, purposes = self._current()
        new = set(purposes)
        if PURPOSE_GOV_PROTECT not in new:
            raise Refused(409, "switch on 'Check government protections' first")
        if PURPOSE_DPI_LPG not in new:
            if body.get("consent_to_purpose") is not True:
                raise Refused(409, "the LPG record check needs its own separate OK")
            new.add(PURPOSE_DPI_LPG)
        current = self._open_payload()
        if current is None:
            raise Refused(409, "there is no LPG subsidy in the connected accounts to check")
        accounts = [c["account"] for c in current["now"]["cards"]
                    if c["code"] in ("LPG_SUBSIDY_QUESTION", "LPG_SUBSIDY_ROUTING")]
        accounts += [m["account"] for m in current["our_household"]["protections"].get("members", [])
                     if any(s["scheme"] == "PAHAL" for s in m["schemes"])]
        if not accounts:
            raise Refused(409, "there is no LPG subsidy in the connected accounts to check")
        account = body.get("account") or accounts[0]
        if not isinstance(account, str) or account not in accounts:
            raise Refused(400, "that account has no LPG subsidy to check")
        rec = lpg.simulated(scenario, requested_on=when, household_id=self.hh, account=account, purposes=new)
        return self._refresh(when, new, (), [rec])

    def _lpg_live(self, body: dict) -> dict:
        if os.environ.get("MIRROR_HUB_LIVE") != "1":
            raise Refused(403, "live LPG lookups are off on this laptop (start with MIRROR_HUB_LIVE=1 for one "
                               "deliberate call on a consenting holder's own ID)")
        _, purposes = self._current()
        lpg_id = body.get("lpg_id")
        extra = {"_opener": self.opener} if self.opener else {}
        try:
            rec = lpg.live(lpg_id if isinstance(lpg_id, str) else "", requested_on=date.today(),
                           purposes=purposes, holder_confirmed=body.get("holder_confirmed") is True,
                           spend_credit=body.get("spend_credit") is True, **extra)
        except lpg.LiveLookupRefused as err:
            raise Refused(403, f"refused before any call: {err}")
        finally:
            lpg_id = None                            # held for this call only; never stored or logged
        # every call that reached the Hub is logged: date, outcome, reason, the ID's last 4 - never the ID,
        # never the fields, and never joined to the household
        entry = {"on": rec.requested_on.isoformat(), "what": "live lookup", "source": lpg.SOURCE,
                 "source_label": lpg.SOURCE_LABEL, "mode": "live", "outcome": rec.status, "reason": rec.reason,
                 "lpg_id_last4": rec.lpg_id_tail, "joined_to_household": False}
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.live_log, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        view = lpg.standalone_view(rec)
        return {"standalone_live_record": view, "joined_to_household": False, "logged": entry,
                "note": gate("A live record is shown on its own. It is never joined to the sandbox household.")}

    def _live_lookups(self) -> list:
        if not self.live_log.is_file():
            return []
        out = []
        for raw in self.live_log.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
        return out

    def erase(self) -> dict:
        self.store.erase(self.hh)
        self.root.mkdir(parents=True, exist_ok=True)
        self.tombstone.write_text("stopped and forgotten; only the operator's replay restart clears this\n",
                                  encoding="utf-8")
        return {"state": "forgotten"}

    # ---- replay controls ----
    def clock(self, body: dict) -> dict:
        if "as_of" not in body:
            raise Refused(400, "send {as_of}")
        when = self._when(body)
        as_of, purposes = self._current()
        if when == as_of and self.store.exists(self.hh):
            raise Refused(409, "the replay is already on that date")
        return self._refresh(when, purposes)

    def restart(self, body: dict) -> dict:
        try:
            when = date.fromisoformat(str(body.get("as_of") or self.start.isoformat()))
        except ValueError:
            raise Refused(400, "as_of must be YYYY-MM-DD")
        if not (date(2025, 9, 24) <= when <= REPLAY_END):
            raise Refused(400, "that date is outside the recorded consent window")
        self.store.erase(self.hh)
        self.tombstone.unlink(missing_ok=True)
        self.start = when
        self.start_if_needed()
        return self.payload()

    def meta(self) -> dict:
        store_error = None
        try:
            as_of, purposes = self._current()
        except StoreError as err:                    # the operator can still restart the replay
            store_error = type(err).__name__
            as_of, purposes = self.start, frozenset({PURPOSE_AA_PROTECT})
        recorded = self.corpus.sha256.upper() == E8_SHA256
        live = self.source.get("kind") == "live"
        label = gate(f"FETCHED LIVE · {self.source['fetched_at']}") if live else \
            MODE_LABELS["recorded_e8" if recorded else "recorded"]
        return {"contract": CONTRACT_VERSION, "mode": self.mode, "stopped": self.stopped,
                "started": self.store.exists(self.hh), "store_error": store_error,
                "as_of": as_of.isoformat(), "start": self.start.isoformat(), "replay_end": REPLAY_END.isoformat(),
                "corpus_sha256": self.corpus.sha256, "corpus_is_e8": recorded,
                "corpus_label": label, "corpus_source": "live" if live else "recorded",
                "stops": [{"date": d, "hint": h} for d, h in REPLAY_STOPS],
                "purposes_on": sorted(purposes), "switchable": list(SWITCHABLE),
                "lpg": {"scenarios": sorted(lpg.SCENARIOS), "live_enabled": os.environ.get("MIRROR_HUB_LIVE") == "1"}}

    def history(self) -> dict:
        live = self._live_lookups()
        if self.stopped or not self.store.exists(self.hh):
            return {"purpose_history": [], "access_log": [], "standalone_live_lookups": live}
        p = self.payload()
        return {"purpose_history": self.store.purpose_history(self.hh),
                "access_log": p["what_we_know"]["access_log"], "standalone_live_lookups": live}


def options_answer(m: "Mirror", body: dict) -> dict:
    """--options: read-only. The household's saved state and validated payload in; options/1.0 out.
    Nothing is written: not the amount, not an event, not a log line."""
    if m.stopped:
        raise Refused(410, "forgotten")
    st, ev = m._saved()
    if st is None:
        raise Refused(412, "not started")
    payload = m._payload(st, ev)
    try:
        out = build_options(st, payload, body.get("member"), body.get("amount"))
    except OptionsRefused as err:
        raise Refused(400, str(err))
    return validate_options(out, st, payload)                # fails closed (OptionsInvalid -> nothing shown)


class Hub:
    """What the page is showing: the welcome screen (Gate 7), the sealed recording, or a household
    built from data fetched through the app. Only the corpus changes; every rule above still applies."""

    def __init__(self, recorded: Mirror, link: "aa_link.AALink | None" = None):
        self.recorded = self.current = recorded
        self.link = link
        self.entry = "connect" if link else "app"
        self.lock = threading.RLock()
        self._terms = None
        self.prefer_recorded = False                  # the operator chose the recording: a late fetch never takes over
        self.live_session = None                      # the consent that produced the live household (a snapshot)
        self.households_on = False                    # --households: the operator's household switcher
        self._by_household = {}                       # (store root, household id) -> its one Mirror
        self.demo_login = False                       # --demo-login: the phone-entry screen opens a household
        self._logins = {}                             # demo number -> (household id, starts the AA journey?)
        self._last_live = None                        # the household fetched live this session (shown, not preferred away)
        self.options_on = False                       # --options: "Within an amount you set"

    def use(self, m: Mirror):
        with self.lock:
            self.current, self.entry = m, "app"

    def attach_live(self, path: Path, info: dict):
        """Called by the AA link after decrypting: a new household state in its own store folder."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        m = Mirror(str(path), str(self.recorded.root / "live" / stamp), DEFAULT_START,
                   source={"kind": "live", "fetched_at": info["fetched_at"], "matches_e8": info["matches_e8"]})
        m.start_if_needed()
        m.payload()                                    # validated before anyone sees it (fails closed)
        with self.lock:
            if self.prefer_recorded:
                return                                 # kept out of view: the operator is on the recording
            self.live_session = {**self.link.status_unlocked(), "fetched_at": info["fetched_at"]} if self.link else None
            self.current, self.entry = m, "app"
            self._last_live = m                        # --demo-login: signing back in reopens this, no new consent

    def terms(self):
        """The consent terms as the contract states them (they describe the verified anumati_client call)."""
        if self._terms is None:
            try:
                self._terms = self.recorded.payload()["what_we_know"]["consent"]
            except Exception:
                return None
        return self._terms

    def connect_status(self) -> dict:
        if not self.link:
            return {"enabled": False}
        return {**self.link.status(), "entry": self.entry, "terms": self.terms(),
                "showing": self.current.source.get("kind"),
                "live_session": self.live_session if self.current.source.get("kind") == "live" else None}

    def connect_start(self, b: dict) -> dict:
        self._need_link()
        if self.demo_login:                            # --demo-login: only the AA test customer may start a consent
            mobile = b.get("mobile")
            if not isinstance(mobile, str) or not self._logins.get(mobile.strip(), (None, False))[1]:
                raise Refused(403, DEMO_LOGIN_NO_AA)
        with self.lock:
            self.entry, self.prefer_recorded = "connect", False
        return {**self.link.start(b.get("mobile")), "entry": self.entry}

    def connect_reset(self, b: dict) -> dict:
        self._need_link()
        st = self.link.reset()
        with self.lock:
            self.entry = "connect"
        return {**st, "entry": self.entry}

    def use_recorded(self, b: dict) -> dict:
        """Operator fallback. Stops any journey that is still waiting, so nothing takes over later."""
        with self.lock:
            self.prefer_recorded = True
        if self.link:
            try:
                self.link.reset()
            except aa_link.LinkError:
                pass                                   # the fetch is mid-flight: prefer_recorded keeps it out of view
        self.use(self.recorded)
        return {"entry": self.entry, "showing": "recorded"}

    def preflight(self) -> dict:
        self._need_link()
        return self.link.preflight()

    # ---- --households: the operator's household switcher (a demo control, not customer access) ----
    def enable_households(self) -> None:
        with self.lock:
            self.households_on = True
            self._remember(self.recorded)

    def _remember(self, m: Mirror) -> None:
        """One Mirror per (store root, household): two objects must never share a household's folder."""
        self._by_household.setdefault((str(m.root), m.hh), m)

    def _need_households(self):
        if not self.households_on:
            raise Refused(404, "the household switcher is off (start Mirror with --households)")

    def household_label(self, m: Mirror) -> str:
        """Named from the holders as delivered, e.g. 'SELA household'. Never from PAN, never invented."""
        groups = household_groups(m.corpus)
        for g in groups:
            for hh in g["households"]:
                if hh["id"] == m.hh:
                    return hh["label"]
        return "Household"

    def households(self) -> dict:
        self._need_households()
        cur = self.current
        groups = household_groups(cur.corpus)
        unassigned = [f"…{a.masked[-4:]}" for a in cur.corpus.accounts if not a.household_id]
        return {"enabled": True, "current": cur.hh, "source": cur.source.get("kind", "recorded"),
                "groups": groups, "unassigned_accounts": unassigned,
                "unassigned_note": gate("No holder details came with this account, so it belongs to no household.")
                if unassigned else None,
                "caveat": HOUSEHOLDS_CAVEAT}

    def select_household(self, b: dict) -> dict:
        self._need_households()
        hh = b.get("household")
        if self.entry == "connect":
            raise Refused(409, "leave the AA journey screens first (finish the journey, or use the sealed recording)")
        with self.lock:
            cur = self.current
            if not isinstance(hh, str) or hh not in cur.corpus.households():
                raise Refused(400, "that household is not in the data being shown")
            self._remember(cur)                        # e.g. the live SELA household, before leaving it
            m = self._open(cur, hh)
            self.current, self.entry = m, "app"
        return {"current": m.hh, "label": self.household_label(m)}

    def _open(self, src: Mirror, hh: str) -> Mirror:
        """The one Mirror for household `hh` on `src`'s corpus and store root (created on first use)."""
        key = (str(src.root), hh)
        m = self._by_household.get(key)
        if m is None:
            m = Mirror(src.corpus.path, str(src.root), src.first_start, src.mode, source=dict(src.source),
                       household=hh)
            m.start_if_needed()                        # the first refresh happens on this operator/login POST
            if not m.stopped:
                m.payload()                            # validated before anyone sees it (fails closed)
            self._by_household[key] = m
        return m

    # ---- --demo-login: the phone-entry screen opens a sandbox household (DEMO / SANDBOX, not authentication) ----
    def enable_demo_login(self) -> None:
        """Resolve the demo directory against the sealed recording once, at start-up; refuse to start if it
        does not map three numbers to three different households, or if the AA number is not the Gate 7 one."""
        by_tail = {a.masked[-4:]: a.household_id for a in self.recorded.corpus.accounts}
        logins, seen = {}, set()
        for row in DEMO_LOGINS:
            hh = by_tail.get(row["account"])
            if not hh:
                raise SystemExit(f"demo login: no household holds an account ending {row['account']}")
            if hh in seen:
                raise SystemExit("demo login: two demo numbers would open the same household")
            if row["aa"] and hh != self.recorded.hh:
                raise SystemExit("demo login: the AA number must open the household the AA journey shows")
            seen.add(hh)
            logins[row["number"]] = (hh, bool(row["aa"]))
        with self.lock:
            self.demo_login, self._logins, self.entry = True, logins, "login"
            self._remember(self.recorded)

    def enable_options(self) -> None:
        self.options_on = True

    def _need_demo_login(self):
        if not self.demo_login:
            raise Refused(404, "the demo login is off (start Mirror with --demo-login)")

    def login(self, b: dict) -> dict:
        self._need_demo_login()
        mobile = b.get("mobile")
        if not isinstance(mobile, str) or not MOBILE_RX.fullmatch(mobile.strip()):
            raise Refused(400, "enter a 10-digit mobile number")
        row = self._logins.get(mobile.strip())
        mobile = None                                  # used for this lookup only; never stored or logged
        if row is None:
            raise Refused(404, DEMO_LOGIN_UNKNOWN)
        hh, aa = row
        if aa and self._last_live is not None:         # already consented and fetched this session: reopen it,
            with self.lock:                            # no new AA call (the consent is still valid)
                self.current, self.entry, self.prefer_recorded = self._last_live, "app", False
            return {"route": "app", "label": self.household_label(self._last_live)}
        if aa and self.link:                           # the verified Gate 7 journey, exactly as before
            try:
                self.link.reset()                      # a fresh start, as 'Back to welcome' does
            except aa_link.LinkError as err:
                raise Refused(err.status, err.message)
            with self.lock:
                self.entry, self.prefer_recorded = "connect", False
            return {"route": "aa"}
        with self.lock:                                # the sealed recording only: never an AA call
            m = self.recorded if hh == self.recorded.hh else self._open(self.recorded, hh)
            self.current, self.entry = m, "app"
        return {"route": "app", "label": self.household_label(m)}

    def logout(self, b: dict) -> dict:
        """Operator: back to the phone screen. Every household keeps its saved state; a waiting journey stops."""
        self._need_demo_login()
        if self.link:
            try:
                self.link.reset()
            except aa_link.LinkError as err:
                raise Refused(err.status, err.message)
        with self.lock:
            self.entry, self.prefer_recorded = "login", True
        return {"entry": "login"}

    def _need_link(self):
        if not self.link:
            raise aa_link.LinkError(404, "the in-app AA journey is off (start Mirror with --aa-kit)")


def create_app(mirror: "Mirror | Hub", port: int = DEFAULT_PORT, token: str | None = None) -> Flask:
    hub = mirror if isinstance(mirror, Hub) else Hub(mirror)
    app = Flask(__name__, static_folder=None)
    app.config.update(JSON_AS_ASCII=False, JSON_SORT_KEYS=False, MAX_CONTENT_LENGTH=16 * 1024)
    if hasattr(app, "json") and hasattr(app.json, "ensure_ascii"):    # Flask >= 2.2
        app.json.ensure_ascii = False
        app.json.sort_keys = False
    token = token or secrets.token_urlsafe(24)
    allowed_hosts = {f"{HOST}:{port}", f"localhost:{port}", HOST, "localhost"}
    index = (WEB / "index.html").read_text(encoding="utf-8")

    @app.before_request
    def guard():
        if request.host not in allowed_hosts:
            return jsonify(error="unknown host"), 403
        if request.method == "POST":
            sent = request.headers.get("X-Mirror-Token", "")
            if not hmac.compare_digest(sent, token):
                return jsonify(error="missing or wrong launch token"), 403
            if not request.is_json:
                return jsonify(error="JSON only"), 415
        return None

    @app.after_request
    def headers(resp: Response):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def run(name, *args):
        m = hub.current
        if name == "payload" and hub.entry == "connect":
            return jsonify(state="connect"), 200
        if hub.entry == "login":                       # --demo-login: signed out, nothing of any household is served
            if name in ("payload", "history"):
                return jsonify(state="login"), 200
            if request.method == "POST":
                return jsonify(error="sign in first (demo login)"), 409
        fn = getattr(m, name) if isinstance(name, str) else (lambda: name(m))
        with m.lock:
            try:
                return jsonify(fn(*args))
            except Refused as r:
                if r.status == 410:
                    return jsonify(state="forgotten"), 200
                if r.status == 412:
                    return jsonify(state="not_started"), 200
                return jsonify(error=r.message), r.status
            except (PayloadInvalid, UnsafeLanguage) as err:
                # fail closed: nothing that failed validation is ever sent. The operator sees why, here only.
                print(f"[mirror] validation refused the payload: {type(err).__name__}: {str(err)[:160]}", file=sys.stderr)
                return jsonify(error="the engine's output failed validation; nothing is shown"), 500
            except StoreError as err:
                print(f"[mirror] the saved state was refused: {type(err).__name__}", file=sys.stderr)
                return jsonify(error=f"the saved state was refused: {type(err).__name__}. The operator can "
                                     f"restart the replay."), 500

    def body() -> dict:
        b = request.get_json(silent=True)
        if not isinstance(b, dict):
            raise Refused(400, "send a JSON object")
        return b

    @app.route("/", methods=["GET"])
    def root():
        return Response(index.replace("__MIRROR_TOKEN__", token), mimetype="text/html")

    @app.route("/static/<path:name>", methods=["GET"])
    def static_file(name):
        return send_from_directory(WEB, name)

    def meta(cur):
        m = cur.meta()
        m["connect"] = {"enabled": bool(hub.link), "entry": hub.entry}
        if hub.households_on:                          # --households only; without it meta is unchanged
            m["households_enabled"] = True
            m["household"] = {"id": cur.hh, "label": hub.household_label(cur)}
        if hub.demo_login:                             # --demo-login only: a label, never an id or a number
            signed_in = hub.entry != "login"
            m["demo_login"] = {"signed_in": signed_in, "note": DEMO_LOGIN_NOTE}
            if signed_in:
                m["household"] = {**m.get("household", {}), "label": hub.household_label(cur)}
            else:
                m.pop("household", None)
        if hub.options_on:                             # --options only; without it meta is unchanged
            m["options"] = {"reply": OPTIONS_REPLY, "button": OPTIONS_BUTTON, "link": OPTIONS_LINK,
                            "step1": OPTIONS_STEP1}
        if (hub.households_on or hub.demo_login) and cur.hh != hub.recorded.hh:
            m["stops"] = [{"date": s["date"], "hint": ""} for s in m["stops"]]   # the hints tell the SELA story only
        return m

    def crun(fn, *args):
        """The AA journey's endpoints: no household lock (the fetch runs on its own thread)."""
        try:
            return jsonify(fn(*args))
        except aa_link.LinkError as err:
            return jsonify(error=err.message), err.status
        except Refused as r:
            return jsonify(error=r.message), r.status

    app.add_url_rule("/api/payload", "payload", lambda: run("payload"), methods=["GET"])
    app.add_url_rule("/api/meta", "meta", lambda: run(meta), methods=["GET"])
    app.add_url_rule("/api/vocab", "vocab", lambda: run(lambda cur: cur.vocab), methods=["GET"])
    app.add_url_rule("/api/history", "history", lambda: run("history"), methods=["GET"])
    for path, name in (("answers", "answers"), ("facts", "fact"), ("purposes", "purpose"),
                       ("lpg-check", "lpg_check"), ("clock", "clock"), ("replay/restart", "restart")):
        app.add_url_rule(f"/api/{path}", path, (lambda n: lambda: run(lambda cur: getattr(cur, n)(body())))(name),
                         methods=["POST"])
    app.add_url_rule("/api/erase", "erase", lambda: run("erase"), methods=["POST"])
    if hub.options_on:                                 # --options only: read-only, nothing stored
        app.add_url_rule("/api/options", "options", lambda: run(lambda cur: options_answer(cur, body())),
                         methods=["POST"])
    app.add_url_rule("/api/connect", "connect", lambda: crun(hub.connect_status), methods=["GET"])
    app.add_url_rule("/api/connect/preflight", "preflight", lambda: crun(hub.preflight), methods=["GET"])
    for path, fn in (("start", hub.connect_start), ("reset", hub.connect_reset), ("use-recorded", hub.use_recorded)):
        app.add_url_rule(f"/api/connect/{path}", f"connect_{path}", (lambda f: lambda: crun(lambda: f(body())))(fn),
                         methods=["POST"])
    if hub.households_on or hub.demo_login:
        def hrun(fn):
            try:
                return jsonify(fn())
            except Refused as r:
                return jsonify(error=r.message), r.status
            except (PayloadInvalid, UnsafeLanguage) as err:
                print(f"[mirror] validation refused the payload: {type(err).__name__}", file=sys.stderr)
                return jsonify(error="the engine's output failed validation; nothing is shown"), 500
            except StoreError as err:
                print(f"[mirror] the saved state was refused: {type(err).__name__}", file=sys.stderr)
                return jsonify(error=f"the saved state was refused: {type(err).__name__}"), 500
        if hub.households_on:                          # --households only: the operator API (no page UI)
            app.add_url_rule("/api/households", "households", lambda: hrun(hub.households), methods=["GET"])
            app.add_url_rule("/api/households/select", "households_select",
                             lambda: hrun(lambda: hub.select_household(body())), methods=["POST"])
        if hub.demo_login:                             # --demo-login only
            app.add_url_rule("/api/login", "demo_login", lambda: hrun(lambda: hub.login(body())), methods=["POST"])
            app.add_url_rule("/api/logout", "demo_logout", lambda: hrun(lambda: hub.logout(body())), methods=["POST"])

    @app.errorhandler(Exception)
    def unexpected(err):
        from werkzeug.exceptions import HTTPException
        if isinstance(err, HTTPException):
            return jsonify(error=err.name), err.code
        print(f"[mirror] unexpected error: {type(err).__name__}", file=sys.stderr)   # never the request body
        return jsonify(error="unexpected error; nothing was changed"), 500
    return app


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="the sealed corpus (decrypted.json)")
    ap.add_argument("--store", required=True, help="a folder OUTSIDE the git repository")
    ap.add_argument("--start", default=DEFAULT_START.isoformat(), help="first replay date (default 2026-08-28)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--mode", choices=["replay", "live"], default="replay")
    ap.add_argument("--aa-kit", help="Gate 7: the verified aa-kit folder; lets the customer start the Anumati "
                                     "journey from the app (needs the webhook + ngrok running, as for the CLI)")
    ap.add_argument("--callback-health", help="Gate 7 pre-flight: the tunnel's public /health URL (optional)")
    ap.add_argument("--households", action="store_true",
                    help="operator API only: switch between the households in the corpus being shown "
                         "(each keeps its own saved state; not customer login or access control)")
    ap.add_argument("--options", action="store_true",
                    help="'Within an amount you set': Ask Mirror's scheme question opens a neutral options list "
                         "(deterministic, nothing stored, no recommendation)")
    ap.add_argument("--demo-login", action="store_true",
                    help="DEMO / SANDBOX phone entry: three demo numbers open three sandbox households "
                         "(not authentication; only 9999999999 can start the AA journey)")
    a = ap.parse_args()
    if a.port == 8080:
        sys.exit("port 8080 belongs to the AA webhook; the app never shares it")
    mirror = Mirror(a.data, a.store, date.fromisoformat(a.start), a.mode)
    mirror.start_if_needed()
    hub = Hub(mirror)
    if a.aa_kit:
        client, decrypt, captures, jar = aa_link.load_kit(a.aa_kit)
        hub.link = aa_link.AALink(client, decrypt, captures, hub.attach_live, health_url=a.callback_health, jar=jar)
        hub.entry = "connect"
        print("Gate 7 on: the app opens on the welcome screen; the sealed recording stays one click away")
    if a.households:
        hub.enable_households()
        print(f"Households on (operator demo control): {len(mirror.corpus.households())} households in this corpus; "
              f"each keeps its own saved state under the same --store folder")
    if a.options:
        hub.enable_options()
        print("Options on: Ask Mirror's scheme question lists published options within an amount (nothing stored)")
    if a.demo_login:
        hub.enable_demo_login()
        print("Demo login on (DEMO / SANDBOX, not authentication): the app opens on the phone screen; "
              "only the AA test customer can start an AA consent")
    app = create_app(hub, a.port)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)   # method/path only; bodies are never logged
    print(f"Mirror (Gate 6) · replay of {mirror.meta()['corpus_label']} · household {mirror.hh}")
    print(f"open  http://{HOST}:{a.port}   (this laptop only; Ctrl+C to stop)")
    app.run(host=HOST, port=a.port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
