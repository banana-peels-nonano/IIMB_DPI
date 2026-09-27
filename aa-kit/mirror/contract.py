"""
Counterparty Mirror - the APP CONTRACT: the one JSON document the app renders.

    payload = build_payload(state, events)          # NOW / AHEAD / OUR HOUSEHOLD / WHAT WE KNOW
    validate_payload(payload)                        # raises if anything unsafe or unsourced
    python -m mirror.contract --schema               # prints the schema for the frontend

The app is a RENDERER. Every sentence, date, amount, status and label it shows is
already in this payload, already gated, and already carries its evidence class and
provenance. The app must never compute a date, an amount, a status or a sentence
about money itself (see FRONTEND_RULES).

Gate 4 + 5 extend it without moving any reasoning into the app:
  NOW          + DOOR cards ("worth checking"), Unlock questions, LPG record cards;
               SUPPRESSIONS never appear here (they are "checked, not shown").
  AHEAD        + RENEWAL items for government covers seen in an account (R, conditional).
  OUR HOUSEHOLD + protections: per member x scheme status with its evidence class;
               checked-not-shown explanations; household context (LPG connection).
  WHAT WE KNOW + household facts you told us (editable, with the rules each feeds),
               corrections, every purpose with its on/off state, the access log of
               every external lookup and every forgetting, DPI sources with their mode.
Every card or line that rests on a SIMULATED record says so in its title/text, and
validate_payload() refuses the payload if it doesn't.

AI boundary (not implemented, deliberately preserved):
    validated payload -> [future AI rephrasing] -> validate_explanation() -> customer
An explanation may only use figures and dates already present in the view it
explains, and must pass the same language gate. The AI is never the authority for
facts, deadlines, eligibility, rules, state transitions, balances or evidence.
"""
from __future__ import annotations
import argparse, json, re
from collections import defaultdict
from datetime import date

from .briefing import since_last_time, resolved_text
from .cards import FORBIDDEN_KEYS, PAN_RX, MOBILE_RX
from .events import State, fingerprint
from .facts import FACTS
from .horizon import horizon
from .language import (gate, customer_text, evidence_trail, inr, dt, OPTION_LABELS, QUESTION_TEXT, UnsafeLanguage,
                       question_text, scheme_copy)
from .rules import RULES, STATE_RULES, PURPOSES, PURPOSE_AA_PROTECT, PURPOSE_GOV_PROTECT, rule
from .unlock import PROTECTION_FACTS, ENGINE as UNLOCK_ENGINE
from .sources.lpg import INTEGRATION as LPG_INTEGRATION, DISCLOSURE as LPG_DISCLOSURE

CONTRACT_VERSION = "mirror.app/1.0"

BADGE = {"O": "Seen in your bank data", "R": "Published rule", "I": "Our reading", "U": "Only you can tell us"}
BADGE_ANSWERED = "You told us"                              # a U the customer has answered: still U, never O
BADGE_RECORD = {"live": "Seen in the oil company's record", "simulated": "SIMULATED oil company record"}
BASIS_LABEL = {"you_told_us": "You told us", "seen_in_data": "Seen in your bank data",
               "rule_implied": "Our reading of the rule", "evidence": "Based on your bank data",
               "pattern": "A repeating pattern in your bank data", "rule": "Published rule",
               "revealed_liquidity": "Our reading of which payments went through",
               "consent": "Your choice", "source_record": "From the oil company's record"}
U_TEXT = {"DUE_DATE": "when the premium was due", "PAID_ANOTHER_WAY": "whether it was paid another way",
          "PAYMENT_ALLOCATION": "how the lender applies your payments",
          "PAID_OR_AGREED_OTHERWISE": "whether anything was paid or agreed another way",
          "REASON_FOR_GAP": "why the collections stopped", "WHICH_PAYMENT": "which payment was returned",
          **{code: spec["why"] for code, spec in FACTS.items()}}
ACTION_TEXT = {"PAY_THROUGH_INSURER": "Pay through LIC's own channels",
               "ASK_LENDER_OVERDUE_AMOUNT": "Ask the lender for today's overdue amount and how payments are applied",
               "ENROL_THROUGH_BANK": "Ask a bank or post office where you have an account — only they can enrol you",
               "CHECK_LPG_RECORD": "Let us check the oil company's LPG record (needs your LPG ID and a separate OK)",
               "RESEED_OR_ASK_DISTRIBUTOR": "Move the subsidy to an account you use, or ask your distributor"}
LANE_STATUS = {"SEEN": "collected", "NOT_SEEN": "not collected", "NOT_YET_DUE": "not yet due",
               "OUTSIDE_DATA_WINDOW": "no data"}
CHARGE_LABEL = {"ECS_RETURN": "returned collections", "CARD_DECLINE": "declined card payments",
                "MIN_BALANCE": "minimum-balance charges", "ROUTINE_CHARGE": "routine bank charges"}
