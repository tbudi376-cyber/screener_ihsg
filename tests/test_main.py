import unittest
import tempfile
from pathlib import Path

from src.main import run_pipeline
from src.models import OHLCRow, QuotaUsageBreakdown


class TestMainPipeline(unittest.TestCase):
    def test_run_pipeline_end_to_end(self):
        screener_data = {
            "rows": [
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
            ]
        }

        # Benchmark: 25 days of closes in oldest-to-newest order
        bench_closes = [7000 + i * 10 for i in range(25)]
        benchmark_ohlc = [
            OHLCRow(
                date=f"2026-09-{i+1:02d}",
                open=7000,
                high=7050,
                low=6950,
                close=bench_closes[i],
                volume=1e9,
                value=7e12,
            )
            for i in range(25)
        ]

        # Sector stock closes (oldest-to-newest)
        sector_stock_closes = {
            "Financials": {
                "BBCA": [6000 + i * 20 for i in range(25)],
            },
            "Energy": {
                "ADRO": [3000 + i * 5 for i in range(25)],
            },
        }

        # Candidate OHLC in oldest-to-newest order
        bbca_ohlc = [
            OHLCRow(
                date=f"2026-09-{i+1:02d}",
                open=6200,
                high=6275,
                low=6200,
                close=6200 + i * 5,
                volume=89e6,
                value=558e9,
                f_buy=73e6,
                f_sell=57e6,
                n_foreign=10e6 + i * 1e6,
            )
            for i in range(20)
        ]

        validations_data = {
            "BBCA": {
                "analysis_text": "BBCA strong accumulation signal",
                "broker_data": {
                    "brokers": [
                        {"broker_code": "YU", "broker_name": "CGS", "nval": 238e9}
                    ]
                },
                "ohlc_rows": bbca_ohlc,
                "fundamental_data": {
                    "eps": 85.0,
                    "per": 18.2,
                    "der": 0.75,
                }
            }
        }

        quota_breakdown = QuotaUsageBreakdown(
            screener_calls=1,
            benchmark_calls=1,
            rrg_sector_calls=2,
            rrg_sectors_processed=2,
            rrg_stocks_processed=2,
            validation_calls=5,
            validation_stocks_processed=1,
            total_calls=9,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = run_pipeline(
                screener_data=screener_data,
                benchmark_ohlc=benchmark_ohlc,
                sector_stock_closes=sector_stock_closes,
                validations_data=validations_data,
                output_dir=tmpdir,
                quota_used=quota_breakdown,
            )

            self.assertTrue(Path(report_path).exists())
            content = Path(report_path).read_text(encoding="utf-8")
            self.assertIn("Screener IHSG - Laporan Harian", content)
            self.assertIn("Financials", content)
            self.assertIn("BBCA", content)
            self.assertIn("Trade Plan", content)
            self.assertIn("Rincian Penggunaan Kuota API per Modul", content)
            self.assertIn("9 request", content)
            self.assertIn("Kamus Metrik & Sumber Data", content)


if __name__ == "__main__":
    unittest.main()
