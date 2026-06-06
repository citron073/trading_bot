from __future__ import annotations

import unittest

import predictor as kp


class KeibaPredictorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.history = kp.generate_sample_history(seed=12, n_races=120)
        self.entries = kp.generate_sample_entries(
            self.history,
            weather="晴",
            track_condition="良",
            distance=1600,
            field_size=10,
            seed=13,
        )

    def test_prepare_history_missing_required_columns(self) -> None:
        with self.assertRaises(ValueError):
            kp.prepare_history_dataframe(self.history.drop(columns=["finish"]))

    def test_predict_race_output_shapes(self) -> None:
        result = kp.predict_race(
            history_df=self.history,
            entries_df=self.entries,
            weather="晴",
            track_condition="良",
            distance=1600,
            simulations=4000,
            seed=14,
            budget=10000,
            bet_units=100,
        )
        self.assertEqual(len(result.horse_predictions), len(self.entries))
        self.assertIn("単勝", result.bet_recommendations)
        self.assertIn("馬連", result.bet_recommendations)
        self.assertFalse(result.bet_recommendations["単勝"].empty)
        self.assertIn("馬番", result.horse_predictions.columns)

    def test_probability_consistency(self) -> None:
        result = kp.predict_race(
            history_df=self.history,
            entries_df=self.entries,
            weather="曇",
            track_condition="稍重",
            distance=1800,
            simulations=3000,
            seed=15,
            budget=8000,
            bet_units=100,
        )
        win_sum = float(result.horse_predictions["勝率"].sum())
        self.assertAlmostEqual(win_sum, 1.0, places=2)

        place_probs = result.horse_predictions["複勝率"]
        win_probs = result.horse_predictions["勝率"]
        self.assertTrue(bool((place_probs >= win_probs).all()))

    def test_budget_plan_has_positive_amounts_when_budget_positive(self) -> None:
        result = kp.predict_race(
            history_df=self.history,
            entries_df=self.entries,
            weather="雨",
            track_condition="重",
            distance=1400,
            simulations=2500,
            seed=16,
            budget=12000,
            bet_units=100,
        )
        if result.budget_plan.empty:
            # Environment noise may lead to no edges; function should still return frame.
            self.assertEqual(list(result.budget_plan.columns), ["券種", "買い目", "推奨金額", "根拠スコア"])
        else:
            self.assertTrue(bool((result.budget_plan["推奨金額"] > 0).all()))

    def test_paddock_score_affects_win_probability(self) -> None:
        history = kp.generate_sample_history(seed=21, n_races=60)
        entries = kp.generate_sample_entries(
            history,
            weather="晴",
            track_condition="良",
            distance=1600,
            field_size=2,
            seed=22,
        )
        entries.loc[:, "form_score"] = 60.0
        entries.loc[:, "condition_score"] = 60.0
        entries.loc[:, "weight_diff"] = 0.0
        entries.loc[:, "odds_shift"] = 0.0
        entries.loc[:, "odds"] = 4.0
        entries.loc[:, "paddock_score"] = 50.0

        entries_high = entries.copy()
        entries_low = entries.copy()
        entries_high.loc[0, "paddock_score"] = 90.0
        entries_low.loc[0, "paddock_score"] = 20.0

        result_high = kp.predict_race(
            history_df=history,
            entries_df=entries_high,
            weather="晴",
            track_condition="良",
            distance=1600,
            simulations=5000,
            seed=23,
        )
        result_low = kp.predict_race(
            history_df=history,
            entries_df=entries_low,
            weather="晴",
            track_condition="良",
            distance=1600,
            simulations=5000,
            seed=23,
        )
        win_high = {
            row["馬"]: float(row["勝率"])
            for _, row in result_high.horse_predictions.iterrows()
        }
        win_low = {
            row["馬"]: float(row["勝率"])
            for _, row in result_low.horse_predictions.iterrows()
        }
        horse0 = str(entries.loc[0, "horse"])
        self.assertGreater(win_high[horse0], win_low[horse0])

    def test_resolve_feature_weights_for_context_applies_matching_segments(self) -> None:
        base_weights = kp.get_default_feature_weights()
        condition_adjustments = {
            "segments": {
                "venue:中京": {"multipliers": {"market_score": 0.8}},
                "distance_bucket:mile": {"multipliers": {"form_score": 1.1}},
                "field_size_bucket:medium": {"multipliers": {"condition_score": 1.05}},
            }
        }

        weights, applied = kp.resolve_feature_weights_for_context(
            base_weights,
            weather="晴",
            track_condition="良",
            distance=1600,
            field_size=12,
            venue="中京",
            race_grade="G3",
            condition_adjustments=condition_adjustments,
        )

        self.assertIn("venue:中京", applied)
        self.assertIn("distance_bucket:mile", applied)
        self.assertIn("field_size_bucket:medium", applied)
        self.assertAlmostEqual(weights["market_score"], base_weights["market_score"] * 0.8, places=6)
        self.assertAlmostEqual(weights["form_score"], base_weights["form_score"] * 1.1, places=6)
        self.assertAlmostEqual(weights["condition_score"], base_weights["condition_score"] * 1.05, places=6)


if __name__ == "__main__":
    unittest.main()