LIMITS = [
    "We only see the accounts you connect. Cash, other banks and other accounts are invisible to us.",
    "We never use the balance your bank reports; ranges come only from which payments went through.",
    "Money coming in is not treated as income unless it arrives as a regular pattern.",
    "Rule-derived dates depend on facts in your own contracts that bank data does not show; we ask for them.",
    "This is a replay of a recorded sandbox fetch: the dates are real data, replayed in time.",
    "Government protections: we only see scheme debits in the accounts you connect. Not seeing one tells us "
    "nothing about cover through other accounts, and only a bank, post office or insurer decides who can join.",
    "The oil company's LPG record check is built for live use through Perfios Hub. No successful live lookup was "
    "made for this household: there is no valid LPG ID from a consenting member, so the record shown is SIMULATED "
    "with the real field names and runs through the same code as a live one.",
]
CONSENT_AS_CONFIGURED = {
    "rail": "Account Aggregator (Anumati UAT)", "purpose_code": "102",
    "purpose_text": "Personal finance management", "fi_types": ["DEPOSIT"], "fetch_type": "PERIODIC",
    "frequency": "once a month", "data_life": "12 months", "data_range": "up to 12 months back",
    "expiry": "about 350 days after approval", "status": None, "status_source": None,
    "terms_source": "consent request as configured in aa-kit/anumati_client.py",
}
FRONTEND_RULES = {
    "render_as_given": ["every *text*, title, label, date and amount field"],
    "may_compute": ["layout, ordering already given, relative wording like 'in 5 days' ONLY from days_left fields"],
    "must_never": ["compute or adjust an amount, date, deadline or status",
                   "turn an evidence class into a stronger claim (I -> fact, U -> answer)",
                   "call any credit 'income' or show a balance",
                   "hide the 'if' conditions of a deadline or pressure point",
                   "show a DEADLINE or card after it appears in now.resolved",
                   "send anything to an AI model except a validated view, and never show AI text "
                   "that fails validate_explanation()",
                   "say 'eligible', 'qualify' or 'not covered' - a door is only 'worth checking'",
                   "show a door, question or protection status when protections.switched_on is false",
                   "drop the SIMULATED label from any card, line, record or closure that carries it",
                   "show a failed or refused lookup as anything but 'we couldn't check'",
                   "ask for a date of birth, or any fact not in what_we_know.household_facts[].options",
                   "present a SIMULATED DPI response as a live lookup, or hide dpi_integrations[].disclosure "
                   "wherever the simulated record is shown"],
}
HUMAN_TEXT_KEYS = {"text", "title", "body", "label", "detail", "question", "badge", "basis_label",
                   "action_text", "depends_on_text", "why", "notes", "conditions", "headline", "what",
                   "status_text", "answer", "limits"}
MACHINE_KEYS = {"id", "card_id", "event_ids", "txn_ids", "based_on_txn_ids", "evidence_txn_ids", "fingerprint",
                "corpus_sha256", "household_id", "subject", "items", "lower_bound_txn", "record_id", "request_ref",
                "facts_used", "fields_dropped", "fields_kept", "via_card"}


# ---------- views ----------
def _title(card) -> str:
    cp = next((e.data["counterparty"] for e in card.evidence
               if e.code in ("COLLECTION_HISTORY", "EARLIER_COLLECTION")), None)
    scheme = next((e.data["scheme"] for e in card.evidence if e.code == "SCHEME_RULE"), None)
    lpg = next((e.data["payer_label"] for e in card.evidence if e.code == "SUBSIDY_CREDITS_SEEN"), None)
    title = {"LIC_GRACE_CLOCK": f"{cp} premium returned",
             "LOAN_OVERDUE_CLOCK": f"{cp} collection returned",
             "RETURN_LINK_QUESTION": "A payment was returned",
             "COLLECTION_GAP_QUESTION": f"{cp} stopped collecting",
             "AGE_BAND_QUESTION": "A quick question for government protections",
             "TAXPAYER_QUESTION": "One more question for APY",
             "PROTECTION_DOOR": f"{scheme_copy(scheme)['kind'] if card.code == 'PROTECTION_DOOR' else ''} "
                                f"worth checking: {scheme}",
             "PROTECTION_NOT_SHOWN": f"{scheme}: not shown",
             "PMUY_NOT_SHOWN": "Ujjwala (PMUY): not shown",
             "LPG_SUBSIDY_QUESTION": f"LPG subsidy from {lpg} stopped",
             "LPG_SUBSIDY_ROUTING": "Where your LPG subsidy goes"}[card.code]
    return title + (" (SIMULATED record)" if card.provenance.get("simulated") else "")


def card_view(state: State, card, first_seen: date) -> dict:
    who = state.snapshot.member(card.account)
    trail = evidence_trail(card).splitlines()
    why = []
    for i, e in enumerate(card.evidence):
        item = {"class": e.cls, "badge": BADGE[e.cls], "code": e.code, "detail": trail[i].split(" — ", 1)[-1],
                "txn_ids": list(e.txn_ids), "based_on": list(e.based_on)}
        if e.cls == "R":
            rid = e.rule.split("@")[0]
            item.update(rule=e.rule, rule_name=rule(rid)["name"], citation=rule(rid)["citation"],
                        source=rule(rid)["source"], last_verified=rule(rid)["last_verified"])
        if e.cls == "U" and e.answered:
            item.update(badge=BADGE_ANSWERED, answered=True, answer=OPTION_LABELS[e.data["answered"]],
                        stated_on=e.data["stated_on"], fact_id=e.resolved_by.removeprefix("fact:"))
        if e.cls == "O" and e.data.get("record"):
            rec = e.data["record"]
            item.update(badge=BADGE_RECORD[rec["mode"]], record_id=rec["record_id"], mode=rec["mode"],
                        request_ref=rec["request_ref"], simulated=rec["mode"] == "simulated")
        why.append(item)
    view = {
        "id": card.id, "type": card.type, "code": card.code, "status": "OPEN",
        "member": who.display_name.split()[0], "account": card.account, "subject": card.subject,
        "first_seen": first_seen.isoformat(), "fingerprint": fingerprint(card),
        "title": gate(_title(card)), "body": customer_text(card).splitlines(),
        "evidence_classes": sorted({e.cls for e in card.evidence}), "why": why,
        "deadline": None, "action": None, "question": None,
        "purpose": card.provenance.get("purpose", PURPOSE_AA_PROTECT),
        "simulated": bool(card.provenance.get("simulated")),
        "lookup": card.provenance.get("dpi_lookup"),
    }
    if card.deadline:
        conds = [card.ev(u).code for u in card.deadline.conditional_on]
        view["deadline"] = {"date": card.deadline.date, "evidence_class": "R",
                            "days_left": (date.fromisoformat(card.deadline.date) - state.as_of).days,
                            "conditional": bool(conds), "depends_on": conds,
                            "depends_on_text": [U_TEXT[c] for c in conds],
                            "rules": [card.ev(b).rule for b in card.deadline.basis]}
    if card.action:
        view["action"] = {"code": card.action, "action_text": ACTION_TEXT[card.action]}
    if card.question:
        view["question"] = {"id": f"{card.id}:{card.question.id}", "card_id": card.id,
                            "question": question_text(card),
                            "options": [{"id": o, "label": OPTION_LABELS[o]} for o in card.question.options],
                            "resolves": [card.ev(u).code for u in card.question.resolves],
                            "answer_shape": {"card_id": card.id, "option": "<one option id>",
                                             "answered_on": "<YYYY-MM-DD>", "fingerprint": fingerprint(card)}}
    return view


