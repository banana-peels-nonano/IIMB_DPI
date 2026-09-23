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
    import argparse, hashlib, pathlib
    ap = argparse.ArgumentParser(description="Household timeline - observation-only demo spine")
    ap.add_argument("--data", required=True, help="path to decrypted.json; never read from the working directory")
    args = ap.parse_args()
    data = pathlib.Path(args.data).resolve(strict=True)
    print(f"INPUT   {data}")
    print(f"SHA256  {hashlib.sha256(data.read_bytes()).hexdigest().upper()}\n")
    accs = parse(str(data))
    last = max(t.ym for a in accs for t in a.txns)
    sela = households(accs)["916999974812"]
    n_members = len({a.holder for a in sela})
    n_txns = sum(len(a.txns) for a in sela)
    print(f"HOUSEHOLD 916999974812 \u2014 {n_members} members, {len(sela)} accounts, {n_txns} transactions\n")
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
