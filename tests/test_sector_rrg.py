import unittest
from src.sector_rrg import (
    calculate_rs_ratio,
    calculate_rs_momentum,
    classify_quadrant,
    normalize_to_100,
    compute_rrg_for_stock,
    rank_sectors,
)
from src.mcp_client import McpClient, extract_closes
from src.models import RRGPoint


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

    def test_rank_sectors_tie_breaking_by_rs_metrics(self):
        """Audit Check 5a: Sektor dengan skor identik diurutkan berdasarkan RS-Ratio & Momentum."""
        sector_points = {
            "Financials": [
                RRGPoint(code="BBCA", rs_ratio=105.0, rs_momentum=102.0, quadrant="Leading"),
            ],
            "Energy": [
                RRGPoint(code="PTBA", rs_ratio=115.0, rs_momentum=108.0, quadrant="Leading"),
            ],
            "Transportation": [
                RRGPoint(code="WBSA", rs_ratio=92.0, rs_momentum=95.0, quadrant="Lagging"),
            ],
        }

        ranked = rank_sectors(sector_points)
        self.assertEqual(ranked[0][0], "Energy")
        self.assertEqual(ranked[1][0], "Financials")
        self.assertEqual(ranked[2][0], "Transportation")
        self.assertEqual(len(ranked[0]), 5)
        self.assertEqual(ranked[0][3], 115.0)
        self.assertEqual(ranked[0][4], 108.0)

    def test_rrg_with_real_api_response_format_newest_first(self):
        """Poin 2: Data mentah API yang newest-first otomatis diurutkan oldest-to-newest."""
        # Simulasi output riwayat_harga API yang terurut newest-first (D-0, D-1, ... D-24)
        raw_api_stock_rows = [
            {
                "date": f"2026-09-{25-i:02d}",
                "open": 1000 + (25 - i) * 10,
                "high": 1050 + (25 - i) * 10,
                "low": 980 + (25 - i) * 10,
                "close": 1020 + (25 - i) * 10,  # harga naik seiring berjalannya waktu
                "volume": 5000000.0,
                "value": 5000000000.0,
            }
            for i in range(25)
        ]
        raw_api_bench_rows = [
            {
                "date": f"2026-09-{25-i:02d}",
                "open": 7000 + (25 - i) * 2,
                "high": 7050 + (25 - i) * 2,
                "low": 6950 + (25 - i) * 2,
                "close": 7010 + (25 - i) * 2,  # benchmark naik lambat
                "volume": 1000000000.0,
                "value": 7000000000000.0,
            }
            for i in range(25)
        ]

        # 1. Parse menggunakan McpClient
        parsed_stock = McpClient.parse_ohlc_rows(raw_api_stock_rows)
        parsed_bench = McpClient.parse_ohlc_rows(raw_api_bench_rows)

        # Verifikasi parser membalik data mentah menjadi ascending (oldest-to-newest)
        self.assertEqual(parsed_stock[0].date, "2026-09-01")
        self.assertEqual(parsed_stock[-1].date, "2026-09-25")
        self.assertLess(parsed_stock[0].date, parsed_stock[-1].date)

        # 2. Ekstrak closes menggunakan helper resmi
        stock_closes = extract_closes(parsed_stock)
        bench_closes = extract_closes(parsed_bench)
        self.assertEqual(len(stock_closes), 25)
        self.assertEqual(stock_closes[0], parsed_stock[0].close)
        self.assertEqual(stock_closes[-1], parsed_stock[-1].close)

        # 3. Hitung RRG point
        rrg_point = compute_rrg_for_stock(stock_closes, bench_closes, code="TEST", period=10)
        self.assertIsInstance(rrg_point, RRGPoint)
        # Karena stock naik jauh lebih cepat daripada benchmark (outperformer), kuadran harus Leading
        self.assertEqual(rrg_point.quadrant, "Leading")
        self.assertGreater(rrg_point.rs_ratio, 100.0)


if __name__ == "__main__":
    unittest.main()