def _horizon_text(state: State, item: dict) -> str:
    when = (dt(item["date_from"]) if item["date_from"] == item["date_to"]
            else f"between {dt(item['date_from'])} and {dt(item['date_to'])}")
    if item["kind"] == "COLLECTION":
        return f"{item['member']}: {item['label']} usually collects about {inr(item['amount'])} — expected {when}."
    if item["kind"] == "REGULAR_CREDIT_DAYS":
        return f"{item['member']}: the {item['label']} usually lands {when}."
    if item["kind"] == "RENEWAL":
        return (f"{item['member']}: {item['scheme']}'s cover year starts {dt(item['date_from'])}. If "
                f"{item['member']} is still enrolled through this account, the {inr(item['amount'])} premium is "
                f"taken by auto-debit for it.")
    card = next(c for c, _ in state.open_cards if c.id == item["card_id"])
    s = next(e.data for e in card.evidence if e.code == "RETURN_CHARGE_POSTED")
    cp = next((e.data["counterparty"] for e in card.evidence if e.code == "COLLECTION_HISTORY"), "")
    if card.code == "LIC_GRACE_CLOCK":
        return (f"{item['member']}: if the {cp} premium was due on {dt(s['return_date'])}, "
                f"its grace period ends around {dt(item['date_from'])}.")
    return f"{item['member']}: lenders' next credit-bureau report date for the {cp} loan is {dt(item['date_from'])}."


def _pressure_text(p: dict) -> str:
    c = p["covered_by_outcomes"]
    before = (f"before {p['member']}'s usual credit (from {dt(p['next_regular_credit_from'])})"
              if p["next_regular_credit_from"] else "in the next 30 days, with no regular credit expected")
    room = ("payments so far don't show any spare room" if c["low"] < 1
            else f"payments so far only prove room for about {inr(c['low'])}")
    if p["severity"] == "LIKELY_SHORT":
        return (f"Likely short around {dt(p['date'])}: about {inr(p['collections_before_next_credit'])} is expected "
                f"to be collected {before} — more than the {inr(c['low'])}–{inr(c['high'])} that payment "
                f"outcomes suggest this account can cover, unless money comes in first.")
    return (f"Could be tight around {dt(p['date'])}: about {inr(p['collections_before_next_credit'])} is expected "
            f"to be collected {before}, and {room}.")


