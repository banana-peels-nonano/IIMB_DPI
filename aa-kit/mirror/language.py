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
from .facts import FACTS
from .rules import rule, STATE_RULES
from .snapshot import display_name


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
    # Gate 4: what we don't see is never "not enrolled"; and no product advice
    (r"\b(not|never|isn't|aren't|wasn't|weren't)\s+(enrolled|covered|insured|a member)\b",
     "enrolment status we cannot observe"),
    (r"\b(you|he|she|they)\s+(don't|do not|doesn't|does not)\s+have\s+(any\s+)?(cover|insurance|a pension)\b",
     "enrolment status we cannot observe"),
    (r"\byou should (buy|enrol|join|invest|switch)\b", "product advice"),
    (r"\b(replace|cancel|surrender) (your|his|her|their) (LIC|policy|insurance|cover)\b", "product advice"),
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
for _code, _spec in FACTS.items():                  # Gate 4: every household-fact answer
    for _v, _label in _spec["values"].items():
        OPTION_LABELS.setdefault(_v, _label)


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


# ---------- Gate 4 + 5 templates: Unlock and the LPG record ----------
def _who(c: Card) -> str:
    return display_name(c.member).split()[0]


def _window(e) -> str:
    a = e.data["absence"]
    return f"{dt(a['from'])} – {dt(a['to'])}"


def scheme_copy(scheme: str) -> dict:
    p = STATE_RULES[scheme]["params"]
    if scheme == "PMSBY":
        return {"kind": "Accident cover", "ages": f"{p['age_min']}–{p['age_max']}",
                "what": (f"pays {inr(p['cover_inr']['death_or_permanent_total_disability'])} on accidental death "
                         f"or permanent total disability ({inr(p['cover_inr']['partial_disability'])} for partial "
                         f"disability), for {inr(p['premium_inr'])} a year taken by auto-debit")}
    if scheme == "PMJJBY":
        return {"kind": "Life cover", "ages": f"{p['age_min']}–{p['age_max']} at joining",
                "what": (f"pays {inr(p['cover_inr'])} on death from any cause, for {inr(p['premium_inr'])} a year "
                         f"taken by auto-debit; the cover can continue to age {p['cover_until_age']}")}
    return {"kind": "Pension", "ages": f"{p['age_min']}–{p['age_max']} at joining",
            "what": (f"pays a pension of {inr(p['pension_options_inr'][0])}–{inr(p['pension_options_inr'][-1])} "
                     f"a month from age {p['pension_from_age']}, for regular contributions taken by auto-debit")}


def _or(xs: list) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " or " + xs[-1]


def _age_q(c: Card) -> list:
    who = _who(c)
    asked = [e.data["scheme"] for e in c.evidence if e.code == "SCHEME_RULE"]
    seen = [e.data["scheme"] for e in c.evidence if e.code == "SCHEME_DEBIT_SEEN"]
    ns = next(e for e in c.evidence if e.code == "SCHEME_DEBIT_NOT_SEEN")
    limits = ", ".join(f"{s} ({scheme_copy(s)['ages']})" for s in asked)
    lines = [f"{len(asked)} government protection{'s' if len(asked) != 1 else ''} with age limits could matter "
             f"for {who}: {limits}.",
             f"We don't see {_or(asked)} in {who}'s connected account ({_window(ns)}). "
             f"That doesn't tell us about other accounts."]
    if seen:
        lines.append(f"We do see {' and '.join(seen)} in {who}'s account.")
    lines.append("We only ask for an age band — never a date of birth.")
    return lines


def _tax_q(c: Card) -> list:
    who, a = _who(c), scheme_copy("APY")
    return [f"APY {a['what']}. It is for people who join at 18–40 and are not income-tax payers.",
            f"You told us {who} is {OPTION_LABELS[c.ev('e_age').data['answered']]}. "
            f"We don't see APY contributions in {who}'s connected account ({_window(c.ev('e_ns'))})."]


def _door_t(c: Card) -> list:
    who = _who(c)
    scheme = c.ev("e_rule").data["scheme"]
    a = scheme_copy(scheme)
    told = [f"{who} is {OPTION_LABELS[c.ev('e_age').data['answered']]}"]
    if scheme == "APY":
        told.append({"no": f"{who} has not paid income tax",
                     "not_sure": f"you're not sure whether {who} has ever paid income tax — if so, APY is closed"}
                    [c.ev("e_tax").data["answered"]])
    lines = [f"{a['kind']} worth checking: {scheme} {a['what']}. It is for ages {a['ages']}.",
             f"You told us {' and '.join(told)}.",
             f"We don't see {scheme} in {who}'s connected account ({_window(c.ev('e_ns'))}) — "
             f"but it could be through another bank or the post office."]
    cov = c.ev("e_cov")
    if cov.answered:
        lines.append({"no": f"You told us {who} doesn't have it through another account.",
                      "not_sure": f"You weren't sure whether {who} has it through another account — "
                                  f"the bank can check."}[cov.data["answered"]])
    if scheme == "PMJJBY":
        lines.append("New cover doesn't pay for death other than by accident in the first 30 days.")
    lines.append(f"Only a bank or post office can enrol {who} and confirm the terms.")
    return lines


