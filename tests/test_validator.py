import unittest
from src.validator import (
    parse_foreign_flow_5d,
    assemble_validation,
    format_validation_summary,
    extract_fundamental_metrics,
    extract_personality_wr_stats,
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

    def test_assemble_validation_auto_extracts_raw_fundamentals(self):
        raw_fin_data = {
            "INCOME_STATEMENT": {
                "items": [
                    {
                        "data": {
                            "penjualan_dan_pendapatan_usaha": 10e12,
                            "laba_rugi": 1e12,
                            "laba_rugi_per_saham": {
                                "laba_per_saham_dasar_diatribusikan_kepada_pemilik_entitas_induk": {
                                    "total": 50.0
                                }
                            }
                        }
                    }
                ]
            },
            "BALANCE_SHEET": {
                "items": [
                    {
                        "data": {
                            "liabilitas_dan_ekuitas": {
                                "liabilitas": {"total": 10e12},
                                "ekuitas": {"total": 10e12},
                            }
                        }
                    }
                ]
            }
        }
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text="Test analysis",
            broker_data={"brokers": []},
            ohlc_rows=self.ohlc_rows,
            fundamental_data=raw_fin_data,
        )
        self.assertEqual(result.fundamental_data["eps"], 50.0)
        self.assertEqual(result.fundamental_data["der"], 1.0)
        text = format_validation_summary(result)
        self.assertIn("EPS: Rp50", text)
        self.assertIn("DER: 1.0x", text)

    def test_extract_fundamental_metrics_ttm_4_quarters_and_continuity(self):
        """Verifikasi perhitungan PER TTM dari jumlah 4 kuartal dan deteksi diskontinuitas."""
        mock_4q_data = {
            "INCOME_STATEMENT": {
                "items": [
                    {"label": "Q4 2025", "year": "2025", "quarter": "4", "data": {"laba_rugi_per_saham": 400.0}},
                    {"label": "Q3 2025", "year": "2025", "quarter": "3", "data": {"laba_rugi_per_saham": 300.0}},
                    # Missing Q2 2025
                    {"label": "Q1 2025", "year": "2025", "quarter": "1", "data": {"laba_rugi_per_saham": 100.0}},
                    {"label": "Q4 2024", "year": "2024", "quarter": "4", "data": {"laba_rugi_per_saham": 380.0}},
                    {"label": "Q3 2024", "year": "2024", "quarter": "3", "data": {"laba_rugi_per_saham": 280.0}},
                ]
            },
            "BALANCE_SHEET": {
                "items": [
                    {
                        "data": {
                            "liabilitas_dan_ekuitas": {
                                "liabilitas": {"total": 30e12},
                                "ekuitas": {
                                    "total": 35e12,
                                    "ekuitas_yang_diatribusikan_kepada_pemilik_entitas_induk": {"total": 25e12}
                                }
                            }
                        }
                    }
                ]
            }
        }
        metrics = extract_fundamental_metrics(mock_4q_data, close_price=1050.0)
        # Diskontinuitas Q2 terlewat
        self.assertTrue(metrics["needs_manual_verification"])
        self.assertIn("tidak kontinu", metrics["verification_note"])

    def test_extract_fundamental_metrics_ttm_continuous(self):
        """Verifikasi perhitungan TTM dengan data kontinu."""
        mock_data = {
            "INCOME_STATEMENT": {
                "items": [
                    {"label": "Q4 2025", "year": "2025", "quarter": "4", "data": {"laba_rugi_per_saham": 400.0}},
                    {"label": "Q3 2025", "year": "2025", "quarter": "3", "data": {"laba_rugi_per_saham": 300.0}},
                    {"label": "Q2 2025", "year": "2025", "quarter": "2", "data": {"laba_rugi_per_saham": 200.0}},
                    {"label": "Q1 2025", "year": "2025", "quarter": "1", "data": {"laba_rugi_per_saham": 100.0}},
                ]
            }
        }
        metrics = extract_fundamental_metrics(mock_data, close_price=1050.0)
        # Standalone: Q4=100, Q3=100, Q2=100, Q1=100 => TTM = 400
        self.assertEqual(metrics["eps_ttm"], 400.0)
        self.assertFalse(metrics.get("needs_manual_verification"))

    def test_per_cap_high_priced_stock(self):
        """Uji saham harga tinggi dengan EPS kecil (MGLV scenario) tidak menghasilkan PER 1000x+."""
        mock_data = {
            "INCOME_STATEMENT": {
                "items": [
                    {"label": "Q4 2025", "year": "2025", "quarter": "4", "data": {"laba_rugi_per_saham": 11.0}},
                    {"label": "Q3 2025", "year": "2025", "quarter": "3", "data": {"laba_rugi_per_saham": 8.0}},
                    {"label": "Q2 2025", "year": "2025", "quarter": "2", "data": {"laba_rugi_per_saham": 5.0}},
                    {"label": "Q1 2025", "year": "2025", "quarter": "1", "data": {"laba_rugi_per_saham": 2.0}},
                ]
            }
        }
        metrics = extract_fundamental_metrics(mock_data, close_price=15000.0)
        # TTM EPS = 11.0
        # PER = 15000 / 11 = 1363.63 -> should cap at N/M
        self.assertEqual(metrics["eps_ttm"], 11.0)
        self.assertEqual(metrics["per"], "N/M")

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

    def test_extract_fundamental_metrics_pege_near_zero_eps_sets_nm(self):
        """Temuan 2: PEGE EPS mendekati nol (0.07) harus menghasilkan PER 'N/M' bukan 503.57x."""
        fin_data = {
            "INCOME_STATEMENT": {
                "items": [
                    {
                        "data": {
                            "laba_rugi_per_saham": {
                                "laba_per_saham_dasar_diatribusikan_kepada_pemilik_entitas_induk": {
                                    "total": 0.07
                                }
                            }
                        }
                    }
                ]
            }
        }
        metrics = extract_fundamental_metrics(fin_data, close_price=141.0)
        self.assertEqual(metrics["eps"], 0.07)
        self.assertEqual(metrics["per"], "N/M")

    def test_extract_fundamental_metrics_visi_negative_eps_sets_nm(self):
        """Temuan 2: VISI EPS negatif (-0.01) harus konsisten menghasilkan PER 'N/M'."""
        fin_data = {
            "INCOME_STATEMENT": {
                "items": [
                    {
                        "data": {
                            "laba_rugi_per_saham": {
                                "laba_per_saham_dasar_diatribusikan_kepada_pemilik_entitas_induk": {
                                    "total": -0.01
                                }
                            }
                        }
                    }
                ]
            }
        }
        metrics = extract_fundamental_metrics(fin_data, close_price=1390.0)
        self.assertEqual(metrics["eps"], -0.01)
        self.assertEqual(metrics["per"], "N/M")

    def test_format_validation_shows_per_nm_and_decimal_eps(self):
        """Temuan 2: Output laporan menampilkan 'PER: N/M (Not Meaningful)' dan desimal EPS bila < 1."""
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text="Analysis",
            broker_data={},
            ohlc_rows=self.ohlc_rows,
            fundamental_data={
                "eps": 0.07,
                "per": "N/M",
                "der": 0.17,
            }
        )
        text = format_validation_summary(result)
        self.assertIn("EPS: Rp0.07", text)
        self.assertIn("PER: N/M (Not Meaningful)", text)
        self.assertNotIn("503.57x", text)

    def test_extract_personality_wr_stats_weak_history(self):
        """PTBA case: average WR Event from valid patterns < 50% triggers weak history flag."""
        analysis_text = """
🧬 PERSONALITY HISTORIS
  Basis: pola aktif hari ini | WR Event pakai TP/CL ATR dinamis
  1. asing beli kuat — **SAMPEL VALID**
     WR Event 45.8% | rata2 event +0.12% | D3 +0.09%
     Sample 565
  2. Gabungan (Asing + Teknikal) — **SAMPEL VALID**
     WR Event 44.5% | rata2 event +0.05% | D3 +0.13%
     Sample 409
  3. Gabungan (Broker + Asing) — **SAMPEL VALID**
     WR Event 44.0% | rata2 event +0.01% | D3 +0.06%
     Sample 409
  4. harga di atas MA5 — **SAMPEL VALID**
     WR Event 43.9% | rata2 event +0.14% | D3 +0.19%
     Sample 788

📋 REKOMENDASI
        """
        stats = extract_personality_wr_stats(analysis_text)
        self.assertTrue(stats["is_weak_history"])
        self.assertEqual(len(stats["valid_patterns"]), 4)
        self.assertAlmostEqual(stats["avg_wr"], 44.55, delta=0.1)
        self.assertIn("⚠️ Historis Lemah", stats["flag"])

    def test_extract_personality_wr_stats_strong_history(self):
        """WBSA case: valid pattern WR Event >= 50% does not trigger weak history flag."""
        analysis_text = """
🧬 PERSONALITY HISTORIS
  Basis: pola aktif hari ini | WR Event pakai TP/CL ATR dinamis
  1. top broker akumulasi pekat — **EDGE HISTORIS**
     WR Event 66.7% | rata2 event +3.03% | D3 +1.42%
     Sample 21
  2. asing beli kuat — **SAMPEL KECIL**
     WR Event 66.7%
     Sample 18
  3. Gabungan (Broker + Asing) — **SAMPEL KECIL**
     WR Event 60.0%
     Sample 15

📋 REKOMENDASI
        """
        stats = extract_personality_wr_stats(analysis_text)
        self.assertFalse(stats["is_weak_history"])
        self.assertEqual(len(stats["valid_patterns"]), 1)
        self.assertEqual(stats["avg_wr"], 66.7)
        self.assertIsNone(stats["flag"])

    def test_assemble_validation_sets_candidate_wr_event_flag(self):
        """Assembling validation sets candidate.wr_event_flag when history is weak."""
        analysis_text = """
🧬 PERSONALITY HISTORIS
  1. pola downtrend — **SAMPEL VALID**
     WR Event 42.0%
     Sample 100
📋 REKOMENDASI
        """
        cand = Candidate(
            stock=self.stock,
            bucket="AKUMULASI SENYAP",
            summary="test",
            wr_event=None,
        )
        val = assemble_validation(
            candidate=cand,
            analysis_text=analysis_text,
            broker_data={},
            ohlc_rows=self.ohlc_rows,
        )
        self.assertTrue(val.personality_stats["is_weak_history"])
        self.assertIn("42.0% ⚠️ Historis Lemah", cand.wr_event_flag)

    def test_expand_abbreviated_prices_high_priced_stock(self):
        """Verifikasi ekspansi format harga 'Rp15K' menjadi presisi penuh sesuai OHLC dan PivotLevels."""
        from src.validator import expand_abbreviated_prices
        from src.models import PivotLevels
        analysis_sample = """**📈 PRICE ACTION**
  🟢 **Rp15K** (Rp25 | +0.17%)
  Prev: Rp15K | Open: Rp15K
  High: Rp15K | Low: Rp14K
  Range: Rp750 (5.0%)
  **Support & Resistance:**
  Daily: R2 Rp16K | R1 Rp15K | P Rp15K | S1 Rp15K | S2 Rp14K
"""
        rows = [
            OHLCRow(date="2026-09-25", open=15800, high=15900, low=14975, close=14975, volume=1e6, value=1e10),
            OHLCRow(date="2026-09-28", open=15000, high=15100, low=14350, close=15000, volume=1e6, value=1e10),
        ]
        pivots = PivotLevels(pivot=14817, r1=15283, r2=15567, r3=16033, s1=14533, s2=14067, s3=13783)
        expanded = expand_abbreviated_prices(analysis_sample, rows, pivots)

        self.assertIn("🟢 **Rp15,000**", expanded)
        self.assertIn("Prev: Rp14,975", expanded)
        self.assertIn("Open: Rp15,000", expanded)
        self.assertIn("High: Rp15,100", expanded)
        self.assertIn("Low: Rp14,350", expanded)
        self.assertIn("Daily: R2 Rp15,567 | R1 Rp15,283 | P Rp14,817 | S1 Rp14,533 | S2 Rp14,067", expanded)
        self.assertNotIn("Prev: Rp15K", expanded)
        self.assertNotIn("Low: Rp14K", expanded)

    def test_per_relative_threshold_nm_for_mglv(self):
        """Verifikasi PER relatif (earnings yield < 0.5% atau PER > 200x) menghasilkan N/M pada MGLV."""
        fin_data = {
            "stock_code": "MGLV",
            "INCOME_STATEMENT": {
                "items": [
                    {"label": "Q4 2023", "year": "2023", "quarter": "4", "data": {"laba_rugi_per_saham": 11.0}},
                ]
            }
        }
        # Price 15,000 with EPS 11.0 -> PER 1363.6x -> N/M
        metrics = extract_fundamental_metrics(fin_data, close_price=15000.0)
        self.assertEqual(metrics["per"], "N/M")

    def test_dssa_stock_split_corporate_action_flag(self):
        """Verifikasi deteksi aksi korporasi stock split 1:25 DSSA yang belum disesuaikan."""
        fin_data = {
            "stock_code": "DSSA",
            "INCOME_STATEMENT": {
                "items": [
                    {"label": "Q4 2025", "year": "2025", "quarter": "4", "data": {"laba_rugi_per_saham": 170.88}},
                ]
            }
        }
        metrics = extract_fundamental_metrics(fin_data, close_price=1055.0)
        self.assertTrue(metrics["needs_manual_verification"])
        self.assertIn("Stock Split 1:25", metrics["verification_note"])
        self.assertLess(metrics["eps_ttm"], 50.0)
        self.assertGreater(metrics["per"], 25.0)

    def test_fundamental_data_very_stale_flag(self):
        """Verifikasi flag otomatis 'Data Fundamental Sangat Basi' jika periode laporan > 3 kuartal di belakang kuartal berjalan."""
        fin_data = {
            "stock_code": "MGLV",
            "INCOME_STATEMENT": {
                "items": [
                    {"label": "Q4 2023", "year": "2023", "quarter": "4", "data": {"laba_rugi_per_saham": 11.0}},
                ]
            }
        }
        metrics = extract_fundamental_metrics(fin_data, close_price=15000.0)
        self.assertTrue(metrics["is_very_stale"])
        self.assertGreater(metrics["staleness_gap_quarters"], 3)
        self.assertIn("Data Fundamental Sangat Basi", metrics["verification_note"])
        self.assertIn("Q4 2023", metrics["verification_note"])

    def test_avoid_stock_trade_plan_formatting(self):
        """Verifikasi saham AVOID / Skor <= 25 memformat Trade Plan pengaman dan meniadakan area beli."""
        analysis_avoid = """📊 **HRUM** — Analisis
  Score: **20/75** — ⚪ **NETRAL**
  **📋 REKOMENDASI**
  ⛔ **AVOID**
  Jika sudah punya: Cut loss. Harga dalam tekanan jual
  Jika belum punya: Lewati, cari saham lain
  Stop Loss: Rp820
"""
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text=analysis_avoid,
            broker_data={},
            ohlc_rows=self.ohlc_rows,
        )
        self.assertIsNotNone(result.trade_plan)
        self.assertEqual(result.trade_plan.status, "TIDAK DIREKOMENDASIKAN (Sinyal AVOID / Tekanan Jual Kuat)")

        summary = format_validation_summary(result)
        self.assertIn("Status: **TIDAK DIREKOMENDASIKAN (Sinyal AVOID / Tekanan Jual Kuat)**", summary)
        self.assertIn("Entry Range: TIDAK DISARANKAN ENTRY", summary)
        self.assertIn("Batas Pengaman / Cutloss Eksisting: Rp", summary)
        self.assertNotIn("Entry Range: Rp", summary)
        self.assertNotIn("TUNGGU (Buy on Weakness)", summary)

    def test_empty_broker_data_displays_eod_informative_note(self):
        """Verifikasi bahwa broker data kosong menampilkan catatan penarikan sebelum EOD bursa."""
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text="Normal analysis",
            broker_data={"brokers": []},
            ohlc_rows=self.ohlc_rows,
        )
        summary = format_validation_summary(result)
        self.assertIn("Data broker summary belum tersedia untuk sesi ini", summary)
        self.assertIn("End of Day / EOD", summary)

    def test_avoid_stock_cleans_mantul_hold_and_active_buy_recommendations(self):
        """Verifikasi bahwa narasi 'mantul/hold Rp...' dan 'Jika belum punya: Buy...' dibersihkan pada saham AVOID."""
        analysis_avoid = (
            "📊 **HRUM** — Analisis\n"
            "Score: **20/75** — ⚪ **NETRAL**\n"
            "**📋 REKOMENDASI**\n"
            "⛔ **AVOID**\n"
            "Jika sudah punya: Cut loss jika break Rp820\n"
            "Jika belum punya: Buy on weakness jika mantul/hold Rp800 - Rp820\n"
            "Entry: Rp800 - Rp820\n"
            "Stop Loss: Rp780\n"
        )
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text=analysis_avoid,
            broker_data={},
            ohlc_rows=self.ohlc_rows,
        )
        summary = format_validation_summary(result)
        self.assertNotIn("mantul/hold Rp800", summary)
        self.assertNotIn("Buy on weakness", summary)
        self.assertIn("tidak disarankan entry", summary)
        self.assertIn("Jika belum punya: Lewati / tidak disarankan entry", summary)
        self.assertIn("Entry: TIDAK DISARANKAN ENTRY", summary)
        self.assertIn("Stop Loss (Pengaman Eksisting): Rp", summary)

    def test_extract_personality_and_assemble_potential_and_drawdown(self):
        """Poin 1: Ekstraksi potensi (+6%) dan drawdown (-3%) dipasangkan ke candidate jika None."""
        analysis_mandiri = """📊 **ASGR** — Analisis
Score: **55/75** — ⚠️ **WATCH**
**🧬 PERSONALITY HISTORIS**
  Basis: pola aktif hari ini | WR Event pakai TP/CL ATR dinamis
  1. Gabungan (Volume + Asing + Teknikal) — **EDGE HISTORIS**
     WR Event 63.0% | rata2 event +1.90% | D3 +3.95%
     potensi +6% | DD -3% | TP 55.6% | CL 33.3% | Timeout 11.1%
     Sample 27 | PF 2.95 | exit avg D+2.6
"""
        stats = extract_personality_wr_stats(analysis_mandiri)
        self.assertEqual(stats["potential"], 6.0)
        self.assertEqual(stats["drawdown"], -3.0)

        # Candidate with None potential and drawdown (typical Mode Mandiri)
        cand = Candidate(
            stock=Stock(code="ASGR", name="Astra Graphia Tbk.", sector="Technology"),
            bucket="🟢 SINYAL MANDIRI (PRD §6)",
            summary="mandiri 4/4",
            wr_event=None,
            potential=None,
            drawdown=None,
        )
        res = assemble_validation(
            candidate=cand,
            analysis_text=analysis_mandiri,
            broker_data={},
            ohlc_rows=self.ohlc_rows,
        )
        self.assertEqual(cand.wr_event, 63.0)
        self.assertEqual(cand.potential, 6.0)
        self.assertEqual(cand.drawdown, -3.0)


if __name__ == "__main__":
    unittest.main()
