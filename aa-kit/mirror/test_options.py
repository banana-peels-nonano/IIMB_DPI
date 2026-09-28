"""
--options acceptance tests: "Within an amount you set", a deterministic, neutral options explorer.

    MIRROR_DATA=<sealed decrypted.json> python -m unittest mirror.test_options -v

What is proven here:
  * without --options nothing changes (no endpoint, meta unchanged, the fixed Ask Mirror reply as before);
  * the three approved examples (SELA/John 500, SELA/Kiran 500, NAGARAJ/Kumar 250) come out as designed;
  * the section order is fixed, 'None of these' is always present, the amount is a closed set;
  * RUNNING and GOING_OUT are never compared with the amount; nothing is summed, subtracted or divided;
  * only schemes the engine shows as WORTH_CHECKING appear, in rulebook order; changing the amount changes
    the grouping only, never the order; figures trace to the rulebook or the cited tables;
  * validate_options() fails closed on every tampering tried below;
  * nothing is written (store files byte-identical), no network is touched, the usual guards apply.
"""
import copy, hashlib, json, os, re, shutil, socket, tempfile, unittest
from datetime import date
from pathlib import Path
from unittest import mock

from . import serve
from .options import (build_options, validate_options, OptionsInvalid, OptionsRefused, SECTION_ORDER,
                      BANNED_OPTIONS, _g)
from .options_rules import APY_MONTHLY, AMOUNTS, pmjjby_first_premium, OPTIONS_RULES_VERSION
from .rules import PURPOSE_GOV_PROTECT as GOV, RULEBOOK_VERSION
from .language import UnsafeLanguage

DATA = os.environ.get("MIRROR_DATA")
PORT = 8787
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = "test-token-options"


def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


