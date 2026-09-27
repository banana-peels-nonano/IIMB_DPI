"""
Counterparty Mirror - the Card contract.

A Card is the only object the product shows a customer. It is structured
data, not prose. Its governance rules are checked when the Card is created,
so an invalid card cannot exist anywhere in the system:

  1. Every evidence item has a class: O, R, I or U.
  2. O (observed) points at transaction IDs - or, for an ABSENCE, at the
     checked window, which must lie inside the account's data window.
  3. R (rule-derived) names a rule@version that exists in the rulebook.
  4. I (inferred) says which evidence it rests on - and may not rest on U.
  5. U (unknowable) must be resolved by the card's question.
  6. The claim (what the card asserts) may only use O, R and I.
  7. A deadline must name its rule, and if the card has any U, must list the
     U items it is conditional on.
  8. No sensitive identifiers (PAN, mobile, DOB, email, address) anywhere.

Gate 4 + 5 additions (nothing above is relaxed):
  9.  O may also point at an external RECORD (a DPI source such as the oil
      company's LPG record via Perfios Hub) instead of transactions. The record
      reference says its source, its id and its MODE: live or simulated. A card
      that rests on a simulated record must say so in its provenance.
  10. A U item may be ANSWERED by the customer (resolved_by "fact:<id>"). It is
      still U - the customer's knowledge, not our observation - so it can never
      be part of the claim and no inference may rest on it. It only gates rules.
  11. A DOOR must carry the unknowable "already covered through another
      account": what we do not see in the connected accounts is never
      treated as "not enrolled".

The evaluator builds Cards; language.py turns them into words.
"""
from __future__ import annotations
import hashlib, re
from dataclasses import dataclass, field
from typing import Optional

from .rules import known_rule_refs, RULEBOOK_VERSION

CLASSES = ("O", "R", "I", "U")
RECORD_MODES = ("live", "simulated")
CARD_TYPES = ("CLOCK", "DOOR", "SUPPRESSION", "QUESTION")
FORBIDDEN_KEYS = {"pan", "dob", "date_of_birth", "email", "address", "mobile", "aadhaar", "nominee"}
PAN_RX = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
MOBILE_RX = re.compile(r"(?<!\d)(?:91)?[6-9]\d{9}(?!\d)")


class CardInvalid(Exception):
    """Raised when a card would break a governance rule. The card is not created."""


@dataclass(frozen=True)
class Evidence:
    id: str
    cls: str
    code: str                       # machine code, e.g. "RETURN_CHARGE_POSTED"
    data: dict = field(default_factory=dict)
    txn_ids: tuple = ()             # O: the transactions observed
    rule: str = ""                  # R: "RULE_ID@version"
    based_on: tuple = ()            # I: evidence ids this inference rests on
    resolved_by: str = ""           # U: id of the question that resolves it, or "fact:<id>" once answered

    @property
    def answered(self) -> bool:
        return self.cls == "U" and self.resolved_by.startswith("fact:")


@dataclass(frozen=True)
class Question:
    id: str
    code: str
    options: tuple
    resolves: tuple                 # U evidence ids this question resolves


@dataclass(frozen=True)
class Deadline:
    date: str
    basis: tuple                    # R evidence ids the date comes from
    conditional_on: tuple = ()      # U evidence ids the date depends on
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Card:
    id: str
    type: str
    code: str                       # which template renders it
    member: Optional[str]
    account: str                    # masked, as delivered
    subject: str                    # obligation or trace id
    as_of: str
    evidence: tuple
    claim: tuple                    # evidence ids the card asserts
    provenance: dict
    deadline: Optional[Deadline] = None
    action: Optional[str] = None
    question: Optional[Question] = None

    def __post_init__(self):
        validate(self)

    def ev(self, eid: str) -> Evidence:
        return next(e for e in self.evidence if e.id == eid)

    def txn_ids(self) -> list:
        return [t for e in self.evidence for t in e.txn_ids]


def card_id(code: str, subject: str, anchor: str) -> str:
    """Stable across replays: the same situation keeps the same id."""
    return "C-" + hashlib.sha256(f"{code}|{subject}|{anchor}".encode()).hexdigest()[:12]


def _strings(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)
    elif obj is not None:
        yield str(obj)


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k).lower()
            yield from _keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _keys(v)