def _not_shown_t(c: Card) -> list:
    who = _who(c)
    scheme = c.ev("e_rule").data["scheme"]
    if c.ev("e_age").data.get("reason") == "TAXPAYER":
        return [f"{scheme} isn't shown for {who}: it is for people who are not income-tax payers, and you told us "
                f"{who} is or has been one."]
    return [f"{scheme} isn't shown for {who}: the published rule is for ages {scheme_copy(scheme)['ages']}, "
            f"and you told us {who} is {OPTION_LABELS[c.ev('e_age').data['answered']]}."]


def _pmuy_t(c: Card) -> list:
    d = c.ev("e_credits").data
    return [f"Ujjwala (PMUY) isn't shown: it gives new LPG connections to households that don't have one, and "
            f"{d['count']} LPG subsidy credits from {d['payer_label']} in {_who(c)}'s account "
            f"({dt(d['first'])} – {dt(d['last'])}) show the household has had a connection."]


def _lpg_base(c: Card) -> str:
    d, n = c.ev("e_credits").data, c.ev("e_none").data
    return (f"{_who(c)}'s account received {d['count']} LPG subsidy credits from {d['payer_label']} between "
            f"{dt(d['first'])} and {dt(d['last'])} ({inr(d['amount_low'])}–{inr(d['amount_high'])} each) — "
            f"none since (data runs to {dt(n['absence']['account_data_until'])}).")


LOOKUP_REASON = {"ID_NOT_RECOGNISED": "the LPG ID wasn't recognised", "TIMEOUT": "the record didn't answer in time",
                 "UNREACHABLE_OR_TIMEOUT": "the record didn't answer",
                 "NO_USABLE_FIELDS": "the record didn't include a usable last booking date",
                 "AMBIGUOUS_RECORD": "the record mixed more than one connection",
                 "NOT_JSON": "the record's reply was unreadable", "NOT_JSON_OBJECT": "the record's reply was unreadable",
                 "PURPOSE_NOT_GRANTED": "the LPG check isn't switched on"}


def _lookup_note(c: Card) -> list:
    lk = c.provenance.get("dpi_lookup")
    if not lk:
        return []
    why = LOOKUP_REASON.get(lk["reason"], "the record returned an error")
    sim = " (simulated failure)" if lk["mode"] == "simulated" else ""
    return [f"We tried to check the oil company's record on {dt(lk['on'])} but couldn't: {why}{sim}. "
            f"Nothing has changed."]


def _lpg_q(c: Card) -> list:
    lines = [_lpg_base(c),
             "Subsidy is paid into a bank account for each refill, so there are two ordinary explanations: no "
             "refills since then, or the subsidy is going to another account (government transfers go to the "
             "bank where the Aadhaar number was given last)."]
    r = c.ev("e_refills")
    if r.answered:
        lines.append({"still_booking": "You told us refills are still being booked.",
                      "not_sure": "You weren't sure whether refills were booked."}[r.data["answered"]])
    return lines + _lookup_note(c)


def _routing_t(c: Card) -> list:
    rec, fnd, cr = c.ev("e_rec").data, c.ev("e_find").data["finding"], c.ev("e_credits").data
    sim = rec["record"]["mode"] == "simulated"
    head = ("SIMULATED record — " if sim else "") + "the oil company's record (via Perfios Hub) says"
    refills = rec.get("subsidised_refills")
    facts = [f"the last refill was booked on {dt(rec['last_booking_date'])}"]
    if refills is not None:
        facts.append(f"{refills} subsidised refill{'s' if refills != 1 else ''} this year")
    lines = [f"{head}: {', '.join(facts)} — after the last subsidy credit on {dt(cr['last'])}."]
    tail, bank = rec.get("account_tail"), rec.get("bank_name")
    if fnd == "ELSEWHERE":
        lines.append(f"It says the subsidy is paid into an account ending {tail}{f' at {bank}' if bank else ''}. "
                     f"None of your connected accounts ends in {tail}, and no subsidy has arrived in them since "
                     f"{dt(cr['last'])}.")
        lines.append("Government transfers go to the bank where the Aadhaar number was given last. To move the "
                     "subsidy to an account you use, give your Aadhaar number to that bank for DBT seeding "
                     "(or use NPCI's BASE service).")
    elif fnd == "NOT_SHOWN":
        lines.append("It doesn't show which bank account the subsidy goes to, so we can't tell where it went.")
        lines.append("Your bank can tell you which account your Aadhaar number is linked to for government transfers.")
    elif fnd == "SAME":
        lines.append(f"It says the subsidy goes to an account ending {tail} — the same last 4 digits as "
                     f"{_who(c)}'s connected account — but no subsidy has arrived there since {dt(cr['last'])}. "
                     f"Your distributor can say whether subsidy was paid.")
    elif fnd == "OTHER_MEMBER":
        other = c.ev("e_find").data["other_member"]
        lines.append(f"It says the subsidy goes to an account ending {tail} — the same last 4 digits as "
                     f"{other}'s connected account. Four digits can't prove it is the same account, and this "
                     f"check only looked for subsidy credits in {_who(c)}'s account.")
    else:
        lines.append("It says the subsidy on this connection was given up. If that wasn't your choice, your "
                     "distributor can explain how to restart it.")
    if sim:
        lines.append("We couldn't do a live lookup: there's no valid LPG ID from a consenting member of this "
                     "household. This SIMULATED record shows exactly what the product does with a real one.")
    return lines


