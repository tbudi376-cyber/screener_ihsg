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

    def test_trade_plan_asymmetric_rr(self):
        plan = calculate_trade_plan(close=6250, atr=136, support=6200)
        self.assertIsInstance(plan, TradePlan)
        self.assertAlmostEqual(plan.cutloss, 6250 - 136, places=0)
        self.assertAlmostEqual(plan.target1, 6250 + 1.5 * 136, places=0)
        self.assertAlmostEqual(plan.target2, 6250 + 2.0 * 136, places=0)
        self.assertGreater(plan.rr_ratio, 1.0,
                           "R:R must be > 1.0 to avoid the old SmartScreener bug")

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
