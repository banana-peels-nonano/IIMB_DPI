"""
Counterparty Mirror - Gate 2 + 3 developer verification path (read-only).

    python -m mirror.demo_gate23 --data <sealed decrypted.json>
    python -m mirror.demo_gate23 --data <path> --json-out <file outside the repo>

Replays John's LIC story through the time axis, prints what the app would
receive at each refresh, and CHECKS the lifecycle:
    27 Aug  first look          -> no card and no event for John
    28 Aug  refresh             -> LIC clock NEW
     7 Sep  refresh             -> same clock CONTINUING (same card id)
     9 Sep  customer answers "I've already paid it" -> RESOLVED (you told us)
    12 Sep  refresh             -> stays closed, nothing re-asked
then shows AHEAD on 9 Sep, and AHEAD as it looked on 9 Aug (two weeks before
the premium was returned). Exit code 1 if any check fails.
This is a verification tool; the real demo is the app rendering the same payload.
"""
import argparse, json, sys
from datetime import date

from .corpus import load
from .snapshot import take_snapshot
from .events import advance, initial, Answer, fingerprint
from .briefing import since_last_time
from .contract import build_payload, validate_payload

FAILS = []


def check(ok: bool, what: str):
    print(f"   {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        FAILS.append(what)


def show_briefing(state, events):
    b = since_last_time(state, events)
    head = f"since {b.since}" if b.since else "first look"
    print(f"  NOW · since last time ({head}){'  · silent' if b.silent else ''}{f'  · +{b.more} more' if b.more else ''}")
    for l in b.lines:
        print(f"    {l.kind:<9} {l.text}")
    return b


def show_ahead(payload):
    a = payload["ahead"]
    print(f"  AHEAD · {a['from']} to {a['to']}")
    for i in a["items"]:
        print(f"    {i['kind']:<20}[{i['evidence_class']}] {i['text']}")
    for p in a["pressure_points"]:
        print(f"    {'PRESSURE':<20}[I] {p['text']}")
        print(f"    {'':<24}if: {p['conditions'][0]}")
    for n in a["not_projected"]:
        print(f"    {'not projected':<20}    {(n['member'] + ': ') if n['member'] else ''}{n['what']} — {n['why']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--json-out", help="write the 9 Sep app payload here (UTF-8). Keep it OUT of the repo.")
    a = ap.parse_args()

    c = load(a.data)
    john = c.account("9741")
    hh = john.household_id
    print(f"INPUT   {c.path}\nSHA256  {c.sha256}\nHOUSEHOLD {hh} (real data, replayed time; nothing is written)\n")
    state, answers = initial(), []

    def step(d, label):
        nonlocal state
        state, events = advance(state, take_snapshot(c, hh, d), answers)
        print("=" * 100)
        print(f"{d.isoformat()} · {label}")
        show_briefing(state, events)
        payload = validate_payload(build_payload(state, events))
        john_cards = [v for v in payload["now"]["cards"] if v["account"] == john.masked]
        john_events = [e for e in events if e.account == john.masked and e.status != "CONTINUING"]
        return events, payload, john_cards, john_events

    ev, p, jc, je = step(date(2026, 8, 27), "first look")
    check(not jc and not je, "John: no card and no event on 27 Aug (the charge has not posted yet)")

    ev, p, jc, je = step(date(2026, 8, 28), "refresh: the ₹590 return charge has posted")
    lic = [e for e in je if e.kind == "CARD_OPENED"]
    check(len(lic) == 1 and lic[0].status == "NEW", "John: LIC clock opened (NEW)")
    card_id = lic[0].card_id if lic else None

    ev, p, jc, je = step(date(2026, 9, 7), "refresh: ten days later, nothing paid yet")
    cont = [e for e in ev if e.card_id == card_id]
    check(len(cont) == 1 and cont[0].status == "CONTINUING", "John: same clock CONTINUING, same card id")
    view = next(v for v in p["now"]["cards"] if v["id"] == card_id)
    print(f"\n  the app sends back (customer taps '{view['question']['options'][2]['label']}'):")
    ans = {"card_id": card_id, "option": "already_paid", "answered_on": "2026-09-09",
           "fingerprint": view["fingerprint"]}
    print(f"    {json.dumps(ans)}")
    answers.append(Answer(ans["card_id"], ans["option"], date.fromisoformat(ans["answered_on"]), ans["fingerprint"]))

    ev, p, jc, je = step(date(2026, 9, 9), "refresh after the customer's answer")
    res = [e for e in ev if e.card_id == card_id and e.status == "RESOLVED"]
    check(len(res) == 1 and res[0].basis == "you_told_us", "John: RESOLVED, basis 'you told us' (not 'seen in data')")
    check(not jc, "John: no open cards remain")
    check(not [i for i in p["ahead"]["items"] if i["kind"] == "DEADLINE"], "AHEAD no longer shows the LIC deadline")
    payload_0909 = p
    print()
    show_ahead(p)

    ev, p, jc, je = step(date(2026, 9, 12), "refresh three days later")
    check(not [e for e in ev if e.card_id == card_id], "John: the closed clock is not reopened or re-asked")

    print("=" * 100)
    print("AHEAD as it looked on 9 Aug 2026 (replay; nothing after 9 Aug is used)")
    s0, e0 = advance(initial(), take_snapshot(c, hh, date(2026, 8, 9)))
    p0 = validate_payload(build_payload(s0, e0))
    show_ahead(p0)
    pp = [x for x in p0["ahead"]["pressure_points"] if x["member"] == "John"]
    check(bool(pp) and pp[0]["date"] == "2026-08-23" and pp[0]["evidence_class"] == "I",
          "9 Aug: pressure point flagged for the ~23 Aug LIC premium (inferred, conditional)")
    print("   what happened next in the data: that premium was returned on 22 Aug (the ₹590 charge).")

    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(payload_0909, f, indent=2, ensure_ascii=False)
        print(f"\nwrote the 9 Sep app payload to {a.json_out}")

    print("\n" + ("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} CHECK(S) FAILED: {FAILS}"))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
