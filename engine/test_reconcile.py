import unittest
from datetime import date
from reconcile import *

B = date(2026, 9, 17)
def mk(months, amt, narr="SALARY CREDIT", start=(2026,4)):
    out=[]; y,m=start
    for i in range(months):
        out.append(Credit(date(y,m,28), amt(i) if callable(amt) else amt, narr))
        m+=1
        if m>12: m=1; y+=1
    return out

class T(unittest.TestCase):
    def test_expected_delta_is_not_universal(self):
        self.assertEqual(expected_ee_delta(14000), 0)       # below old ceiling
        self.assertAlmostEqual(expected_ee_delta(18000), 360)
        self.assertAlmostEqual(expected_ee_delta(20000), 600)
        self.assertAlmostEqual(expected_ee_delta(25000), 1200)
        self.assertAlmostEqual(expected_ee_delta(40000), 1200)  # capped

    def test_clean_drop_with_filing_is_consistent(self):
        c = mk(5, 20000) + mk(3, 19400, start=(2026,10))
        f = reconcile(c, Employment(uan="1", is_employed=True, is_recent=True), B)
        self.assertEqual(f.state, "CONSISTENT")
        self.assertAlmostEqual(f.delta, 600, delta=1)

    def test_drop_without_filing_never_accuses(self):
        c = mk(5, 20000) + mk(3, 19400, start=(2026,10))
        f = reconcile(c, Employment(uan="1", is_employed=True, is_recent=False), B)
        self.assertEqual(f.state, "NEEDS_VERIFICATION")
        blob = " ".join([f.state]+f.observations+f.caveats+[f.suggested_check]).lower()
        for banned in ("fraud","stole","theft","defaulted","illegal","misappropriat","your employer has not paid"):
            self.assertNotIn(banned, blob)
        self.assertTrue(any("lag" in x.lower() for x in f.caveats))

    def test_variable_pay_downgrades_confidence(self):
        c = mk(5, lambda i: 20000 + (i%2)*5000) + mk(3, 19400, start=(2026,10))
        f = reconcile(c, Employment(uan="1", is_employed=True, is_recent=False), B)
        self.assertTrue(any("varies" in x for x in f.caveats))
        self.assertEqual(f.confidence, "low")

    def test_employment_transition_flagged(self):
        c = mk(5, 20000) + mk(3, 19400, start=(2026,10))
        f = reconcile(c, Employment(uan="1", is_employed=True, is_recent=False,
                                    date_of_exit=date(2026,8,30)), B)
        self.assertTrue(any("employment change" in x.lower() for x in f.caveats))

    def test_insufficient_data(self):
        f = reconcile(mk(1, 20000), Employment(uan="1", is_recent=True), B)
        self.assertEqual(f.state, "INSUFFICIENT_DATA")

    def test_no_statutory_record(self):
        c = mk(5, 20000) + mk(3, 20000, start=(2026,10))
        f = reconcile(c, Employment(uan=None, is_employed=False), B)
        self.assertEqual(f.state, "NO_STATUTORY_RECORD")
        self.assertIn("not proof", " ".join(f.caveats))

    def test_split_payment_is_not_a_shift(self):
        # same monthly total, paid in two halves after the boundary
        c = mk(5, 20000)
        for m in (10,11,12):
            c += [Credit(date(2026,m,15),10000,"SALARY CREDIT"), Credit(date(2026,m,28),10000,"SALARY CREDIT")]
        f = reconcile(c, Employment(uan="1", is_employed=True, is_recent=True), B)
        self.assertAlmostEqual(f.delta, 0, delta=1)

    def test_delayed_credit_same_month_total(self):
        c = mk(5, 20000) + [Credit(date(2026,10,3),20000,"SALARY"),
                            Credit(date(2026,11,2),20000,"SALARY"),
                            Credit(date(2026,12,1),20000,"SALARY")]
        f = reconcile(c, Employment(uan="1", is_employed=True, is_recent=True), B)
        self.assertAlmostEqual(f.delta, 0, delta=1)

    def test_boundary_month_excluded(self):
        c = mk(5, 20000) + [Credit(date(2026,9,20),8000,"SALARY PARTIAL")] + mk(3,19400,start=(2026,10))
        f = reconcile(c, Employment(uan="1", is_employed=True, is_recent=True), B)
        self.assertAlmostEqual(f.delta, 600, delta=1)  # partial Sept ignored

    def test_non_salary_narration_ignored(self):
        c = mk(5,20000) + mk(3,19400,start=(2026,10)) + [Credit(date(2026,11,5),50000,"UPI FROM BROTHER")]
        f = reconcile(c, Employment(uan="1", is_employed=True, is_recent=True), B)
        self.assertAlmostEqual(f.delta, 600, delta=1)

    def test_compounding_numbers(self):
        self.assertAlmostEqual(compound_monthly(1200,30), 1894801, delta=200)
        self.assertAlmostEqual(compound_monthly(360,30), 568440, delta=200)

if __name__=="__main__":
    unittest.main(verbosity=2)
