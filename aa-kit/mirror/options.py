"""
"Within an amount you set" (--options): a deterministic, neutral options explorer. NOT a recommender.

    out = build_options(state, payload, member, amount)     # pure: no network, no LLM, nothing stored
    validate_options(out, state, payload)                    # fails closed (OptionsInvalid)

The customer's amount (a closed set) is used for ONE thing only: a one-by-one comparison with each
published option's single debit. It is never income, spare cash, affordability, an allocation or a
remainder; it is never added up, subtracted or divided, and it is never written anywhere.

Three concepts, kept apart:
  RUNNING / NO_COST   - obligations and zero-cost actions already on the member's cards (context, never
                        compared with the amount)
  WITHIN / OVER       - published options (only schemes the engine already shows as WORTH_CHECKING),
                        in rulebook order, never ranked
  GOING_OUT           - observed regular collections (context, never compared with the amount)
"""
from __future__ import annotations
import re
from datetime import date

from .contract import PayloadInvalid
from .language import gate, inr, dt, ordinal, scheme_copy
from .rules import STATE_RULES
from .options_rules import (OPTIONS_RULES_VERSION, PMJJBY_FIRST_PREMIUM, APY_MONTHLY, APY_PENSION_LEVELS,
                            APY_TABLE, AMOUNTS, BAND_AGES, pmjjby_first_premium)

VERSION = "options/1.0"
SECTION_ORDER = ("RUNNING", "NO_COST", "WITHIN", "OVER", "NOT_SHOWN", "GOING_OUT", "CANNOT_TELL", "NONE")
SCHEME_ORDER = ("PMSBY", "PMJJBY", "APY")            # rulebook order: accident cover, life cover, pension
NO_COST_ACTIONS = {"RESEED_OR_ASK_DISTRIBUTOR"}      # actions on existing cards that cost nothing
GAP_QUESTIONS = {"COLLECTION_GAP_QUESTION"}

# words the options screen may never use (on top of language.gate)
BANNED_OPTIONS = [
    (r"\bbest\b", "ranking"), (r"\brecommend(s|ed|ation)?\b", "advice"), (r"\bsuitab(le|ility)\b", "advice"),
    (r"\bsuits you\b", "advice"), (r"\bideal\b", "advice"), (r"\bafford(s|able|ability)?\b", "affordability"),
    (r"\bspare\b", "spare cash"), (r"\bdisposable\b", "disposable income"), (r"\ballocat(e|es|ed|ion)\b", "allocation"),
    (r"\bappropriate for you\b", "advice"), (r"\bright for you\b", "advice"), (r"\bwe selected\b", "selection"),
    (r"\btop pick\b", "selection"), (r"\byou should (take|choose|pick|start)\b", "advice"),
    (r"\bremaining\b|\bleft over\b|\bleftover\b", "remainder"),
]
# products that must never appear as an option (securities, commercial insurance)
OUT_OF_SCOPE = re.compile(r"\b(mutual fund|SIP|equit(y|ies)|shares?|stocks?|bonds?|gold|ULIP|term plan|"
                          r"endowment|NPS tier|crypto|fixed deposit|recurring deposit|PPF|Sukanya)\b", re.I)
FORBIDDEN_KEYS = {"rank", "ranking", "score", "total", "sum", "remainder", "remaining", "left", "split",
                  "allocation", "allocate", "pick", "picked", "recommended", "recommendation", "best", "top",
                  "affordable", "spare", "disposable", "priority"}
RUNNING_KEYS = {"card_id", "title", "amount_inr", "amount_text", "deadline_date", "deadline_line",
                "action_text", "classes", "evidence_note"}
NO_COST_KEYS = {"card_id", "action_text", "simulated", "classes"}
GOING_OUT_KEYS = {"kind", "label", "amount_inr", "cadence", "usual_days", "status", "text", "classes", "txn_ids"}


