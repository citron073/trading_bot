from __future__ import annotations

import unittest

import pandas as pd

import evaluation as ke


class KeibaEvaluationTest(unittest.TestCase):
    def test_upsert_prediction_archive_keeps_existing_timestamp_when_prediction_unchanged(self) -> None:
        existing = pd.DataFrame(
            [
                {
                    "race_id": "202603210101",
                    "race_date": "2026-03-21",
                    "top_horse": "A",
                    "single_pick": "A",
                    "budget_basis_key": "trend",
                    "budget_basis_label": "今週傾向反映",
                    "budget_basis_mode": "半自動",
                    "predicted_at": "2026-03-21T08:00:00",
                }
            ]
        )
        fresh = pd.DataFrame(
            [
                {
                    "race_id": "202603210101",
                    "race_date": "2026-03-21",
                    "top_horse": "A",
                    "single_pick": "A",
                    "budget_basis_key": "trend",
                    "budget_basis_label": "今週傾向反映",
                    "budget_basis_mode": "半自動",
                    "predicted_at": "2026-03-21T09:00:00",
                }
            ]
        )

        merged = ke.upsert_prediction_archive(existing, fresh)

        self.assertEqual(len(merged), 1)
        self.assertEqual(str(merged.iloc[0]["predicted_at"]), "2026-03-21T08:00:00")

    def test_build_prediction_feedback_and_aggregate(self) -> None:
        predictions = pd.DataFrame(
            [
                {
                    "race_id": "202603210101",
                    "race_date": "2026-03-21",
                    "race_name": "中京1R",
                    "race_grade": "未判定",
                    "venue": "中京",
                    "condition_adjustment_count": 2,
                    "condition_adjustments": "開催 中京 / 距離帯 マイル",
                    "budget_basis_key": "trend",
                    "budget_basis_label": "今週傾向反映",
                    "budget_basis_mode": "半自動",
                    "top_horse": "A",
                    "llm_top_horse": "B",
                    "llm_dark_horse": "B",
                    "llm_danger_favorite": "A",
                    "top_horse_odds": 2.5,
                    "single_pick": "A",
                    "place_pick": "B",
                    "quinella_pick": "A-B",
                    "wide_pick": "B-C",
                    "exacta_pick": "A-B",
                    "trio_pick": "A-B-C",
                    "trifecta_pick": "A-B-C",
                    "predicted_at": "2026-03-21T09:00:00",
                },
                {
                    "race_id": "202603210102",
                    "race_date": "2026-03-21",
                    "race_name": "中京2R",
                    "race_grade": "未判定",
                    "venue": "中京",
                    "condition_adjustment_count": 0,
                    "condition_adjustments": "-",
                    "budget_basis_key": "base",
                    "budget_basis_label": "ベース配分",
                    "budget_basis_mode": "手動",
                    "top_horse": "X",
                    "llm_top_horse": "L",
                    "llm_dark_horse": "L",
                    "llm_danger_favorite": "X",
                    "top_horse_odds": 9.9,
                    "single_pick": "X",
                    "place_pick": "Y",
                    "quinella_pick": "X-Y",
                    "wide_pick": "X-Z",
                    "exacta_pick": "X-Y",
                    "trio_pick": "X-Y-Z",
                    "trifecta_pick": "X-Y-Z",
                    "predicted_at": "2026-03-21T09:00:00",
                },
            ]
        )
        history = pd.DataFrame(
            [
                {"race_id": "202603210101", "horse": "A", "gate": 1, "finish": 1, "odds": 2.5, "place_odds": 1.2},
                {"race_id": "202603210101", "horse": "B", "gate": 2, "finish": 2, "odds": 4.2, "place_odds": 1.4},
                {"race_id": "202603210101", "horse": "C", "gate": 3, "finish": 3, "odds": 8.7, "place_odds": 1.8},
                {"race_id": "202603210102", "horse": "L", "gate": 1, "finish": 1, "odds": 5.5, "place_odds": 1.8},
                {"race_id": "202603210102", "horse": "M", "gate": 2, "finish": 2, "odds": 6.8, "place_odds": 2.1},
                {"race_id": "202603210102", "horse": "N", "gate": 3, "finish": 3, "odds": 7.2, "place_odds": 2.4},
            ]
        )
        payouts = pd.DataFrame(
            [
                {"race_id": "202603210101", "bet_type": "単勝", "ticket": "1", "payout": 250},
                {"race_id": "202603210101", "bet_type": "複勝", "ticket": "2", "payout": 140},
                {"race_id": "202603210101", "bet_type": "馬連", "ticket": "1-2", "payout": 430},
                {"race_id": "202603210101", "bet_type": "ワイド", "ticket": "2-3", "payout": 260},
                {"race_id": "202603210101", "bet_type": "馬単", "ticket": "1-2", "payout": 720},
                {"race_id": "202603210101", "bet_type": "三連複", "ticket": "1-2-3", "payout": 910},
                {"race_id": "202603210101", "bet_type": "三連単", "ticket": "1-2-3", "payout": 3210},
            ]
        )

        feedback = ke.build_prediction_feedback(predictions, history, payouts)
        summary = ke.aggregate_prediction_feedback(feedback)
        bet_rows = ke.build_bet_type_feedback_rows(feedback)
        budget_perf = ke.build_budget_basis_performance_table(feedback)
        condition_perf = ke.build_condition_adjustment_performance_table(feedback)
        condition_segments = ke.build_condition_segment_performance_table(feedback)
        llm_disagreement_perf = ke.build_llm_disagreement_performance_table(feedback)

        race1 = feedback[feedback["race_id"] == "202603210101"].iloc[0]
        race2 = feedback[feedback["race_id"] == "202603210102"].iloc[0]
        race1_quinella = bet_rows[(bet_rows["race_id"] == "202603210101") & (bet_rows["bet_type"] == "馬連")].iloc[0]

        self.assertTrue(bool(race1["single_hit"]))
        self.assertTrue(bool(race1["place_hit"]))
        self.assertTrue(bool(race1["trifecta_hit"]))
        self.assertFalse(bool(race2["single_hit"]))
        self.assertEqual(len(bet_rows), 14)
        self.assertIn("budget_basis_label", bet_rows.columns)
        self.assertEqual(str(race1_quinella["pick"]), "A-B")
        self.assertTrue(bool(race1_quinella["hit"]))
        self.assertAlmostEqual(float(race1_quinella["payout_100"]), 430.0, places=6)
        self.assertEqual(summary["evaluated_races"], 2)
        self.assertAlmostEqual(float(summary["single_hit_rate"]), 0.5, places=6)
        self.assertAlmostEqual(float(summary["place_hit_rate"]), 0.5, places=6)
        self.assertAlmostEqual(float(summary["trifecta_hit_rate"]), 0.5, places=6)
        self.assertAlmostEqual(float(summary["single_roi"]), 1.25, places=6)
        self.assertAlmostEqual(float(summary["place_roi"]), 0.7, places=6)
        self.assertAlmostEqual(float(summary["quinella_roi"]), 2.15, places=6)
        self.assertAlmostEqual(float(summary["trio_roi"]), 4.55, places=6)
        self.assertAlmostEqual(float(summary["trifecta_roi"]), 16.05, places=6)
        self.assertEqual(int(len(budget_perf)), 2)
        self.assertIn("今週傾向反映", budget_perf["配分基準"].tolist())
        self.assertEqual(int(condition_perf.iloc[0]["評価済みレース"]), 1)
        self.assertIn("開催 中京", condition_segments["条件補正"].tolist())
        self.assertIn("llm_top_horse", feedback.columns)
        self.assertEqual(str(race1["llm_disagreement_reason"]), "LLMは穴候補を本命視 / LLMはデータ本命を危険視")
        self.assertEqual(int(llm_disagreement_perf.iloc[0]["評価済みレース"]), 2)
        self.assertAlmostEqual(float(llm_disagreement_perf.iloc[0]["データ本命勝率"]), 0.5, places=6)
        self.assertAlmostEqual(float(llm_disagreement_perf.iloc[0]["LLM本命勝率"]), 0.5, places=6)

    def test_aggregate_prediction_feedback_splits_pending_and_upcoming(self) -> None:
        feedback = pd.DataFrame(
            [
                {
                    "race_id": "202603210101",
                    "race_date": "2026-03-21",
                    "result_available": True,
                    "single_pick": "A",
                    "place_pick": "A",
                },
                {
                    "race_id": "202603220101",
                    "race_date": "2026-03-22",
                    "result_available": False,
                    "single_pick": "B",
                    "place_pick": "B",
                },
                {
                    "race_id": "209903220101",
                    "race_date": "2099-03-22",
                    "result_available": False,
                    "single_pick": "C",
                    "place_pick": "C",
                },
                {
                    "race_id": "UNKNOWN",
                    "race_date": "",
                    "result_available": False,
                    "single_pick": "D",
                    "place_pick": "D",
                },
            ]
        )

        summary = ke.aggregate_prediction_feedback(feedback)

        self.assertEqual(int(summary["stored_predictions"]), 4)
        self.assertEqual(int(summary["evaluated_races"]), 1)
        self.assertEqual(int(summary["pending_races"]), 1)
        self.assertEqual(int(summary["upcoming_races"]), 1)
        self.assertEqual(int(summary["undated_predictions"]), 1)


if __name__ == "__main__":
    unittest.main()
