"""Household timeline - the demo spine. Dated, observation-only."""
from household import *
from statistics import median
from collections import defaultdict

def timeline(accs, last_ym):
    ev = []
    for a in accs:
        for s in streams(a.txns, last_ym):
            med = median(s.amounts)
            if s.kind == "CREDIT" and s.status == "STOPPED":
                ev.append((s.months[-1], a.holder, a.masked,
                           "BENEFIT STOPPED" if s.is_benefit else "INCOME STREAM STOPPED",
                           f"Rs{med:,.0f} · '{s.sig}' · last seen {s.months[-1]}"))
            if s.kind == "DEBIT" and s.fixed and s.gaps:
                for g in s.gaps:
                    ev.append((g, a.holder, a.masked, "MANDATE DID NOT APPEAR",
                               f"Rs{med:,.0f} · '{s.sig}'"))
            if s.kind == "DEBIT" and s.fixed and s.status == "STOPPED":
                ev.append((s.months[-1], a.holder, a.masked, "COMMITMENT STOPPED",
                           f"Rs{med:,.0f} · '{s.sig}' · last seen {s.months[-1]}"))
    return sorted(ev)

if __name__ == "__main__":
    accs = parse("decrypted.json")
    last = max(t.ym for a in accs for t in a.txns)
    sela = households(accs)["916999974812"]
    print("HOUSEHOLD 916999974812 — two members, two accounts, 596 transactions\n")
    for a in sela:
        for s in streams(a.txns, last):
            if s.status == "CONTINUING" and s.kind in ("CREDIT", "DEBIT"):
                print(f"  BASELINE  {a.holder:<18} {s.kind:<6} Rs{median(s.amounts):>8,.0f}  "
                      f"{len(s.months)} months unbroken  '{s.sig}'")
    print()
    cur = None
    for ym, holder, acc, kind, detail in timeline(sela, last):
        if ym != cur: print(f"\n  {ym}"); cur = ym
        print(f"      {kind:<24} {holder:<18} {detail}")