def household_view(state: State) -> dict:
    snap = state.snapshot
    closed_by_subject = {cl.subject: cl for cl in state.closed}
    gap_subjects = {c.subject for c, _ in state.open_cards if c.code == "COLLECTION_GAP_QUESTION"}
    members, commitments, credits, protections, charges, pay_cycle = [], [], [], [], [], []
    for m in snap.members:
        who = m.display_name.split()[0]
        members.append({"member_key": m.member_key, "display_name": m.display_name, "account": m.account,
                        "data_from": m.data_from.isoformat() if m.data_from else None,
                        "data_until": m.data_until.isoformat() if m.data_until else None,
                        "status": "watched" if m.quality == "OK" else "not_used",
                        "not_used_reason": m.quality_reason or None})
        if m.quality != "OK":
            continue
        returned = {(t.linked_obligation, (t.event_date or "")[:7]) for t in m.traces
                    if t.kind == "ECS_RETURN" and t.linked_obligation}
        for ob in m.obligations:
            cl = closed_by_subject.get(ob.id)
            status = ("ended (you told us)" if cl and cl.reason == "ENDED" else
                      "paused (you told us)" if cl and cl.reason == "PAUSE_AGREED" else
                      "gap - asked about" if ob.id in gap_subjects else "active")
            seen = [o for o in ob.occurrences if o.status == "SEEN"]
            commitments.append({
                "id": ob.id, "member": who, "account": m.account, "label": ob.counterparty,
                "cadence": ob.cadence, "usual_days": list(ob.day_window), "last_amount": seen[-1].amount,
                "amount_range": list(ob.amount_band), "first_seen": ob.first_seen, "last_seen": ob.last_seen,
                "status": status, "evidence_class": "O", "txn_ids": ob.seen_txn_ids,
                "lane": [{"period": o.period,
                          "status": "returned" if (ob.id, o.period) in returned else LANE_STATUS[o.status],
                          "amount": o.amount} for o in ob.occurrences]})
        for s in m.income:
            credits.append({"id": s.id, "member": who, "account": m.account, "label": f"regular credit ('{s.signature}')",
                            "usual_days": list(s.day_window), "months_seen": len(s.months), "last_seen": s.last_seen,
                            "evidence_class": "O", "txn_ids": list(s.txn_ids),
                            "notes": ["a regular pattern of credits; we do not call it income or project amounts"]})
        grouped = defaultdict(list)
        for p in m.protections:
            grouped[(p["marker"], p["direction"])].append(p)
        for (marker, direction), rows in sorted(grouped.items()):
            protections.append({"member": who, "account": m.account, "marker": marker, "label": rows[0]["label"],
                                "direction": "paid" if direction == "DEBIT" else "received",
                                "count": len(rows), "last_date": rows[-1]["date"],
                                "txn_ids": [r["txn_id"] for r in rows], "evidence_class": "O",
                                "notes": ["seen in bank data only - it does not tell us who is covered"]})
        by_kind = defaultdict(list)
        for t in m.traces:
            by_kind[t.kind].append(t)
        for kind, ts in sorted(by_kind.items()):
            charges.append({"member": who, "account": m.account, "kind": kind, "label": CHARGE_LABEL[kind],
                            "count": len(ts), "total": round(sum(t.total_charge for t in ts), 2),
                            "evidence_class": "O", "txn_ids": [i for t in ts for i in t.txn_ids]})
        # pay-cycle visual: money in (all credits) vs recurring collections, by month
        months_in = defaultdict(float)
        for t in m.txns:
            if t.kind == "CREDIT":
                months_in[t.ym] += t.amount
        due, paid = defaultdict(float), defaultdict(float)
        for ob in m.obligations:
            last = None
            for o in ob.occurrences:
                if o.status == "SEEN":
                    last = o.amount
                    paid[o.period] += o.amount
                if o.status in ("SEEN", "NOT_SEEN") and last is not None:
                    due[o.period] += o.amount if o.status == "SEEN" else last
        for p in sorted(set(months_in) | set(due)):
            pay_cycle.append({"member": who, "account": m.account, "month": p,
                              "money_in": round(months_in.get(p, 0.0), 2), "money_in_class": "O",
                              "collections_expected": round(due.get(p, 0.0), 2), "collections_expected_class": "I",
                              "collections_made": round(paid.get(p, 0.0), 2), "collections_made_class": "O"})
    return {"members": members, "commitments": commitments, "regular_credits": credits,
            "other_credit_sources": {m.display_name.split()[0]: m.other_credit_sources for m in snap.members
                                     if m.quality == "OK"},
            "protections_observed": protections, "charges": charges,
            "visual_data": {"pay_cycle": pay_cycle,
                            "pay_cycle_notes": ["money_in is every credit, not income",
                                                "collections_expected uses the last amount actually collected"]}}


STATUS_TEXT = {
    "SEEN": "Seen in this account", "NEEDS_AGE": "Needs an age band to check",
    "WORTH_CHECKING": "Worth checking — not seen in this account",
    "NEEDS_TAXPAYER": "Needs one more answer", "COVERED_ELSEWHERE": "Through another account (you told us)",
    "NOT_ENOUGH_DATA": "Not enough data in this account to look",
    "NOT_SHOWN_HAS_LPG": "Not shown — the household has had an LPG connection",
    "ARRIVING": "Subsidy credits arriving", "ASKING": "Subsidy credits stopped — we asked you",
    "ASKING_AFTER_FAILED_LOOKUP": "Subsidy credits stopped — the record check failed, so we asked you",
    "NO_REFILLS_PER_RECORD": "No refills since the last credit (oil company's record)",
    "RECORD_ELSEWHERE": "The record names an account you haven't connected",
    "RECORD_NOT_SHOWN": "The record doesn't show which account gets the subsidy",
    "RECORD_SAME": "The record names your connected account, but nothing arrived",
    "RECORD_GIVEN_UP": "The record says the subsidy was given up",
    "RECORD_OTHER_MEMBER": "The record names an account with another member's last 4 digits",
    "ANSWERED": "You told us",
}