def validate(c: Card) -> None:
    def fail(msg):
        raise CardInvalid(f"{c.code} [{c.subject}]: {msg}")

    if c.type not in CARD_TYPES:
        fail(f"unknown card type {c.type!r}")
    if not c.evidence:
        fail("a card needs evidence")
    ids = [e.id for e in c.evidence]
    if len(ids) != len(set(ids)):
        fail("duplicate evidence ids")
    by_id = {e.id: e for e in c.evidence}
    u_ids = {e.id for e in c.evidence if e.cls == "U"}
    open_u = {e.id for e in c.evidence if e.cls == "U" and not e.answered}
    rules_known = known_rule_refs()
    simulated = False

    for e in c.evidence:
        if e.cls not in CLASSES:
            fail(f"{e.id}: evidence class {e.cls!r} is not O/R/I/U")
        if e.cls == "O":
            absence = e.data.get("absence")
            record = e.data.get("record")
            if not e.txn_ids and not absence and not record:
                fail(f"{e.id}: observed evidence must cite transaction ids, an absence window or a source record")
            if absence and not (absence["from"] <= absence["to"] <= absence["account_data_until"]):
                fail(f"{e.id}: absence claimed outside the account's data window")
            if record:
                if record.get("mode") not in RECORD_MODES or not record.get("source") or not record.get("record_id"):
                    fail(f"{e.id}: a source record must name its source, id and mode (live/simulated)")
                simulated = simulated or record["mode"] == "simulated"
        if e.cls == "R" and e.rule not in rules_known:
            fail(f"{e.id}: rule {e.rule!r} is not in rulebook {RULEBOOK_VERSION}")
        if e.cls == "I":
            if not e.based_on:
                fail(f"{e.id}: an inference must say what it is based on")
            for b in e.based_on:
                if b not in by_id or b == e.id:
                    fail(f"{e.id}: based_on {b!r} is not evidence on this card")
                if b in u_ids:
                    fail(f"{e.id}: an inference may not rest on an unknowable ({b})")
        if e.cls == "U":
            if e.answered:
                if "answered" not in e.data or not e.data.get("stated_on"):
                    fail(f"{e.id}: an answered unknowable must carry the answer and when it was given")
            elif not c.question or e.resolved_by != c.question.id or e.id not in c.question.resolves:
                fail(f"{e.id}: an unknowable must be resolved by this card's question")

    if c.type != "QUESTION" and not c.claim:
        fail("a non-question card must assert something")
    for cid in c.claim:
        if cid not in by_id:
            fail(f"claim references missing evidence {cid!r}")
        if cid in u_ids:
            fail(f"claim may not assert an unknowable ({cid})")

    if c.question:
        for r in c.question.resolves:
            if r not in open_u:
                fail(f"question resolves {r!r}, which is not an open unknowable on this card")
        if not c.question.options:
            fail("a question needs answer options")

    if c.deadline:
        if not c.deadline.basis or any(by_id.get(b) is None or by_id[b].cls != "R"
                                       for b in c.deadline.basis):
            fail("a deadline must be based on rule-derived evidence")
        if u_ids and not c.deadline.conditional_on:
            fail("this card has unknowables, so its deadline must say what it is conditional on")
        for u in c.deadline.conditional_on:
            if u not in u_ids:
                fail(f"deadline conditional_on {u!r} is not an unknowable on this card")

    if c.type == "DOOR" and not any(e.cls == "U" and e.code == "COVERED_ELSEWHERE" for e in c.evidence):
        fail("a door must carry 'already covered through another account' as an unknowable")
    if simulated and c.provenance.get("simulated") is not True:
        fail("this card rests on a simulated record, so its provenance must say simulated")

    for k in ("corpus_sha256", "rulebook_version", "engine", "as_of"):
        if not c.provenance.get(k):
            fail(f"provenance missing {k!r}")

    bad_keys = set(_keys([e.data for e in c.evidence] + [c.provenance])) & FORBIDDEN_KEYS
    if bad_keys:
        fail(f"sensitive field(s) {sorted(bad_keys)} may not appear on a card")
    for s in _strings([[e.data for e in c.evidence], c.provenance,
                       c.deadline.data if c.deadline else {}, c.member]):
        if PAN_RX.search(s) or MOBILE_RX.search(s):
            fail("a PAN or mobile number appears on the card")
