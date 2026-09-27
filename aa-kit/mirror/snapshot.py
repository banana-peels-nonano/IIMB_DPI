"""
Counterparty Mirror - Household snapshot: the evaluated Financial Reality of one
household at one explicit date.

A snapshot is the unit the time axis compares. It bundles, per member account:
  * what Batch 1a learned (commitments, regular credit streams, charge traces)
  * the Batch 1b cards (already validated)
  * the data window (so nothing is claimed beyond it)
  * the transactions visible at as_of (kept in memory for the Horizon's
    liquidity maths; they are NEVER copied into the app payload)
Accounts whose data is refused (padded / too thin) are carried with their
refusal reason and nothing else.

Deterministic: the same corpus + household + as_of + purposes gives the same
snapshot. No system clock, no writes.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import date

from .corpus import Corpus, as_of as visible
from .evaluate import evaluate, ENGINE
from .learn import learn_obligations, learn_income
from .rules import RULEBOOK_VERSION, PURPOSE_AA_PROTECT
from .traces import classify_charges, link_returns

# Narration markers of government-backed protections / transfers. OBSERVED only:
# a marker says a debit or credit happened, never that anyone is covered or eligible.
# APBS credits name the paying scheme after the slash (e.g. "APBS/IOC"): the oil
# companies pay the PAHAL LPG subsidy. Only the payer code is kept, never the narration.
OMC_PAYERS = {"IOC": "Indian Oil", "HPCL": "HP Gas", "BPCL": "Bharat Gas"}

PROTECTION_MARKERS = {
    "PMSBY": "Pradhan Mantri Suraksha Bima Yojana premium",
    "PMJJBY": "Pradhan Mantri Jeevan Jyoti Bima Yojana premium",
    "APY": "Atal Pension Yojana contribution",
    "APBS": "government transfer via Aadhaar Payment Bridge",
}


@dataclass(frozen=True)
class MemberState:
    member_key: str               # "M1", "M2" ... stable order by masked account
    display_name: str
    account: str                  # masked, as delivered
    quality: str                  # OK | PADDED | INSUFFICIENT
    quality_reason: str
    data_from: date | None
    data_until: date | None       # min(account's last data day, as_of)
    obligations: tuple = ()
    income: tuple = ()
    other_credit_sources: int = 0
    traces: tuple = ()
    protections: tuple = ()       # observed marker rows: dicts with txn ids
    txns: tuple = ()              # in memory only; never serialised


@dataclass(frozen=True)
class Snapshot:
    household_id: str
    as_of: date
    corpus_sha256: str
    rulebook_version: str
    engine: str
    purposes: frozenset
    members: tuple
    cards: tuple                  # validated Card objects, all members

    def member(self, account: str) -> MemberState:
        return next(m for m in self.members if m.account == account)


def display_name(raw: str | None) -> str:
    if not raw:
        return "Account holder"
    s = re.sub(r"^(MR|MRS|MS|SHRI|SMT)\.?\s*", "", raw.strip(), flags=re.I)
    return " ".join(w.capitalize() for w in s.split())


def _protections(txns) -> tuple:
    rows = []
    for t in txns:
        up = t.narration.upper()
        for marker, label in PROTECTION_MARKERS.items():
            if re.search(rf"\b{marker}\b", up):
                payer = re.search(r"\bAPBS/(IOC|HPCL|BPCL)\b", up) if marker == "APBS" else None
                rows.append({"marker": marker, "label": label, "direction": t.kind,
                             "date": t.d.isoformat(), "amount": t.amount, "txn_id": t.txn_id,
                             "payer": payer.group(1) if payer else None})
    return tuple(rows)


def take_snapshot(corpus: Corpus, household_id: str, as_of_date: date,
                  purposes=frozenset({PURPOSE_AA_PROTECT})) -> Snapshot:
    accounts = sorted(corpus.households()[household_id], key=lambda a: a.masked)
    members, cards = [], []
    for i, acc in enumerate(accounts, start=1):
        key, name = f"M{i}", display_name(acc.member)
        if acc.quality != "OK":
            members.append(MemberState(key, name, acc.masked, acc.quality, acc.quality_reason,
                                       acc.window[0], acc.window[1]))
            continue
        txns = visible(acc.txns, as_of_date)
        obs = learn_obligations(acc, txns, as_of_date)
        income, other = learn_income(acc, txns, as_of_date)
        traces = link_returns(acc, classify_charges(acc, txns), obs, txns)
        members.append(MemberState(
            key, name, acc.masked, "OK", "", acc.window[0], min(acc.window[1], as_of_date),
            tuple(obs), tuple(income), other, tuple(traces), _protections(txns), tuple(txns)))
        cards.extend(evaluate(corpus, acc, as_of_date, purposes=purposes))
    return Snapshot(household_id, as_of_date, corpus.sha256, RULEBOOK_VERSION, ENGINE,
                    frozenset(purposes), tuple(members), tuple(cards))
