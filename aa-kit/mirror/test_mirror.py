"""
Counterparty Mirror - Batch 1a tests (Learn + Trace with provenance).

Two layers:
  * SYNTHETIC tests always run and need no financial data.
  * CORPUS tests run only when MIRROR_DATA points at the sealed decrypted.json
    (never read from the working directory, never committed).

    python -m unittest mirror.test_mirror -v            (from aa-kit/)
    MIRROR_DATA=<path> python -m unittest mirror.test_mirror -v
"""
import dataclasses, json, os, re, tempfile, unittest
from datetime import date

from mirror.corpus import load, as_of, Account, household_id
from mirror.learn import learn_obligations, learn_income, obligation_key
from mirror.traces import classify_charges, link_returns

SEALED_SHA256 = "49248032661E2509D8F98B3ABB4593BCD8F72CB48790DFEE04DF0FA16BB9584D"
DATA = os.environ.get("MIRROR_DATA")
PAN_RX = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")


# ---------- synthetic fixtures ----------
def _xml(holder_attrs: str, txns: list) -> str:
    rows = "".join(
        f'<Transaction txnId="{i}" type="{k}" amount="{a}" narration="{n}" reference="{r}" '
        f'mode="OTHERS" transactionTimestamp="{d}T10:00:00.0" valueDate="{d}T00:00:00.0"/>'
        for i, k, a, n, r, d in txns)
    return ('<?xml version="1.0" encoding="UTF-8"?><Account xmlns="http://api.rebit.org.in/FISchema/deposit">'
            f'<Profile><Holders><Holder {holder_attrs}/></Holders></Profile>'
            f'<Summary accountSubType="SAVINGS"/><Transactions>{rows}</Transactions></Account>')


def _write(sessions) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump([{"fipId": "T", "maskedAccNumber": m, "linkRefNumber": "x", "data": x}
               for m, x in sessions], f)
    f.close()
    return f.name


def _monthly(prefix, n, narr, amt, day=7, start=(2025, 1), kind="DEBIT"):
    out, (y, m) = [], start
    for i in range(n):
        out.append((f"{prefix}{i}", kind, amt, narr, f"R{prefix}{i}", f"{y:04d}-{m:02d}-{day:02d}"))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


FILLER = _monthly("f", 24, "UPI/123/FOOD/x@y", 100.0, day=3)


