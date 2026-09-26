"""
Counterparty Mirror - Language: the ONLY place customer-facing words are made.

  render(card)  -> (customer_text, evidence_trail)   both pass through gate()
  gate(text)    -> returns text, or RAISES UnsafeLanguage

Templates are fixed strings filled from card fields. No free text, no LLM.
A future AI explanation layer would sit before gate() and be checked by it
exactly like these templates are; it could never add evidence or change a
date, because it would only ever see a validated Card.

Why the gate runs here, at render time: a card can be structurally valid
while a template or a data value (e.g. a counterparty label) still produces
an unsafe sentence. Only the final text shows what the customer would read.
"""
from __future__ import annotations
import re
from datetime import date

from .cards import Card, PAN_RX, MOBILE_RX
from .rules import RULES


class UnsafeLanguage(Exception):
    """The text would make an unsupported claim or leak an identifier. Nothing is shown."""


BANNED = [
    (r"\bNPA\b", "asset-classification label"),
    (r"\bnon[- ]?performing\b", "asset-classification label"),
    (r"\bdefault(s|ed|er)?\b", "status we cannot observe"),
    (r"\blaps(e|es|ed|ing)\b", "policy status we cannot observe"),
    (r"\bcredit (report|score|history) (shows|says|is|has)\b", "bureau data we never see"),
    (r"\b(is|are) (now )?(overdue|in arrears)\b", "lender status stated as fact"),
    (r"\beligib(le|ility)\b", "formal eligibility claim"),
    (r"\bqualif(y|ies|ied)\b", "formal eligibility claim"),
    (r"\bentitled\b", "formal eligibility claim"),
    (r"\b(your|account|current|available) balance\b", "balance used as a fact"),
    (r"\b(your|his|her|their|household|family|monthly|regular|total|net) income\b", "inflow called income"),
    (r"\bL&T\b|\bLarsen\b", "lender name inferred from a code"),
    (r"\b(fraud|theft|stole|illegal)\b", "accusation"),
    (r"\b(you must pay by|your deadline is)\b", "unconditional deadline"),
]
IDENTIFIERS = [
    (PAN_RX, "PAN"),
    (MOBILE_RX, "mobile number"),
    (re.compile(r"(?<![\w-])\d{9,}(?![\w-])"), "unmasked account or reference number"),
]


def gate(text: str) -> str:
    for pattern, why in BANNED:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raise UnsafeLanguage(f"blocked '{m.group(0)}': {why}")
    for rx, why in IDENTIFIERS:
        m = rx.search(text)
        if m:
            raise UnsafeLanguage(f"blocked {why}")
    return text


# ---------- formatting ----------
def inr(x: float) -> str:
    n = int(round(x))
    s = str(abs(n))
    if len(s) > 3:                                   # Indian grouping: 1,23,456
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = head + "," + tail
    return ("-" if n < 0 else "") + "₹" + s


