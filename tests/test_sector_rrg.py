import unittest
from src.sector_rrg import (
    calculate_rs_ratio,
    calculate_rs_momentum,
    classify_quadrant,
    normalize_to_100,
)


class TestRRG(unittest.TestCase):
    def test_rs_ratio_outperformer(self):
        stock = [100 + i * 2 for i in range(30)]
        bench = [100 + i * 0.5 for i in range(30)]
        ratios = calculate_rs_ratio(stock, bench, period=10)
        self.assertGreater(len(ratios), 0)
        self.assertGreater(ratios[-1], ratios[0],
                           "RS-Ratio should increase when stock outperforms")

    def test_rs_ratio_underperformer(self):
        stock = [100 - i * 1 for i in range(30)]
        bench = [100 + i * 1 for i in range(30)]
        ratios = calculate_rs_ratio(stock, bench, period=10)
        self.assertLess(ratios[-1], ratios[0])

    def test_rs_momentum_rising(self):
        ratios = [100 + i * 0.5 for i in range(30)]
        momentum = calculate_rs_momentum(ratios, period=10)
        self.assertGreater(len(momentum), 0)
        self.assertGreater(momentum[-1], 100,
                           "Momentum should be >100 when ratio is rising")

    def test_classify_quadrant_leading(self):
        self.assertEqual(classify_quadrant(105, 102), "Leading")

    def test_classify_quadrant_improving(self):
        self.assertEqual(classify_quadrant(95, 102), "Improving")

    def test_classify_quadrant_weakening(self):
        self.assertEqual(classify_quadrant(105, 98), "Weakening")

    def test_classify_quadrant_lagging(self):
        self.assertEqual(classify_quadrant(95, 98), "Lagging")

    def test_normalize_centers_at_100(self):
        values = [90, 95, 100, 105, 110]
        normed = normalize_to_100(values)
        self.assertAlmostEqual(sum(normed) / len(normed), 100, places=0)


if __name__ == "__main__":
    unittest.main()
