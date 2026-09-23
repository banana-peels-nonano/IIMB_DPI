"""
Household Shock Ledger - core engine.

Hard design rule (inherited): NEVER emit a diagnosis. Emit dated observations,
caveats, and a check the customer can perform. No accusation vocabulary.
"""
from __future__ import annotations
import re, json
from dataclasses import dataclass, field
from statistics import median
from collections import defaultdict
from typing import Optional
import xml.etree.ElementTree as ET

MONTHS = {"JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","SEPT","OCT","NOV","DEC"}

# Statutory / government transfer markers. A stream carrying one of these is
# material regardless of amount: losing an entitlement usually signals a broken
# linkage (KYC, account seeding) that can affect other entitlements too.
BENEFIT_MARKERS = ("APBS", "PMSBY", "PMJJBY", "PAHAL", "NREGA", "DBT")

MATERIAL_MEDIAN = 1000.0     # rupees
MATERIAL_ANNUAL = 6000.0

# ---------- model ----------
@dataclass
class Txn:
    ym: str; day: int; amount: float; kind: str; narration: str

@dataclass
class Account:
    masked: str; holder: Optional[str]; mobile: Optional[str]
    subtype: Optional[str]; txns: list = field(default_factory=list)

@dataclass
class Stream:
    sig: str; kind: str; months: list; amounts: list; n: int
    fixed: bool; status: str; gaps: list; is_benefit: bool

@dataclass
class Finding:
    account: str; holder: Optional[str]; kind: str; stream: Stream
    observation: str; caveats: list; suggested_check: str

# ---------- parsing ----------
def _ns(tag): return tag[1:].split("}")[0] if tag.startswith("{") else ""

def parse(path) -> list[Account]:
    out = []
    for s in json.load(open(path, encoding="utf-8")):
        r = ET.fromstring(s["data"]); N = {"aa": _ns(r.tag)}
        h = r.find(".//aa:Holder", N); sm = r.find("aa:Summary", N)
        a = Account(s["maskedAccNumber"], h.get("name") if h is not None else None,
                    h.get("mobile") if h is not None else None,
                    sm.get("accountSubType") if sm is not None else None)
        for t in r.findall(".//aa:Transaction", N):
            vd = t.get("valueDate") or ""
            if len(vd) >= 10:
                a.txns.append(Txn(vd[:7], int(vd[8:10]), float(t.get("amount") or 0),
                                  t.get("type") or "", t.get("narration") or ""))
        out.append(a)
    return out

def households(accounts) -> dict:
    """Group by shared mobile. NEVER by PAN: in this sandbox a father and son
    share a PAN, which is impossible in reality and an invalid join key."""
    g = defaultdict(list)
    for a in accounts:
        if a.mobile: g[a.mobile].append(a)
    return dict(g)

# ---------- streams ----------
def signature(narration: str) -> str:
    toks = re.split(r"[^A-Za-z0-9]+", (narration or "").upper())
    keep = [t for t in toks if t and not any(c.isdigit() for c in t) and t not in MONTHS]
    return " ".join(keep[:5])

def _mk(ym): y, m = ym.split("-"); return int(y) * 12 + int(m) - 1
def _unmk(k): return f"{k//12:04d}-{k%12+1:02d}"

def _is_fixed(amts):
    m = median(amts)
    return m > 0 and all(abs(a - m) <= max(1.0, 0.03 * m) for a in amts)

def _clusters(ts, tol=0.08):
    out = []
    for t in sorted(ts, key=lambda x: x.amount):
        for c in out:
            m = median([x.amount for x in c])
            if m > 0 and abs(t.amount - m) <= max(1.0, tol * m):
                c.append(t); break
        else: out.append([t])
    return out

def _material(amts, months, is_benefit):
    if is_benefit: return True                      # entitlements always matter
    med = median(amts)
    return med >= MATERIAL_MEDIAN or sum(amts) >= MATERIAL_ANNUAL

def _mkstream(sig, kind, ts, last_ym, stop_tol):
    months = sorted({t.ym for t in ts}); amts = [t.amount for t in ts]
    span = range(_mk(months[0]), _mk(months[-1]) + 1)
    present = {_mk(m) for m in months}
    gaps = [_unmk(k) for k in span if k not in present]
    tail = _mk(last_ym) - _mk(months[-1])
    status = "STOPPED" if tail >= stop_tol else ("GAPPED" if gaps else "CONTINUING")
    ben = any(b in sig for b in BENEFIT_MARKERS)
    return Stream(sig, kind, months, amts, len(ts), _is_fixed(amts), status, gaps, ben)

