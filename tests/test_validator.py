import unittest
from src.validator import (
    parse_foreign_flow_5d,
    assemble_validation,
    format_validation_summary,
    extract_fundamental_metrics,
)
from src.models import Candidate, Stock, OHLCRow, ValidationResult


class TestValidator(unittest.TestCase):
    def setUp(self):
        self.stock = Stock(code="BBCA", name="Bank Central Asia Tbk.", sector="Financials")
        self.candidate = Candidate(
            stock=self.stock,
            bucket="SINYAL BERSIH",
            summary="asing beli kuat",
            wr_event=74.1,
            potential=11.0,
            drawdown=-5.0,
        )
        # Oldest-to-newest convention: index 0 is oldest, index 19 is newest (2026-09-25)
        self.ohlc_rows = [
            OHLCRow(
                date=f"2026-09-{i+1:02d}",
                open=6200,
                high=6275,
                low=6180,
                close=6250,
                volume=89e6,
                value=558e9,
                f_buy=73e6,
                f_sell=57e6,
                n_foreign=10e6 + i * 1e6,  # 10M up to 29M
            )
            for i in range(20)
        ]

    def test_parse_foreign_flow_5d(self):
        """Poin 2 & 4: 5 hari terakhir dihitung dari data oldest-to-newest beserta estimasi Rupiah."""
        flows = parse_foreign_flow_5d(self.ohlc_rows)
        self.assertEqual(len(flows), 5)
        # D-0 is the newest day (index 19): 10M + 19M = 29M shares
        d0_shares, d0_idr = flows[0]
        self.assertEqual(d0_shares, 29e6)
        self.assertEqual(d0_idr, 29e6 * 6250)

    def test_parse_foreign_flow_short_data(self):
        short = self.ohlc_rows[:3]
        flows = parse_foreign_flow_5d(short)
        self.assertEqual(len(flows), 3)

    def test_assemble_validation(self):
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text="Test analysis",
            broker_data={"brokers": []},
            ohlc_rows=self.ohlc_rows,
        )
        self.assertIsInstance(result, ValidationResult)
        self.assertIsNotNone(result.pivot)
        self.assertIsNotNone(result.trade_plan)
        self.assertLess(result.trade_plan.cutloss, result.trade_plan.entry_low,
                        "Cutloss must be strictly below entry_low")

    def test_format_validation_not_empty(self):
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text="Test analysis text",
            broker_data={"brokers": []},
            ohlc_rows=self.ohlc_rows,
        )
        text = format_validation_summary(result)
        self.assertIn("BBCA", text)
        self.assertIn("Trade Plan", text)
        self.assertGreater(len(text), 100)

    def test_format_includes_foreign_flow_with_rupiah_value(self):
        """Poin 4: Tampilkan nilai estimasi Rupiah berdampingan dengan jumlah lembar saham."""
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text="Test",
            broker_data={"brokers": []},
            ohlc_rows=self.ohlc_rows,
        )
        text = format_validation_summary(result)
        self.assertIn("Foreign Flow", text)
        self.assertIn("shares", text)
        # Must show estimated Rupiah value in B or M (e.g. +Rp181.25B)
        self.assertIn("Rp", text)
        self.assertNotIn("Money Flow", text,
                         "Must use 'Foreign Flow', not 'Money Flow' (data honesty)")

    def test_extract_fundamental_metrics(self):
        mock_fin_data = {
            "INCOME_STATEMENT": {
                "items": [
                    {
                        "data": {
                            "penjualan_dan_pendapatan_usaha": 10e12,
                            "laba_rugi": 1e12,
                            "laba_rugi_per_saham": {
                                "laba_per_saham_dasar_diatribusikan_kepada_pemilik_entitas_induk": {
                                    "total": 85.0
                                }
                            }
                        }
                    },
                    {
                        "data": {
                            "penjualan_dan_pendapatan_usaha": 8e12,
                            "laba_rugi": 800e9,
                        }
                    }
                ]
            },
            "BALANCE_SHEET": {
                "items": [
                    {
                        "data": {
                            "liabilitas_dan_ekuitas": {
                                "liabilitas": {"total": 15e12},
                                "ekuitas": {"total": 20e12},
                            }
                        }
                    }
                ]
            }
        }
        metrics = extract_fundamental_metrics(mock_fin_data, close_price=3000.0)
        self.assertEqual(metrics["eps"], 85.0)
        self.assertEqual(metrics["der"], 0.75)
        self.assertEqual(metrics["revenue_growth_yoy"], 25.0)
        self.assertEqual(metrics["net_income_growth_yoy"], 25.0)
        self.assertIsNotNone(metrics["per"])

    def test_format_validation_with_fundamentals(self):
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text="Test analysis",
            broker_data={"brokers": []},
            ohlc_rows=self.ohlc_rows,
            fundamental_data={
                "eps": 85.0,
                "per": 8.8,
                "der": 0.75,
                "revenue_growth_yoy": 25.0,
                "net_income_growth_yoy": 20.0,
            }
        )
        text = format_validation_summary(result)
        self.assertIn("Fundamental & Valuasi", text)
        self.assertIn("EPS", text)
        self.assertIn("DER: 0.75x", text)
        self.assertIn("Pertumbuhan Pendapatan", text)

    def test_format_validation_fallback_reason(self):
        amrt_candidate = Candidate(
            stock=Stock(code="AMRT", name="Sumber Alfaria Trijaya Tbk.", sector="Consumer Non-Cyclicals"),
            bucket="AKUMULASI SENYAP",
            summary="mode senyap",
        )
        result = assemble_validation(
            candidate=amrt_candidate,
            analysis_text="",
            broker_data={},
            ohlc_rows=[],
            fallback_reason="Dilewati dari validasi mendalam untuk menghemat kuota API harian (tier AKUMULASI SENYAP peringkat cadangan). Lakukan cek manual bila diperlukan."
        )
        text = format_validation_summary(result)
        self.assertIn("Catatan Validasi", text)
        self.assertIn("Dilewati dari validasi mendalam untuk menghemat kuota API harian", text)
        self.assertNotIn("No detailed analysis available", text)

    def test_format_validation_shows_rr_warning_when_rr_below_1(self):
        """Temuan 2: format_validation_summary menampilkan warning saat R:R < 1.0."""
        pege_candidate = Candidate(
            stock=Stock(code="PEGE", name="Panca Global Kapital Tbk.", sector="Financials"),
            bucket="SINYAL BERSIH",
            summary="Bullish",
        )
        # Create minimal 15 rows with low ATR
        rows = [
            OHLCRow(
                date=f"2026-09-{i+1:02d}",
                open=135.0,
                high=142.0,
                low=129.0,
                close=141.0,
                volume=1e6,
                value=140e6,
            )
            for i in range(15)
        ]
        result = assemble_validation(
            candidate=pege_candidate,
            analysis_text="Analisis PEGE",
            broker_data={},
            ohlc_rows=rows,
        )
        text = format_validation_summary(result)
        self.assertIn("Trade Plan (Fraksi BEI)", text)
        if result.trade_plan and result.trade_plan.rr_ratio < 1.0:
            self.assertIn("⚠️ PERINGATAN R:R < 1.0", text)


if __name__ == "__main__":
    unittest.main()