def protections_view(state: State) -> dict:
    """OUR HOUSEHOLD > protections: one row per member x scheme, with its evidence class."""
    snap = state.snapshot
    if PURPOSE_GOV_PROTECT not in snap.purposes:
        return {"switched_on": False, "members": [], "not_shown": [], "context": [],
                "text": gate("Switched off. Turn on 'Check government protections' to see what may protect your "
                             "household — nothing is checked until you do.")}
    open_by_subject = {c.subject: c for c, _ in state.open_cards}
    rows = {}
    for st in state.unlock_status:
        card = open_by_subject.get(f"{st['account']}:{st['scheme']}")
        text = STATUS_TEXT.get(st["status"], "")
        if st["status"] == "NOT_APPLICABLE":
            text = ("Not shown — closed to income-tax payers" if st.get("reason") == "TAXPAYER"
                    else f"Not shown — its age range is {scheme_copy(st['scheme'])['ages']}")
        if st["status"] == "SEEN":
            text += f" (last premium debit {dt(st['last_seen'])})"
        if st["status"] == "ANSWERED" and st["facts_used"]:
            said = [f for f in state.hfacts if f.id == st["facts_used"][-1]]
            if said:
                text = f"You told us: {OPTION_LABELS[said[0].value]}"
        if st.get("simulated"):
            text += " — SIMULATED record"
        name = (scheme_copy(st["scheme"])["kind"] + ": " + st["scheme"]) if st["scheme"] in ("PMSBY", "PMJJBY", "APY") \
            else {"PMUY": "Ujjwala (PMUY)", "PAHAL": "LPG subsidy (PAHAL)"}[st["scheme"]]
        rows.setdefault((st["member"], st["account"]), []).append({
            "scheme": st["scheme"], "label": name, "status": st["status"], "status_text": gate(text),
            "evidence_class": st["evidence_class"],
            "badge": (BADGE_RECORD["simulated" if st.get("simulated") else "live"] if st.get("record")
                      else BADGE_ANSWERED if st["evidence_class"] == "U" and st["facts_used"]
                      else BADGE[st["evidence_class"]]),
            "rule": st["rule"], "card_id": card.id if card else None, "facts_used": list(st["facts_used"]),
            "txn_ids": list(st["txn_ids"])})
    not_shown = [card_view(state, c, since) for c, since in state.open_cards if c.type == "SUPPRESSION"]
    context = []
    for st in state.unlock_status:
        sig = st.get("signal")
        if st["scheme"] == "PAHAL" and sig:
            context.append({"what": "LPG connection", "member": st["member"], "account": st["account"],
                            "evidence_class": "I", "badge": BADGE["I"], "txn_ids": list(sig["txn_ids"]),
                            "text": gate(f"{sig['count']} LPG subsidy credits from {sig['payer_label']} "
                                         f"({dt(sig['first'])} – {dt(sig['last'])}) show the household has had an "
                                         f"LPG connection.")})
    for rec in state.records:
        if rec.ok:
            f = rec.fields
            context.append({"what": "Oil company's LPG record", "member": None, "account": rec.account,
                            "evidence_class": "O", "badge": BADGE_RECORD[rec.mode], "record_id": rec.id,
                            "mode": rec.mode, "simulated": rec.mode == "simulated",
                            "kept": {k: v for k, v in f.items() if v is not None},
                            "text": gate(("SIMULATED — " if rec.mode == "simulated" else "")
                                         + f"checked on {dt(rec.requested_on.isoformat())} through Perfios Hub; "
                                         f"we kept {len([v for v in f.values() if v is not None])} fields and "
                                         f"dropped {len(rec.dropped)}.")})
    return {"switched_on": True,
            "members": [{"member": m, "account": a, "schemes": r} for (m, a), r in rows.items()],
            "not_shown": not_shown, "context": context}


def household_facts_view(state: State) -> list:
    snap = state.snapshot
    out = []
    for f in state.hfacts:
        m = snap.member(f.account)
        spec = FACTS[f.code]
        out.append({"id": f.id, "member": m.display_name.split()[0], "account": f.account, "fact": f.code,
                    "scheme": f.scheme, "answer": OPTION_LABELS[f.value], "value": f.value,
                    "stated_on": f.stated_on.isoformat(), "source": "you", "evidence_class": "U",
                    "badge": BADGE_ANSWERED, "feeds_rules": [f.scheme] if f.scheme else list(spec["feeds"]),
                    "purpose": spec["purpose"], "why": spec["why"],
                    "options": [{"id": v, "label": l} for v, l in spec["values"].items()],
                    "correct_shape": {"account": f.account, "code": f.code, "scheme": f.scheme,
                                      "value": "<one option id>", "stated_on": "<YYYY-MM-DD>"}})
    return out


def know_view(state: State, consent: dict) -> dict:
    snap = state.snapshot
    facts = [{"id": f.fact_id, "card_id": f.card_id, "question": QUESTION_TEXT[f.question_code],
              "answer": OPTION_LABELS[f.option], "stated_on": f.stated_on.isoformat(), "source": "you"}
             for f in state.facts]
    facts += [{"id": "FACT-" + cl.card_id, "card_id": cl.card_id, "question": "closed by your answer",
               "answer": cl.reason.replace("_", " ").lower(), "stated_on": cl.closed_on.isoformat(), "source": "you"}
              for cl in state.closed if cl.basis == "you_told_us"]
    hub = [r for r in state.records]
    purposes = [{"purpose": pid, "label": p["label"], "on": pid in snap.purposes,
                 "status_source": "AA consent as configured (replay)" if pid == PURPOSE_AA_PROTECT
                 else "this app's switch (replay)", "granted_through": p["granted_through"],
                 "uses": p["uses"], "never_uses": p["never_uses"], "withdraw": p["withdraw"]}
                for pid, p in PURPOSES.items()]
    sources_extra = ([{"name": "Perfios Hub — LPG ID Authentication (oil company's record)",
                       "mode": sorted({r.mode for r in hub}), "join": sorted({r.join for r in hub}),
                       "records": [{"id": r.id, "on": r.requested_on.isoformat(), "status": r.status,
                                    "reason": r.reason, "mode": r.mode} for r in hub]}] if hub else [])
    modes = sorted({r.mode for r in hub})
    live_ok = [r for r in hub if r.mode == "live" and r.ok]
    dpi = [{**LPG_INTEGRATION,
            "live_lookup_for_this_household": (
                {"status": "succeeded", "record_ids": [r.id for r in live_ok]} if live_ok
                else LPG_INTEGRATION["live_lookup_for_this_household"]),
            "responses_used_here": modes or ["none yet"],
            "disclosure": LPG_DISCLOSURE if "simulated" in modes else None}]
    return {"facts": facts, "household_facts": household_facts_view(state), "consent": consent,
            "purposes": purposes, "dpi_integrations": dpi,
            "sources": [{"name": "Account Aggregator: Anumati UAT sandbox, ACME-FIP", "fi_type": "DEPOSIT",
                         "mode": "replay of a recorded fetch", "corpus_sha256": snap.corpus_sha256,
                         "accounts": [{"account": m.account, "member": m.display_name.split()[0],
                                       "data_from": m.data_from.isoformat() if m.data_from else None,
                                       "data_until": m.data_until.isoformat() if m.data_until else None,
                                       "used": m.quality == "OK"} for m in snap.members]}] + sources_extra,
            "rules_in_use": [{"rule": f"{rid}@{r['version']}", "name": r["name"], "citation": r["citation"],
                              "source": r["source"], "last_verified": r["last_verified"], "purpose": r["purpose"],
                              "book": "counterparty" if rid in RULES else "state"}
                             for rid, r in list(RULES.items()) + list(STATE_RULES.items())
                             if r["purpose"] in snap.purposes],
            "limits": LIMITS,
            "corrections": [{"fact_id": c.fact_id, "fact": c.code, "scheme": c.scheme,
                             "member": snap.member(c.account).display_name.split()[0],
                             "before": OPTION_LABELS[c.old_value], "after": OPTION_LABELS[c.new_value],
                             "stated_on": c.stated_on.isoformat()} for c in state.corrections],
            "access_log": [dict(e) for e in state.access_log],
            "not_yet_recorded": ["answers, corrections and the access log live in the replayed state; storing "
                                 "them across sessions arrives with Batch 1c (memory)"]}


