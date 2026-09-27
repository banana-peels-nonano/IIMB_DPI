"""
Counterparty Mirror - Batch 1c persistence demo (developer verification path).

Each session is a SEPARATE Python process, like separate app sessions. State survives only
through the store on disk.

    python -m mirror.demo_batch1c --data <decrypted.json> --store <dir outside the repo> all
      (runs session1 -> session2 -> session3 -> session4 as four processes and compares them)

    or one at a time:
    python -m mirror.demo_batch1c --data <path> --store <dir> session1 --fresh
    python -m mirror.demo_batch1c --data <path> --store <dir> session2 --expect <digest printed by session1>
    python -m mirror.demo_batch1c --data <path> --store <dir> session3
    python -m mirror.demo_batch1c --data <path> --store <dir> session4

  session1  8-13 Sep: protections ON, answers, LPG check ON + SIMULATED record, a correction. Saves.
  session2  reload -> the SAME contract (digest); refresh on 14 Sep re-sending every old answer and
            the old record -> no new facts, corrections or log entries. Saves.
  session3  15 Sep: government protections switched OFF. Saves.
  session4  reload -> still forgotten, nothing forgotten is on disk; switch ON again with the old
            answers re-sent -> they are NOT re-applied.
The store refuses to live inside a git repository (it holds the household's answers).
"""
import argparse, hashlib, json, subprocess, sys
from datetime import date
from pathlib import Path

from .corpus import load
from .events import Answer
from .facts import FactStatement
from .briefing import since_last_time
from .contract import build_payload, validate_payload
from .rules import PURPOSE_AA_PROTECT, PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG
from .sources import lpg
from .store import JsonFileStore, refresh

AA = frozenset({PURPOSE_AA_PROTECT})
GOV = AA | {PURPOSE_GOV_PROTECT}
DPI = GOV | {PURPOSE_DPI_LPG}
FAILS = []


