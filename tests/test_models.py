import unittest
import json
from pathlib import Path


class TestSectorConfig(unittest.TestCase):
    def test_sectors_json_exists(self):
        path = Path(__file__).parent.parent / "config" / "sectors.json"
        self.assertTrue(path.exists(), f"Missing {path}")

    def test_sectors_has_11_sectors(self):
        path = Path(__file__).parent.parent / "config" / "sectors.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 11)

    def test_each_sector_has_stocks(self):
        path = Path(__file__).parent.parent / "config" / "sectors.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for sector, stocks in data.items():
            self.assertIsInstance(stocks, list, f"{sector} stocks must be a list")
            self.assertGreater(len(stocks), 0, f"{sector} has no stocks")
            for code in stocks:
                self.assertRegex(code, r'^[A-Z0-9]{4}$', f"Invalid code: {code}")

    def test_known_sectors_present(self):
        path = Path(__file__).parent.parent / "config" / "sectors.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        expected = [
            "Energy", "Basic Materials", "Industrials",
            "Consumer Non-Cyclicals", "Consumer Cyclicals",
            "Healthcare", "Financials", "Properties & Real Estate",
            "Technology", "Infrastructures", "Transportation & Logistic",
        ]
        for s in expected:
            self.assertIn(s, data, f"Missing sector: {s}")


if __name__ == "__main__":
    unittest.main()
