"""
Counterparty Mirror - Evaluator: facts x rules -> Cards.

Input : one account's Batch 1a facts (as of a replay date) + the rulebook.
Output: a list of validated Card objects. No customer wording is produced here
        (language.py does that), and nothing is written anywhere.

Four situations produce cards in Batch 1b:
  1. A return strongly linked to an LIC collection   -> LIC_GRACE_CLOCK       (CLOCK)
  2. A return strongly linked to a bank loan          -> LOAN_OVERDUE_CLOCK    (CLOCK)
  3. A return with a weak or no link                  -> RETURN_LINK_QUESTION  (QUESTION)
  4. Expected collections with no debit AND no return -> COLLECTION_GAP_QUESTION (QUESTION)
Everything else stays silent. Deterministic: same data + same as_of -> same cards.
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta

from .cards import Card, Evidence as E, Question, Deadline, card_id
from .corpus import as_of as visible
from .learn import learn_obligations, obligation_key, DAY_TOLERANCE
from .traces import classify_charges, link_returns, RETURN_TO_CHARGE_MAX_DAYS
from .liquidity import revealed_liquidity
from .rules import RULES, RULEBOOK_VERSION, PURPOSE_AA_PROTECT, rule_ref

ENGINE = "mirror-1b"


# ---------- small calendar helpers (real calendar; corpus days are clamped, rules are not) ----------
def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _add_months(d: date, n: int) -> date:
    k = d.year * 12 + d.month - 1 + n
    y, m = divmod(k, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def _period_bounds(period: str) -> tuple:
    y, m = int(period[:4]), int(period[5:7])
    return date(y, m, 1), _month_end(y, m)


def grace_end(due: date, cadence_months: int) -> date:
    p = RULES["LIC_GRACE"]["params"]
    if cadence_months == 1:
        return due + timedelta(days=p["monthly_days"])
    nm = p["non_monthly"]
    return max(_add_months(due, nm["months"]), due + timedelta(days=nm["min_days"]))


def reporting_reference_dates(start: date, end: date) -> list:
    """Credit-bureau reference dates in (start, end], using whichever schedule was in force."""
    out, y, m = [], start.year, start.month
    while date(y, m, 1) <= end:
        for entry in RULES["CIC_REPORTING_CADENCE"]["params"]["schedule"]:
            for rd in entry["reference_days"]:
                d = _month_end(y, m) if rd == "last" else date(y, m, rd)
                lo = date.fromisoformat(entry["effective_from"])
                hi = date.fromisoformat(entry["effective_to"]) if entry["effective_to"] else date.max
                if lo <= d <= hi and start < d <= end:
                    out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return sorted(set(out))


def _schedule_in_force(d: date) -> dict:
    for entry in RULES["CIC_REPORTING_CADENCE"]["params"]["schedule"]:
        hi = date.fromisoformat(entry["effective_to"]) if entry["effective_to"] else date.max
        if date.fromisoformat(entry["effective_from"]) <= d <= hi:
            return entry
    raise LookupError(d)


# ---------- entry point ----------
def evaluate(corpus, acc, as_of_date: date, purposes=frozenset({PURPOSE_AA_PROTECT}),
             confirmed: dict | None = None) -> list:
    """purposes: what the customer consented to. A rule whose purpose is not in
    here never runs. confirmed: customer answers - these arrive in Batch 1c."""
    if confirmed:
        raise NotImplementedError("customer confirmations are wired in Batch 1c")
    if acc.quality != "OK" or PURPOSE_AA_PROTECT not in purposes:
        return []
    txns = visible(acc.txns, as_of_date)
    obligations = learn_obligations(acc, txns, as_of_date)
    traces = link_returns(acc, classify_charges(acc, txns), obligations, txns)
    ctx = {"corpus": corpus, "acc": acc, "as_of": as_of_date, "txns": txns,
           "obs": {o.id: o for o in obligations}, "purposes": purposes,
           "data_until": min(acc.window[1], as_of_date)}

    cards = []
    for tr in traces:
        if tr.kind != "ECS_RETURN":
            continue
        if tr.link_confidence == "strong":
            ob = ctx["obs"][tr.linked_obligation]
            if ob.counterparty.startswith("LIC") and _allowed(ctx, "LIC_GRACE"):
                cards.append(_lic_clock(ctx, tr, ob))
            elif "BANK" in ob.counterparty.split() and _allowed(ctx, "RBI_IRACP_OVERDUE"):
                c = _loan_clock(ctx, tr, ob, traces)
                if c:
                    cards.append(c)
        else:
            cards.append(_link_question(ctx, tr))
    for ob in obligations:
        for run in _unexplained_gaps(ob, traces, ctx["data_until"]):
            cards.append(_gap_question(ctx, ob, run))
    return cards


def _allowed(ctx, rule_id: str) -> bool:
    return RULES[rule_id]["purpose"] in ctx["purposes"]


def _provenance(ctx) -> dict:
    return {"source": "AA (ACME-FIP sandbox)", "account": ctx["acc"].masked,
            "corpus_sha256": ctx["corpus"].sha256, "rulebook_version": RULEBOOK_VERSION,
            "engine": ENGINE, "as_of": ctx["as_of"].isoformat()}


def _absence(ctx, frm: date, to: date) -> dict:
    return {"from": frm.isoformat(), "to": min(to, ctx["data_until"]).isoformat(),
            "account_data_until": ctx["data_until"].isoformat()}


def _history(ob, eid="e_hist") -> E:
    return E(eid, "O", "COLLECTION_HISTORY",
             {"counterparty": ob.counterparty, "cadence": ob.cadence, "usual_day": ob.day_window[0],
              "amount_low": ob.amount_band[0], "amount_high": ob.amount_band[1],
              "amount_last": _last_amount(ob),
              "seen_periods": [o.period for o in ob.occurrences if o.status == "SEEN"],
              "ref_tail": ob.ref_root[-3:]},
             txn_ids=tuple(ob.seen_txn_ids))


def _return_charge(tr, eid="e_ret") -> E:
    return E(eid, "O", "RETURN_CHARGE_POSTED",
             {"charge": tr.total_charge, "charge_posted": tr.posted, "return_date": tr.event_date},
             txn_ids=tuple(tr.txn_ids))


def _last_amount(ob) -> float:
    seen = [o for o in ob.occurrences if o.status == "SEEN"]
    return seen[-1].amount


def _liquidity(ctx, tr, amount, based_on) -> E | None:
    r = revealed_liquidity(ctx["acc"].masked, ctx["txns"], at_end_of=ctx["as_of"],
                           returned={"date": date.fromisoformat(tr.event_date),
                                     "amount": amount, "trace_id": tr.id})
    if r is None or r.high is None:
        return None
    return E("e_liq", "I", "REVEALED_LIQUIDITY",
             {"point": r.point, "low": r.low, "high": r.high, "covers": r.low >= amount,
              "amount": amount, "assumptions": list(r.assumptions),
              "not_considered": list(r.not_considered)},
             txn_ids=(r.lower_bound_txn,), based_on=based_on)


# ---------- 1. LIC grace clock ----------
def _lic_clock(ctx, tr, ob) -> Card:
    ret_date = date.fromisoformat(tr.event_date)
    amount = _last_amount(ob)
    p0, p1 = _period_bounds(f"{ret_date.year:04d}-{ret_date.month:02d}")
    ev = [
        _return_charge(tr),
        _history(ob),
        E("e_miss", "O", "NOT_COLLECTED", {"period": p0.isoformat()[:7], "absence": _absence(ctx, p0, p1)}),
        E("e_link", "I", "LINKED_TO_PAYMENT", {"confidence": tr.link_confidence},
          based_on=("e_ret", "e_hist", "e_miss")),
        E("e_amt", "I", "PRESENTED_AMOUNT", {"amount": amount}, based_on=("e_hist",)),
        E("e_rule", "R", "GRACE_RULE",
          {"mode": ob.cadence.lower(), "grace": "15 days" if ob.cadence_months == 1
           else "one month (and not less than 30 days)"}, rule=rule_ref("LIC_GRACE")),
        E("e_due", "U", "DUE_DATE", {"assumed": ret_date.isoformat()}, resolved_by="q"),
        E("e_paid", "U", "PAID_ANOTHER_WAY", {}, resolved_by="q"),
    ]
    liq = _liquidity(ctx, tr, amount, based_on=("e_link", "e_amt"))
    if liq:
        ev.append(liq)
    return Card(
        id=card_id("LIC_GRACE_CLOCK", ob.id, tr.event_date), type="CLOCK", code="LIC_GRACE_CLOCK",
        member=ctx["acc"].member, account=ctx["acc"].masked, subject=ob.id,
        as_of=ctx["as_of"].isoformat(), evidence=tuple(ev),
        claim=("e_ret", "e_miss", "e_link", "e_rule") + (("e_liq",) if liq else ()),
        provenance=_provenance(ctx),
        deadline=Deadline(grace_end(ret_date, ob.cadence_months).isoformat(), basis=("e_rule",),
                          conditional_on=("e_due", "e_paid")),
        action="PAY_THROUGH_INSURER",
        question=Question("q", "LIC_RETURN_CONFIRM",
                          ("it_was_this_premium", "not_this_policy", "already_paid", "due_date_differs"),
                          resolves=("e_due", "e_paid")))


# ---------- 2. bank loan overdue clock (RBI day-end rule, stated assumptions) ----------
def _implied_overdue(ob, due_day: int, until: date) -> dict:
    """What RBI's rule implies IF payments go to the oldest unpaid instalment first
    and nothing was paid another way. Walks day by day; day-end classification."""
    dues, pays = [], []
    for o in ob.occurrences:
        if o.status not in ("SEEN", "NOT_SEEN"):
            continue
        y, m = int(o.period[:4]), int(o.period[5:7])
        dues.append(date(y, m, min(due_day, calendar.monthrange(y, m)[1])))
        if o.status == "SEEN":
            pays.append(date(y, m, o.day))
    unpaid, touches, spell_start_touched = [], [], False
    d = dues[0]
    while d <= until:
        unpaid += [x for x in dues if x == d]
        for _ in [p for p in pays if p == d]:
            if unpaid:
                unpaid.pop(0)            # oldest first (the assumption)
        if unpaid:
            age = (d - unpaid[0]).days
            if age >= RULES["RBI_IRACP_OVERDUE"]["params"]["sma_1_after_days"] and not spell_start_touched:
                touches.append(d.isoformat())
                spell_start_touched = True
            if age < RULES["RBI_IRACP_OVERDUE"]["params"]["sma_1_after_days"]:
                spell_start_touched = False
        d += timedelta(days=1)
    return {"instalments_behind": len(unpaid),
            "overdue_since": unpaid[0].isoformat() if unpaid else None,
            "passed_30_days_on": touches}


def _loan_clock(ctx, tr, ob, traces) -> Card | None:
    ret_date = date.fromisoformat(tr.event_date)
    if _unexplained_gaps(ob, traces, ctx["data_until"], after=f"{ret_date.year:04d}-{ret_date.month:02d}"):
        return None                                      # PRODUCT_POLICIES["NO_STATE_ACROSS_GAP"]
    due_day = ob.day_window[0]
    state = _implied_overdue(ob, due_day, ctx["as_of"])
    if not state["instalments_behind"]:
        return None                                      # nothing implied overdue: stay quiet
    refs_since = reporting_reference_dates(ret_date, ctx["as_of"])
    nxt = reporting_reference_dates(ctx["as_of"], ctx["as_of"] + timedelta(days=40))[0]
    amount = _last_amount(ob)
    p0, p1 = _period_bounds(f"{ret_date.year:04d}-{ret_date.month:02d}")
    ev = [
        _return_charge(tr),
        _history(ob),
        E("e_miss", "O", "NOT_COLLECTED", {"period": p0.isoformat()[:7], "absence": _absence(ctx, p0, p1)}),
        E("e_link", "I", "LINKED_TO_PAYMENT", {"confidence": tr.link_confidence},
          based_on=("e_ret", "e_hist", "e_miss")),
        E("e_loan", "I", "LOOKS_LIKE_LOAN_INSTALMENT",
          {"counterparty": ob.counterparty, "lender_type": "bank (the collector's own label says BANK)"},
          based_on=("e_hist",)),
        E("e_dueday", "I", "DUE_DAY_FROM_COLLECTIONS", {"day": due_day}, based_on=("e_hist",)),
        E("e_rule", "R", "OVERDUE_RULE", {"sma_1_after_days": 30}, rule=rule_ref("RBI_IRACP_OVERDUE")),
        E("e_cic", "R", "BUREAU_REPORTING_DATES",
          {"next_reference_date": nxt.isoformat(),
           "reference_days_in_force": _schedule_in_force(nxt)["reference_days"],
           "reference_dates_since_return": len(refs_since)},
          rule=rule_ref("CIC_REPORTING_CADENCE")),
        E("e_alloc", "U", "PAYMENT_ALLOCATION", {"assumed": "oldest_first"}, resolved_by="q"),
        E("e_other", "U", "PAID_OR_AGREED_OTHERWISE", {}, resolved_by="q"),
    ]
    liq = _liquidity(ctx, tr, amount, based_on=("e_link", "e_loan"))
    if liq:
        ev.append(liq)
    return Card(
        id=card_id("LOAN_OVERDUE_CLOCK", ob.id, tr.event_date), type="CLOCK", code="LOAN_OVERDUE_CLOCK",
        member=ctx["acc"].member, account=ctx["acc"].masked, subject=ob.id,
        as_of=ctx["as_of"].isoformat(), evidence=tuple(ev),
        claim=("e_ret", "e_miss", "e_link", "e_loan", "e_rule") + (("e_liq",) if liq else ()),
        provenance=_provenance(ctx),
        deadline=Deadline(nxt.isoformat(), basis=("e_rule", "e_cic"),
                          conditional_on=("e_alloc", "e_other"),
                          data=dict(state, cure_amount=amount * state["instalments_behind"])),
        action="ASK_LENDER_OVERDUE_AMOUNT",
        question=Question("q", "LOAN_STATUS_CHECK", ("paid_extra_instalment", "lender_says_up_to_date",
                                                     "not_sure_yet"), resolves=("e_alloc", "e_other")))


# ---------- 3. return we cannot confidently link ----------
def _link_question(ctx, tr) -> Card:
    ev = [_return_charge(tr)]
    if tr.candidates and tr.candidates[0].startswith("UNLEARNED:"):
        rail, name, root = tr.candidates[0].split(":", 1)[1].split("/")
        prev = [t for t in ctx["txns"] if t.kind == "DEBIT" and obligation_key(t.narration) == (rail, name, root)]
        ev.append(E("e_prev", "O", "EARLIER_COLLECTION",
                    {"counterparty": name, "day": prev[0].d.day, "amount": prev[-1].amount,
                     "times_seen": len(prev)}, txn_ids=tuple(t.txn_id for t in prev)))
        ev.append(E("e_cand", "I", "POSSIBLE_MATCH", {"confidence": tr.link_confidence},
                    based_on=("e_ret", "e_prev")))
    ev.append(E("e_which", "U", "WHICH_PAYMENT", {}, resolved_by="q"))
    return Card(
        id=card_id("RETURN_LINK_QUESTION", tr.id, tr.event_date or tr.posted), type="QUESTION",
        code="RETURN_LINK_QUESTION", member=ctx["acc"].member, account=ctx["acc"].masked,
        subject=tr.id, as_of=ctx["as_of"].isoformat(), evidence=tuple(ev), claim=("e_ret",),
        provenance=_provenance(ctx),
        question=Question("q", "RETURN_LINK_CONFIRM", ("yes_that_payment", "something_else", "not_sure"),
                          resolves=("e_which",)))


# ---------- 4. expected collections that simply did not happen ----------
def _settled(period: str, usual_day: int, data_until: date) -> bool:
    """A missing collection is only 'unexplained' once a return charge would
    have had time to post: usual day + tolerance + charge-posting window."""
    y, m = int(period[:4]), int(period[5:7])
    due = date(y, m, min(usual_day, calendar.monthrange(y, m)[1]))
    return due + timedelta(days=DAY_TOLERANCE + RETURN_TO_CHARGE_MAX_DAYS) <= data_until


def _unexplained_gaps(ob, traces, data_until: date, after: str = "") -> list:
    """Runs of consecutive NOT_SEEN periods with no return charge linked to them,
    counting only periods where a return charge would already have posted."""
    returned = {t.event_date[:7] for t in traces
                if t.kind == "ECS_RETURN" and t.linked_obligation == ob.id and t.event_date}
    runs, cur = [], []
    for o in ob.occurrences:
        if (o.status == "NOT_SEEN" and o.period not in returned and o.period > after
                and _settled(o.period, ob.day_window[1], data_until)):
            cur.append(o.period)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _gap_question(ctx, ob, periods: list) -> Card:
    frm = _period_bounds(periods[0])[0]
    to = _period_bounds(periods[-1])[1]
    ab = _absence(ctx, frm, to)
    ev = (
        _history(ob),
        E("e_none", "O", "NOT_COLLECTED", {"periods": periods, "absence": ab}),
        E("e_noret", "O", "NO_RETURN_CHARGE", {"periods": periods, "absence": ab}),
        E("e_why", "U", "REASON_FOR_GAP", {}, resolved_by="q"),
    )
    return Card(
        id=card_id("COLLECTION_GAP_QUESTION", ob.id, periods[0]), type="QUESTION",
        code="COLLECTION_GAP_QUESTION", member=ctx["acc"].member, account=ctx["acc"].masked,
        subject=ob.id, as_of=ctx["as_of"].isoformat(), evidence=ev,
        claim=("e_hist", "e_none", "e_noret"), provenance=_provenance(ctx),
        question=Question("q", "GAP_REASON", ("agreed_pause_or_restructure", "paid_another_way",
                                              "it_has_ended", "not_sure"), resolves=("e_why",)))
