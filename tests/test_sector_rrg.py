import unittest
from src.sector_rrg import (
    calculate_rs_ratio,
    calculate_rs_momentum,
    classify_quadrant,
    normalize_to_100,
    compute_rrg_for_stock,
    rank_sectors,
    select_representative_stocks,
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

    def test_select_representative_stocks_minimum_5(self):
        """Temuan 1: Memilih minimal 5 saham representatif per sektor."""
        mock_config = {
            "Financials": ["BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "BBTN"],
            "Energy": ["ADRO", "PTBA", "MEDC", "PGAS", "AKRA", "ELSA"],
        }
        selected = select_representative_stocks(mock_config, ["Financials", "Energy"], min_stocks=5)
        self.assertEqual(len(selected["Financials"]), 5)
        self.assertEqual(len(selected["Energy"]), 5)
        self.assertEqual(selected["Financials"], ["BBCA", "BBRI", "BMRI", "BBNI", "BRIS"])

    def test_rank_sectors_aggregates_5_stocks_per_sector(self):
        """Temuan 1: rank_sectors menghitung skor dan median dari saham per sektor."""
        sector_points = {
            "Financials": [
                RRGPoint(code="BBCA", rs_ratio=105.0, rs_momentum=102.0, quadrant="Leading"),
                RRGPoint(code="BBRI", rs_ratio=103.0, rs_momentum=101.0, quadrant="Leading"),
                RRGPoint(code="BMRI", rs_ratio=104.0, rs_momentum=100.5, quadrant="Leading"),
                RRGPoint(code="BBNI", rs_ratio=99.0, rs_momentum=101.0, quadrant="Improving"),
                RRGPoint(code="BRIS", rs_ratio=101.0, rs_momentum=99.0, quadrant="Weakening"),
            ],
            "Energy": [
                RRGPoint(code="ADRO", rs_ratio=97.0, rs_momentum=98.0, quadrant="Lagging"),
                RRGPoint(code="PTBA", rs_ratio=96.0, rs_momentum=97.0, quadrant="Lagging"),
                RRGPoint(code="MEDC", rs_ratio=98.0, rs_momentum=99.0, quadrant="Lagging"),
                RRGPoint(code="PGAS", rs_ratio=99.0, rs_momentum=98.5, quadrant="Lagging"),
                RRGPoint(code="AKRA", rs_ratio=95.0, rs_momentum=96.0, quadrant="Lagging"),
            ],
        }
        ranked = rank_sectors(sector_points)
        self.assertEqual(len(ranked), 2)
        # Financials median ratio=103.0, median mom=101.0 -> Leading, score=4.0
        fin = ranked[0]
        self.assertEqual(fin[0], "Financials")
        self.assertEqual(fin[1], "Leading")
        self.assertEqual(fin[2], 4.0)
        self.assertEqual(fin[3], 103.0)
        self.assertEqual(fin[4], 101.0)

        # Energy median ratio=97.0, median mom=98.0 -> Lagging, score=1.0
        nrg = ranked[1]
        self.assertEqual(nrg[0], "Energy")
        self.assertEqual(nrg[1], "Lagging")
        self.assertEqual(nrg[2], 1.0)
        self.assertEqual(nrg[3], 97.0)
        self.assertEqual(nrg[4], 98.0)

    def test_classify_quadrant_with_tolerance(self):
        """Verifikasi toleransi sekitar 100 (misalnya 0.2) untuk nilai momentum ketat."""
        # 99.85 dengan tolerance 0.2 diakui sebagai >= 100
        self.assertEqual(classify_quadrant(102.0, 99.85, tolerance=0.2), "Leading")
        self.assertEqual(classify_quadrant(98.0, 99.85, tolerance=0.2), "Improving")
        # Nilai di bawah tolerance (misal 99.7) tetap Lagging / Weakening
        self.assertEqual(classify_quadrant(98.0, 99.70, tolerance=0.2), "Lagging")
        self.assertEqual(classify_quadrant(102.0, 99.70, tolerance=0.2), "Weakening")

    def test_rank_sectors_filters_out_unknown_sector(self):
        """Sektor 'Unknown' harus disaring dari hasil ranking RRG."""
        sector_points = {
            "Unknown": [
                RRGPoint(code="MGLV", rs_ratio=142.33, rs_momentum=101.21, quadrant="Leading"),
                RRGPoint(code="BAIK", rs_ratio=53.28, rs_momentum=99.69, quadrant="Lagging"),
            ],
            "Energy": [
                RRGPoint(code="ADRO", rs_ratio=105.0, rs_momentum=101.0, quadrant="Leading"),
            ],
        }
        ranked = rank_sectors(sector_points)
        sector_names = [r[0] for r in ranked]
        self.assertNotIn("Unknown", sector_names)
        self.assertIn("Energy", sector_names)

    def test_quadrant_always_consistent_with_printed_metrics(self):
        """Unit test: Kuadran yang dihasilkan rank_sectors SELALU konsisten dengan RS-Ratio & RS-Momentum."""
        sector_points = {
            "Transportation & Logistic": [
                RRGPoint(code="GIAA", rs_ratio=96.49, rs_momentum=99.27, quadrant="Lagging"),
                RRGPoint(code="ASSA", rs_ratio=87.80, rs_momentum=99.87, quadrant="Lagging"),
                RRGPoint(code="BIRD", rs_ratio=98.10, rs_momentum=100.08, quadrant="Improving"),
                RRGPoint(code="TMAS", rs_ratio=109.19, rs_momentum=99.70, quadrant="Weakening"),
                RRGPoint(code="SMDR", rs_ratio=121.83, rs_momentum=100.84, quadrant="Leading"),
            ]
        }
        ranked = rank_sectors(sector_points, tolerance=0.2)
        for sector, quadrant, score, rs_r, rs_m in ranked:
            expected_quad = classify_quadrant(rs_r, rs_m, tolerance=0.2)
            self.assertEqual(quadrant, expected_quad, f"Quadrant '{quadrant}' must match classify_quadrant result '{expected_quad}' for {sector}")

    def test_classify_quadrant_healthcare_lagging(self):
        """Koreksi Logika RRG: RS-Ratio 99.9 dan RS-Momentum 99.9 wajib Lagging (bukan Leading)."""
        # Nilai di bawah 100 secara matematis berada di kuadran Lagging
        self.assertEqual(classify_quadrant(99.9, 99.9), "Lagging")
        self.assertEqual(classify_quadrant(99.9, 99.9, tolerance=0.0), "Lagging")
        self.assertEqual(classify_quadrant(99.91, 99.90, tolerance=0.0), "Lagging")


if __name__ == "__main__":
    unittest.main()