def check(ok, what):
    print(f"   {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        FAILS.append(what)


def digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def card(st, code, account=None):
    return next((c for c, _ in st.open_cards if c.code == code and (account is None or c.account == account)), None)


def inside_git(p: Path) -> bool:
    return any((q / ".git").exists() for q in [p, *p.parents])


class App:
    def __init__(self, data, store):
        self.c = load(data)
        self.hh = self.c.account("9741").household_id
        self.john, self.kiran = self.c.account("9741").masked, self.c.account("9648").masked
        self.store = JsonFileStore(store)

    def refresh(self, d, purposes, answers=(), records=(), label=""):
        st, ev = refresh(self.store, self.c, self.hh, d, purposes, answers, records)
        p = validate_payload(build_payload(st, ev))
        print(f"  {d} · {label}")
        for line in since_last_time(st, ev).lines:
            if "LIC OF INDIA" not in line.text:
                print(f"      {line.kind:<9} {line.text}")
        return st, ev, p

    def reload(self):
        st, ev = self.store.load(self.c, self.hh)
        return st, ev, validate_payload(build_payload(st, ev))

    def summary(self, st, p):
        print(f"    state as of {st.as_of} (since {st.since}) · purposes on: {sorted(st.snapshot.purposes)}")
        print(f"    facts: {[(f.code, f.value) for f in st.hfacts]}")
        print(f"    corrections: {[(c.code, c.old_value, c.new_value) for c in st.corrections]}")
        print(f"    records: {[(r.mode, r.status, r.join) for r in st.records]} · "
              f"access log: {[(e['what'], e.get('outcome')) for e in st.access_log]}")
        print(f"    closures: {len(st.closed)} · open cards: {len(st.open_cards)}")
        print(f"    CONTRACT DIGEST {digest(p)}")


def session1(app, fresh):
    print("SESSION 1 — first app session: answers, LPG record (SIMULATED), a correction; saved after every refresh")
    if app.store.exists(app.hh):
        if not fresh:
            sys.exit("a saved state already exists; pass --fresh to erase it and start again")
        app.store.erase(app.hh)
    st, _, _ = app.refresh(date(2026, 9, 8), GOV, label="protections switched ON")
    a = [Answer(card(st, "AGE_BAND_QUESTION", app.john).id, "41_50", date(2026, 9, 9)),
         Answer(card(st, "AGE_BAND_QUESTION", app.kiran).id, "18_40", date(2026, 9, 9))]
    st, _, _ = app.refresh(date(2026, 9, 9), GOV, a, label="two age bands")
    a.append(Answer(card(st, "TAXPAYER_QUESTION", app.kiran).id, "no", date(2026, 9, 10)))
    app.refresh(date(2026, 9, 10), GOV, a, label="Kiran: not a taxpayer")
    r = [lpg.simulated("rerouted", requested_on=date(2026, 9, 11), household_id=app.hh, account=app.kiran,
                       purposes=DPI)]
    print(f"      (LPG: \"{lpg.DISCLOSURE}\")")
    st, _, _ = app.refresh(date(2026, 9, 11), DPI, a, r, label="LPG check ON, SIMULATED record")
    a.append(Answer(card(st, "LPG_SUBSIDY_ROUTING").id, "old_not_in_use", date(2026, 9, 12)))
    app.refresh(date(2026, 9, 12), DPI, a, r, label="Kiran: that account is old")
    a.append(FactStatement(app.john, "AGE_BAND", "51_70", date(2026, 9, 13)))
    st, ev, p = app.refresh(date(2026, 9, 13), DPI, a, r, label="John corrects his age band")
    print("\n  saved. What session 2 should see:")
    app.summary(st, p)


def session2(app, expect):
    print("SESSION 2 — a new process: reload, then refresh re-sending everything ever sent")
    st, ev, p = app.reload()
    app.summary(st, p)
    if expect:
        check(digest(p) == expect, "reloaded contract is identical to session 1's (same digest)")
    check([(r.mode, r.status) for r in st.records] == [("simulated", "ok")]
          and "SIMULATED" in next(v for v in p["now"]["resolved"] if v.get("simulated"))["title"]
          and p["what_we_know"]["dpi_integrations"][0]["disclosure"] == lpg.DISCLOSURE,
          "the LPG record is still SIMULATED, with the live-vs-simulated disclosure")
    everything = [FactStatement(f.account, f.code, f.value, f.stated_on, f.scheme) for f in st.hfacts] + \
                 [FactStatement(app.john, "AGE_BAND", "41_50", date(2026, 9, 9))]
    old_record = [lpg.simulated("rerouted", requested_on=date(2026, 9, 11), household_id=app.hh,
                                account=app.kiran, purposes=DPI)]
    n_corr, n_log = len(st.corrections), len(st.access_log)
    st, ev, p = app.refresh(date(2026, 9, 14), DPI, everything, old_record, label="refresh; old answers re-sent")
    check(not [e for e in ev if e.kind.startswith("FACT_")] and len(st.corrections) == n_corr
          and len(st.access_log) == n_log, "no FACT events, no new corrections, no duplicate log entries")


def session3(app):
    print("SESSION 3 — the customer switches government protections OFF")
    st, _, p = app.refresh(date(2026, 9, 15), AA, label="protections OFF (the LPG check goes with it)")
    app.summary(st, p)


def session4(app):
    print("SESSION 4 — a new process: is the forgetting durable?")
    st, _, p = app.reload()
    app.summary(st, p)
    text = (app.store.root / app.hh / "state.json").read_text(encoding="utf-8")
    check(st.hfacts == () and st.records == () and st.corrections == ()
          and not any(x in text for x in ('"41_50"', '"51_70"', '"18_40"', "4471", "Sample Bank")),
          "answers, corrections and the record are gone — from state AND from the file on disk")
    check([e["what"] for e in st.access_log][-2:] == ["forgotten", "forgotten"],
          "the access log still shows the lookup happened and that it was forgotten")
    resend = [FactStatement(app.john, "AGE_BAND", "51_70", date(2026, 9, 13)),
              FactStatement(app.kiran, "AGE_BAND", "18_40", date(2026, 9, 9))]
    st, _, _ = app.refresh(date(2026, 9, 16), GOV, resend, label="switched ON again; old answers re-sent")
    check(st.hfacts == () and card(st, "AGE_BAND_QUESTION") is not None,
          "forgotten answers are not re-applied: the age questions are asked again")
    print(f"\n  purpose history: {app.store.purpose_history(app.hh)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--store", required=True, help="a folder OUTSIDE the git repository")
    ap.add_argument("session", choices=["session1", "session2", "session3", "session4", "all"])
    ap.add_argument("--fresh", action="store_true", help="session1: erase a previous saved state first")
    ap.add_argument("--expect", help="session2: the CONTRACT DIGEST printed at the end of session1")
    a = ap.parse_args()
    store = Path(a.store).resolve()
    if inside_git(store):
        sys.exit(f"refusing: {store} is inside a git repository; saved answers must never be committed")
    if a.session == "all":
        base = [sys.executable, "-m", "mirror.demo_batch1c", "--data", a.data, "--store", str(store)]
        out = subprocess.run(base + ["session1", "--fresh"], capture_output=True, text=True, encoding="utf-8")
        print(out.stdout, out.stderr, sep="")
        dig = [x.split()[-1] for x in out.stdout.splitlines() if "CONTRACT DIGEST" in x][-1]
        codes = [out.returncode]
        for s, extra in (("session2", ["--expect", dig]), ("session3", []), ("session4", [])):
            out = subprocess.run(base + [s] + extra, capture_output=True, text=True, encoding="utf-8")
            print("=" * 100)
            print(out.stdout, out.stderr, sep="")
            codes.append(out.returncode)
        ok = not any(codes)
        print("ALL SESSIONS PASSED" if ok else f"SESSION FAILURES (exit codes {codes})")
        sys.exit(0 if ok else 1)
    app = App(a.data, store)
    {"session1": lambda: session1(app, a.fresh), "session2": lambda: session2(app, a.expect),
     "session3": lambda: session3(app), "session4": lambda: session4(app)}[a.session]()
    print("\n" + ("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} CHECK(S) FAILED: {FAILS}"))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
