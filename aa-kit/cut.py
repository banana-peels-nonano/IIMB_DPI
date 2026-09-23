import json
from pathlib import Path
from collections import defaultdict
import xml.etree.ElementTree as ET

d = json.loads(Path("captures/decrypted.json").read_text(encoding="utf-8"))
def ns_of(t): return t[1:].split("}")[0] if t.startswith("{") else ""
TARGET = "XXXXXXXX9741"
PAT = ("SALARY", "LIC", "APBS", "ACH/", "NACH", "EMI")

print("=== 9741 MONTHLY CREDIT / DEBIT / NET ===")
for s in d:
    if s["maskedAccNumber"] != TARGET: continue
    r = ET.fromstring(s["data"]); N = {"aa": ns_of(r.tag)}
    m = defaultdict(lambda: [0.0, 0.0, 0, 0])
    for t in r.findall(".//aa:Transaction", N):
        k = (t.get("valueDate") or "")[:7]; a = float(t.get("amount") or 0)
        if t.get("type") == "CREDIT": m[k][0] += a; m[k][2] += 1
        else: m[k][1] += a; m[k][3] += 1
    for k in sorted(m):
        c, db, nc, nd = m[k]
        print(f"  {k}  CR {c:>11,.0f} ({nc:>3})   DR {db:>11,.0f} ({nd:>3})   NET {c-db:>11,.0f}")

print("\n=== RECURRING / STRUCTURED TRANSACTIONS (all accounts) ===")
for s in d:
    r = ET.fromstring(s["data"]); N = {"aa": ns_of(r.tag)}
    for t in r.findall(".//aa:Transaction", N):
        n = (t.get("narration") or "").upper()
        if any(p in n for p in PAT):
            print(f'{s["maskedAccNumber"]} {(t.get("valueDate") or "")[:10]} {t.get("type"):<6} '
                  f'{float(t.get("amount") or 0):>10,.0f}  {n[:70]}')
