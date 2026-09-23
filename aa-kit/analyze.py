import json
from pathlib import Path
from collections import defaultdict, Counter
import xml.etree.ElementTree as ET

d = json.loads(Path("captures/decrypted.json").read_text(encoding="utf-8"))
def ns_of(t): return t[1:].split("}")[0] if t.startswith("{") else ""

print("=== ACCOUNTS ===")
print(f'{"ACCOUNT":<14}{"ROOT":<10}{"SCHEMA":<18}{"SUBTYPE":<10}{"BALANCE":>16}{"TXNS":>7}')
grand = 0
monthly = defaultdict(lambda: defaultdict(float))
narr = Counter()
for s in d:
    r = ET.fromstring(s["data"]); ns = ns_of(r.tag); N = {"aa": ns}
    sm = r.find("aa:Summary", N); tx = r.findall(".//aa:Transaction", N)
    grand += len(tx)
    acc = s["maskedAccNumber"]
    bal = sm.get("currentBalance") if sm is not None else None
    print(f'{acc:<14}{r.tag.split("}")[-1]:<10}{ns.rsplit("/",1)[-1]:<18}'
          f'{(sm.get("accountSubType") if sm is not None else "?"):<10}'
          f'{(float(bal) if bal else 0):>16,.2f}{len(tx):>7}')
    for t in tx:
        vd = (t.get("valueDate") or "")[:7]
        if t.get("type") == "CREDIT":
            monthly[acc][vd] += float(t.get("amount") or 0)
        w = (t.get("narration") or "").upper().split()
        if w: narr[w[0]] += 1
print(f"\nTOTAL TRANSACTIONS: {grand}")

print("\n=== MONTHLY CREDIT TOTALS (salary hunt) ===")
months = sorted({m for a in monthly for m in monthly[a]})
for acc in monthly:
    print(f"\n{acc}")
    for m in months:
        v = monthly[acc].get(m, 0)
        if v: print(f"   {m}  {v:>14,.2f}")

print("\n=== TOP NARRATION PREFIXES ===")
for k, v in narr.most_common(25): print(f"   {v:>5}  {k}")
