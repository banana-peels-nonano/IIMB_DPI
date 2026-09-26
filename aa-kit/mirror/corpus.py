"""
Counterparty Mirror - corpus loader.

Reads a decrypted AA payload (list of FI sessions, XML per account) into
day-level transactions that keep their provenance: txnId, file order,
account, corpus SHA-256.

Governance built in here, not later:
  * MINIMISATION  - only masked account number, holder display name and the
    holder mobile (the AA handle / household join key) are read. PAN, DOB,
    email, address, nominee and CKYC fields are never read, so nothing
    downstream can use them. The mobile itself never leaves this module:
    households are identified by a salted hash.
  * DATA WINDOWS  - every account carries the first/last day it has data for;
    nothing may be called "missing" outside that window.
  * PADDING GUARD - accounts whose txnIds or references repeat are marked
    PADDED and must not be learned from (the mirror refuses and says why).
  * LABEL CALENDAR - narration labels (e.g. 'DEC19', 'ECSRTNCHG211019',
    LIC ref suffix MMYY) are in the source system's calendar. In this sandbox
    the postings were re-dated by +73/+74 months; in production the offset is
    0. It is estimated per account from period labels and exposed, never hidden.
"""
from __future__ import annotations
import hashlib, json, re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7,
          "AUG": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DEC": 12}

PADDED_DUP_SHARE = 0.05       # >5% repeated txnIds or references -> refuse
MIN_TXNS = 20                 # fewer than this -> insufficient to learn


@dataclass(frozen=True)
class Txn:
    txn_id: str
    seq: int                  # position in the FIP file; the only within-day order
    d: date                   # posting date (transactionTimestamp)
    kind: str                 # CREDIT / DEBIT
    amount: float
    narration: str
    reference: str
    mode: str

    @property
    def ym(self) -> str:      # duck-type compatibility with hsl.household streams
        return f"{self.d.year:04d}-{self.d.month:02d}"


@dataclass
class Account:
    masked: str
    member: Optional[str]     # holder display name as delivered
    household_id: Optional[str]
    txns: list = field(default_factory=list)
    window: tuple = (None, None)       # (first day, last day) with data
    quality: str = "OK"                # OK | PADDED | INSUFFICIENT
    quality_reason: str = ""
    label_offset_months: Optional[int] = None
    label_offset_evidence: list = field(default_factory=list)


@dataclass
class Corpus:
    path: str
    sha256: str
    accounts: list

    def households(self) -> dict:
        """Mobile-derived household id only. Never PAN (the sandbox gives a
        father and son the same PAN; the loader does not even read it)."""
        out = {}
        for a in self.accounts:
            if a.household_id:
                out.setdefault(a.household_id, []).append(a)
        return out

    def account(self, suffix: str) -> Account:
        hits = [a for a in self.accounts if a.masked.endswith(suffix)]
        if len(hits) != 1:
            raise KeyError(suffix)
        return hits[0]


def household_id(mobile: str) -> str:
    return "HH-" + hashlib.sha256(("mirror:" + mobile).encode()).hexdigest()[:10]


def _ns(tag):
    return tag[1:].split("}")[0] if tag.startswith("{") else ""


def _d(s: str) -> date:
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def mk(y: int, m: int) -> int:
    return y * 12 + m - 1


def unmk(k: int) -> tuple:
    return k // 12, k % 12 + 1


def add_months(d: date, n: int) -> date:
    y, m = unmk(mk(d.year, d.month) + n)
    return date(y, m, min(d.day, 28))  # corpus days are clamped at 28


# ---------- period labels in narrations (source calendar) ----------
_RX_MON_YY = re.compile(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)\s?(\d{2})\b")
_RX_ACH_MMYY = re.compile(r"^(?:ACH|NACH)/[^/]+/\d{5,}(\d{2})(\d{2})$")