def tree_digest(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@unittest.skipUnless(DATA, "set MIRROR_DATA to the sealed corpus")
class Options(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        corpus = serve.load(DATA)
        cls.KUMAR = next(a.household_id for a in corpus.accounts if a.masked.endswith("9950"))
        cls.NAVEEN = next(a.household_id for a in corpus.accounts if a.masked.endswith("9960"))

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mirror-opt-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.environ.pop("MIRROR_HUB_LIVE", None)

    # ---- helpers ----
    @staticmethod
    def card(p, code, tail=None):
        return next(c for c in p["now"]["cards"] if c["code"] == code and (tail is None or c["account"].endswith(tail)))

    def sela(self):
        """SELA as of 8 Sep 2026 after the demo answers (the approved example's setup)."""
        m = serve.Mirror(DATA, str(self.tmp / "store"), date(2026, 8, 28))
        m.start_if_needed()
        m.clock({"as_of": "2026-09-07"})
        p = m.purpose({"purpose": GOV, "on": True})
        p = m.answers({"answers": [{"card_id": self.card(p, "AGE_BAND_QUESTION", "9741")["id"], "option": "41_50"},
                                   {"card_id": self.card(p, "AGE_BAND_QUESTION", "9648")["id"], "option": "18_40"}]})
        p = m.answers({"answers": [{"card_id": self.card(p, "TAXPAYER_QUESTION", "9648")["id"], "option": "no"}]})
        m.lpg_check({"mode": "simulated", "scenario": "rerouted", "consent_to_purpose": True, "as_of": "2026-09-08"})
        return m

    def nagaraj(self, store=None):
        """NAGARAJ as of 28 Aug 2026: protections on, Kumar 18-40, taxpayer not answered."""
        m = serve.Mirror(DATA, str(store or self.tmp / "store"), date(2026, 8, 28), household=self.KUMAR)
        m.start_if_needed()
        p = m.purpose({"purpose": GOV, "on": True})
        m.answers({"answers": [{"card_id": self.card(p, "AGE_BAND_QUESTION")["id"], "option": "18_40"}]})
        return m

    def ask(self, m, member, amount):
        return serve.options_answer(m, {"member": member, "amount": amount})

    def raw(self, m, member, amount):
        st, ev = m._saved()
        payload = m._payload(st, ev)
        return build_options(st, payload, member, amount), st, payload

    @staticmethod
    def sec(out, kind):
        return next(s for s in out["sections"] if s["kind"] == kind)

    def app(self, m, options=True, demo=False):
        hub = serve.Hub(m)
        if options:
            hub.enable_options()
        if demo:
            hub.enable_demo_login()
        return hub, serve.create_app(hub, PORT, TOKEN).test_client()

    def post(self, c, path, body, token=TOKEN, **kw):
        headers = {"X-Mirror-Token": token} if token else {}
        return c.post(path, base_url=BASE, json=body, headers=headers, **kw)

    # ---- 1. flag off: nothing changes ----
    def test_without_the_flag_nothing_changes(self):
        m = serve.Mirror(DATA, str(self.tmp / "store"), date(2026, 8, 28))
        m.start_if_needed()
        hub, c = self.app(m, options=False)
        self.assertEqual(self.post(c, "/api/options", {"member": "John", "amount": 500}).status_code, 404)
        meta = c.get("/api/meta", base_url=BASE).get_json()
        self.assertNotIn("options", meta)
        vocab = c.get("/api/vocab", base_url=BASE).get_json()
        advice = next(q for q in vocab["ask_mirror"] if q["id"] == "advice")
        self.assertEqual(advice["fixed_reply"], "Mirror doesn't recommend products. Here is what we saw and where you can check it.")
        self.assertEqual(RULEBOOK_VERSION, "2026-09-27")                   # the rulebook version is untouched

    # ---- 2. the approved examples ----
    def test_sela_john_500_matches_the_design(self):
        out = self.ask(self.sela(), "John", 500)
        self.assertEqual(out["header"]["title"], "Within ₹500 a month · John")
        run = self.sec(out, "RUNNING")["items"]
        self.assertEqual([(i["title"], i["amount_inr"], i["deadline_date"]) for i in run],
                         [("LIC OF INDIA premium returned", 4525.0, "2026-09-22")])
        self.assertIn("the grace period ends around 22 Sep 2026", run[0]["deadline_line"])
        self.assertEqual(run[0]["action_text"], "Pay through LIC's own channels")
        self.assertEqual(run[0]["amount_text"], "About ₹4,525.")                # no comparison with ₹500
        self.assertEqual(self.sec(out, "NO_COST")["items"], [])
        within = self.sec(out, "WITHIN")["items"]
        self.assertEqual([i["scheme"] for i in within], ["PMJJBY"])
        self.assertEqual([p["inr"] for p in within[0]["payments"]], [342, 436])  # joining Sep-Nov, then yearly
        self.assertEqual(within[0]["facts_text"], "You told us John is 41–50.")
        self.assertEqual(self.sec(out, "OVER")["items"], [])
        self.assertEqual([i["text"] for i in self.sec(out, "NOT_SHOWN")["items"]],
                         ["Not shown for John: Pension: APY. Joining is for ages 18–40, and you told us John is 41–50."])
        going = [i["text"] for i in self.sec(out, "GOING_OUT")["items"]]
        self.assertIn("LIC OF INDIA: about ₹1,493 monthly, between the 7th and the 8th.", going)
        self.assertIn("LIC OF INDIA: about ₹4,525 quarterly, around the 23rd.", going)
        self.assertTrue(any(t.startswith("Pradhan Mantri Suraksha Bima Yojana premium: seen in this account") for t in going))

    def test_sela_kiran_500_matches_the_design(self):
        out = self.ask(self.sela(), "Kiran", 500)
        run = self.sec(out, "RUNNING")
        self.assertEqual(run["items"], [])
        self.assertEqual(run["blocked_questions"], 3)
        nc = self.sec(out, "NO_COST")["items"]
        self.assertEqual([(i["action_text"], i["simulated"]) for i in nc],
                         [("Move the subsidy to an account you use, or ask your distributor", True)])
        within = self.sec(out, "WITHIN")["items"]
        self.assertEqual([i["scheme"] for i in within], ["PMSBY", "PMJJBY", "APY"])
        apy = within[2]
        self.assertEqual([(r["pension"], r["min"], r["max"], r["within_ages"]) for r in apy["rows"]],
                         [(1000, 42, 291, [18, 40]), (2000, 84, 582, [18, 38]), (3000, 126, 873, [18, 34]),
                          (4000, 168, 1164, [18, 30]), (5000, 210, 1454, [18, 28])])
        self.assertEqual(apy["facts_text"], "You told us Kiran is 18–40, and not an income-tax payer.")
        self.assertEqual(self.sec(out, "OVER")["items"], [])
        self.assertEqual([i["label"] for i in self.sec(out, "GOING_OUT")["items"]],
                         ["BAJAJ AUTO C D", "LTGURXX42921", "INDUSIND BANK CFD"])

    def test_nagaraj_kumar_250_matches_the_design_and_500_changes_grouping_not_order(self):
        m = self.nagaraj()
        o250, o500 = self.ask(m, "Kumar", 250), self.ask(m, "Kumar", 500)
        self.assertEqual(self.sec(o250, "RUNNING")["items"], [])
        self.assertEqual(self.sec(o250, "NO_COST")["items"], [])
        self.assertEqual([i["scheme"] for i in self.sec(o250, "WITHIN")["items"]], ["PMSBY"])
        over = self.sec(o250, "OVER")["items"]
        self.assertEqual([(i["scheme"], i["largest_single_debit"]) for i in over], [("PMJJBY", 436)])   # Jun-Aug
        self.assertEqual([i["text"] for i in self.sec(o250, "NOT_SHOWN")["items"]], ["APY needs one more answer first."])
        self.assertEqual([i["text"] for i in self.sec(o250, "GOING_OUT")["items"]],
                         ["ADTPSLSIPG: about ₹4,000 monthly, between the 7th and the 8th."])
        self.assertEqual([i["scheme"] for i in self.sec(o500, "WITHIN")["items"]], ["PMSBY", "PMJJBY"])
        self.assertEqual(self.sec(o500, "OVER")["items"], [])
        order = lambda o: [i["scheme"] for k in ("WITHIN", "OVER") for i in self.sec(o, k)["items"]]
        self.assertEqual(order(o250), order(o500))                             # grouping changes, order never
        for kind in ("RUNNING", "NO_COST", "GOING_OUT"):                        # context is identical
            self.assertEqual(self.sec(o250, kind)["items"], self.sec(o500, kind)["items"])

    # ---- 3. structure and the three concepts ----
    def test_fixed_order_none_always_and_no_comparison_in_context_sections(self):
        m = self.sela()
        for member in ("John", "Kiran"):
            for amount in AMOUNTS:
                out = self.ask(m, member, amount)
                self.assertEqual(tuple(s["kind"] for s in out["sections"]), SECTION_ORDER)
                self.assertTrue(self.sec(out, "NONE")["lines"])
                self.assertEqual(out["amount_basis"], {"class": "U", "stored": False})
                for kind in ("RUNNING", "GOING_OUT"):
                    for it in self.sec(out, kind)["items"]:
                        self.assertFalse({"tag", "within_ages", "largest_single_debit"} & set(it))
                        for t in strings(it):
                            self.assertNotRegex(t, r"(?i)\b(within|more than)\s+₹")
                for t in strings(out):   # "permanent total disability" is the rulebook's PMSBY cover wording
                    self.assertIsNone(re.search(r"\b(total(?! disability)|remaining|left over|split|allocat\w*)\b", t, re.I), t)

    def test_pmjjby_first_premium_follows_the_replay_month(self):
        self.assertEqual([pmjjby_first_premium(mo)[0] for mo in range(1, 13)],
                         [228, 228, 114, 114, 114, 436, 436, 436, 342, 342, 342, 228])
        m = self.nagaraj()
        self.assertEqual(self.sec(self.ask(m, "Kumar", 500), "WITHIN")["items"][1]["payments"][0]["inr"], 436)
        m.clock({"as_of": "2026-09-12"})
        self.assertEqual(self.sec(self.ask(m, "Kumar", 500), "WITHIN")["items"][1]["payments"][0]["inr"], 342)

    def test_apy_table_matches_the_pfrda_chart(self):
        self.assertEqual(APY_MONTHLY[18], (42, 84, 126, 168, 210))
        self.assertEqual(APY_MONTHLY[30], (116, 231, 347, 462, 577))
        self.assertEqual(APY_MONTHLY[40], (291, 582, 873, 1164, 1454))
        self.assertEqual(OPTIONS_RULES_VERSION, "2026-09-28")

    def test_only_worth_checking_schemes_appear(self):
        m = self.sela()
        for member in ("John", "Kiran"):
            out = self.ask(m, member, 2500)
            st, ev = m._saved()
            payload = m._payload(st, ev)
            rows = next(x for x in payload["our_household"]["protections"]["members"] if x["member"] == member)["schemes"]
            worth = [s["scheme"] for s in rows if s["status"] == "WORTH_CHECKING"]
            shown = [i["scheme"] for k in ("WITHIN", "OVER") for i in self.sec(out, k)["items"]]
            self.assertEqual(shown, [s for s in ("PMSBY", "PMJJBY", "APY") if s in worth])

    def test_protections_off_lists_no_options_but_keeps_context(self):
        m = serve.Mirror(DATA, str(self.tmp / "store"), date(2026, 8, 28))
        m.start_if_needed()
        out = self.ask(m, "John", 500)
        self.assertTrue(out["protections_off"])
        self.assertEqual(self.sec(out, "WITHIN")["items"] + self.sec(out, "OVER")["items"], [])
        self.assertEqual(len(self.sec(out, "RUNNING")["items"]), 1)

    # ---- 4. fail closed ----
    def test_validate_options_fails_closed_on_tampering(self):
        m = self.sela()
        base, st, payload = self.raw(m, "Kiran", 500)
        validate_options(copy.deepcopy(base), st, payload)
        john, _, _ = self.raw(m, "John", 500)

        def breaks(mutate, src=None):
            o = copy.deepcopy(src or base)
            mutate(o)
            with self.assertRaises((OptionsInvalid, UnsafeLanguage)):
                validate_options(o, st, payload)

        breaks(lambda o: o["sections"].reverse())                                            # order
        breaks(lambda o: self.sec(o, "NONE").update(lines=[]))                                 # none of these
        breaks(lambda o: o.update(amount=300))                                                  # closed set
        breaks(lambda o: o.update(amount_basis={"class": "U", "stored": True}))                 # stored
        breaks(lambda o: o.update(total=1234))                                                  # sum field
        breaks(lambda o: self.sec(o, "WITHIN")["items"][0].update(rank=1))                     # rank field
        breaks(lambda o: self.sec(o, "GOING_OUT")["items"][0].update(tag="within ₹500"))       # compare context
        breaks(lambda o: self.sec(o, "RUNNING")["items"][0].update(tag="more than ₹500"), john)
        breaks(lambda o: self.sec(o, "RUNNING")["items"][0].update(amount_inr=100.0), john)    # untraced amount
        breaks(lambda o: self.sec(o, "WITHIN")["items"][0]["payments"][0].update(inr=12))      # untraced premium
        breaks(lambda o: self.sec(o, "OVER")["items"].append(self.sec(o, "WITHIN")["items"].pop(1)))   # wrong group
        breaks(lambda o: self.sec(o, "WITHIN")["items"].reverse())                              # ranked order
        breaks(lambda o: self.sec(o, "WITHIN")["items"][0].update(pays="The best cover for you."))   # banned word
        breaks(lambda o: self.sec(o, "WITHIN")["items"][0].update(pays="A mutual fund SIP of ₹500."))  # securities
        breaks(lambda o: o["header"].update(title="Money left over after bills: ₹500"))         # remainder

        def add_apy_for_john(o):                                                                # not WORTH_CHECKING
            apy = copy.deepcopy(self.sec(base, "WITHIN")["items"][2])
            self.sec(o, "WITHIN")["items"].append(apy)
        with self.assertRaises(OptionsInvalid):
            o = copy.deepcopy(john)
            add_apy_for_john(o)
            _, st2, payload2 = self.raw(m, "John", 500)
            validate_options(o, st2, payload2)

    def test_banned_phrases_raise(self):
        for phrase in ("the best option", "we recommend this", "suitable for you", "you can afford it", "spare cash",
                       "disposable income", "allocate ₹500", "right for you", "top pick", "you should take PMJJBY"):
            with self.assertRaises((OptionsInvalid, UnsafeLanguage)):
                _g(phrase)

    # ---- 5. nothing written, no network, guards ----
    def test_nothing_is_written_and_no_network_is_touched(self):
        m = self.sela()
        root = self.tmp / "store"
        before = tree_digest(root)
        hist_before = m.history()

        def no_network(*a, **k):
            raise AssertionError("the options calculation touched the network")
        with mock.patch.object(socket.socket, "connect", no_network):
            hub, c = self.app(m)
            for amount in AMOUNTS:
                for member in ("John", "Kiran"):
                    r = self.post(c, "/api/options", {"member": member, "amount": amount})
                    self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        self.assertEqual(tree_digest(root), before)                            # the store is byte-identical
        self.assertEqual(m.history(), hist_before)                             # no access-log line

    def test_the_usual_guards_apply(self):
        m = self.nagaraj()
        hub, c = self.app(m)
        ok = {"member": "Kumar", "amount": 250}
        self.assertEqual(self.post(c, "/api/options", ok).status_code, 200)
        self.assertEqual(self.post(c, "/api/options", ok, token=None).status_code, 403)
        r = c.post("/api/options", base_url=BASE, data="member=Kumar", headers={"X-Mirror-Token": TOKEN},
                   content_type="application/x-www-form-urlencoded")
        self.assertEqual(r.status_code, 415)
        self.assertEqual(c.post("/api/options", base_url="http://evil.example", json=ok,
                                headers={"X-Mirror-Token": TOKEN}).status_code, 403)
        for bad in ({"member": "Kumar", "amount": 300}, {"member": "Kumar", "amount": "250"},
                    {"member": "Kumar", "amount": True}, {"member": "John", "amount": 250}, {"member": 7, "amount": 250}, {}):
            self.assertEqual(self.post(c, "/api/options", bad).status_code, 400, bad)
        meta = c.get("/api/meta", base_url=BASE).get_json()
        self.assertEqual(set(meta["options"]), {"reply", "button", "link", "step1"})
        for t in strings(meta["options"]):
            _g(t)

    def test_signed_out_demo_login_and_refused_households(self):
        m = serve.Mirror(DATA, str(self.tmp / "store"), date(2026, 8, 28))
        m.start_if_needed()
        hub, c = self.app(m, demo=True)
        self.assertEqual(self.post(c, "/api/options", {"member": "John", "amount": 500}).status_code, 409)
        self.assertEqual(self.post(c, "/api/login", {"mobile": "9999999997"}).status_code, 200)   # NAVEEN: none watched
        self.assertEqual(self.post(c, "/api/options", {"member": "Naveen", "amount": 500}).status_code, 400)
        with self.assertRaises(OptionsRefused):
            n = serve.Mirror(DATA, str(self.tmp / "n"), date(2026, 8, 28), household=self.NAVEEN)
            n.start_if_needed()
            self.raw(n, "Naveen", 500)


if __name__ == "__main__":
    unittest.main()
