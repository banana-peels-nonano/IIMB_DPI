"""
Counterparty Mirror - Batch 1b end-to-end demo (read-only).

    python -m mirror.demo_1b --data <path to sealed decrypted.json>
    python -m mirror.demo_1b --data <path> --json      (also print each card as JSON)

Reads the corpus, replays chosen dates, and prints for each card:
  CUSTOMER    what the household would read (passed the language gate)
  WHY         the evidence trail: O/R/I/U items, transaction ids, rules, provenance
It writes nothing and makes no network calls.
"""
import argparse, dataclasses, json
from datetime import date

from .corpus import load
from .evaluate import evaluate
from .language import render
from .rules import RULEBOOK_VERSION

SCENES = [
    ("9741", date(2026, 8, 27), "John, the day before the bank charge posts - expect silence"),
    ("9741", date(2026, 8, 28), "John, the ₹590 charge has posted - expect the LIC grace clock"),
    ("9741", date(2026, 9, 7),  "John, ten days later - same card id, new liquidity range"),
    ("9648", date(2025, 12, 1), "Kiran, only one earlier IndusInd collection seen - expect a question, not a clock"),
    ("9648", date(2026, 4, 21), "Kiran, history is clear - expect the RBI-rule loan clock, stated under assumptions"),
    ("9648", date(2026, 8, 28), "Kiran, May-Jul had no collection and no return - expect questions, no status"),
    ("9950", date(2026, 9, 22), "Kumar, one clean mandate - expect silence"),
    ("9960", date(2026, 9, 22), "Naveen, templated data - expect a refusal"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="path to the sealed decrypted.json (never read from cwd)")
    ap.add_argument("--json", action="store_true", help="also print each card as JSON")
    a = ap.parse_args()

    c = load(a.data)
    print(f"INPUT     {c.path}")
    print(f"SHA256    {c.sha256}")
    print(f"RULEBOOK  {RULEBOOK_VERSION}   (real data, replayed time; nothing is written)\n")

    for suffix, when, what in SCENES:
        acc = c.account(suffix)
        print("=" * 100)
        print(f"{acc.member or '(no holder name)'} · {acc.masked} · as of {when.isoformat()}")
        print(f"  scene: {what}")
        if acc.quality != "OK":
            print(f"  REFUSED ({acc.quality}): {acc.quality_reason}")
            continue
        cards = evaluate(c, acc, when)
        if not cards:
            print("  (no cards - nothing needs this household)")
        for card in cards:
            text, trail = render(card)
            print(f"\n  ┌ {card.type} · {card.code} · id {card.id}")
            print("  │ CUSTOMER")
            for line in text.splitlines():
                print(f"  │   {line}")
            print("  │ WHY")
            for line in trail.splitlines():
                print(f"  │   {line}")
            print("  └")
            if a.json:
                print(json.dumps(dataclasses.asdict(card), indent=2, default=str))
        print()


if __name__ == "__main__":
    main()