def build_payload(state: State, events: list, consent: dict | None = None) -> dict:
    consent = dict(CONSENT_AS_CONFIGURED if consent is None else consent)
    snap = state.snapshot
    b = since_last_time(state, events)
    ahead = horizon(state)
    for item in ahead["items"]:
        item["text"] = gate(_horizon_text(state, item))
    for p in ahead["pressure_points"]:
        p["text"] = gate(_pressure_text(p))
    cards = [card_view(state, c, since) for c, since in state.open_cards if c.type != "SUPPRESSION"]
    order = {"CLOCK": 0, "DOOR": 1, "SUPPRESSION": 2, "QUESTION": 3}
    cards.sort(key=lambda v: (order[v["type"]], v["deadline"]["date"] if v["deadline"] else "9999", v["id"]))
    sim_closed = lambda cl: cl.summary.get("record_mode") == "simulated"
    resolved = [{"card_id": cl.card_id,
                 "title": gate(f"{cl.summary.get('counterparty', 'Payment')}: closed"
                               + (" (SIMULATED record)" if sim_closed(cl) else "")),
                 "simulated": sim_closed(cl),
                 "text": gate(resolved_text(state, cl.account, cl.summary, cl.reason, cl.evidence_txn_ids)),
                 "closed_on": cl.closed_on.isoformat(), "basis": cl.basis,
                 "basis_label": BASIS_LABEL[cl.basis] + (" — SIMULATED" if cl.summary.get("record_mode") == "simulated"
                                                          and cl.basis == "source_record" else ""),
                 "evidence_txn_ids": list(cl.evidence_txn_ids) if cl.basis != "source_record" else [],
                 "record_id": cl.summary.get("record_id"),
                 "member": snap.member(cl.account).display_name.split()[0]}
                for cl in sorted(state.closed, key=lambda c: (c.closed_on, c.card_id), reverse=True)
                if not (cl.reason == "ANSWERED" and cl.summary.get("fact") in PROTECTION_FACTS)]
    return {
        "contract": CONTRACT_VERSION,
        "generated": {"as_of": state.as_of.isoformat(), "since": state.since.isoformat() if state.since else None,
                      "household_id": snap.household_id, "engine": snap.engine,
                      "rulebook_version": snap.rulebook_version, "corpus_sha256": snap.corpus_sha256,
                      "data_mode": "replay", "authored_by": "deterministic engine - no AI in this payload",
                      "engines": {"protect": snap.engine, "unlock": UNLOCK_ENGINE},
                      "purposes_on": sorted(snap.purposes),
                      "simulated_sources": any(r.mode == "simulated" for r in state.records)},
        "now": {"since_last_time": {"since": b.since, "silent": b.silent, "more": b.more,
                                    "lines": [{"id": l.id, "kind": l.kind, "text": l.text, "member": l.member,
                                               "card_id": l.card_id, "event_ids": list(l.event_ids),
                                               "basis": l.basis, "basis_label": BASIS_LABEL.get(l.basis, ""),
                                               "evidence_classes": list(l.evidence_classes), "action": l.action}
                                              for l in b.lines],
                                    "provenance": b.provenance},
                "cards": cards,
                "questions": [v["question"] for v in cards if v["question"]],
                "resolved": resolved},
        "ahead": ahead,
        "our_household": {**household_view(state), "protections": protections_view(state)},
        "what_we_know": know_view(state, consent),
        "events": [{"id": e.id, "kind": e.kind, "status": e.status, "subject": e.subject, "card_id": e.card_id,
                    "basis": e.basis, "evidence_classes": list(e.evidence_classes), "txn_ids": list(e.txn_ids),
                    "reason": e.data.get("reason"), "caused_by_fact": e.data.get("caused_by_fact")}
                   for e in events],
    }


# ---------- validation ----------
class PayloadInvalid(Exception):
    pass