def period_label(narration: str) -> Optional[tuple]:
    """(year, month) a narration says it belongs to, in the source calendar.
    Only 'business' labels count (salary month, loan period, ACH ref MMYY).
    Charge narrations are excluded: charges post weeks after the event."""
    n = (narration or "").upper().strip()
    if any(c in n for c in ("CHG", "CHRG", "CHARGE", "JFEE")):
        return None
    m = _RX_MON_YY.search(n)
    if m:
        return 2000 + int(m.group(2)), MONTHS[m.group(1)]
    m = _RX_ACH_MMYY.match(n)
    if m:
        mm, yy = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12 and 15 <= yy <= 30:
            return 2000 + yy, mm
    return None


def estimate_label_offset(txns) -> tuple:
    """Months between posting date and label period, as the mode over all
    labelled transactions. Returns (offset or None, evidence list)."""
    diffs, ev = Counter(), []
    for t in txns:
        p = period_label(t.narration)
        if p:
            k = mk(t.d.year, t.d.month) - mk(*p)
            diffs[k] += 1
            ev.append((t.txn_id, t.narration, k))
    if not diffs:
        return None, []
    off, n = diffs.most_common(1)[0]
    # labels may post in the period's month or the next one (salary for May
    # paid end-May or early June): accept the mode if it holds for the large
    # majority once +/-1 neighbours are counted as consistent.
    consistent = sum(v for k, v in diffs.items() if abs(k - off) <= 1)
    if consistent / sum(diffs.values()) < 0.8:
        return None, ev
    return off, ev


# ---------- loader ----------
def load(path: str) -> Corpus:
    p = Path(path).resolve(strict=True)
    raw = p.read_bytes()
    sessions = json.loads(raw.decode("utf-8"))
    accounts = []
    for s in sessions:
        r = ET.fromstring(s["data"])
        N = {"aa": _ns(r.tag)}
        h = r.find(".//aa:Holder", N)
        # MINIMISATION: exactly two holder attributes are read. Nothing else.
        name = h.get("name") if h is not None else None
        mobile = h.get("mobile") if h is not None else None
        a = Account(s["maskedAccNumber"], name, household_id(mobile) if mobile else None)
        for i, t in enumerate(r.findall(".//aa:Transaction", N)):
            ts = t.get("transactionTimestamp") or t.get("valueDate") or ""
            if len(ts) < 10:
                continue
            a.txns.append(Txn(t.get("txnId") or f"noid-{i}", i, _d(ts),
                              (t.get("type") or "").upper(), float(t.get("amount") or 0),
                              t.get("narration") or "", t.get("reference") or "",
                              t.get("mode") or ""))
        a.txns.sort(key=lambda x: (x.d, x.seq))
        if a.txns:
            a.window = (a.txns[0].d, a.txns[-1].d)
        _assess_quality(a)
        a.label_offset_months, a.label_offset_evidence = estimate_label_offset(a.txns)
        accounts.append(a)
    return Corpus(str(p), hashlib.sha256(raw).hexdigest().upper(), accounts)


def _assess_quality(a: Account) -> None:
    n = len(a.txns)
    if n < MIN_TXNS:
        a.quality, a.quality_reason = "INSUFFICIENT", f"only {n} transaction(s)"
        return
    dup_ids = n - len({t.txn_id for t in a.txns})
    refs = [t.reference for t in a.txns if t.reference]
    dup_refs = len(refs) - len(set(refs))
    share = max(dup_ids, dup_refs) / n
    if share > PADDED_DUP_SHARE:
        a.quality = "PADDED"
        a.quality_reason = (f"{dup_ids} of {n} transaction IDs and {dup_refs} references "
                            f"repeat; the data looks templated, so we will not infer "
                            f"anything from this account")


def as_of(txns, cutoff: date) -> list:
    """Replay: what the mirror would have seen on `cutoff` (inclusive)."""
    return [t for t in txns if t.d <= cutoff]


def provenance(corpus: Corpus, acc: Account, txns) -> dict:
    return {"source": "AA", "fip": "ACME-FIP (sandbox)", "account": acc.masked,
            "corpus_sha256": corpus.sha256, "txn_ids": [t.txn_id for t in txns]}
