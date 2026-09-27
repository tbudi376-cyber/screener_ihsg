import unittest
from src.pivot import calculate_pivot, calculate_atr, calculate_trade_plan
from src.models import PivotLevels, OHLCRow, TradePlan


class TestPivot(unittest.TestCase):
    def test_standard_pivot_bbca(self):
        result = calculate_pivot(high=6275, low=6200, close=6250)
        self.assertIsInstance(result, PivotLevels)
        self.assertAlmostEqual(result.pivot, (6275 + 6200 + 6250) / 3, places=2)
        self.assertAlmostEqual(result.r1, 2 * result.pivot - 6200, places=0)
        self.assertAlmostEqual(result.s1, 2 * result.pivot - 6275, places=0)
        self.assertAlmostEqual(result.r2, result.pivot + (6275 - 6200), places=0)
        self.assertAlmostEqual(result.s2, result.pivot - (6275 - 6200), places=0)

    def test_pivot_symmetry(self):
        result = calculate_pivot(high=100, low=90, close=95)
        self.assertGreater(result.r1, result.pivot)
        self.assertGreater(result.r2, result.r1)
        self.assertLess(result.s1, result.pivot)
        self.assertLess(result.s2, result.s1)

    def test_pege_cutloss_strictly_below_entry_low(self):
        """PEGE Bug Fix: Cutloss must NEVER be inside entry range [129, 141]."""
        pivots = PivotLevels(
            pivot=135.0,
            r1=148.0,
            r2=154.0,
            r3=167.0,
            s1=129.0,
            s2=116.0,
            s3=110.0,
        )
        plan = calculate_trade_plan(
            close=141.0,
            atr=8.21,
            support=129.0,
            pivot_levels=pivots,
        )
        self.assertIsInstance(plan, TradePlan)
        # Core audit check 1: Cutloss MUST be strictly lower than entry_low
        self.assertLess(
            plan.cutloss,
            plan.entry_low,
            f"Cutloss ({plan.cutloss}) must be below entry_low ({plan.entry_low})",
        )
        self.assertEqual(plan.entry_low, 129.0)
        self.assertEqual(plan.entry_high, 141.0)
        # Cutloss should be adjusted by support/swing level (e.g. S2 or below S1)
        self.assertLessEqual(plan.cutloss, 125.0)

    def test_rr_ratio_varies_dynamically_by_stock_structure(self):
        """Audit Check 2: R:R must not be rigidly hardcoded to 1.5:1."""
        # Stock A: High upside resistance (R1 far away)
        pivots_a = PivotLevels(
            pivot=1000.0, r1=1150.0, r2=1250.0, r3=1350.0,
            s1=950.0, s2=900.0, s3=850.0,
        )
        plan_a = calculate_trade_plan(close=1000.0, atr=30.0, support=950.0, pivot_levels=pivots_a)

        # Stock B: Tight resistance (R1 close, wide support)
        pivots_b = PivotLevels(
            pivot=500.0, r1=520.0, r2=540.0, r3=560.0,
            s1=480.0, s2=450.0, s3=420.0,
        )
        plan_b = calculate_trade_plan(close=500.0, atr=15.0, support=480.0, pivot_levels=pivots_b)

        # R:R ratios should be different and determined by their actual levels
        self.assertNotEqual(plan_a.rr_ratio, plan_b.rr_ratio)
        self.assertLess(plan_a.cutloss, plan_a.entry_low)
        self.assertLess(plan_b.cutloss, plan_b.entry_low)

    def test_atr_calculation(self):
        rows = [
            OHLCRow(date=f"2026-09-{25-i:02d}", open=6200+i*10,
                    high=6275+i*5, low=6200-i*5, close=6250+i*3,
                    volume=89e6, value=558e9, f_buy=0, f_sell=0, n_foreign=0)
            for i in range(15)
        ]
        atr = calculate_atr(rows, period=14)
        self.assertGreater(atr, 0)
        self.assertIsInstance(atr, float)


if __name__ == "__main__":
    unittest.main()