class OptionsRefused(ValueError):
    """A request Mirror will not answer (unknown member, amount outside the closed set)."""


class OptionsInvalid(PayloadInvalid):
    """The computed screen broke a rule. Nothing is shown (fail closed)."""


def _g(text: str) -> str:
    """The existing language gate, plus the options screen's own banned phrases."""
    text = gate(text)
    for pat, why in BANNED_OPTIONS:
        if re.search(pat, text, flags=re.I):
            raise OptionsInvalid(f"banned on the options screen ({why}): {text[:80]}")
    return text


# ---- fixed copy (the approved design, section 2) ----
REPLY = _g("Mirror doesn't pick a scheme or policy for you. It can show what is within an amount you set: the "
           "published cost of each, and what only you or the institution can tell.")
BUTTON = _g("See what's within an amount")
LINK = _g("What's within an amount you set?")
STEP1 = {"title": _g("Within an amount you set"),
         "lede": _g("Tell us about how much could be set aside each month. Mirror lists what your bank data and "
                    "the published rules put on the table, and what each costs. It doesn't rank them or pick one."),
         "for_label": _g("For"), "amount_label": _g("About how much a month?"),
         "fine": _g("Used for this answer only. Mirror doesn't save it."), "show": _g("Show"),
         "none_watched": _g("Mirror infers nothing from this household's data, so it has no options to list."),
         "amounts": [{"value": a, "label": inr(a)} for a in AMOUNTS]}


def _facts(payload, member) -> dict:
    return {f["fact"]: f for f in payload["what_we_know"]["household_facts"] if f["member"] == member}


def _band(f) -> str | None:
    return f["AGE_BAND"]["answer"] if "AGE_BAND" in f else None


def _engine_amount(card) -> float | None:
    """The amount already on an open clock: the presented amount (LIC) or the rule-implied cure (loan)."""
    for e in card.evidence:
        if e.code == "PRESENTED_AMOUNT" and isinstance(e.data, dict) and "amount" in e.data:
            return float(e.data["amount"])
    if card.deadline is not None and isinstance(card.deadline.data, dict) and "cure_amount" in card.deadline.data:
        return float(card.deadline.data["cure_amount"])
    return None


