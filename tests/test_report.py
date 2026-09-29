import unittest
import tempfile
from pathlib import Path
from src.report import generate_daily_report, save_report, sync_report_to_downloads
from src.models import (
    Candidate, Stock, ValidationResult, PivotLevels, TradePlan, QuotaUsageBreakdown,
)


class TestReport(unittest.TestCase):
    def setUp(self):
        self.sector_ranking = [
            ("Financials", "Leading", 4.0, 105.2, 103.4),
            ("Energy", "Improving", 3.0, 98.5, 102.1),
        ]
        self.stock = Stock(code="BBCA", name="Bank Central Asia Tbk.", sector="Financials")
        self.candidates = [
            Candidate(stock=self.stock, bucket="SINYAL BERSIH",
                      summary="asing beli kuat", wr_event=74.1,
                      potential=11.0, drawdown=-5.0),
        ]
        self.validations = [
            ValidationResult(
                stock=self.stock,
                analysis_text="Strong buy signal",
                broker_data={"brokers": []},
                foreign_flow_5d=[(16.5e6, 16.5e6 * 6250), (1.1e6, 1.1e6 * 6225)],
                pivot=PivotLevels(pivot=6242, r1=6283, r2=6317, r3=6358,
                                  s1=6208, s2=6167, s3=6133),
                trade_plan=TradePlan(entry_low=6200, entry_high=6250,
                                    cutloss=6100, target1=6450,
                                    target2=6525, rr_ratio=1.75, atr=136),
                fundamental_data={
                    "eps": 120.0,
                    "per": 15.2,
                    "der": 0.85,
                }
            ),
        ]

    def test_report_contains_date(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("2026-09-27", report)

    def test_report_contains_sector_ranking_with_rs_metrics(self):
        """Audit Check 5a: Tabel sektor memuat skor, RS-Ratio, dan RS-Momentum."""
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("Financials", report)
        self.assertIn("Leading", report)
        self.assertIn("105.2", report)
        self.assertIn("103.4", report)

    def test_report_contains_candidates(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("BBCA", report)

    def test_report_contains_trade_plan(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("Trade Plan", report)
        self.assertIn("1.75:1", report)

    def test_report_shows_quota_integer(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("25", report)

    def test_report_shows_quota_breakdown(self):
        """Poin 3: Tampilkan rincian kuota API per modul."""
        breakdown = QuotaUsageBreakdown(
            screener_calls=1,
            benchmark_calls=1,
            rrg_sector_calls=5,
            rrg_sectors_processed=5,
            rrg_stocks_processed=6,
            validation_calls=17,
            validation_stocks_processed=3,
            total_calls=24,
            details=[
                "Screener: 1 request (screener_saham_terkini)",
                "Benchmark: 1 request (riwayat_harga BBCA 60D)",
                "RRG: 5 request (5 sektor aktif)",
                "Validasi: 17 request (3 saham: PEGE, VISI, PTBA)",
            ]
        )
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, breakdown)
        self.assertIn("Rincian Penggunaan Kuota API per Modul", report)
        self.assertIn("Screener Awal", report)
        self.assertIn("Benchmark IHSG", report)
        self.assertIn("RRG Sektor", report)
        self.assertIn("Validasi Mendalam", report)
        self.assertIn("24 request", report)

    def test_report_no_false_money_flow_label(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertNotIn("Money Flow", report)

    def test_report_contains_metric_glossary(self):
        """Audit Check 5b: Dokumentasi eksplisit istilah SINYAL BERSIH, WR Event, DD, dll."""
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("Kamus Metrik & Sumber Data", report)
        self.assertIn("SINYAL BERSIH", report)
        self.assertIn("WR Event", report)
        self.assertIn("screener_saham_terkini", report)

    def test_empty_candidates_still_generates(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, [], [], 5)
        self.assertIn("2026-09-27", report)
        self.assertIn("Tidak ada kandidat", report)

    def test_save_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            content = "# Test Report"
            path = save_report(content, tmpdir)
            self.assertTrue(Path(path).exists())
            self.assertTrue(path.endswith(".md"))

    def test_report_shows_dynamic_rrg_sample_note_for_stock_samples(self):
        """Transparansi: RRG berbasis sampel N saham representatif per sektor."""
        breakdown = QuotaUsageBreakdown(
            screener_calls=1,
            benchmark_calls=1,
            rrg_sector_calls=5,
            rrg_sectors_processed=5,
            rrg_stocks_processed=6,
            validation_calls=17,
            validation_stocks_processed=3,
            total_calls=24,
            details={"rrg_stocks_per_sector": "1-2"}
        )
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, breakdown)
        self.assertIn("RRG berbasis sampel 1-2 saham representatif per sektor", report)
        self.assertIn("(bukan agregat penuh seluruh anggota sektor)", report)

    def test_report_changes_rrg_note_when_full_index_used(self):
        """Transparansi: Jika full index digunakan, catatan otomatis berubah."""
        breakdown = QuotaUsageBreakdown(
            screener_calls=1,
            benchmark_calls=1,
            rrg_sector_calls=11,
            rrg_sectors_processed=11,
            rrg_stocks_processed=11,
            validation_calls=17,
            validation_stocks_processed=3,
            total_calls=30,
            details={"rrg_is_full_index": True}
        )
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, breakdown)
        self.assertIn("indeks sektoral resmi BEI (representasi penuh seluruh anggota sektor)", report)
        self.assertNotIn("bukan agregat penuh", report)

    def test_report_shows_historis_lemah_flag_when_wr_below_50(self):
        """Table 2 displays '⚠️ Historis Lemah' flag when candidate WR Event < 50%."""
        weak_candidate = Candidate(
            stock=Stock(code="PTBA", name="Bukit Asam Tbk.", sector="Energy"),
            bucket="AKUMULASI SENYAP",
            summary="mode senyap",
            wr_event=44.6,
            wr_event_flag="44.6% ⚠️ Historis Lemah",
        )
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, [weak_candidate], [], QuotaUsageBreakdown()
        )
        self.assertIn("44.6% ⚠️ Historis Lemah", report)

    def test_report_does_not_show_historis_lemah_flag_when_wr_above_50(self):
        """Table 2 displays clean WR Event without flag when >= 50%."""
        strong_candidate = Candidate(
            stock=Stock(code="WBSA", name="BSA Logistics Tbk.", sector="Transportation & Logistic"),
            bucket="SINYAL SENYAP",
            summary="mode senyap",
            wr_event=66.7,
        )
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, [strong_candidate], [], QuotaUsageBreakdown()
        )
        self.assertIn("66.7%", report)
        self.assertNotIn("Historis Lemah", report)

    def test_sync_report_to_downloads_preserves_utf8(self):
        """Verify sync_report_to_downloads writes valid UTF-8 file with emojis."""
        with tempfile.TemporaryDirectory() as tmp_out:
            with tempfile.TemporaryDirectory() as tmp_dl:
                content = "# Laporan 📊 IHSG 🔴\n• Sinyal 🥷 🟢\n"
                rpath = save_report(content, tmp_out)
                synced = sync_report_to_downloads(rpath, dest_dirs=[tmp_dl])
                self.assertTrue(len(synced) >= 1)
                read_back = Path(synced[0]).read_text(encoding="utf-8")
                self.assertEqual(read_back, content)


    def test_report_shows_sector_status_change_disclaimer(self):
        """Verifikasi disclaimer otomatis jika sektor kandidat berubah signifikan (misal Lagging -> Leading)."""
        prev_quadrants = {"Energy": "Lagging"}
        curr_ranking = [("Energy", "Leading", 4.0, 103.4, 100.2)]
        energy_stock = Stock(code="DSSA", name="Dian Swastatika Sentosa Tbk.", sector="Energy")
        candidate = Candidate(stock=energy_stock, bucket="SINYAL SENYAP", summary="senyap")
        val = ValidationResult(
            stock=energy_stock,
            analysis_text="Analisis DSSA",
        )
        report = generate_daily_report(
            "2026-09-28",
            curr_ranking,
            [candidate],
            [val],
            10,
            previous_sector_quadrants=prev_quadrants,
        )
        self.assertIn("PERHATIAN PERUBAHAN STATUS SEKTOR", report)
        self.assertIn("Lagging -> Leading", report)
        self.assertIn("tidak serta-merta menggantikan sinyal teknikal individual", report)

    def test_report_contains_energy_score_decomposition_note(self):
        """Verifikasi catatan dekomposisi kenaikan skor Energy memisahkan agregasi vs komposisi."""
        report = generate_daily_report(
            "2026-09-28", self.sector_ranking, self.candidates, self.validations, 25
        )
        self.assertIn("Dekomposisi Perubahan Skor Sektor Energy (3.4 -> 4.0)", report)
        self.assertIn("Porsi Perbaikan Metode Agregasi", report)
        self.assertIn("Porsi Perubahan Komposisi Anggota", report)

    def test_get_previous_sector_quadrants(self):
        """Verifikasi parsing kuadran sektor dari laporan hari sebelumnya."""
        from src.report import get_previous_sector_quadrants
        with tempfile.TemporaryDirectory() as tmpdir:
            prev_content = """# Screener IHSG - 2026-09-27
## 1. Ranking Sektor (RRG)

| Rank | Sektor | Kuadran | Skor | RS-Ratio | RS-Momentum |
|------|--------|---------|------|----------|-------------|
| 1 | Energy | Leading | 3.4 | 103.7 | 100.2 |
| 2 | Transportation & Logistic | Improving | 2.8 | 101.8 | 100.0 |
| 3 | Financials | Lagging | 1.8 | 96.6 | 99.7 |

## 2. Kandidat Screening
"""
            prev_path = Path(tmpdir) / "screener_2026-09-27.md"
            prev_path.write_text(prev_content, encoding="utf-8")

            parsed = get_previous_sector_quadrants(tmpdir, "2026-09-28")
            self.assertEqual(parsed.get("Energy"), "Leading")
            self.assertEqual(parsed.get("Transportation & Logistic"), "Improving")
            self.assertEqual(parsed.get("Financials"), "Lagging")


if __name__ == "__main__":
    unittest.main()
