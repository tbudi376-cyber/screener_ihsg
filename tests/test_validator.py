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
        self.ohlc_rows = [
            OHLCRow(date=f"2026-09-{25-i:02d}", open=6225, high=6275,
                    low=6200, close=6250-i*25, volume=89e6, value=558e9,
                    f_buy=73e6, f_sell=57e6, n_foreign=16.5e6 - i * 5e6)
            for i in range(20)
        ]

    def test_parse_foreign_flow_5d(self):
        flows = parse_foreign_flow_5d(self.ohlc_rows)
        self.assertEqual(len(flows), 5)
        self.assertEqual(flows[0], self.ohlc_rows[0].n_foreign)

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

    def test_format_includes_foreign_flow(self):
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text="Test",
            broker_data={"brokers": []},
            ohlc_rows=self.ohlc_rows,
        )
        text = format_validation_summary(result)
        self.assertIn("Foreign Flow", text)
        self.assertNotIn("Money Flow", text,
                         "Must use 'Foreign Flow', not 'Money Flow' (data honesty)")

    def test_extract_fundamental_metrics(self):
        """Audit Check 3: Ekstraksi rasio fundamental dari laporan_keuangan."""
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
        self.assertEqual(metrics["der"], 0.75)  # 15T / 20T
        self.assertEqual(metrics["revenue_growth_yoy"], 25.0)  # (10-8)/8 * 100
        self.assertEqual(metrics["net_income_growth_yoy"], 25.0)
        self.assertIsNotNone(metrics["per"])

    def test_format_validation_with_fundamentals(self):
        """Audit Check 3: Format output menampilkan data fundamental."""
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
        """Audit Check 4: Fallback message informatif dan tidak kosong tanpa alasan."""
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


if __name__ == "__main__":
    unittest.main()
