"""
Counterparty Mirror - Gate 4 + 5 developer verification path (read-only).

    python -m mirror.demo_gate45 --data <sealed decrypted.json>
    python -m mirror.demo_gate45 --data <path> --json-out <file outside the repo>

Replays the SELA household through the same time axis as Gate 2 + 3, now with
the government-protections purpose and one DPI record (the oil company's LPG
record via Perfios Hub, SIMULATED - the sandbox household has no real LPG ID):

     7 Sep  AA only                          -> no protection checks at all
     8 Sep  "Check government protections" ON -> two age-band questions, the LPG question,
                                                 Ujjwala explained-not-shown (quiet)
     9 Sep  John 41-50, Kiran 18-40           -> ONE line each: several rules re-read at once
    10 Sep  Kiran: never an income-tax payer  -> APY becomes worth checking
    11 Sep  LPG record check ON, record arrives (SIMULATED) -> the LPG question is refined
            (and, as a side branch, what a FAILED lookup does: nothing changes, question stays)
    12 Sep  Kiran: "that account is old"      -> closed, with the re-seeding action
    13 Sep  John corrects his band to 51-70   -> PMJJBY withdrawn (not "resolved"), correction kept
    14 Sep  protections switched OFF          -> answers, record and closures forgotten; logged
Exit code 1 if any check fails. The real demo is the app rendering these payloads.
"""
import argparse, json, sys
from datetime import date

from .corpus import load
from .snapshot import take_snapshot
from .events import advance, initial, Answer
from .facts import FactStatement
from .briefing import since_last_time
from .contract import build_payload, validate_payload
from .rules import PURPOSE_AA_PROTECT, PURPOSE_GOV_PROTECT, PURPOSE_DPI_LPG
from .sources import lpg

AA = frozenset({PURPOSE_AA_PROTECT})
GOV = AA | {PURPOSE_GOV_PROTECT}
DPI = GOV | {PURPOSE_DPI_LPG}
FAILS = []