class Synthetic(unittest.TestCase):
    def test_loader_never_reads_pan_dob_email_address(self):
        holder = ('name="A ONE" mobile="9000000001" pan="ABCDE1234F" dob="1990-01-01" '
                  'email="a@b.c" address="1 Road" nominee="REGISTERED" ckycCompliance="true"')
        p = _write([("XXXX0001", _xml(holder, FILLER))])
        c = load(p)
        blob = json.dumps([dataclasses.asdict(a) for a in c.accounts], default=str)
        for secret in ("ABCDE1234F", "1990-01-01", "a@b.c", "1 Road", "9000000001"):
            self.assertNotIn(secret, blob, f"{secret!r} leaked past the loader")
        self.assertFalse(PAN_RX.search(blob))
        fields = {f.name for f in dataclasses.fields(Account)}
        self.assertFalse(fields & {"pan", "dob", "email", "address", "nominee", "mobile"})

    def test_households_join_on_mobile_never_pan(self):
        same_pan = 'pan="ABCDE1234F"'
        p = _write([("XXXX0001", _xml(f'name="A" mobile="9000000001" {same_pan}', FILLER)),
                    ("XXXX0002", _xml(f'name="B" mobile="9000000002" {same_pan}', FILLER)),
                    ("XXXX0003", _xml(f'name="C" mobile="9000000001"', FILLER))])
        hh = load(p).households()
        self.assertEqual(len(hh), 2)
        self.assertEqual(len(hh[household_id("9000000001")]), 2)

    def test_padded_account_is_refused(self):
        rows = [("dup", "DEBIT", 50.0, "UPI/1/X", "SAME", f"2025-01-{d:02d}") for d in range(1, 26)]
        rows += _monthly("m", 6, "ACH/LIC OF INDIA/9093410450819", 1500.0)
        p = _write([("XXXX0009", _xml('name="P" mobile="9000000009"', rows))])
        a = load(p).accounts[0]
        self.assertEqual(a.quality, "PADDED")
        self.assertEqual(learn_obligations(a, a.txns, date(2025, 12, 31)), [])
        self.assertEqual(learn_income(a, a.txns, date(2025, 12, 31)), ([], 0))

    def test_obligation_keys(self):
        k1 = obligation_key("ACH/LIC OF INDIA/9093410450819")
        k2 = obligation_key("ACH/LIC OF INDIA/9118815710919")
        self.assertEqual(k1[:2], ("ACH", "LIC OF INDIA"))
        self.assertNotEqual(k1, k2, "two LIC policies must be two instances")
        self.assertEqual(obligation_key("ACH/INDUSIND BANK CFD/222681815")[2],
                         obligation_key("ACH/INDUSIND BANK CFD/222681820")[2])
        self.assertEqual(obligation_key("CMS/000573987107/BAJAJ_AUTO_C D__580DPFFC021540")[0], "CMS")
        self.assertEqual(obligation_key("LTGURXX42921 DEC19 Manish Kum")[1], "LTGURXX42921")
        for n in ("ECSRTNCHGS220620_SR684167193GST (Ref# BANK CHARGES)", "UPI/0152/x@ybl/ICICI",
                  "MABchgs-Jul19+GST", "Coral Paywave Drcard Jfee+GST"):
            self.assertIsNone(obligation_key(n), n)

    def test_quarterly_with_a_miss_and_a_linked_return(self):
        q = [("q1", "DEBIT", 4600.0, "ACH/LIC OF INDIA/9118815710119", "r1", "2025-01-23"),
             ("q2", "DEBIT", 4600.0, "ACH/LIC OF INDIA/9118815710419", "r2", "2025-04-23"),
             ("q3", "DEBIT", 4600.0, "ACH/LIC OF INDIA/9118815710719", "r3", "2025-07-23"),
             ("c1", "DEBIT", 590.0, "ECSRTNCHGS221019_SR1 (Ref# BANK CHARGES)", "r4", "2025-10-28")]
        p = _write([("XXXX0005", _xml('name="Q" mobile="9000000005"', FILLER + q))])
        a = load(p).accounts[0]
        obs = learn_obligations(a, a.txns, date(2025, 11, 5))
        self.assertEqual([o.cadence for o in obs], ["QUARTERLY"])
        self.assertEqual(obs[0].occurrences[-1].status, "NOT_SEEN")
        tr = [t for t in link_returns(a, classify_charges(a, a.txns), obs, a.txns)
              if t.kind == "ECS_RETURN"][0]
        self.assertEqual(tr.event_date, "2025-10-22")
        self.assertEqual((tr.linked_obligation, tr.link_class, tr.link_confidence),
                         (obs[0].id, "I", "strong"))

    def test_not_seen_is_never_claimed_outside_the_data_window(self):
        rows = _monthly("s", 6, "ACH/LIC OF INDIA/9093410450819", 1500.0, day=20)
        p = _write([("XXXX0006", _xml('name="W" mobile="9000000006"', FILLER[:14] + rows))])
        a = load(p).accounts[0]           # data window ends 2026-02-03 (last filler row)
        self.assertEqual(a.window[1], date(2026, 2, 3))
        obs = learn_obligations(a, a.txns, date(2026, 6, 30))
        ledger = {o.period: o.status for o in obs[0].occurrences}
        self.assertEqual(ledger["2026-01"], "NOT_SEEN")          # inside the window: honest miss
        tail = [s for p, s in ledger.items() if p >= "2026-02"]
        self.assertTrue(tail and all(s == "OUTSIDE_DATA_WINDOW" for s in tail), tail)


