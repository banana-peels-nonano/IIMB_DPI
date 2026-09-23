import unittest
from statistics import median
from household import *

import os, pathlib
_DATA = os.environ.get("HSL_DATA")
if not _DATA:
    raise RuntimeError("Set HSL_DATA to the path of decrypted.json; tests never read from the working directory")
ACCS = parse(str(pathlib.Path(_DATA).resolve(strict=True)))
LAST = max(t.ym for a in ACCS for t in a.txns)
BY = {a.masked: a for a in ACCS}
SR, JR = BY["XXXXXXXX9741"], BY["XXXXXXXX9648"]

def find(acc, frag, kind=None):
    return [s for s in streams(acc.txns, LAST)
            if frag in s.sig and (kind is None or s.kind == kind)]

class T(unittest.TestCase):
    # ---- household assembly ----
    def test_household_grouped_by_mobile(self):
        hh = households(ACCS)
        sela = hh["916999974812"]
        self.assertEqual({a.holder for a in sela},
                         {"MR.JOHN SELA SR", "MR.KIRAN SELA JR"})

    def test_pan_is_never_a_join_key(self):
        """Father and son share PAN DRWPG2761P in this sandbox - impossible in
        reality. Two accounts with an identical PAN but different mobiles must
        NOT be treated as one household. Behavioural, not a source grep."""
        a = Account("XXXX0001", "A ONE", "9000000001", "SAVINGS")
        b = Account("XXXX0002", "B TWO", "9000000002", "SAVINGS")
        hh = households([a, b])
        self.assertEqual(len(hh), 2, "different mobiles must stay separate households")
        c = Account("XXXX0003", "C THREE", "9000000001", "SAVINGS")
        hh2 = households([a, c])
        self.assertEqual(len(hh2), 1, "shared mobile is the only valid join key")
        self.assertEqual(len(hh2["9000000001"]), 2)

    # ---- signature ----
    def test_signature_drops_digits_and_months(self):
        self.assertEqual(signature("By Sal Aug 19Sarita Dabir"), "BY SAL DABIR")
        self.assertEqual(signature("ICSP/By Sal Apr 20"), "ICSP BY SAL")

    # ---- narration drift (the false-positive we found and fixed) ----
    def test_salary_is_one_continuous_stream_not_gapped(self):
        s = find(SR, "BY SAL", "CREDIT")
        self.assertEqual(len(s), 1, "salary must not fragment across narrations")
        s = s[0]
        self.assertEqual(s.status, "CONTINUING")
        self.assertEqual(len(s.months), 11)
        self.assertEqual(s.gaps, [], "fabricated salary gaps are indefensible")
        self.assertAlmostEqual(median(s.amounts), 36645, delta=500)

    def test_unrelated_streams_do_not_merge(self):
        # amount proximity alone must not merge a person transfer with a rail booking
        sigs = [s.sig for s in streams(JR.txns, LAST)]
        self.assertIn("MANISH KUM", sigs)
        self.assertFalse(any("IRCTC" in s for s in sigs if "MANISH" in s))

    # ---- benefit detection ----
    def test_apbs_benefit_survives_materiality_floor(self):
        s = find(JR, "APBS", "CREDIT")
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0].is_benefit)
        self.assertLess(median(s[0].amounts), MATERIAL_MEDIAN,
                        "this is exactly the case the amount floor would wrongly drop")
        self.assertEqual(s[0].status, "STOPPED")
        self.assertEqual(s[0].months[-1], "2026-05")

    def test_trivial_streams_are_filtered(self):
        sigs = " ".join(s.sig for s in streams(SR.txns, LAST))
        self.assertNotIn("REWARDED", sigs, "a Rs10 cashback stopping is not a finding")

    # ---- mandates ----
    def test_emi_gaps_detected_exactly(self):
        s = find(JR, "INDUSIND", "DEBIT")[0]
        self.assertTrue(s.fixed)
        self.assertEqual(median(s.amounts), 3573)
        self.assertEqual(s.gaps, ["2025-11", "2026-05", "2026-06", "2026-07"])

    def test_lic_commitment_continues_unbroken(self):
        s = find(SR, "LIC", "DEBIT")[0]
        self.assertEqual(s.status, "CONTINUING")
        self.assertEqual(len(s.months), 12)

    # ---- convergence: the actual finding ----
    def test_multiple_mandates_break_in_same_window(self):
        broken = [s for s in streams(JR.txns, LAST)
                  if s.kind == "DEBIT" and s.fixed and s.status in ("GAPPED", "STOPPED")]
        window = {"2026-05", "2026-06", "2026-07"}
        hit = [s for s in broken if (set(s.gaps) & window) or
               (s.status == "STOPPED" and s.months[-1] in ("2026-05", "2026-06"))]
        self.assertGreaterEqual(len(hit), 3,
            "the convergent May-Jul failure cluster is the core evidence")

    # ---- language guard ----
    def test_no_accusation_vocabulary_anywhere(self):
        banned = ("fraud", "stole", "theft", "default", "illegal", "misappropriat",
                  "delinquen", "evasion", "failed to pay", "did not pay")
        for acc in (SR, JR):
            for f in findings_for(acc, LAST):
                blob = " ".join([f.kind, f.observation, f.suggested_check] + f.caveats).lower()
                for b in banned:
                    self.assertNotIn(b, blob, f"accusatory term '{b}' in output")

    def test_every_finding_carries_a_caveat_or_is_neutral(self):
        for acc in (SR, JR):
            for f in findings_for(acc, LAST):
                if f.kind != "COMMITMENT_CONTINUING":
                    self.assertTrue(f.caveats, f"{f.kind} must state what it cannot establish")
                self.assertTrue(f.suggested_check)

if __name__ == "__main__":
    unittest.main(verbosity=2)