def check(ok: bool, what: str):
    print(f"   {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        FAILS.append(what)


def show(state, events, label):
    b = since_last_time(state, events)
    print("=" * 100)
    print(f"{state.as_of.isoformat()} · {label}")
    print(f"  NOW · since last time{'  · silent' if b.silent else ''}{f'  · +{b.more} more' if b.more else ''}")
    for l in b.lines:
        if "LIC OF INDIA" in l.text:                 # Gate 2 + 3's clock is still there; shortened here
            print(f"    {l.kind:<9} (John's LIC grace clock, still open)")
            continue
        print(f"    {l.kind:<9} {l.text}")
    return validate_payload(build_payload(state, events))


def card(state, code, account=None, scheme=None):
    return next((c for c, _ in state.open_cards if c.code == code and (account is None or c.account == account)
                 and (scheme is None or c.subject.endswith(":" + scheme))), None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--json-out", help="write the 11 Sep app payload here (UTF-8). Keep it OUT of the repo.")
    a = ap.parse_args()

    c = load(a.data)
    hh = c.account("9741").household_id
    john, kiran = c.account("9741").masked, c.account("9648").masked
    print(f"INPUT   {c.path}\nSHA256  {c.sha256}\nHOUSEHOLD {hh} (real data, replayed time; LPG record SIMULATED; "
          f"nothing is written)\n")
    answers, records = [], []
    st = initial()

    def step(d, purposes, label):
        nonlocal st
        st, ev = advance(st, take_snapshot(c, hh, d, purposes=purposes), answers, records)
        return ev, show(st, ev, label)

    ev, p = step(date(2026, 9, 7), AA, "AA consent only")
    check(not p["our_household"]["protections"]["switched_on"] and not
          [x for x in p["now"]["cards"] if x["purpose"] == PURPOSE_GOV_PROTECT],
          "no protection checks run before the customer switches them on")

    ev, p = step(date(2026, 9, 8), GOV, "customer switches on 'Check government protections'")
    jq, kq, lq = card(st, "AGE_BAND_QUESTION", john), card(st, "AGE_BAND_QUESTION", kiran), card(st, "LPG_SUBSIDY_QUESTION")
    check(bool(jq and kq and lq), "age-band questions for John and Kiran, and the LPG subsidy question")
    check("PMUY_NOT_SHOWN" in [x["code"] for x in p["our_household"]["protections"]["not_shown"]]
          and "PMUY_NOT_SHOWN" not in [x["code"] for x in p["now"]["cards"]],
          "Ujjwala is explained under OUR HOUSEHOLD, never pushed into NOW")
    seen = next(s for m in p["our_household"]["protections"]["members"] if m["account"] == john for s in m["schemes"]
                if s["scheme"] == "PMSBY")
    check(seen["status"] == "SEEN" and seen["evidence_class"] == "O", "John's PMSBY debit is observed (O)")

    answers += [Answer(jq.id, "41_50", date(2026, 9, 9)), Answer(kq.id, "18_40", date(2026, 9, 9))]
    ev, p = step(date(2026, 9, 9), GOV, "John answers 41–50, Kiran answers 18–40")
    facts = {e.account: e for e in ev if e.kind == "FACT_CONFIRMED"}
    check(len(facts[john].data["effects"]) == 3 and len(facts[kiran].data["effects"]) == 3,
          "each answer re-evaluated PMSBY, PMJJBY and APY in the same pass (one line each)")
    check(card(st, "TAXPAYER_QUESTION", kiran) is not None and card(st, "TAXPAYER_QUESTION", john) is None,
          "the taxpayer question is asked only for Kiran (the only band where APY could apply)")
    door = next(x for x in p["now"]["cards"] if x["type"] == "DOOR" and x["account"] == john)
    print("\n  John's door, as the app receives it:")
    print(f"    {door['title']}")
    for line in door["body"]:
        print(f"      {line}")
    print("    why: " + " · ".join(f"[{w['class']}] {w['badge']}" for w in door["why"]))

    answers.append(Answer(card(st, "TAXPAYER_QUESTION", kiran).id, "no", date(2026, 9, 10)))
    ev, p = step(date(2026, 9, 10), GOV, "Kiran: never an income-tax payer")
    check(card(st, "PROTECTION_DOOR", kiran, "APY") is not None, "APY is now worth checking for Kiran")

    # side branch: what a failed lookup does (replayed from the 10 Sep state, then discarded)
    fail_rec = lpg.simulated("invalid_id", requested_on=date(2026, 9, 11), household_id=hh, account=kiran, purposes=DPI)
    fst, fev = advance(st, take_snapshot(c, hh, date(2026, 9, 11), purposes=DPI), answers, [fail_rec])
    print("\n  side branch — the same lookup FAILING (simulated invalid LPG ID):")
    for l in since_last_time(fst, fev).lines:
        if "LPG" in l.text:
            print(f"    {l.kind:<9} {l.text}")
    check(card(fst, "LPG_SUBSIDY_QUESTION") is not None and not [e for e in fev if e.status == "RESOLVED"]
          and fst.access_log[-1]["outcome"] == "failed",
          "a failed lookup changes nothing: the question stays open (U), logged as failed, never success")

    print("\n  DPI · Perfios Hub LPG ID Authentication — first-class integration")
    print("    LIVE capability (built):")
    for x in lpg.INTEGRATION["live_capability"]:
        print(f"      - {x}")
    print(f"    verified against the Hub: {lpg.INTEGRATION['verified_against_the_hub'][0]}")
    print(f"    live lookup for this household: {lpg.INTEGRATION['live_lookup_for_this_household']['status']}"
          f" — {lpg.INTEGRATION['live_lookup_for_this_household']['reason']}")
    print(f"    SAY THIS: \"{lpg.DISCLOSURE}\"")
    records.append(lpg.simulated("rerouted", requested_on=date(2026, 9, 11), household_id=hh, account=kiran,
                                 purposes=DPI))
    ev, p = step(date(2026, 9, 11), DPI, "customer switches on the LPG record check; record arrives (SIMULATED)")
    r = next((x for x in p["now"]["cards"] if x["code"] == "LPG_SUBSIDY_ROUTING"), None)
    check(r is not None and "SIMULATED" in r["title"] and any(w.get("simulated") for w in r["why"]),
          "the record refined the LPG question, and every surface says SIMULATED")
    d = p["what_we_know"]["dpi_integrations"][0]
    check(d["live_lookup_for_this_household"]["status"] == "not performed" and d["disclosure"] == lpg.DISCLOSURE
          and d["responses_used_here"] == ["simulated"],
          "the payload says live capability is built, no live lookup was made here, and carries the disclosure")
    log = p["what_we_know"]["access_log"][-1]
    check(log["mode"] == "simulated" and "ConsumerName" in log["fields_dropped"] and "account_tail" in log["fields_kept"],
          "access log shows the lookup, its mode, and the personal fields dropped on arrival")
    payload_1109 = p
    print("\n  the routing card:")
    for line in r["body"]:
        print(f"      {line}")

    answers.append(Answer(card(st, "LPG_SUBSIDY_ROUTING").id, "old_not_in_use", date(2026, 9, 12)))
    ev, p = step(date(2026, 9, 12), DPI, "Kiran: 'that account is old'")
    check(not card(st, "LPG_SUBSIDY_ROUTING") and p["now"]["resolved"][0]["basis"] == "you_told_us",
          "closed as 'you told us', with the re-seeding action in its text")

    answers.append(FactStatement(john, "AGE_BAND", "51_70", date(2026, 9, 13)))
    ev, p = step(date(2026, 9, 13), DPI, "John corrects his age band to 51–70")
    wd = [e for e in ev if e.kind == "CARD_WITHDRAWN" and e.account == john]
    check(bool(wd) and all(e.data["reason"] == "FACT_CHANGED" for e in wd) and
          not [e for e in ev if e.status == "RESOLVED" and e.account == john],
          "PMJJBY is withdrawn because the fact changed — never shown as 'resolved'")
    check(p["what_we_know"]["corrections"][-1]["before"] == "41–50", "the correction is kept in WHAT WE KNOW")

    print("\n  OUR HOUSEHOLD · protections (13 Sep):")
    for m in p["our_household"]["protections"]["members"]:
        for s in m["schemes"]:
            print(f"    {m['member']:<6} {s['label']:<26} [{s['evidence_class']}] {s['status_text']}")
    print("\n  WHAT WE KNOW · things you told us:")
    for f in p["what_we_know"]["household_facts"]:
        print(f"    {f['member']:<6} {f['fact']:<22} {f['answer']:<30} feeds {', '.join(f['feeds_rules'])}")

    ev, p = step(date(2026, 9, 14), AA, "customer switches government protections OFF")
    check(st.hfacts == () and st.records == () and not p["our_household"]["protections"]["switched_on"]
          and [x["what"] for x in p["what_we_know"]["access_log"]][-2:] == ["forgotten", "forgotten"],
          "switching off forgets the answers, the record and the closures — and logs that it did")

    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(payload_1109, f, indent=2, ensure_ascii=False)
        print(f"\nwrote the 11 Sep app payload to {a.json_out}")

    print("\n" + ("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} CHECK(S) FAILED: {FAILS}"))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
