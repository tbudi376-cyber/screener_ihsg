import unittest
from src.screener import (
    parse_screener_rows,
    filter_by_sectors,
    filter_by_bucket,
    rank_candidates,
)
from src.models import Candidate, Stock


class TestScreener(unittest.TestCase):
    def setUp(self):
        self.sector_config = {
            "Financials": ["BBCA", "BBRI", "BMRI"],
            "Energy": ["ADRO", "PTBA", "MEDC"],
            "Technology": ["GOTO", "BUKA"],
        }
        self.sample_rows = [
            {
                "stock_code": "BBCA",
                "stock_name": "Bank Central Asia Tbk.",
                "bucket": "SINYAL BERSIH",
                "summary": "asing beli kuat",
                "wr_event": 74.1,
                "potential": 11.0,
                "drawdown": -5.0,
                "note": "",
            },
            {
                "stock_code": "ADRO",
                "stock_name": "Adaro Energy Tbk.",
                "bucket": "SINYAL SENYAP",
                "summary": "top broker akumulasi",
                "wr_event": 66.7,
                "potential": 8.0,
                "drawdown": -3.0,
                "note": "teknikal lemah",
            },
            {
                "stock_code": "GOTO",
                "stock_name": "GoTo Gojek Tokopedia Tbk.",
                "bucket": "RISIKO PANTULAN",
                "summary": "broker jual",
                "wr_event": 40.0,
                "potential": 5.0,
                "drawdown": -8.0,
                "note": "risiko pantulan",
            },
        ]

    def test_parse_screener_rows(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        self.assertEqual(len(candidates), 3)
        self.assertEqual(candidates[0].stock.code, "BBCA")
        self.assertEqual(candidates[0].stock.sector, "Financials")

    def test_parse_assigns_sector_from_config(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        self.assertEqual(candidates[1].stock.sector, "Energy")
        self.assertEqual(candidates[2].stock.sector, "Technology")

    def test_filter_by_sectors(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        filtered = filter_by_sectors(candidates, ["Financials", "Energy"])
        codes = [c.stock.code for c in filtered]
        self.assertIn("BBCA", codes)
        self.assertIn("ADRO", codes)
        self.assertNotIn("GOTO", codes)

    def test_filter_by_bucket_positive(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        filtered = filter_by_bucket(candidates, ["SINYAL BERSIH", "SINYAL SENYAP"])
        self.assertEqual(len(filtered), 2)

    def test_rank_limits_results(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        ranked = rank_candidates(candidates, max_results=2)
        self.assertEqual(len(ranked), 2)

    def test_rank_prefers_higher_wr_event(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        ranked = rank_candidates(candidates, max_results=3)
        self.assertEqual(ranked[0].stock.code, "BBCA")

    def test_empty_screener_rows(self):
        candidates = parse_screener_rows([], self.sector_config)
        self.assertEqual(candidates, [])
        msg_candidates = rank_candidates(candidates)
        self.assertEqual(msg_candidates, [])

    def test_screen_mandiri_constituents_full_criteria(self):
        """Verifikasi mode mandiri: 4/4 filter PRD menghasilkan bucket SINYAL MANDIRI."""
        from src.models import OHLCRow
        from src.screener import screen_mandiri_constituents

        # 20 rows where latest has val > 1B, vol > sma20, n_foreign > 0, close >= sma20
        rows_bbca = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=6000, high=6050, low=5950, close=6000, volume=5e6, value=30e9, f_buy=1e6, f_sell=1e6, n_foreign=0)
            for i in range(19)
        ]
        rows_bbca.append(
            OHLCRow(date="2026-09-20", open=6000, high=6300, low=6000, close=6250, volume=15e6, value=93e9, f_buy=10e6, f_sell=2e6, n_foreign=8e6)
        )

        stock_ohlc_map = {"BBCA": rows_bbca}
        results = screen_mandiri_constituents(
            favored_sectors=["Financials"],
            sector_config=self.sector_config,
            stock_ohlc_map=stock_ohlc_map,
        )

        self.assertEqual(len(results), 1)
        cand = results[0]
        self.assertEqual(cand.stock.code, "BBCA")
        self.assertEqual(cand.bucket, "🟢 SINYAL MANDIRI (PRD §6)")
        self.assertIn("Lolos 4/4 filter PRD", cand.note)
        self.assertEqual(cand.stock.sector, "Financials")

    def test_screen_mandiri_constituents_strict_4_of_4_rejects_partial(self):
        """Verifikasi disiplin 4/4: tanpa toleransi 3/4, saham dengan vol <= sma20 atau nbsa <= 0 harus digugurkan."""
        from src.models import OHLCRow
        from src.screener import screen_mandiri_constituents

        # 20 rows where latest has vol <= sma20, but n_foreign > 0 and close >= sma20 and val > 1B
        rows_adro = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=3000, high=3050, low=2950, close=3000, volume=10e6, value=30e9, f_buy=1e6, f_sell=1e6, n_foreign=0)
            for i in range(19)
        ]
        # latest has volume 5M (below 10M SMA20), close 3100 (> 3000 SMA20), n_foreign +2M, value 15.5B (> 1B)
        rows_adro.append(
            OHLCRow(date="2026-09-20", open=3000, high=3150, low=3000, close=3100, volume=5e6, value=15.5e9, f_buy=4e6, f_sell=2e6, n_foreign=2e6)
        )

        stock_ohlc_map = {"ADRO": rows_adro}
        results = screen_mandiri_constituents(
            favored_sectors=["Energy"],
            sector_config=self.sector_config,
            stock_ohlc_map=stock_ohlc_map,
        )

        # Under strict 4/4 filter, ADRO fails because vol <= sma20
        self.assertEqual(results, [])

    def test_screen_mandiri_constituents_filters_low_value_and_non_favored(self):
        """Verifikasi mode mandiri: nilai transaksi < 1B diabaikan dan sektor non-unggulan disaring."""
        from src.models import OHLCRow
        from src.screener import screen_mandiri_constituents

        # MEDC has value only 500M (< 1B)
        rows_medc = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=1000, high=1050, low=950, close=1000, volume=500000, value=500e6, f_buy=1e5, f_sell=5e4, n_foreign=5e4)
            for i in range(20)
        ]
        # GOTO is in Technology (not in favored_sectors)
        rows_goto = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=60, high=65, low=58, close=60, volume=50e6, value=3e9, f_buy=1e7, f_sell=5e6, n_foreign=5e6)
            for i in range(20)
        ]

        stock_ohlc_map = {"MEDC": rows_medc, "GOTO": rows_goto}
        results = screen_mandiri_constituents(
            favored_sectors=["Energy"],
            sector_config=self.sector_config,
            stock_ohlc_map=stock_ohlc_map,
        )
        self.assertEqual(results, [])

    def test_screen_mandiri_constituents_rejects_downtrend_even_if_vol_and_nbsa_pass(self):
        """Syarat tren (close >= sma20) adalah syarat wajib mutlak (hard filter).
        Saham downtrend / falling knives (misal GOTO) harus digugurkan meski vol > ma20 dan nbsa > 0."""
        from src.models import OHLCRow
        from src.screener import screen_mandiri_constituents

        # 19 rows at 50, latest drops to 37 (Downtrend, close 37 < SMA20 ~49.35)
        # but latest has massive volume (20M) and large net foreign buy (+10M) and high value (7B)
        rows_downtrend = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=50, high=52, low=49, close=50, volume=5e6, value=250e6, f_buy=1e6, f_sell=1e6, n_foreign=0)
            for i in range(19)
        ]
        rows_downtrend.append(
            OHLCRow(date="2026-09-20", open=38, high=39, low=36, close=37, volume=20e6, value=7e9, f_buy=15e6, f_sell=5e6, n_foreign=10e6)
        )

        stock_ohlc_map = {"GOTO": rows_downtrend}
        results = screen_mandiri_constituents(
            favored_sectors=["Technology"],
            sector_config=self.sector_config,
            stock_ohlc_map=stock_ohlc_map,
        )
        self.assertEqual(results, [])

    def test_screen_mandiri_constituents_rejects_auto_rejection(self):
        """Gugurkan saham yang terkunci batas auto rejection (High == Low)."""
        from src.models import OHLCRow
        from src.screener import screen_mandiri_constituents

        rows_ar = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=1000, high=1050, low=950, close=1000, volume=1e6, value=1e9, f_buy=1e5, f_sell=5e4, n_foreign=5e4)
            for i in range(19)
        ]
        # Latest locked at AR: high == low == close == 1100
        rows_ar.append(
            OHLCRow(date="2026-09-20", open=1100, high=1100, low=1100, close=1100, volume=2e6, value=2.2e9, f_buy=1.5e6, f_sell=1e5, n_foreign=1.4e6)
        )

        stock_ohlc_map = {"BBCA": rows_ar}
        results = screen_mandiri_constituents(
            favored_sectors=["Financials"],
            sector_config=self.sector_config,
            stock_ohlc_map=stock_ohlc_map,
        )
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