def _walk(obj, key=None):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)
    elif isinstance(obj, str):
        yield key, obj


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def validate_payload(p: dict) -> dict:
    for section in ("contract", "generated", "now", "ahead", "our_household", "what_we_know"):
        if section not in p:
            raise PayloadInvalid(f"missing section {section!r}")
    for k in ("corpus_sha256", "rulebook_version", "engine", "as_of"):
        if not p["generated"].get(k):
            raise PayloadInvalid(f"generated.{k} missing")
    consent = p["what_we_know"].get("consent", {})
    if consent.get("status") and not consent.get("status_source"):
        raise PayloadInvalid("consent status shown without saying where it came from")
    bad = {k.lower() for k in _keys(p)} & (FORBIDDEN_KEYS | {"balance", "narration", "txns", "income"})
    if bad:
        raise PayloadInvalid(f"forbidden field(s) {sorted(bad)}")
    for key, s in _walk(p):
        if key in MACHINE_KEYS:
            continue
        if key in HUMAN_TEXT_KEYS:
            gate(s)                                           # raises UnsafeLanguage
        elif PAN_RX.search(s) or MOBILE_RX.search(s):
            raise PayloadInvalid("a PAN or mobile number appears in the payload")
    for card in p["now"]["cards"]:
        if not card["why"] or any(w["class"] not in BADGE for w in card["why"]):
            raise PayloadInvalid(f"card {card['id']} has no evidence trail")
        if card["deadline"] and card["deadline"]["depends_on"] and not card["deadline"]["conditional"]:
            raise PayloadInvalid(f"card {card['id']} hides a conditional deadline")
    for line in p["now"]["since_last_time"]["lines"]:
        if line["kind"] != "ROUTINE" and not line["event_ids"]:
            raise PayloadInvalid(f"briefing line {line['id']} has no event behind it")
    for item in p["ahead"]["items"]:
        if item["kind"] == "REGULAR_CREDIT_DAYS" and "amount" in item:
            raise PayloadInvalid("a regular-credit band may never carry an amount")
        if item["evidence_class"] not in ("I", "R"):
            raise PayloadInvalid("horizon items are projections (I) or rule dates (R), never observations")
        if item["kind"] == "RENEWAL" and not item.get("conditional_on"):
            raise PayloadInvalid("a renewal date must say it depends on still being enrolled")
    # Gate 4 + 5
    prot = p["our_household"].get("protections", {})
    for card in p["now"]["cards"] + prot.get("not_shown", []):
        sim = any(w.get("simulated") for w in card["why"])
        if sim and not (card["simulated"] and "simulated" in card["title"].lower()):
            raise PayloadInvalid(f"card {card['id']} rests on a simulated record but doesn't say so")
        if card["type"] == "DOOR" and not any(w["code"] == "COVERED_ELSEWHERE" for w in card["why"]):
            raise PayloadInvalid(f"door {card['id']} treats 'not seen' as 'not enrolled'")
        if card["type"] == "SUPPRESSION" and card in p["now"]["cards"]:
            raise PayloadInvalid("a suppression is 'checked, not shown' - it never appears in NOW")
        for w in card["why"]:
            if w.get("answered") and w["class"] != "U":
                raise PayloadInvalid("a customer answer must stay class U")
    for r in p["now"]["resolved"]:
        if r.get("simulated") and not ("SIMULATED" in r["title"] and "SIMULATED" in r["text"]):
            raise PayloadInvalid(f"resolved item {r['card_id']} rests on a simulated record but doesn't say so")
        if r["basis"] == "source_record" and r.get("record_id"):
            rec = next((x for x in p["what_we_know"]["access_log"] if x.get("id") == r["record_id"]), None)
            if rec is None:
                raise PayloadInvalid("a closure from a source record must appear in the access log")
            if rec["mode"] == "simulated" and "SIMULATED" not in r["basis_label"]:
                raise PayloadInvalid("a closure from a simulated record must say SIMULATED")
    for entry in p["what_we_know"].get("access_log", []):
        if entry.get("what") == "lookup" and entry["outcome"] != "ok" and entry.get("fields_kept"):
            raise PayloadInvalid("a failed lookup cannot carry household fields")
    # LIVE capability vs SIMULATED execution: never blurred, never a fabricated live success
    log = p["what_we_know"].get("access_log", [])
    for d in p["what_we_know"].get("dpi_integrations", []):
        status = d["live_lookup_for_this_household"]["status"]
        if status == "succeeded" and not any(e.get("mode") == "live" and e.get("outcome") == "ok" for e in log):
            raise PayloadInvalid("a live lookup is claimed as succeeded, but no live record is in the access log")
        if "simulated" in d["responses_used_here"] and d.get("disclosure") != LPG_DISCLOSURE:
            raise PayloadInvalid("a simulated DPI response is used without the live-vs-simulated disclosure")
    for pur in p["what_we_know"].get("purposes", []):
        if pur["on"] and not pur.get("status_source"):
            raise PayloadInvalid("a purpose shown as on must say where that came from")
    return p


NUM_RX = re.compile(r"\d[\d,]*(?:\.\d+)?")


def validate_explanation(text: str, view: dict) -> str:
    """The AI boundary. A future AI may rephrase a validated view, but every figure and date
    number it uses must already be in that view, and it must pass the same language gate."""
    gate(text)
    allowed = {n.replace(",", "").lstrip("0") for n in NUM_RX.findall(json.dumps(view, ensure_ascii=False))}
    used = {n.replace(",", "").lstrip("0") for n in NUM_RX.findall(text)}
    invented = sorted(n for n in used - allowed if n)
    if invented:
        raise UnsafeLanguage(f"explanation introduces figures not in the card: {invented}")
    return text


