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


if __name__ == "__main__":
    unittest.main()