QUESTION_TEXT = {
    "LIC_RETURN_CONFIRM": "Was this your LIC premium?",
    "LOAN_STATUS_CHECK": "What did you find out?",
    "RETURN_LINK_CONFIRM": "Was the returned payment the one we think?",
    "GAP_REASON": "Do you know why?",
    "AGE_BAND": "Which age band is {who} in?",
    "TAXPAYER": "Is {who} an income-tax payer now, or has {who} ever been one?",
    "COVERED_ELSEWHERE": "Does {who} already have this through another account?",
    "LPG_REFILLS": "Have refills been booked since the last credit?",
    "SUBSIDY_ACCOUNT": "Do you know which account gets the subsidy?",
    "ROUTED_ACCOUNT_STATUS": "Is that account yours, and do you still use it?",
    "SUBSIDY_GIVEN_UP": "Did you choose to give up the subsidy?",
    "DISTRIBUTOR_ANSWER": "What does your distributor say?",
}
TEMPLATES = {"LIC_GRACE_CLOCK": _lic, "LOAN_OVERDUE_CLOCK": _loan,
             "RETURN_LINK_QUESTION": _link_q, "COLLECTION_GAP_QUESTION": _gap_q,
             "AGE_BAND_QUESTION": _age_q, "TAXPAYER_QUESTION": _tax_q, "PROTECTION_DOOR": _door_t,
             "PROTECTION_NOT_SHOWN": _not_shown_t, "PMUY_NOT_SHOWN": _pmuy_t,
             "LPG_SUBSIDY_QUESTION": _lpg_q, "LPG_SUBSIDY_ROUTING": _routing_t}


def question_text(card: Card) -> str:
    return gate(QUESTION_TEXT[card.question.code].format(who=_who(card)))


def customer_text(card: Card) -> str:
    lines = TEMPLATES[card.code](card)
    if card.question:
        opts = " / ".join(f"[{OPTION_LABELS[o]}]" for o in card.question.options)
        lines.append(f"{question_text(card)}  {opts}")
    return gate("\n".join(lines))


def evidence_trail(card: Card) -> str:
    """What the customer sees on 'why do you think this?'. Also gated."""
    out = []
    for e in card.evidence:
        if e.cls == "O":
            rec = e.data.get("record")
            if rec:
                src = (f"{'SIMULATED ' if rec['mode'] == 'simulated' else ''}record from the oil company via "
                       f"Perfios Hub, ref {rec['request_ref']}, requested {rec['requested_on']}")
            elif e.txn_ids:
                src = f"{len(e.txn_ids)} transaction(s): {', '.join(e.txn_ids[:4])}{' …' if len(e.txn_ids) > 4 else ''}"
            else:
                src = (f"no matching transaction {e.data['absence']['from']} to {e.data['absence']['to']} "
                       f"(data runs to {e.data['absence']['account_data_until']})")
            out.append(f"[O] {e.code} — {src}")
        elif e.cls == "R":
            rid = e.rule.split("@")[0]
            out.append(f"[R] {e.code} — {rule(rid)['name']} ({e.rule}); source: {rule(rid)['citation']}")
        elif e.cls == "I":
            out.append(f"[I] {e.code} — inferred from {', '.join(e.based_on)}")
        elif e.answered:
            out.append(f"[U] {e.code} — you told us: {OPTION_LABELS[e.data['answered']]} "
                       f"(on {e.data['stated_on']}); a statement, not something we observed")
        else:
            out.append(f"[U] {e.code} — not knowable from bank data; asked in the question")
    if card.deadline:
        out.append(f"Deadline {card.deadline.date}: from {', '.join(card.deadline.basis)}; "
                   f"conditional on {', '.join(card.deadline.conditional_on) or 'nothing unknown'}")
    p = card.provenance
    out.append(f"Provenance: {p['source']} · account {p['account']} · corpus {p['corpus_sha256'][:8]}… · "
               f"rulebook {p['rulebook_version']} · {p['engine']} · as of {p['as_of']}"
               + (" · SIMULATED record" if p.get("simulated") else ""))
    return gate("\n".join(out))


def render(card: Card) -> tuple:
    return customer_text(card), evidence_trail(card)
