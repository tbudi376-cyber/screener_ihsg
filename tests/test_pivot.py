import unittest
from src.pivot import (
    calculate_pivot,
    calculate_atr,
    calculate_trade_plan,
    get_idx_tick_size,
    round_to_idx_tick,
)
from src.models import PivotLevels, OHLCRow, TradePlan


class TestPivot(unittest.TestCase):
    def test_standard_pivot_bbca(self):
        result = calculate_pivot(high=6275, low=6200, close=6250)
        self.assertIsInstance(result, PivotLevels)
        self.assertAlmostEqual(result.pivot, (6275 + 6200 + 6250) / 3, places=2)
        self.assertAlmostEqual(result.r1, 2 * result.pivot - 6200, places=0)
        self.assertAlmostEqual(result.s1, 2 * result.pivot - 6275, places=0)
        self.assertAlmostEqual(result.r2, result.pivot + (6275 - 6200), places=0)
        self.assertAlmostEqual(result.s2, result.pivot - (6275 - 6200), places=0)

    def test_pivot_symmetry(self):
        result = calculate_pivot(high=100, low=90, close=95)
        self.assertGreater(result.r1, result.pivot)
        self.assertGreater(result.r2, result.r1)
        self.assertLess(result.s1, result.pivot)
        self.assertLess(result.s2, result.s1)

    def test_get_idx_tick_size(self):
        """Poin 1: Verifikasi seluruh 5 fraksi harga resmi BEI."""
        # Bracket 1: < 200 -> Rp 1
        self.assertEqual(get_idx_tick_size(50), 1)
        self.assertEqual(get_idx_tick_size(199), 1)
        # Bracket 2: 200 - <500 -> Rp 2
        self.assertEqual(get_idx_tick_size(200), 2)
        self.assertEqual(get_idx_tick_size(498), 2)
        # Bracket 3: 500 - <2000 -> Rp 5
        self.assertEqual(get_idx_tick_size(500), 5)
        self.assertEqual(get_idx_tick_size(1337), 5)
        self.assertEqual(get_idx_tick_size(1995), 5)
        # Bracket 4: 2000 - <5000 -> Rp 10
        self.assertEqual(get_idx_tick_size(2000), 10)
        self.assertEqual(get_idx_tick_size(3033), 10)
        self.assertEqual(get_idx_tick_size(4990), 10)
        # Bracket 5: >= 5000 -> Rp 25
        self.assertEqual(get_idx_tick_size(5000), 25)
        self.assertEqual(get_idx_tick_size(6242), 25)

    def test_round_to_idx_tick(self):
        """Poin 1: Pembulatan ke fraksi harga resmi BEI."""
        # < 200
        self.assertEqual(round_to_idx_tick(141.4), 141)
        self.assertEqual(round_to_idx_tick(99.6), 100)
        # 200 - <500 (tick 2)
        self.assertIn(round_to_idx_tick(201), (200, 202))
        self.assertEqual(round_to_idx_tick(455), 456)
        # 500 - <2000 (tick 5) - Kasus VISI
        self.assertEqual(round_to_idx_tick(1337), 1335)
        self.assertEqual(round_to_idx_tick(1338), 1340)
        self.assertEqual(round_to_idx_tick(628), 630)
        # 2000 - <5000 (tick 10) - Kasus PTBA
        self.assertEqual(round_to_idx_tick(3033), 3030)
        self.assertEqual(round_to_idx_tick(3037), 3040)
        # >= 5000 (tick 25) - Kasus BBCA
        self.assertEqual(round_to_idx_tick(6242), 6250)
        self.assertEqual(round_to_idx_tick(6208), 6200)

    def test_pege_cutloss_strictly_below_entry_low(self):
        """PEGE Bug Fix: Cutloss must NEVER be inside entry range [129, 141]."""
        pivots = PivotLevels(
            pivot=135.0,
            r1=148.0,
            r2=154.0,
            r3=167.0,
            s1=129.0,
            s2=116.0,
            s3=110.0,
        )
        plan = calculate_trade_plan(
            close=141.0,
            atr=8.21,
            support=129.0,
            pivot_levels=pivots,
        )
        self.assertIsInstance(plan, TradePlan)
        # Core audit check 1: Cutloss MUST be strictly lower than entry_low
        self.assertLess(
            plan.cutloss,
            plan.entry_low,
            f"Cutloss ({plan.cutloss}) must be below entry_low ({plan.entry_low})",
        )
        self.assertEqual(plan.entry_low, 129)
        self.assertEqual(plan.entry_high, 141)
        self.assertLessEqual(plan.cutloss, 125)

    def test_trade_plan_all_fields_comply_with_idx_tick(self):
        """Poin 1: Seluruh field Trade Plan wajib patuh fraksi BEI."""
        # Emiten VISI: range 1.300-an (tick 5)
        visi_pivots = PivotLevels(
            pivot=1373.0, r1=1427.0, r2=1463.0, r3=1517.0,
            s1=1337.0, s2=1283.0, s3=1247.0
        )
        visi_plan = calculate_trade_plan(
            close=1390.0, atr=95.7, support=1337.0, pivot_levels=visi_pivots
        )
        for field_name in ["entry_low", "entry_high", "cutloss", "target1", "target2"]:
            val = getattr(visi_plan, field_name)
            self.assertEqual(val % 5, 0, f"{field_name}={val} for VISI must be multiple of 5")
            self.assertIsInstance(val, int)

        # Emiten PTBA: range 3.000-an (tick 10)
        ptba_pivots = PivotLevels(
            pivot=3087.0, r1=3143.0, r2=3197.0, r3=3253.0,
            s1=3033.0, s2=2977.0, s3=2923.0
        )
        ptba_plan = calculate_trade_plan(
            close=3090.0, atr=100.0, support=3033.0, pivot_levels=ptba_pivots
        )
        for field_name in ["entry_low", "entry_high", "cutloss", "target1", "target2"]:
            val = getattr(ptba_plan, field_name)
            self.assertEqual(val % 10, 0, f"{field_name}={val} for PTBA must be multiple of 10")
            self.assertIsInstance(val, int)

    def test_rr_ratio_varies_dynamically_by_stock_structure(self):
        """Audit Check 2: R:R must not be rigidly hardcoded to 1.5:1."""
        pivots_a = PivotLevels(
            pivot=1000.0, r1=1150.0, r2=1250.0, r3=1350.0,
            s1=950.0, s2=900.0, s3=850.0,
        )
        plan_a = calculate_trade_plan(close=1000.0, atr=30.0, support=950.0, pivot_levels=pivots_a)

        pivots_b = PivotLevels(
            pivot=500.0, r1=520.0, r2=540.0, r3=560.0,
            s1=480.0, s2=450.0, s3=420.0,
        )
        plan_b = calculate_trade_plan(close=500.0, atr=15.0, support=480.0, pivot_levels=pivots_b)

        self.assertNotEqual(plan_a.rr_ratio, plan_b.rr_ratio)
        self.assertLess(plan_a.cutloss, plan_a.entry_low)
        self.assertLess(plan_b.cutloss, plan_b.entry_low)

    def test_atr_calculation_oldest_to_newest(self):
        """Poin 2: Verifikasi calculate_atr menggunakan urutan data oldest-to-newest."""
        # Row 0 adalah hari tertua (2026-09-01), Row N adalah hari terbaru (2026-09-15)
        rows = [
            OHLCRow(
                date=f"2026-09-{i+1:02d}",
                open=6200 + i * 10,
                high=6275 + i * 5,
                low=6200 - i * 5,
                close=6250 + i * 3,
                volume=89e6,
                value=558e9,
                f_buy=0,
                f_sell=0,
                n_foreign=0,
            )
            for i in range(15)
        ]
        atr = calculate_atr(rows, period=14)
        self.assertGreater(atr, 0)
        self.assertIsInstance(atr, float)

    def test_cutloss_prefers_atr_when_below_entry_low(self):
        """Temuan 1: Cutloss memilih Close - ATR jika berada di bawah entry_low, fallback ke S2 jika tidak."""
        # Kasus 1: VISI -> Close 1390, ATR 95.7, entry_low 1335.
        # Close - ATR = 1294.3 < 1335. Cutloss harus 1295 (ATR-based), bukan S2 (1285).
        visi_pivots = PivotLevels(
            pivot=1373.0, r1=1427.0, r2=1463.0, r3=1517.0,
            s1=1337.0, s2=1283.0, s3=1247.0
        )
        visi_plan = calculate_trade_plan(
            close=1390.0, atr=95.7, support=1337.0, pivot_levels=visi_pivots
        )
        self.assertEqual(visi_plan.cutloss, 1295)
        self.assertLess(visi_plan.cutloss, visi_plan.entry_low)

        # Kasus 2: PTBA -> Close 3090, ATR 100, entry_low 3030.
        # Close - ATR = 2990 < 3030. Cutloss harus 2990 (ATR-based), bukan S2 (2980).
        ptba_pivots = PivotLevels(
            pivot=3087.0, r1=3143.0, r2=3197.0, r3=3253.0,
            s1=3033.0, s2=2977.0, s3=2923.0
        )
        ptba_plan = calculate_trade_plan(
            close=3090.0, atr=100.0, support=3033.0, pivot_levels=ptba_pivots
        )
        self.assertEqual(ptba_plan.cutloss, 2990)
        self.assertLess(ptba_plan.cutloss, ptba_plan.entry_low)

        # Kasus 3: PEGE -> Close 141, ATR 8.21, entry_low 129.
        # Close - ATR = 132.79 >= 129 (jatuh di dalam entry range).
        # Fallback ke S2 (116). Cutloss harus 116.
        pege_pivots = PivotLevels(
            pivot=135.0, r1=148.0, r2=154.0, r3=167.0,
            s1=129.0, s2=116.0, s3=110.0
        )
        pege_plan = calculate_trade_plan(
            close=141.0, atr=8.21, support=129.0, pivot_levels=pege_pivots
        )
        self.assertEqual(pege_plan.cutloss, 116)
        self.assertLess(pege_plan.cutloss, pege_plan.entry_low)

    def test_trade_plan_rr_warning_when_rr_below_1(self):
        """Temuan 2: Trade plan menghasilkan warning saat R:R < 1.0."""
        # PEGE has R:R = 0.68:1 (< 1.0)
        pege_pivots = PivotLevels(
            pivot=135.0, r1=148.0, r2=154.0, r3=167.0,
            s1=129.0, s2=116.0, s3=110.0
        )
        plan = calculate_trade_plan(
            close=141.0, atr=8.21, support=129.0, pivot_levels=pege_pivots
        )
        self.assertLess(plan.rr_ratio, 1.0)
        self.assertTrue(bool(plan.warning))
        self.assertIn("PERINGATAN R:R < 1.0", plan.warning)
        self.assertIn("0.68:1", plan.warning)

        # Stock with healthy R:R >= 1.0 should have empty warning
        visi_pivots = PivotLevels(
            pivot=1373.0, r1=1427.0, r2=1463.0, r3=1517.0,
            s1=1337.0, s2=1283.0, s3=1247.0
        )
        plan_visi = calculate_trade_plan(
            close=1390.0, atr=95.7, support=1337.0, pivot_levels=visi_pivots
        )
    def test_trade_plan_max_entry_formula_and_tunggu_status(self):
        """Verifikasi formula entry maksimum E <= (T + k*S)/(1 + k) dan status TUNGGU."""
        # DSSA scenario: close=1055, atr=70, support=1028 (S1)
        pivots = PivotLevels(
            pivot=1057.0, r1=1083.0, r2=1112.0, r3=1138.0,
            s1=1028.0, s2=1002.0, s3=973.0,
        )
        plan = calculate_trade_plan(
            close=1055.0, atr=69.64, support=1028.0, pivot_levels=pivots, min_rr=1.0
        )
        # Target 1 = 1085, Cutloss = 985
        # Max entry = (1085 + 1.0 * 985) / 2 = 1035
        self.assertEqual(plan.max_entry, 1035)
        self.assertEqual(plan.entry_low, 1030)
        self.assertEqual(plan.entry_high, 1055)
        # Karena close (1055) > max_entry (1035), status harus TUNGGU
        self.assertEqual(plan.status, "TUNGGU (Buy on Weakness)")
        # R:R pada max_entry harus tepat >= 1.0
        self.assertGreaterEqual(plan.rr_at_max_entry, 1.0)
        # R:R pada midpoint harus < 1.0 (0.74:1)
        self.assertEqual(plan.rr_ratio, 0.74)
        self.assertIn("TUNGGU (Buy on Weakness)", plan.warning)

    def test_trade_plan_invalid_when_max_entry_below_entry_low(self):
        """Verifikasi status PLAN TIDAK VALID ketika max_entry < entry_low."""
        # Setup di mana stop loss sangat dalam dan target sangat sempit sehingga max_entry < entry_low
        pivots = PivotLevels(
            pivot=100.0, r1=102.0, r2=104.0, r3=106.0,
            s1=98.0, s2=80.0, s3=70.0,
        )
        # close=100, target1=102, cutloss=80
        # raw max_entry = (102 + 1.0*80)/2 = 91.0 < entry_low (98)
        plan = calculate_trade_plan(
            close=100.0, atr=20.0, support=98.0, pivot_levels=pivots, min_rr=1.0
        )
        self.assertEqual(plan.status, "PLAN TIDAK VALID")
        self.assertLess(plan.max_entry, plan.entry_low)
        self.assertIn("PLAN TIDAK VALID", plan.warning)


if __name__ == "__main__":
    unittest.main()
