"""
Counterparty Mirror - 30-day Horizon: "What is coming, and where could timing get tight?"

    ahead = horizon(state, days=30)

A VIEW over the household State, never a separate forecast engine. It shows only:
  COLLECTION          a recurring collection seen >= 3 times on a stable day window,
                      projected to its next usual date(s)                       (I, pattern)
  REGULAR_CREDIT_DAYS the day-band a REGULAR credit usually lands - dates only,
                      never an amount                                           (I, pattern)
  DEADLINE            an open clock's rule-derived date, with its conditions    (R, conditional)
  PRESSURE            where known collections before the next regular credit
                      exceed what payment outcomes prove the account can cover  (I, conditional)
  RENEWAL             (Gate 4) a government cover SEEN in this account renews on
                      its published cover-year date, by auto-debit              (R, conditional)
And it says explicitly what it does NOT project (irregular credits, spending,
balances, paused collections, refused accounts).

It never reads balances, never projects irregular inflows, and never invents an
amount: collection amounts are the last amount actually collected.
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta

from .events import State
from .liquidity import revealed_liquidity
from .rules import STATE_RULES, rule_ref

HORIZON_DAYS = 30
STABLE_DAY_SPREAD = 7            # a collection whose day moves more than this is not dated
DEADLINE_LABEL = {"LIC_GRACE_CLOCK": "LIC grace period ends (if due as assumed)",
                  "LOAN_OVERDUE_CLOCK": "next credit-bureau report date"}


def _date_in(y: int, m: int, day: int) -> date:
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def _next_periods(first: str, step: int, until: date):
    y, m = int(first[:4]), int(first[5:7])
    while date(y, m, 1) <= until:
        yield y, m
        k = y * 12 + m - 1 + step
        y, m = divmod(k, 12)
        m += 1


def _paused(state: State, ob) -> str | None:
    """Collections we should NOT project: an open gap question whose missing run
    reaches the latest expected period, or a gap the customer closed as ended/paused."""
    for card, _ in state.open_cards:
        if card.code == "COLLECTION_GAP_QUESTION" and card.subject == ob.id:
            last = [o for o in ob.occurrences if o.status in ("SEEN", "NOT_SEEN")][-1]
            if last.status == "NOT_SEEN":
                return "recent collections are missing - we asked you why"
            return None                      # it resumed; projected with a note
    for cl in state.closed:
        if cl.subject == ob.id and cl.reason in ("ENDED", "PAUSE_AGREED"):
            return "you told us it has ended" if cl.reason == "ENDED" else "you told us a pause was agreed"
    return None


def _resumed_note(state: State, ob) -> str | None:
    for card, _ in state.open_cards:
        if card.code == "COLLECTION_GAP_QUESTION" and card.subject == ob.id:
            return "collections resumed after a gap you haven't explained yet"
    return None


def horizon(state: State, days: int = HORIZON_DAYS) -> dict:
    snap = state.snapshot
    start, end = state.as_of + timedelta(days=1), state.as_of + timedelta(days=days)
    items, pressure, not_projected = [], [], []

    for m in snap.members:
        who = m.display_name.split()[0]
        if m.quality != "OK":
            not_projected.append({"member": who, "account": m.account, "what": "everything",
                                  "why": f"we did not learn from this account's data ({m.quality.lower()})"})
            continue

        # --- recurring collections (I, pattern) ---
        mine = []
        for ob in m.obligations:
            why_not = _paused(state, ob)
            if why_not:
                not_projected.append({"member": who, "account": m.account, "what": ob.counterparty, "why": why_not})
                continue
            lo, hi = ob.day_window
            seen = [o for o in ob.occurrences if o.status == "SEEN"]
            last_amount = seen[-1].amount
            anchor = ob.occurrences[-1].period
            for y, mo in _next_periods(anchor, ob.cadence_months, end):
                d_from, d_to = _date_in(y, mo, lo), _date_in(y, mo, hi)
                if d_to < start or d_from > end:
                    continue
                occ = next((o for o in ob.occurrences if o.period == f"{y:04d}-{mo:02d}"), None)
                if occ is not None and occ.status == "SEEN":
                    continue                               # already collected this period
                item = {"kind": "COLLECTION", "member": who, "account": m.account, "subject": ob.id,
                        "label": ob.counterparty, "cadence": ob.cadence,
                        "date_from": d_from.isoformat(), "date_to": d_to.isoformat(),
                        "amount": last_amount, "amount_basis": "last amount collected",
                        "evidence_class": "I", "basis": "pattern", "seen_count": len(seen),
                        "based_on_txn_ids": [i for o in seen[-3:] for i in o.txn_ids],
                        "notes": []}
                if hi - lo > STABLE_DAY_SPREAD:
                    item["notes"].append("the collection day varies; shown as a range")
                if hi == 28:
                    item["notes"].append("day 28 in this data can mean any day to month-end")
                note = _resumed_note(state, ob)
                if note:
                    item["notes"].append(note)
                items.append(item)
                mine.append(item)

        # --- regular credit day-bands (I, pattern; dates only, never amounts) ---
        bands = []
        for s in m.income:
            last_seen = date.fromisoformat(s.last_seen + "-01")
            if (state.as_of.year * 12 + state.as_of.month) - (last_seen.year * 12 + last_seen.month) > 1:
                continue                                   # not recent enough to call regular now
            lo, hi = s.day_window
            y, mo = int(s.last_seen[:4]), int(s.last_seen[5:7])
            for yy, mm in _next_periods(f"{y:04d}-{mo:02d}", 1, end):
                d_from, d_to = _date_in(yy, mm, lo), _date_in(yy, mm, hi)
                if (yy, mm) == (y, mo) or d_to < start or d_from > end:
                    continue
                band = {"kind": "REGULAR_CREDIT_DAYS", "member": who, "account": m.account,
                        "subject": s.id, "label": f"regular credit ('{s.signature}')",
                        "date_from": d_from.isoformat(), "date_to": d_to.isoformat(),
                        "evidence_class": "I", "basis": "pattern", "months_seen": len(s.months),
                        "based_on_txn_ids": list(s.txn_ids[-3:]),
                        "notes": ["dates only: we never project how much will arrive"]
                                 + (["day 28 in this data can mean any day to month-end"] if hi == 28 else [])}
                items.append(band)
                bands.append(band)
        if not m.income:
            not_projected.append({"member": who, "account": m.account, "what": "credits",
                                  "why": "no regular credit pattern found; irregular credits are never projected"})
        elif m.other_credit_sources:
            not_projected.append({"member": who, "account": m.account, "what": "other credits",
                                  "why": f"{m.other_credit_sources} irregular credit sources are never projected"})

        # --- pressure point (I, conditional): liquidity from payment outcomes only ---
        strong = [t for t in m.traces if t.kind == "ECS_RETURN" and t.link_confidence == "strong"]
        returned = None
        if strong:
            t = strong[-1]
            ob = next(o for o in m.obligations if o.id == t.linked_obligation)
            amt = [o for o in ob.occurrences if o.status == "SEEN"][-1].amount
            returned = {"date": date.fromisoformat(t.event_date), "amount": amt, "trace_id": t.id}
        liq = revealed_liquidity(m.account, list(m.txns), at_end_of=state.as_of, returned=returned)
        if liq and mine:
            next_credit = min((date.fromisoformat(b["date_from"]) for b in bands), default=None)
            due = sorted((i for i in mine if next_credit is None or date.fromisoformat(i["date_from"]) < next_credit),
                         key=lambda i: i["date_from"])
            running, involved = 0.0, []
            for i in due:
                running += i["amount"]
                involved.append(i)
                if running > liq.low:
                    likely = liq.high is not None and running > liq.high
                    pressure.append({
                        "kind": "PRESSURE", "member": who, "account": m.account,
                        "date": involved[-1]["date_from"],
                        "severity": "LIKELY_SHORT" if likely else "COULD_BE_TIGHT",
                        "collections_before_next_credit": round(running, 2),
                        "next_regular_credit_from": next_credit.isoformat() if next_credit else None,
                        "covered_by_outcomes": {"point": liq.point, "low": liq.low, "high": liq.high},
                        "items": [x["subject"] + "@" + x["date_from"] for x in involved],
                        "evidence_class": "I", "basis": "revealed_liquidity",
                        "based_on_txn_ids": [liq.lower_bound_txn],
                        "conditions": ["nothing else comes in or goes out of this account before then",
                                       *liq.assumptions],
                        "not_considered": list(liq.not_considered)})
                    break

    # --- open clock deadlines (R, conditional) ---
    for card, _ in state.open_cards:
        if card.deadline and start <= date.fromisoformat(card.deadline.date) <= end:
            m = snap.member(card.account)
            items.append({"kind": "DEADLINE", "member": m.display_name.split()[0], "account": card.account,
                          "subject": card.subject, "card_id": card.id, "label": DEADLINE_LABEL[card.code],
                          "date_from": card.deadline.date, "date_to": card.deadline.date,
                          "evidence_class": "R", "basis": "rule",
                          "rules": [card.ev(b).rule for b in card.deadline.basis],
                          "conditional_on": [card.ev(u).code for u in card.deadline.conditional_on],
                          "notes": ["a rule-derived date that depends on facts only you can confirm"]})

    # --- government covers seen in an account: the published cover year renews (R, conditional) ---
    for st in state.unlock_status:
        if st["status"] != "SEEN" or st["scheme"] not in ("PMSBY", "PMJJBY"):
            continue
        p = STATE_RULES[st["scheme"]]["params"]
        mm, dd = map(int, p["cover_year_starts"].split("-"))
        for y in (start.year, end.year):
            d = date(y, mm, dd)
            if start <= d <= end:
                items.append({"kind": "RENEWAL", "member": st["member"], "account": st["account"],
                              "subject": f"{st['account']}:{st['scheme']}", "label": f"{st['scheme']} cover year renews",
                              "scheme": st["scheme"], "date_from": d.isoformat(), "date_to": d.isoformat(),
                              "amount": float(p["premium_inr"]), "amount_basis": "published premium",
                              "evidence_class": "R", "basis": "rule", "rules": [rule_ref(st["scheme"])],
                              "based_on_txn_ids": list(st["txn_ids"]),
                              "conditional_on": ["still enrolled through this account"],
                              "notes": ["the premium is taken by auto-debit for the new cover year"]
                                       + (["cover ends if the account can't pay the premium at renewal (DFS)"]
                                          if st["scheme"] == "PMJJBY" else [])})
                break

    not_projected += [
        {"member": None, "account": None, "what": "spending", "why": "we never forecast spending"},
        {"member": None, "account": None, "what": "balances", "why": "we never use or predict balances"},
    ]
    items.sort(key=lambda i: (i["date_from"], i["kind"], i["subject"]))
    return {"as_of": state.as_of.isoformat(), "from": start.isoformat(), "to": end.isoformat(),
            "days": days, "items": items, "pressure_points": pressure, "not_projected": not_projected,
            "provenance": {"corpus_sha256": snap.corpus_sha256, "rulebook_version": snap.rulebook_version,
                           "engine": snap.engine}}