def _scheme_option(scheme, member, facts, as_of: date, amount: int, row) -> tuple:
    """(section, item) for one WORTH_CHECKING scheme. Figures come from the rulebook or a cited table."""
    p = STATE_RULES[scheme]["params"]
    kind = scheme_copy(scheme)["kind"]
    label = f"{kind}: {scheme}"
    band = _band(facts)
    told = f"You told us {member} is {band}" if band else ""
    sources = [{"label": f"Department of Financial Services, {scheme}", "url": STATE_RULES[scheme]["source"],
                "checked": STATE_RULES[scheme]["last_verified"]}]
    item = {"scheme": scheme, "label": label, "rule": f"{scheme}@{STATE_RULES[scheme]['version']}",
            "facts_used": list(row["facts_used"]), "classes": ["R", "U"] if band else ["R"]}
    if scheme == "PMSBY":
        prem = p["premium_inr"]
        item["pays"] = _g(f"{label}. Pays {inr(p['cover_inr']['death_or_permanent_total_disability'])} on accidental "
                          f"death or permanent total disability ({inr(p['cover_inr']['partial_disability'])} for "
                          f"partial disability). {inr(prem)} a year, taken by auto-debit around 1 June.")
        item["payments"] = [{"when": "each year, around 1 June", "inr": prem}]
        item["largest_single_debit"] = prem
        within = prem <= amount
    elif scheme == "PMJJBY":
        first, months = pmjjby_first_premium(as_of.month)
        annual = p["premium_inr"]
        item["pays"] = _g(f"{label}. Pays {inr(p['cover_inr'])} on death from any cause; cover can continue to "
                          f"{p['cover_until_age']}. {inr(first)} the first time if joining in {months}, then "
                          f"{inr(annual)} a year around 1 June. New cover doesn't pay for death other than by "
                          f"accident in the first {p['first_days_without_non_accident_cover']} days.")
        item["payments"] = [{"when": f"first time, if joining in {months}", "inr": first},
                            {"when": "each year after, around 1 June", "inr": annual}]
        item["largest_single_debit"] = max(first, annual)
        sources.append({"label": PMJJBY_FIRST_PREMIUM["source_label"] + " (first-time premium by month)",
                        "url": PMJJBY_FIRST_PREMIUM["source"], "checked": PMJJBY_FIRST_PREMIUM["checked"]})
        within = item["largest_single_debit"] <= amount
    else:  # APY
        lo, hi = BAND_AGES.get(facts["AGE_BAND"]["value"]) if "AGE_BAND" in facts else (None, None)
        ages = [a for a in range(max(lo, 18), min(hi, 40) + 1)] if lo is not None else []
        if not ages:
            raise OptionsInvalid("APY shown for a member whose age band has no APY joining age")
        rows = []
        for i, level in enumerate(APY_PENSION_LEVELS):
            vals = [APY_MONTHLY[a][i] for a in ages]
            fit = [a for a in ages if APY_MONTHLY[a][i] <= amount]
            fit_text = (f"within {inr(amount)} when joining at {fit[0]}–{fit[-1]}" if fit
                        else f"more than {inr(amount)} at every joining age")
            rows.append({"pension": level, "min": min(vals), "max": max(vals),
                         "within_ages": [fit[0], fit[-1]] if fit else None,
                         "text": _g(f"{inr(level)} pension: {inr(min(vals))}–{inr(max(vals))} a month; {fit_text}")})
        item["pays"] = _g(f"{label}. A pension of {inr(APY_PENSION_LEVELS[0])}–{inr(APY_PENSION_LEVELS[-1])} a month "
                          f"from age {p['pension_from_age']}. The monthly amount depends on the exact age at joining, "
                          f"which only the bank asks for:")
        item["rows"] = rows
        item["joining_ages"] = [ages[0], ages[-1]]
        if facts.get("TAXPAYER", {}).get("value") == "no":
            told += ", and not an income-tax payer"
        sources.append({"label": APY_TABLE["source_label"], "url": APY_TABLE["source"], "checked": APY_TABLE["checked"]})
        within = any(r["within_ages"] for r in rows)
    item["facts_text"] = _g(told + ".") if told else None
    item["sources"] = sources
    item["sources_text"] = _g("Published rule · " + "; ".join(f"{s['label']}, checked {dt(s['checked'])}" for s in sources))
    item["tag"] = _g(f"within {inr(amount)}" if within else f"more than {inr(amount)} in one go")
    return ("WITHIN" if within else "OVER"), item