# ---------- schema for the frontend ----------
def _obj(props: dict, required=None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props)}


S, N, B = {"type": "string"}, {"type": "number"}, {"type": "boolean"}
NS = {"type": ["string", "null"]}
CLS = {"type": "string", "enum": ["O", "R", "I", "U"]}
ARR = lambda x: {"type": "array", "items": x}
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "title": CONTRACT_VERSION,
    "type": "object", "required": ["contract", "generated", "now", "ahead", "our_household", "what_we_know"],
    "properties": {
        "contract": {"const": CONTRACT_VERSION},
        "generated": _obj({"as_of": S, "since": NS, "household_id": S, "engine": S, "rulebook_version": S,
                           "corpus_sha256": S, "data_mode": S, "authored_by": S}),
        "now": _obj({
            "since_last_time": _obj({"since": NS, "silent": B, "more": N, "provenance": {"type": "object"},
                                     "lines": ARR(_obj({"id": S, "kind": {"enum": ["ATTENTION", "RESOLVED", "CHANGE",
                                                        "DOOR", "QUESTION", "FACT", "LEARNED", "ROUTINE"]},
                                                        "text": S, "member": NS, "card_id": NS,
                                                        "event_ids": ARR(S), "basis": S, "basis_label": S,
                                                        "evidence_classes": ARR(CLS), "action": {}}))}),
            "cards": ARR(_obj({"id": S, "type": {"enum": ["CLOCK", "DOOR", "SUPPRESSION", "QUESTION"]}, "code": S,
                               "status": S, "member": S, "account": S, "subject": S, "first_seen": S,
                               "fingerprint": S, "title": S, "body": ARR(S), "evidence_classes": ARR(CLS),
                               "purpose": S, "simulated": B, "lookup": {},
                               "why": ARR(_obj({"class": CLS, "badge": S, "code": S, "detail": S,
                                                "txn_ids": ARR(S), "based_on": ARR(S)}, ["class", "badge", "code", "detail"])),
                               "deadline": {}, "action": {}, "question": {}})),
            "questions": ARR({"type": "object"}),
            "resolved": ARR(_obj({"card_id": S, "title": S, "text": S, "closed_on": S, "basis": {"enum":
                                  ["you_told_us", "seen_in_data", "rule_implied", "source_record"]}, "basis_label": S,
                                  "evidence_txn_ids": ARR(S), "record_id": NS, "member": S, "simulated": B}))}),
        "ahead": _obj({"as_of": S, "from": S, "to": S, "days": N,
                       "items": ARR(_obj({"kind": {"enum": ["COLLECTION", "REGULAR_CREDIT_DAYS", "DEADLINE", "RENEWAL"]},
                                          "member": S, "date_from": S, "date_to": S, "text": S,
                                          "evidence_class": {"enum": ["I", "R"]}},)),
                       "pressure_points": ARR(_obj({"kind": {"const": "PRESSURE"}, "date": S, "severity":
                                                    {"enum": ["COULD_BE_TIGHT", "LIKELY_SHORT"]}, "text": S,
                                                    "evidence_class": {"const": "I"}, "conditions": ARR(S)},)),
                       "not_projected": ARR({"type": "object"}), "provenance": {"type": "object"}}),
        "our_household": _obj({"members": ARR({"type": "object"}), "commitments": ARR({"type": "object"}),
                               "regular_credits": ARR({"type": "object"}), "other_credit_sources": {"type": "object"},
                               "protections_observed": ARR({"type": "object"}), "charges": ARR({"type": "object"}),
                               "visual_data": {"type": "object"},
                               "protections": _obj({"switched_on": B, "members": ARR({"type": "object"}),
                                                    "not_shown": ARR({"type": "object"}),
                                                    "context": ARR({"type": "object"})},
                                                   ["switched_on", "members", "not_shown", "context"])}),
        "what_we_know": _obj({"facts": ARR({"type": "object"}), "household_facts": ARR({"type": "object"}),
                              "consent": {"type": "object"}, "purposes": ARR({"type": "object"}),
                              "dpi_integrations": ARR(_obj({"name": S, "live_capability": ARR(S),
                                                            "live_lookup_for_this_household": {"type": "object"},
                                                            "responses_used_here": ARR(S), "disclosure": NS},)),
                              "sources": ARR({"type": "object"}), "rules_in_use": ARR({"type": "object"}),
                              "limits": ARR(S), "corrections": ARR({}), "access_log": ARR({}),
                              "not_yet_recorded": ARR(S)}),
    },
    "x-frontend-rules": FRONTEND_RULES,
    "x-evidence-badges": {**BADGE, "U (answered)": BADGE_ANSWERED, "O (record, live)": BADGE_RECORD["live"],
                          "O (record, simulated)": BADGE_RECORD["simulated"]},
    "x-answer-shapes": {
        "card_answer": {"card_id": "<card id>", "option": "<one option id>", "answered_on": "<YYYY-MM-DD>",
                        "fingerprint": "<the card's fingerprint>"},
        "fact_correction": {"account": "<masked account>", "code": "<fact code>", "scheme": "<scheme or null>",
                            "value": "<one option id>", "stated_on": "<YYYY-MM-DD>"},
        "purpose_switch": {"purpose": "<purpose id>", "on": "<true|false>", "on_date": "<YYYY-MM-DD>"},
    },
}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Print the app contract schema (read-only).")
    ap.add_argument("--schema", action="store_true")
    a = ap.parse_args()
    print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
