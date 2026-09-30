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

        # Sector stock closes (oldest-to-newest): 5 stocks per sector
        sector_stock_closes = {
            "Financials": {
                "BBCA": [6000 + i * 20 for i in range(25)],
                "BBRI": [3000 + i * 15 for i in range(25)],
                "BMRI": [5000 + i * 18 for i in range(25)],
                "BBNI": [4000 + i * 10 for i in range(25)],
                "BRIS": [2000 + i * 8 for i in range(25)],
            },
            "Energy": {
                "ADRO": [3000 + i * 5 for i in range(25)],
                "PTBA": [2800 + i * 6 for i in range(25)],
                "MEDC": [1200 + i * 4 for i in range(25)],
                "PGAS": [1500 + i * 3 for i in range(25)],
                "AKRA": [1400 + i * 2 for i in range(25)],
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
            rrg_sector_calls=10,
            rrg_sectors_processed=2,
            rrg_stocks_processed=10,
            validation_calls=5,
            validation_stocks_processed=1,
            total_calls=17,
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
            self.assertIn("17 request", content)
            self.assertIn("RRG berbasis sampel 5 saham representatif per sektor", content)
            self.assertIn("Kamus Metrik & Sumber Data", content)

    def test_run_pipeline_strict_sector_filter_excludes_non_favored(self):
        """Verify strict hard filter PRD 7.3: stocks from non-favored sectors are excluded."""
        screener_data = {
            "rows": [
                {
                    "stock_code": "PEGE",
                    "stock_name": "Panca Global Kapital Tbk.",
                    "bucket": "SINYAL BERSIH",
                    "summary": "asing beli kuat",
                    "wr_event": 74.1,
                    "potential": 11.0,
                    "drawdown": -5.0,
                    "note": "",
                },
                {
                    "stock_code": "WBSA",
                    "stock_name": "BSA Logistics Indonesia Tbk.",
                    "bucket": "SINYAL SENYAP",
                    "summary": "top broker akumulasi",
                    "wr_event": 66.7,
                    "potential": 8.0,
                    "drawdown": -3.0,
                    "note": "",
                },
                {
                    "stock_code": "PTBA",
                    "stock_name": "Bukit Asam Tbk.",
                    "bucket": "AKUMULASI SENYAP",
                    "summary": "mode senyap",
                    "wr_event": None,
                    "potential": None,
                    "drawdown": None,
                    "note": "",
                },
                {
                    "stock_code": "VISI",
                    "stock_name": "Satu Visi Putra Tbk.",
                    "bucket": "SINYAL SENYAP",
                    "summary": "asing beli",
                    "wr_event": 65.2,
                    "potential": 8.0,
                    "drawdown": -3.0,
                    "note": "",
                },
            ]
        }

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

        # Energy & Transportation are Leading; Financials & Basic Materials are Lagging
        sector_stock_closes = {
            "Energy": {
                f"E_{k}": [2000 + i * 30 for i in range(25)] for k in range(5)
            },
            "Transportation & Logistic": {
                f"T_{k}": [1000 + i * 25 for i in range(25)] for k in range(5)
            },
            "Financials": {
                f"F_{k}": [5000 - i * 10 for i in range(25)] for k in range(5)
            },
            "Basic Materials": {
                f"B_{k}": [3000 - i * 15 for i in range(25)] for k in range(5)
            },
        }

        wbsa_ohlc = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=600, high=620, low=590, close=600 + i, volume=1e6, value=6e8)
            for i in range(20)
        ]

        validations_data = {
            "WBSA": {
                "analysis_text": "WBSA strong accumulation",
                "broker_data": {"brokers": [{"broker_code": "MG", "broker_name": "Semesta", "nval": 1e9}]},
                "ohlc_rows": wbsa_ohlc,
                "fundamental_data": {"eps": 10.0, "per": 12.0, "der": 0.5},
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = run_pipeline(
                screener_data=screener_data,
                benchmark_ohlc=benchmark_ohlc,
                sector_stock_closes=sector_stock_closes,
                validations_data=validations_data,
                output_dir=tmpdir,
                date_str="2026-09-25",
            )

            content = Path(report_path).read_text(encoding="utf-8")
            self.assertIn("WBSA", content)
            self.assertIn("PTBA", content)
            # PEGE (Financials - Lagging) and VISI (Basic Materials - Lagging) must NOT be candidates
            # Check Candidates table section specifically
            cand_section = content.split("## 2. Kandidat Screening")[1].split("## 3. Validasi Mendalam")[0]
            self.assertIn("WBSA", cand_section)
            self.assertIn("PTBA", cand_section)
            self.assertNotIn("PEGE", cand_section)
            self.assertNotIn("VISI", cand_section)

    def test_run_pipeline_filters_out_candidate_leakage_from_rrg(self):
        """Verifikasi bahwa run_pipeline memfilter saham kandidat yang bocor ke sector_stock_closes."""
        screener_data = {"rows": []}
        bench_closes = [7000 + i * 10 for i in range(25)]
        benchmark_ohlc = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=7000, high=7050, low=6950, close=bench_closes[i], volume=1e9, value=7e12)
            for i in range(25)
        ]
        # Consumer Cyclicals with 5 official representative stocks + DSSA leaked as 6th stock
        sector_stock_closes = {
            "Consumer Cyclicals": {
                "ERAA": [400 + i for i in range(25)],
                "ACES": [800 + i for i in range(25)],
                "MAPI": [1500 + i for i in range(25)],
                "LPPF": [1600 + i for i in range(25)],
                "RALS": [500 + i for i in range(25)],
                "DSSA": [1055 for _ in range(25)],  # Leaked candidate!
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = run_pipeline(
                screener_data=screener_data,
                benchmark_ohlc=benchmark_ohlc,
                sector_stock_closes=sector_stock_closes,
                validations_data={},
                output_dir=tmpdir,
                date_str="2026-09-28",
                quota_used=QuotaUsageBreakdown(rrg_sectors_processed=1, rrg_stocks_processed=5),
            )
            content = Path(report_path).read_text(encoding="utf-8")
            # Transparency note should state 5 stocks, NOT 6 stocks
            self.assertIn("sampel 5 saham representatif", content)
            self.assertNotIn("sampel 6 saham", content)

    def test_run_pipeline_mode_mandiri(self):
        """Verifikasi run_pipeline dengan mode='mandiri' melakukan top-down screening dari sektor unggulan."""
        bench_closes = [7000 + i * 10 for i in range(25)]
        benchmark_ohlc = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=7000, high=7050, low=6950, close=bench_closes[i], volume=1e9, value=7e12)
            for i in range(25)
        ]
        # Energy is leading
        sector_stock_closes = {
            "Energy": {
                "ADRO": [3000 + i * 20 for i in range(25)],
                "PTBA": [2800 + i * 15 for i in range(25)],
                "MEDC": [1200 + i * 10 for i in range(25)],
                "PGAS": [1500 + i * 8 for i in range(25)],
                "AKRA": [1400 + i * 6 for i in range(25)],
            }
        }
        # ADRO OHLC with full PRD §6 criteria: val > 1B, vol > sma20, n_foreign > 0, close >= sma20
        adro_ohlc = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=3000, high=3050, low=2950, close=3000, volume=5e6, value=15e9, f_buy=1e6, f_sell=1e6, n_foreign=0)
            for i in range(19)
        ]
        adro_ohlc.append(
            OHLCRow(date="2026-09-20", open=3000, high=3550, low=3000, close=3500, volume=12e6, value=40e9, f_buy=5e6, f_sell=1e6, n_foreign=4e6)
        )
        stock_ohlc_map = {"ADRO": adro_ohlc}

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = run_pipeline(
                screener_data={"rows": []},  # empty upstream screener
                benchmark_ohlc=benchmark_ohlc,
                sector_stock_closes=sector_stock_closes,
                validations_data={},
                output_dir=tmpdir,
                date_str="2026-09-29",
                mode="mandiri",
                stock_ohlc_map=stock_ohlc_map,
            )
            content = Path(report_path).read_text(encoding="utf-8")
            self.assertIn("Mode Screening: Mandiri (Top-Down Sektor)", content)
            self.assertIn("ADRO", content)
            self.assertIn("🟢 SINYAL MANDIRI (PRD §6)", content)
            self.assertIn("Energy", content)

    def test_run_pipeline_empty_favored_sectors_produces_no_fallback(self):
        """Verifikasi jika favored_sectors kosong (semua Lagging), tidak ada fallback ke sector_ranking[:3]."""
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
                }
            ]
        }
        # Benchmark rises sharply
        benchmark_ohlc = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=7000, high=7050, low=6950, close=7000 + i * 50, volume=1e9, value=7e12)
            for i in range(25)
        ]
        # Financials drops sharply -> RS-Ratio < 100, RS-Momentum < 100 -> Lagging
        sector_stock_closes = {
            "Financials": {
                f"F_{k}": [5000 - i * 20 for i in range(25)] for k in range(5)
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = run_pipeline(
                screener_data=screener_data,
                benchmark_ohlc=benchmark_ohlc,
                sector_stock_closes=sector_stock_closes,
                validations_data={},
                output_dir=tmpdir,
                date_str="2026-09-29",
                mode="upstream",
            )
            content = Path(report_path).read_text(encoding="utf-8")
            cand_section = content.split("## 2. Kandidat Screening")[1].split("## 3. Validasi Mendalam")[0]
            # Must NOT fall back to processing BBCA
            self.assertNotIn("BBCA", cand_section)
            self.assertIn("Tidak ada kandidat", cand_section)

    def test_run_pipeline_mode_mandiri_detects_and_processes_non_sample_constituents(self):
        """Verifikasi bahwa Mode Mandiri memproses saham konstituen non-sampel RRG (seperti MSJA di Industrials)
        secara independen tanpa memerlukan input dari mode upstream."""
        # Benchmark: 25 days of closes
        bench_closes = [7000 + i * 10 for i in range(25)]
        benchmark_ohlc = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=7000, high=7050, low=6950, close=bench_closes[i], volume=1e9, value=7e12)
            for i in range(25)
        ]
        # Industrials: 5 representative stocks outperforming benchmark (Leading)
        sector_stock_closes = {
            "Industrials": {
                "ASII": [5000 + i * 25 for i in range(25)],
                "UNTR": [25000 + i * 100 for i in range(25)],
                "HEXA": [6000 + i * 30 for i in range(25)],
                "IMPC": [4000 + i * 20 for i in range(25)],
                "ARNA": [800 + i * 5 for i in range(25)],
            }
        }
        # MSJA is a constituent of Industrials in config/sectors.json (not in the 5 sample stocks above)
        msja_ohlc = [
            OHLCRow(date=f"2026-09-{i+1:02d}", open=800, high=810, low=790, close=800, volume=10e6, value=8e9, f_buy=1e6, f_sell=1e6, n_foreign=0)
            for i in range(19)
        ]
        # Latest MSJA passes 4/4 filter
        msja_ohlc.append(
            OHLCRow(date="2026-09-20", open=800, high=850, low=800, close=830, volume=25e6, value=20e9, f_buy=10e6, f_sell=2e6, n_foreign=8e6)
        )
        stock_ohlc_map = {"MSJA": msja_ohlc}

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = run_pipeline(
                screener_data={"rows": []},  # zero upstream screener rows
                benchmark_ohlc=benchmark_ohlc,
                sector_stock_closes=sector_stock_closes,
                validations_data={},
                output_dir=tmpdir,
                date_str="2026-09-30",
                mode="mandiri",
                stock_ohlc_map=stock_ohlc_map,
            )
            content = Path(report_path).read_text(encoding="utf-8")
            self.assertIn("Mode Screening: Mandiri (Top-Down Sektor)", content)
            self.assertIn("MSJA", content)
            self.assertIn("🟢 SINYAL MANDIRI (PRD §6)", content)
            self.assertIn("Industrials", content)


if __name__ == "__main__":
    unittest.main()