def build_options(state, payload, member, amount) -> dict:
    """Pure. Reads the household's validated payload and its engine state; returns the options screen."""
    if isinstance(amount, bool) or not isinstance(amount, int) or amount not in AMOUNTS:
        raise OptionsRefused("the amount must be one of the listed amounts")
    watched = {m["display_name"].split()[0]: m for m in payload["our_household"]["members"] if m["status"] == "watched"}
    if not isinstance(member, str) or member not in watched:
        raise OptionsRefused("that member has no connected account Mirror reads")
    as_of = date.fromisoformat(payload["generated"]["as_of"])
    X = inr(amount)
    facts = _facts(payload, member)
    cards = [c for c in payload["now"]["cards"] if c["member"] == member]
    engine = {c.id: c for c, _ in state.open_cards}

    # RUNNING: open clocks for this member, by deadline date. Context only: never compared with the amount.
    running = []
    for c in sorted((c for c in cards if c["type"] == "CLOCK"), key=lambda c: ((c.get("deadline") or {}).get("date") or "9999", c["id"])):
        amt = _engine_amount(engine[c["id"]])
        dl = c.get("deadline") or {}
        line = next((b for b in c["body"] if dl.get("date") and dt(dl["date"]) in b), None)
        running.append({"card_id": c["id"], "title": c["title"], "amount_inr": amt,
                        "amount_text": _g(f"About {inr(amt)}.") if amt is not None else None,
                        "deadline_date": dl.get("date"), "deadline_line": line,
                        "action_text": (c.get("action") or {}).get("action_text"),
                        "classes": list(c["evidence_classes"])})
    blocked = sum(1 for c in cards if c["code"] in GAP_QUESTIONS)

    # NO_COST: zero-cost actions already on this member's open cards (verbatim)
    no_cost = [{"card_id": c["id"], "action_text": c["action"]["action_text"], "simulated": bool(c.get("simulated")),
                "classes": list(c["evidence_classes"])}
               for c in cards if (c.get("action") or {}).get("code") in NO_COST_ACTIONS]

    # WITHIN / OVER / NOT_SHOWN: only from the engine's protection statuses for this member
    pr = payload["our_household"]["protections"]
    within, over, not_shown = [], [], []
    rows = {}
    if pr.get("switched_on"):
        for m in pr["members"]:
            if m["member"] == member:
                rows = {s["scheme"]: s for s in m["schemes"]}
    band = _band(facts)
    for scheme in SCHEME_ORDER:
        row = rows.get(scheme)
        if row is None:
            continue
        label = f"{scheme_copy(scheme)['kind']}: {scheme}"
        st = row["status"]
        if st == "WORTH_CHECKING":
            where, item = _scheme_option(scheme, member, facts, as_of, amount, row)
            (within if where == "WITHIN" else over).append(item)
        elif st == "NOT_APPLICABLE":
            if "income-tax" in row["status_text"]:
                why = f"It is closed to income-tax payers, and you told us {member} is or has been one."
            else:
                ages = scheme_copy(scheme)["ages"]
                rule = (f"Joining is for ages {ages.replace(' at joining', '')}" if "at joining" in ages
                        else f"It is for ages {ages}")
                why = f"{rule}, and you told us {member} is {band}." if band else f"{rule}."
            not_shown.append({"scheme": scheme, "type": "rule", "text": _g(f"Not shown for {member}: {label}. {why}"),
                              "facts_used": list(row["facts_used"]), "classes": ["R", "U"]})
        elif st == "COVERED_ELSEWHERE":
            not_shown.append({"scheme": scheme, "type": "told",
                              "text": _g(f"Not shown for {member}: {label}. You told us {member} already has it "
                                         f"through another account."),
                              "facts_used": list(row["facts_used"]), "classes": ["U"]})
        elif st in ("NEEDS_AGE", "NEEDS_TAXPAYER"):
            not_shown.append({"scheme": scheme, "type": "needs_answer",
                              "text": _g(f"{scheme} needs one more answer first." if st == "NEEDS_TAXPAYER"
                                         else f"{scheme} needs an age band first."),
                              "facts_used": list(row["facts_used"]), "classes": ["U"]})
        elif st == "NOT_ENOUGH_DATA":
            not_shown.append({"scheme": scheme, "type": "data", "facts_used": [], "classes": ["O"],
                              "text": _g(f"Not shown for {member}: {label}. There is not enough data in this "
                                         f"account to look.")})
        # SEEN appears under GOING_OUT (observed), never as an option

    # GOING_OUT: observed regular collections and scheme premiums seen (context; never compared)
    going = []
    for c in payload["our_household"]["commitments"]:
        if c["member"] != member:
            continue
        d0, d1 = c["usual_days"][0], c["usual_days"][-1]
        when = f"around the {ordinal(d0)}" if d0 == d1 else f"between the {ordinal(d0)} and the {ordinal(d1)}"
        gap = "; collections stopped and we asked you why" if c["status"].startswith("gap") else ""
        going.append({"kind": "collection", "label": c["label"], "amount_inr": c["last_amount"],
                      "cadence": c["cadence"], "usual_days": list(c["usual_days"]), "status": c["status"],
                      "txn_ids": list(c["txn_ids"]), "classes": ["O"],
                      "text": _g(f"{c['label']}: about {inr(c['last_amount'])} {c['cadence'].lower()}, {when}{gap}.")})
    for o in payload["our_household"].get("protections_observed", []):
        if o["member"] == member and o["direction"] == "paid":
            going.append({"kind": "scheme_premium", "label": o["label"], "amount_inr": None, "cadence": None,
                          "usual_days": None, "status": "seen", "txn_ids": list(o["txn_ids"]), "classes": ["O"],
                          "text": _g(f"{o['label']}: seen in this account, last on {dt(o['last_date'])}.")})

    out = {
        "version": VERSION, "rules_version": OPTIONS_RULES_VERSION, "as_of": as_of.isoformat(),
        "member": member, "amount": amount, "amount_basis": {"class": "U", "stored": False},
        "compare_rule": "largest single debit of each published option compared with the amount, one by one; never summed",
        "header": {"title": _g(f"Within {X} a month · {member}"), "badge": _g("You told us · not saved"),
                   "lines": [_g(f"\"Within\" compares each option's amount taken in one go with {X}. Each option is "
                                f"compared on its own. Mirror doesn't add them up or divide {X} among them."),
                             _g(f"{X} is the number you entered. Mirror doesn't treat it as earnings or as money "
                                f"that is free to spend."),
                             _g(f"These are listed because published rules put them on the table for {member}, not "
                                f"because Mirror picked them or decided they fit your situation.")]},
        "groups": {"context_cards": _g("From your cards · context, not options"),
                   "options": _g("Published options you can look at"),
                   "observed": _g("Seen in your bank data · context only")},
        "protections_off": not pr.get("switched_on"),
        "sections": [
            {"kind": "RUNNING", "heading": _g("Already running"),
             "lede": _g(f"Obligations already in motion, from your cards. They are shown for context, not as options, "
                        f"and not set against {X}."),
             "empty": _g(f"Nothing with a published deadline is running for {member}."),
             "items": running, "blocked_questions": blocked,
             "blocked_text": _g(f"{blocked} of {member}'s collections stopped without a return charge. Mirror can't "
                                f"put a cost on them until you tell us why.") if blocked else None},
            {"kind": "NO_COST", "heading": _g("Costs nothing"), "empty": _g(f"Nothing that costs ₹0 is open for {member}."),
             "items": no_cost},
            {"kind": "WITHIN", "heading": _g("Protections worth checking: published costs"),
             "subheading": _g(f"Within {X}"),
             "empty": _g(f"None of the protections worth checking for {member} is within {X}."),
             "off_text": _g("Switch on \"Check government protections\" to see published costs."),
             "items": within},
            {"kind": "OVER", "heading": _g(f"Also worth checking, but more than {X} in one go"),
             "empty": _g(f"None is more than {X}."), "items": over},
            {"kind": "NOT_SHOWN", "heading": _g("Not shown, and why"), "empty": _g("Nothing else to note."),
             "items": not_shown},
            {"kind": "GOING_OUT", "heading": _g("Already going out"),
             "lede": _g(f"Regular collections we see in {member}'s connected account, for context only. Mirror doesn't "
                        f"subtract them from {X}, and it can't see cash, other accounts or other spending."),
             "empty": _g(f"No regular collections recognised in {member}'s connected account."),
             "items": going},
            {"kind": "CANNOT_TELL", "heading": _g("What Mirror can't tell you"),
             "lines": [_g(f"Whether {X} can be set aside. Mirror can't see cash, other accounts or spending."),
                       _g("Which of these, if any, fits your life. That depends on things only you know."),
                       _g("The exact APY amount. It depends on your exact age at joining."),
                       _g("Whether you already have cover through another bank or the post office."),
                       _g("What a lender or insurer says about any payment.")]},
            {"kind": "NONE", "heading": _g("None of these"),
             "lines": [_g("Doing none of these is also an option. Nothing here is required."),
                       _g("Only a bank or post office can enrol you and confirm the terms. Mirror never enrols you "
                          "or moves money.")]},
        ],
        "footer": _g("Mirror doesn't rank these or pick one. Every figure comes from the published source shown with "
                     "it. Nothing on this list pays Mirror."),
    }
    return out