def dt(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


def month(p: str) -> str:
    return date.fromisoformat(p + "-01").strftime("%b %Y")


def months(ps: list) -> str:
    names = [month(p) for p in ps]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


OPTION_LABELS = {
    "it_was_this_premium": "Yes, that was it",
    "not_this_policy": "No, it was something else",
    "already_paid": "I've already paid it",
    "due_date_differs": "My due date is different",
    "paid_extra_instalment": "I've paid the extra instalment",
    "lender_says_up_to_date": "The lender says I'm up to date",
    "not_sure_yet": "Not sure yet",
    "yes_that_payment": "Yes, that payment",
    "something_else": "Something else",
    "not_sure": "Not sure",
    "agreed_pause_or_restructure": "We agreed a pause or restructuring",
    "paid_another_way": "It was paid another way or from another account",
    "it_has_ended": "It has ended",
}


def _liq_line(card: Card) -> str:
    e = next((x for x in card.evidence if x.code == "REVEALED_LIQUIDITY"), None)
    if not e:
        return ""
    d = e.data
    tail = " — enough for this payment." if d["covers"] else " — not enough for this payment."
    return (f"Payments that went through suggest this account could cover between "
            f"{inr(d['low'])} and {inr(d['high'])} at the end of {dt(d['point'].removeprefix('end of '))}"
            f"{tail} (An estimate from payment outcomes, not a balance figure.)")


# ---------- templates: one per card code ----------
def _lic(c: Card) -> list:
    r, h, a, rule = c.ev("e_ret").data, c.ev("e_hist").data, c.ev("e_amt").data, c.ev("e_rule").data
    due = c.ev("e_due").data["assumed"]
    lines = [
        f"A payment from your account was returned on {dt(r['return_date'])} — your bank charged {inr(r['charge'])}.",
        f"It looks like your {h['cadence'].lower()} {h['counterparty']} premium (about {inr(a['amount'])}, "
        f"reference ending …{h['ref_tail']}): it is usually collected around the {ordinal(h['usual_day'])} "
        f"and was not collected in {month(c.ev('e_miss').data['period'])}.",
        f"LIC's conditions allow a grace period of {rule['grace']} for {rule['mode']} premiums. "
        f"If this premium was due on {dt(due)}, the grace period ends around {dt(c.deadline.date)}.",
    ]
    liq = _liq_line(c)
    if liq:
        lines.append(liq)
    lines.append("If it is that premium: pay it through LIC's own channels.")
    return lines


def _loan(c: Card) -> list:
    r, h, s = c.ev("e_ret").data, c.ev("e_hist").data, c.deadline.data
    cp = h["counterparty"]
    amt = inr(h["amount_last"])
    touches = [dt(t) for t in s["passed_30_days_on"]]
    lines = [
        f"A collection of {amt} by {cp} on {dt(r['return_date'])} was returned, and your bank charged {inr(r['charge'])}.",
        f"{cp} collects {amt} around the {ordinal(h['usual_day'])} of each month; it looks like a loan instalment.",
        f"Under RBI's rules an instalment not paid on its due date counts as overdue from that day. "
        f"If {cp} applies each payment to the oldest unpaid instalment first and nothing was paid another way, "
        f"the loan would still be {s['instalments_behind']} instalment{'s' if s['instalments_behind'] != 1 else ''} behind"
        + (f", and would have passed 30 days overdue on {', '.join(touches)}." if touches else "."),
        f"Lenders report overdue amounts to credit bureaus on set dates; the next is {dt(c.deadline.date)}. "
        f"One extra {inr(s['cure_amount'])}, plus any charges {cp} has added, would clear it under these assumptions.",
    ]
    liq = _liq_line(c)
    if liq:
        lines.append(liq)
    lines.append(f"Ask {cp}: \"What is my overdue amount today, and how are my payments being applied?\"")
    return lines


def _link_q(c: Card) -> list:
    r = c.ev("e_ret").data
    lines = [f"A payment from your account was returned on {dt(r['return_date'])} — your bank charged {inr(r['charge'])}."]
    if any(e.id == "e_prev" for e in c.evidence):
        p = c.ev("e_prev").data
        lines.append(f"It may be the {inr(p['amount'])} collected by {p['counterparty']} on the {ordinal(p['day'])}, "
                     f"but we have only seen that collection {p['times_seen']} "
                     f"time{'s' if p['times_seen'] != 1 else ''}, so we are not sure.")
    else:
        lines.append("We could not match it to a regular payment.")
    return lines


def _gap_q(c: Card) -> list:
    h, n = c.ev("e_hist").data, c.ev("e_none").data
    return [
        f"{h['counterparty']} usually collects {inr(h['amount_last'])} around the {ordinal(h['usual_day'])}, "
        f"but nothing was collected in {months(n['periods'])} — and there was no return charge either.",
        "That usually means no collection was attempted. Your bank data cannot tell us why.",
    ]


QUESTION_TEXT = {
    "LIC_RETURN_CONFIRM": "Was this your LIC premium?",
    "LOAN_STATUS_CHECK": "What did you find out?",
    "RETURN_LINK_CONFIRM": "Was the returned payment the one we think?",
    "GAP_REASON": "Do you know why?",
}
TEMPLATES = {"LIC_GRACE_CLOCK": _lic, "LOAN_OVERDUE_CLOCK": _loan,
             "RETURN_LINK_QUESTION": _link_q, "COLLECTION_GAP_QUESTION": _gap_q}


def customer_text(card: Card) -> str:
    lines = TEMPLATES[card.code](card)
    if card.question:
        opts = " / ".join(f"[{OPTION_LABELS[o]}]" for o in card.question.options)
        lines.append(f"{QUESTION_TEXT[card.question.code]}  {opts}")
    return gate("\n".join(lines))


def evidence_trail(card: Card) -> str:
    """What the customer sees on 'why do you think this?'. Also gated."""
    out = []
    for e in card.evidence:
        if e.cls == "O":
            src = (f"{len(e.txn_ids)} transaction(s): {', '.join(e.txn_ids[:4])}{' …' if len(e.txn_ids) > 4 else ''}"
                   if e.txn_ids else f"no matching transaction {e.data['absence']['from']} to {e.data['absence']['to']} "
                                     f"(data runs to {e.data['absence']['account_data_until']})")
            out.append(f"[O] {e.code} — {src}")
        elif e.cls == "R":
            rid = e.rule.split("@")[0]
            out.append(f"[R] {e.code} — {RULES[rid]['name']} ({e.rule}); source: {RULES[rid]['citation']}")
        elif e.cls == "I":
            out.append(f"[I] {e.code} — inferred from {', '.join(e.based_on)}")
        else:
            out.append(f"[U] {e.code} — not knowable from bank data; asked in the question")
    if card.deadline:
        out.append(f"Deadline {card.deadline.date}: from {', '.join(card.deadline.basis)}; "
                   f"conditional on {', '.join(card.deadline.conditional_on) or 'nothing unknown'}")
    p = card.provenance
    out.append(f"Provenance: {p['source']} · account {p['account']} · corpus {p['corpus_sha256'][:8]}… · "
               f"rulebook {p['rulebook_version']} · {p['engine']} · as of {p['as_of']}")
    return gate("\n".join(out))


def render(card: Card) -> tuple:
    return customer_text(card), evidence_trail(card)
