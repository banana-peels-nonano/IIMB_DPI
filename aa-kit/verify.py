import json
from pathlib import Path
from collections import defaultdict
import xml.etree.ElementTree as ET
d = json.loads(Path("captures/decrypted.json").read_text(encoding="utf-8"))
def ns_of(t): return t[1:].split("}")[0] if t.startswith("{") else ""

print("=== APBS credits by month (subsidy continuity) ===")
print("=== INDUSIND EMI by month (obligation continuity) ===")
seen = defaultdict(list)
for s in d:
    r = ET.fromstring(s["data"]); N = {"aa": ns_of(r.tag)}
    for t in r.findall(".//aa:Transaction", N):
        n = (t.get("narration") or "").upper(); m = (t.get("valueDate") or "")[:7]
        if "APBS" in n: seen["APBS " + s["maskedAccNumber"]].append((m, t.get("amount")))
        if "INDUSIND" in n: seen["EMI  " + s["maskedAccNumber"]].append((m, t.get("amount")))
for k in sorted(seen):
    print(f"\n{k}")
    for m, a in sorted(seen[k]): print(f"   {m}  {float(a):>10,.0f}")

print("\n=== 9741 CREDIT SOURCES (what IS the income?) ===")
for s in d:
    if s["maskedAccNumber"] != "XXXXXXXX9741": continue
    r = ET.fromstring(s["data"]); N = {"aa": ns_of(r.tag)}
    for t in r.findall(".//aa:Transaction", N):
        if t.get("type") == "CREDIT":
            print(f'   {(t.get("valueDate") or "")[:10]} {float(t.get("amount")):>10,.0f}  {(t.get("narration") or "")[:66]}')