def _merge_groups(g, tol=0.15):
    """Merge signature groups that are one real stream fragmented by narration
    drift ('By Sal Mar 20' -> 'ICSP/By Sal Apr 20'). Same kind, median amounts
    within tol, and NO overlapping months - overlap means genuinely distinct.
    Runs BEFORE the min-months filter, or short fragments are discarded first."""
    keys = sorted(g, key=lambda k: -median([t.amount for t in g[k]]))
    merged, used = {}, set()
    for i, ka in enumerate(keys):
        if ka in used: continue
        ts = list(g[ka]); months = {t.ym for t in ts}; sigs = [ka[1]]
        for kb in keys[i + 1:]:
            if kb in used or kb[0] != ka[0]: continue
            ma, mb = median([t.amount for t in ts]), median([t.amount for t in g[kb]])
            if ma <= 0 or abs(ma - mb) > tol * ma: continue
            if months & {t.ym for t in g[kb]}: continue
            # signatures must actually look like the same payer/payee: share at
            # least two tokens, or one be a subset of the other. Amount proximity
            # alone merges unrelated things (a person transfer and a rail booking).
            sa, sb = set(ka[1].split()), set(kb[1].split())
            if len(sa & sb) < 2 and not (sa and sb and (sa <= sb or sb <= sa)): continue
            ts += g[kb]; months |= {t.ym for t in g[kb]}
            sigs.append(kb[1]); used.add(kb)
        merged[(ka[0], min(sigs, key=len))] = ts
    return merged

def streams(txns, last_ym, min_months=4, stop_tol=2) -> list[Stream]:
    g = defaultdict(list)
    for t in txns: g[(t.kind, signature(t.narration))].append(t)
    out = []
    for (kind, sig), grp in _merge_groups(dict(g)).items():
        # DEBIT mandates are fixed-amount, so co-signature mandates split by amount.
        # CREDIT streams (salary, benefits) vary legitimately - never split them.
        groups = _clusters(grp) if kind == "DEBIT" else [grp]
        emitted = False
        for ts in groups:
            if len({t.ym for t in ts}) < min_months: continue
            s = _mkstream(sig, kind, ts, last_ym, stop_tol)
            if not _material(s.amounts, s.months, s.is_benefit): continue
            out.append(s); emitted = True
        if not emitted and kind == "DEBIT" and len({t.ym for t in grp}) >= min_months:
            s = _mkstream(sig, kind, grp, last_ym, stop_tol)
            if _material(s.amounts, s.months, s.is_benefit): out.append(s)
    return sorted(out, key=lambda s: -median(s.amounts))

# ---------- findings ----------
def findings_for(acc: Account, last_ym: str) -> list[Finding]:
    res = []
    for s in streams(acc.txns, last_ym):
        first, last, med = s.months[0], s.months[-1], median(s.amounts)
        if s.kind == "CREDIT" and s.status == "STOPPED":
            res.append(Finding(acc.masked, acc.holder,
                "BENEFIT_STOPPED" if s.is_benefit else "INCOME_STREAM_STOPPED", s,
                f"Credits matching '{s.sig}' arrived in {len(s.months)} months from "
                f"{first} to {last}, and have not appeared since.",
                ["A stream can resume, move to another account, or be renamed by the "
                 "payer. Absence is not proof that an entitlement ended."],
                "If this is a government benefit, check with your bank that your account "
                "details and KYC are current." if s.is_benefit else
                "Check whether this payer has changed account or stopped paying."))
        elif s.kind == "DEBIT" and s.fixed and s.status == "GAPPED":
            res.append(Finding(acc.masked, acc.holder, "MANDATE_GAPPED", s,
                f"A recurring fixed debit of Rs{med:,.0f} matching '{s.sig}' did not "
                f"appear in {', '.join(s.gaps)}.",
                ["A missing debit can mean a payment holiday, a changed account, a "
                 "restructured agreement, or a missed payment. We cannot tell which."],
                "Contact the counterparty to confirm the account is in good standing."))
        elif s.kind == "DEBIT" and s.fixed and s.status == "STOPPED":
            res.append(Finding(acc.masked, acc.holder, "COMMITMENT_STOPPED", s,
                f"A recurring fixed debit of Rs{med:,.0f} matching '{s.sig}' ran from "
                f"{first} to {last} and has not appeared since.",
                ["This may mean the agreement ended, was settled, moved account, or "
                 "that payments stopped. We cannot tell which."],
                "Confirm with the counterparty whether this agreement is closed."))
        elif s.kind == "DEBIT" and s.fixed and s.status == "CONTINUING":
            res.append(Finding(acc.masked, acc.holder, "COMMITMENT_CONTINUING", s,
                f"A recurring fixed debit of Rs{med:,.0f} matching '{s.sig}' has "
                f"continued every month from {first} to {last}.", [],
                "Confirm this commitment still matches the income actually arriving."))
    return res

def monthly_net(acc: Account) -> dict:
    m = defaultdict(lambda: [0.0, 0.0])
    for t in acc.txns:
        m[t.ym][0 if t.kind == "CREDIT" else 1] += t.amount
    return {k: (v[0], v[1], v[0] - v[1]) for k, v in sorted(m.items())}
