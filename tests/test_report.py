import unittest
import tempfile
from pathlib import Path
from src.report import generate_daily_report, save_report
from src.models import (
    Candidate, Stock, ValidationResult, PivotLevels, TradePlan,
)


class TestReport(unittest.TestCase):
    def setUp(self):
        self.sector_ranking = [
            ("Financials", "Leading", 3.5),
            ("Energy", "Improving", 2.8),
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
                foreign_flow_5d=[16.5e6, 1.1e6, -2.7e6],
                pivot=PivotLevels(pivot=6242, r1=6283, r2=6317, r3=6358,
                                  s1=6208, s2=6167, s3=6133),
                trade_plan=TradePlan(entry_low=6200, entry_high=6250,
                                    cutloss=6114, target1=6454,
                                    target2=6522, rr_ratio=1.5, atr=136),
            ),
        ]

    def test_report_contains_date(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("2026-09-27", report)

    def test_report_contains_sector_ranking(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("Financials", report)
        self.assertIn("Leading", report)

    def test_report_contains_candidates(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("BBCA", report)

    def test_report_contains_trade_plan(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("Trade Plan", report)
        self.assertIn("1.5:1", report)

    def test_report_shows_quota(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("25", report)

    def test_report_no_false_money_flow_label(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertNotIn("Money Flow", report)

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


if __name__ == "__main__":
    unittest.main()