@unittest.skipUnless(DATA, "set MIRROR_DATA to the sealed decrypted.json")
class Corpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = load(DATA)
        cls.john, cls.kiran = cls.c.account("9741"), cls.c.account("9648")
        cls.kumar = cls.c.account("9950")

    def learn(self, acc, cutoff):
        tx = as_of(acc.txns, cutoff)
        obs = learn_obligations(acc, tx, cutoff)
        return obs, link_returns(acc, classify_charges(acc, tx), obs, tx)

    def test_sealed_corpus(self):
        self.assertEqual(self.c.sha256, SEALED_SHA256)
        self.assertEqual(sum(len(a.txns) for a in self.c.accounts), 1870)
        self.assertEqual(self.john.household_id, self.kiran.household_id)
        self.assertNotEqual(self.john.household_id, self.kumar.household_id)

    def test_padded_and_thin_accounts_refused(self):
        for a in self.c.accounts:
            if a.member and a.member.upper().startswith("NAVEEN") or a.member is None:
                self.assertIn(a.quality, ("PADDED", "INSUFFICIENT"), a.masked)
                self.assertEqual(learn_obligations(a, a.txns, date(2026, 9, 30)), [])

    def test_john_two_lic_instances(self):
        obs, _ = self.learn(self.john, date(2026, 9, 7))
        lic = {o.cadence: o for o in obs if o.counterparty == "LIC OF INDIA"}
        self.assertEqual(set(lic), {"MONTHLY", "QUARTERLY"})
        self.assertTrue(all(o.status == "SEEN" for o in lic["MONTHLY"].occurrences))
        q = lic["QUARTERLY"]
        self.assertEqual(q.day_window, (23, 23))
        self.assertEqual(q.amount_band, (4525.0, 4624.0))
        self.assertEqual([(o.period, o.status) for o in q.occurrences][-1], ("2026-08", "NOT_SEEN"))

    def test_john_return_links_to_quarterly_lic_only_after_charge_posts(self):
        _, trs = self.learn(self.john, date(2026, 8, 27))
        self.assertFalse([t for t in trs if t.kind == "ECS_RETURN"])
        obs, trs = self.learn(self.john, date(2026, 8, 28))
        tr = [t for t in trs if t.kind == "ECS_RETURN"][0]
        q = [o for o in obs if o.cadence == "QUARTERLY"][0]
        self.assertEqual((tr.event_date, tr.total_charge), ("2026-08-22", 590.0))
        self.assertEqual((tr.linked_obligation, tr.link_confidence), (q.id, "strong"))

    def test_kiran_indusind_ledger(self):
        obs, _ = self.learn(self.kiran, date(2026, 8, 28))
        ind = [o for o in obs if o.counterparty == "INDUSIND BANK CFD"][0]
        missing = [o.period for o in ind.occurrences if o.status == "NOT_SEEN"]
        self.assertEqual(missing, ["2025-11", "2026-05", "2026-06", "2026-07"])
        ltg = [o for o in obs if o.counterparty == "LTGURXX42921"][0]
        self.assertEqual([o.period for o in ltg.occurrences if o.status == "NOT_SEEN"],
                         ["2026-05", "2026-06"])
        baj = [o for o in obs if "BAJAJ" in o.counterparty][0]
        self.assertEqual(baj.last_seen, "2026-06")

    def test_kiran_return_weak_on_1_dec_strong_later_no_lookahead(self):
        _, trs = self.learn(self.kiran, date(2025, 12, 1))
        tr = [t for t in trs if t.kind == "ECS_RETURN"][0]
        self.assertEqual((tr.event_date, tr.total_charge, tr.link_confidence),
                         ("2025-11-21", 413.0, "weak"))
        self.assertIsNone(tr.linked_obligation)
        self.assertFalse(any("shifted" in n for n in tr.notes),
                         "1 Dec replay must not use calendar knowledge from later months")
        _, trs = self.learn(self.kiran, date(2026, 8, 28))
        self.assertEqual([t for t in trs if t.kind == "ECS_RETURN"][0].link_confidence, "strong")

    def test_income_is_not_inflow(self):
        j, _ = learn_income(self.john, self.john.txns, date(2026, 9, 7))
        k, k_other = learn_income(self.kiran, self.kiran.txns, date(2026, 8, 28))
        u, _ = learn_income(self.kumar, self.kumar.txns, date(2026, 9, 22))
        self.assertEqual([s.signature for s in j], ["BY SAL"])
        self.assertEqual(len(j[0].months), 11)
        self.assertEqual(k, [], "Kiran has credits but no regular income pattern")
        self.assertGreater(k_other, 0)
        self.assertEqual(len(u), 1, "Kumar's salary must be one stream despite 'SAL FORMAY' labels")
        self.assertIn("GENPACT", u[0].signature)

    def test_charge_totals(self):
        _, j = self.learn(self.john, date(2026, 9, 7))
        _, k = self.learn(self.kiran, date(2026, 8, 28))
        self.assertAlmostEqual(sum(t.total_charge for t in j), 1296.80, places=2)
        self.assertAlmostEqual(sum(t.total_charge for t in k), 996.29, places=2)

    def test_every_fact_traces_to_corpus_rows_and_labels_are_not_resolved(self):
        ids = {t.txn_id: t for a in self.c.accounts for t in a.txns}
        for acc, cut in ((self.john, date(2026, 9, 7)), (self.kiran, date(2026, 8, 28)),
                         (self.kumar, date(2026, 9, 22))):
            obs, trs = self.learn(acc, cut)
            for o in obs:
                self.assertTrue(o.seen_txn_ids)
                for i in o.seen_txn_ids:
                    self.assertIn(i, ids)
                    self.assertIn(o.counterparty.split()[0], ids[i].narration.upper(),
                                  "counterparty label must come from the narration itself")
            for t in trs:
                self.assertTrue(t.txn_ids and all(i in ids for i in t.txn_ids))

    def test_kumar_has_a_clean_mandate_and_nothing_else(self):
        obs, trs = self.learn(self.kumar, date(2026, 9, 22))
        self.assertEqual(len(obs), 1)
        self.assertTrue(all(o.status == "SEEN" for o in obs[0].occurrences))
        self.assertEqual(trs, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