# ---------------------------------------------------------------- validation (fails closed)
def _walk(x, path="$"):
    if isinstance(x, dict):
        for k, v in x.items():
            yield path, k, v
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _walk(v, f"{path}[{i}]")


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def validate_options(out: dict, state, payload) -> dict:
    def bad(msg):
        raise OptionsInvalid(msg)

    if out.get("version") != VERSION or out.get("rules_version") != OPTIONS_RULES_VERSION:
        bad("wrong version")
    amount = out.get("amount")
    if isinstance(amount, bool) or amount not in AMOUNTS:
        bad("amount outside the closed set")
    if out.get("amount_basis") != {"class": "U", "stored": False}:
        bad("the amount must be the customer's statement, not stored")
    kinds = [s.get("kind") for s in out.get("sections", [])]
    if tuple(kinds) != SECTION_ORDER:
        bad(f"sections out of order: {kinds}")
    sec = {s["kind"]: s for s in out["sections"]}
    if not sec["NONE"].get("lines"):
        bad("'None of these' must always be present")
    for path, k, _ in _walk(out):
        if str(k).lower() in FORBIDDEN_KEYS:
            bad(f"forbidden field {k} at {path}")
    member = out["member"]
    watched = {m["display_name"].split()[0] for m in payload["our_household"]["members"] if m["status"] == "watched"}
    if member not in watched:
        bad("member is not a watched member")
    if out["as_of"] != payload["generated"]["as_of"]:
        bad("as_of differs from the household's")

    cards = {c["id"]: c for c in payload["now"]["cards"]}
    engine = {c.id: c for c, _ in state.open_cards}
    # RUNNING: open clocks of this member, verbatim, and never compared with the amount
    for it in sec["RUNNING"]["items"]:
        if set(it) - RUNNING_KEYS:
            bad(f"RUNNING carries a field it may not: {sorted(set(it) - RUNNING_KEYS)}")
        c = cards.get(it["card_id"])
        if not c or c["type"] != "CLOCK" or c["member"] != member:
            bad("RUNNING item is not an open clock of this member")
        if it["amount_inr"] != _engine_amount(engine[c["id"]]):
            bad("RUNNING amount does not trace to the card")
        if it["title"] != c["title"] or it["action_text"] != (c.get("action") or {}).get("action_text"):
            bad("RUNNING text is not the card's own")
        if it["deadline_line"] is not None and it["deadline_line"] not in c["body"]:
            bad("RUNNING deadline line is not verbatim")
    dates = [it["deadline_date"] or "9999" for it in sec["RUNNING"]["items"]]
    if dates != sorted(dates):
        bad("RUNNING must be ordered by deadline date")
    for it in sec["NO_COST"]["items"]:
        if set(it) - NO_COST_KEYS:
            bad("NO_COST carries a field it may not")
        c = cards.get(it["card_id"])
        if not c or c["member"] != member or (c.get("action") or {}).get("code") not in NO_COST_ACTIONS \
                or it["action_text"] != c["action"]["action_text"] or it["simulated"] != bool(c.get("simulated")):
            bad("NO_COST item does not trace to a zero-cost card action")

    # WITHIN / OVER: published options only, WORTH_CHECKING only, figures from the rulebook or the tables
    pr = payload["our_household"]["protections"]
    rows = {}
    for m in pr.get("members", []) if pr.get("switched_on") else []:
        if m["member"] == member:
            rows = {s["scheme"]: s for s in m["schemes"]}
    facts = _facts(payload, member)
    as_of = date.fromisoformat(out["as_of"])
    seen = []
    for kind in ("WITHIN", "OVER"):
        order = [it["scheme"] for it in sec[kind]["items"]]
        if order != [s for s in SCHEME_ORDER if s in order]:
            bad(f"{kind} is not in rulebook order")
        for it in sec[kind]["items"]:
            s = it["scheme"]
            if s not in SCHEME_ORDER or (rows.get(s) or {}).get("status") != "WORTH_CHECKING":
                bad(f"{s} is shown but is not worth checking for {member}")
            p = STATE_RULES[s]["params"]
            if s == "PMSBY":
                if it["payments"] != [{"when": "each year, around 1 June", "inr": p["premium_inr"]}] \
                        or it["largest_single_debit"] != p["premium_inr"]:
                    bad("PMSBY figures do not trace to the rulebook")
                fits = it["largest_single_debit"] <= amount
            elif s == "PMJJBY":
                first, _ = pmjjby_first_premium(as_of.month)
                if [x["inr"] for x in it["payments"]] != [first, p["premium_inr"]] \
                        or it["largest_single_debit"] != max(first, p["premium_inr"]):
                    bad("PMJJBY figures do not trace to the rulebook and the first-premium table")
                fits = it["largest_single_debit"] <= amount
            else:
                lo, hi = BAND_AGES[facts["AGE_BAND"]["value"]]
                ages = list(range(max(lo, 18), min(hi, 40) + 1))
                for i, r in enumerate(it["rows"]):
                    vals = [APY_MONTHLY[a][i] for a in ages]
                    fit = [a for a in ages if APY_MONTHLY[a][i] <= amount]
                    if (r["pension"], r["min"], r["max"]) != (APY_PENSION_LEVELS[i], min(vals), max(vals)) \
                            or r["within_ages"] != ([fit[0], fit[-1]] if fit else None):
                        bad("APY figures do not trace to the PFRDA table")
                fits = any(r["within_ages"] for r in it["rows"])
            if fits != (kind == "WITHIN"):
                bad(f"{s} is in the wrong group for {amount}")
            seen.append(s)
    if len(seen) != len(set(seen)):
        bad("a scheme appears twice")
    for it in sec["NOT_SHOWN"]["items"]:
        if it["scheme"] not in SCHEME_ORDER or (rows.get(it["scheme"]) or {}).get("status") in (None, "WORTH_CHECKING"):
            bad("NOT_SHOWN must hold only schemes that are not worth checking")
    for kind in ("WITHIN", "OVER", "NOT_SHOWN"):
        for t in _strings(sec[kind]["items"]):
            if OUT_OF_SCOPE.search(t):
                bad(f"out-of-scope product in {kind}: {t[:60]}")

    # GOING_OUT: observed only, never compared with the amount
    commitments = {(c["member"], c["label"], c["cadence"]): c for c in payload["our_household"]["commitments"]}
    observed = {(o["member"], o["label"]) for o in payload["our_household"].get("protections_observed", [])}
    for it in sec["GOING_OUT"]["items"]:
        if set(it) - GOING_OUT_KEYS:
            bad(f"GOING_OUT carries a field it may not: {sorted(set(it) - GOING_OUT_KEYS)}")
        if it["kind"] == "collection":
            c = commitments.get((member, it["label"], it["cadence"]))
            if not c or c["last_amount"] != it["amount_inr"]:
                bad("GOING_OUT item does not trace to an observed collection")
        elif it["kind"] != "scheme_premium" or (member, it["label"]) not in observed:
            bad("GOING_OUT item does not trace to observed data")

    for t in _strings(out):
        _g(t)
    return out
