from __future__ import annotations

import unittest

import pandas as pd

import feedback_learning as fl


class FeedbackLearningTest(unittest.TestCase):
    def test_apply_feedback_learning_adjusts_market_weight_down_when_top_misses_dominate(self) -> None:
        rows = []
        for idx in range(20):
            rows.append(
                {
                    "race_id": f"R{idx:03d}",
                    "horse": f"Fav{idx}",
                    "predicted_rank": 1,
                    "market_factor": 0.95,
                    "form_factor": 0.35,
                    "condition_factor": 0.40,
                    "horse_win_rate": 0.20,
                    "horse_place_rate": 0.30,
                    "jockey_win_rate": 0.18,
                    "jockey_place_rate": 0.28,
                    "trainer_win_rate": 0.16,
                    "trainer_place_rate": 0.24,
                    "gate_place_rate": 0.25,
                    "weather_fit": 0.30,
                    "track_fit": 0.32,
                    "distance_fit": 0.38,
                    "paddock_factor": 0.42,
                    "weight_diff_factor": 0.55,
                    "odds_shift_factor": 0.60,
                    "finish": 6,
                }
            )
            rows.append(
                {
                    "race_id": f"R{idx:03d}",
                    "horse": f"Shot{idx}",
                    "predicted_rank": 5,
                    "market_factor": 0.25,
                    "form_factor": 0.78,
                    "condition_factor": 0.82,
                    "horse_win_rate": 0.44,
                    "horse_place_rate": 0.58,
                    "jockey_win_rate": 0.33,
                    "jockey_place_rate": 0.46,
                    "trainer_win_rate": 0.29,
                    "trainer_place_rate": 0.41,
                    "gate_place_rate": 0.40,
                    "weather_fit": 0.64,
                    "track_fit": 0.66,
                    "distance_fit": 0.72,
                    "paddock_factor": 0.80,
                    "weight_diff_factor": 0.70,
                    "odds_shift_factor": 0.68,
                    "finish": 1,
                }
            )
        learning_df = pd.DataFrame(rows)
        learning_df["win_target"] = (learning_df["finish"] == 1).astype(float)
        learning_df["place_target"] = (learning_df["finish"] <= 3).astype(float)
        base_weights = {
            "market_score": 0.55,
            "form_score": 0.80,
            "condition_score": 0.90,
            "horse_win": 1.70,
            "horse_place": 1.35,
            "jockey_win": 1.10,
            "jockey_place": 0.70,
            "trainer_win": 0.90,
            "trainer_place": 0.60,
            "gate_place": 0.50,
            "weather_place": 0.80,
            "track_place": 0.80,
            "distance_fit": 0.80,
            "paddock_score": 0.70,
            "weight_diff_score": 0.40,
            "odds_shift_score": 0.40,
        }

        adjusted, meta = fl.apply_feedback_learning(base_weights, learning_df, alpha=0.5, min_rows=10)

        self.assertTrue(bool(meta.get("applied")))
        self.assertLess(adjusted["market_score"], base_weights["market_score"])
        self.assertGreater(adjusted["form_score"], base_weights["form_score"])
        self.assertGreater(adjusted["condition_score"], base_weights["condition_score"])

    def test_build_condition_adjustments_creates_segment_payload(self) -> None:
        rows = []
        for idx in range(14):
            rows.append(
                {
                    "race_id": f"C{idx:03d}",
                    "horse": f"Fav{idx}",
                    "predicted_rank": 1,
                    "race_grade": "G3",
                    "venue": "中京",
                    "weather": "雨",
                    "track_condition": "重",
                    "distance": 1400,
                    "field_size": 16,
                    "market_factor": 0.94,
                    "form_factor": 0.30,
                    "condition_factor": 0.34,
                    "horse_win_rate": 0.18,
                    "horse_place_rate": 0.28,
                    "jockey_win_rate": 0.16,
                    "jockey_place_rate": 0.24,
                    "trainer_win_rate": 0.15,
                    "trainer_place_rate": 0.22,
                    "gate_place_rate": 0.25,
                    "weather_fit": 0.28,
                    "track_fit": 0.30,
                    "distance_fit": 0.36,
                    "paddock_factor": 0.40,
                    "weight_diff_factor": 0.45,
                    "odds_shift_factor": 0.50,
                    "finish": 7,
                    "win_target": 0.0,
                    "place_target": 0.0,
                    "distance_bucket": "sprint",
                    "field_size_bucket": "large",
                }
            )
            rows.append(
                {
                    "race_id": f"C{idx:03d}",
                    "horse": f"Shot{idx}",
                    "predicted_rank": 5,
                    "race_grade": "G3",
                    "venue": "中京",
                    "weather": "雨",
                    "track_condition": "重",
                    "distance": 1400,
                    "field_size": 16,
                    "market_factor": 0.22,
                    "form_factor": 0.82,
                    "condition_factor": 0.84,
                    "horse_win_rate": 0.42,
                    "horse_place_rate": 0.58,
                    "jockey_win_rate": 0.31,
                    "jockey_place_rate": 0.44,
                    "trainer_win_rate": 0.28,
                    "trainer_place_rate": 0.39,
                    "gate_place_rate": 0.36,
                    "weather_fit": 0.70,
                    "track_fit": 0.72,
                    "distance_fit": 0.76,
                    "paddock_factor": 0.81,
                    "weight_diff_factor": 0.68,
                    "odds_shift_factor": 0.64,
                    "finish": 1,
                    "win_target": 1.0,
                    "place_target": 1.0,
                    "distance_bucket": "sprint",
                    "field_size_bucket": "large",
                }
            )

        learning_df = pd.DataFrame(rows)
        payload = fl.build_condition_adjustments(
            learning_df,
            alpha=0.25,
            min_rows=20,
            min_races=10,
            min_top_rank_rows=8,
        )

        self.assertTrue(bool(payload.get("applied")))
        self.assertIn("venue:中京", payload.get("segments", {}))
        venue_segment = payload["segments"]["venue:中京"]
        self.assertLess(float(venue_segment["multipliers"]["market_score"]), 1.0)
        self.assertGreater(float(venue_segment["multipliers"]["form_score"]), 1.0)

    def test_filter_reflection_learning_rows_keeps_missed_top_pick_races(self) -> None:
        learning_df = pd.DataFrame(
            [
                {"race_id": "R1", "horse": "A", "predicted_rank": 1, "win_target": 0.0},
                {"race_id": "R1", "horse": "B", "predicted_rank": 2, "win_target": 1.0},
                {"race_id": "R2", "horse": "C", "predicted_rank": 1, "win_target": 1.0},
                {"race_id": "R2", "horse": "D", "predicted_rank": 2, "win_target": 0.0},
            ]
        )

        filtered = fl.filter_reflection_learning_rows(learning_df)

        self.assertEqual(sorted(filtered["race_id"].unique().tolist()), ["R1"])
        self.assertTrue(bool(filtered["reflection_focus"].all()))


if __name__ == "__main__":
    unittest.main()
