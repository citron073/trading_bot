from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

import pandas as pd

import auto_agent as aa


class AutoAgentTests(unittest.TestCase):
    def test_generate_weekly_predictions_creates_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            history = pd.DataFrame(
                [
                    {"race_id": "H1", "horse": "Alpha", "jockey": "J1", "trainer": "T1", "weather": "晴", "track_condition": "良", "distance": 1600, "finish": 1, "odds": 2.5, "place_odds": 1.4, "gate": 1},
                    {"race_id": "H1", "horse": "Beta", "jockey": "J2", "trainer": "T2", "weather": "晴", "track_condition": "良", "distance": 1600, "finish": 2, "odds": 4.0, "place_odds": 1.7, "gate": 2},
                    {"race_id": "H1", "horse": "Gamma", "jockey": "J3", "trainer": "T3", "weather": "晴", "track_condition": "良", "distance": 1600, "finish": 3, "odds": 8.5, "place_odds": 2.4, "gate": 3},
                    {"race_id": "H2", "horse": "Alpha", "jockey": "J1", "trainer": "T1", "weather": "晴", "track_condition": "良", "distance": 1800, "finish": 2, "odds": 3.1, "place_odds": 1.6, "gate": 1},
                    {"race_id": "H2", "horse": "Beta", "jockey": "J2", "trainer": "T2", "weather": "晴", "track_condition": "良", "distance": 1800, "finish": 1, "odds": 2.8, "place_odds": 1.5, "gate": 2},
                    {"race_id": "H2", "horse": "Gamma", "jockey": "J3", "trainer": "T3", "weather": "晴", "track_condition": "良", "distance": 1800, "finish": 3, "odds": 9.2, "place_odds": 2.6, "gate": 3},
                ]
            )
            entries = pd.DataFrame(
                [
                    {"race_id": "R202604040101", "race_date": "2026-04-04", "race_name": "テスト特別", "venue": "中京", "horse": "Alpha", "jockey": "J1", "trainer": "T1", "weather": "晴", "track_condition": "良", "distance": 1600, "odds": 2.9, "place_odds": 1.5, "gate": 1},
                    {"race_id": "R202604040101", "race_date": "2026-04-04", "race_name": "テスト特別", "venue": "中京", "horse": "Beta", "jockey": "J2", "trainer": "T2", "weather": "晴", "track_condition": "良", "distance": 1600, "odds": 3.8, "place_odds": 1.8, "gate": 2},
                    {"race_id": "R202604040101", "race_date": "2026-04-04", "race_name": "テスト特別", "venue": "中京", "horse": "Gamma", "jockey": "J3", "trainer": "T3", "weather": "晴", "track_condition": "良", "distance": 1600, "odds": 8.8, "place_odds": 2.7, "gate": 3},
                ]
            )
            history.to_csv(data_dir / aa.AUTO_HISTORY_FILENAME, index=False, encoding="utf-8-sig")
            entries.to_csv(data_dir / aa.AUTO_ENTRIES_FILENAME, index=False, encoding="utf-8-sig")
            (data_dir / aa.AUTO_WEIGHTS_FILENAME).write_text(json.dumps({"best_weights": {"horse_win": 1.7}}, ensure_ascii=False), encoding="utf-8")

            report = aa.generate_weekly_predictions(data_dir, simulations_per_race=300, seed=7)

            self.assertTrue(report["ok"])
            self.assertEqual(report["rows"], 1)
            weekly_df = pd.read_csv(data_dir / aa.WEEKLY_PREDICTIONS_FILENAME)
            self.assertEqual(len(weekly_df), 1)
            self.assertIn("top_horse", weekly_df.columns)
            archive_df = pd.read_csv(data_dir / aa.PREDICTION_ARCHIVE_FILENAME)
            self.assertEqual(len(archive_df), 1)
            feature_df = pd.read_csv(data_dir / aa.PREDICTION_FEATURE_ARCHIVE_FILENAME)
            self.assertGreaterEqual(len(feature_df), 3)

    def test_sync_feedback_memory_only_appends_new_rows_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            feedback = pd.DataFrame(
                [
                    {
                        "race_id": "R1",
                        "predicted_at": "2026-04-04T09:00:00",
                        "result_available": True,
                        "top_horse": "Alpha",
                        "actual_winner": "Beta",
                        "top_horse_hit": False,
                        "top_pop_rank": 1,
                        "track_condition": "重",
                        "condition_adjustment_count": 0,
                    }
                ]
            )
            feedback.to_csv(data_dir / aa.PREDICTION_FEEDBACK_FILENAME, index=False, encoding="utf-8-sig")

            first = aa.sync_feedback_memory(data_dir)
            second = aa.sync_feedback_memory(data_dir)

            self.assertEqual(first["rows_added"], 1)
            self.assertEqual(second["rows_added"], 0)
            memory_lines = (data_dir / aa.LOCAL_LLM_MEMORY_FILENAME).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(memory_lines), 1)

    def test_free_prediction_harness_reports_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            weekly = pd.DataFrame(
                [
                    {
                        "race_id": "R202604040101",
                        "race_date": "2026-04-04",
                        "race_name": "テスト特別",
                        "venue": "中京",
                        "top_horse": "Alpha",
                        "top_jockey": "J1",
                        "top_pop_rank": 1,
                        "top_horse_odds": 2.4,
                        "dark_horse": "Gamma",
                        "single_pick": "Alpha",
                        "place_pick": "Alpha",
                        "quinella_pick": "Alpha-Beta",
                        "wide_pick": "Alpha-Gamma",
                        "exacta_pick": "Alpha-Beta",
                        "trio_pick": "Alpha-Beta-Gamma",
                        "trifecta_pick": "Alpha-Beta-Gamma",
                    }
                ]
            )
            entries = pd.DataFrame(
                [
                    {"race_id": "R202604040101", "horse": "Alpha"},
                    {"race_id": "R202604040101", "horse": "Beta"},
                    {"race_id": "R202604040101", "horse": "Gamma"},
                ]
            )
            feedback = pd.DataFrame(
                [
                    {
                        "race_id": "R202604040101",
                        "race_date": "2026-04-04",
                        "result_available": False,
                        "top_horse": "Alpha",
                    }
                ]
            )
            weekly.to_csv(data_dir / aa.WEEKLY_PREDICTIONS_FILENAME, index=False, encoding="utf-8-sig")
            entries.to_csv(data_dir / aa.AUTO_ENTRIES_FILENAME, index=False, encoding="utf-8-sig")
            feedback.to_csv(data_dir / aa.PREDICTION_FEEDBACK_FILENAME, index=False, encoding="utf-8-sig")

            status = aa.run_free_prediction_harness(data_dir)

            self.assertTrue((data_dir / aa.FREE_HARNESS_STATUS_FILENAME).exists())
            self.assertEqual(status["planner"]["next_action"], "結果取得だけ")
            self.assertEqual(status["evaluator"]["pending_due_races"], 1)
            self.assertEqual(status["contract"]["failed_count"], 0)

    def test_free_prediction_harness_handles_no_due_feedback_without_race_id_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            weekly = pd.DataFrame(
                [
                    {
                        "race_id": "R209904040101",
                        "race_date": "2099-04-04",
                        "race_name": "未来特別",
                        "venue": "中京",
                        "top_horse": "Alpha",
                        "top_jockey": "J1",
                        "top_pop_rank": 1,
                        "top_horse_odds": 2.4,
                        "dark_horse": "Gamma",
                        "single_pick": "Alpha",
                        "place_pick": "Alpha",
                        "quinella_pick": "Alpha-Beta",
                        "wide_pick": "Alpha-Gamma",
                        "exacta_pick": "Alpha-Beta",
                        "trio_pick": "Alpha-Beta-Gamma",
                        "trifecta_pick": "Alpha-Beta-Gamma",
                    }
                ]
            )
            entries = pd.DataFrame(
                [
                    {"race_id": "R209904040101", "horse": "Alpha"},
                    {"race_id": "R209904040101", "horse": "Beta"},
                    {"race_id": "R209904040101", "horse": "Gamma"},
                ]
            )
            feedback = pd.DataFrame(
                [
                    {
                        "race_id": "R209904040101",
                        "race_date": "2099-04-04",
                        "result_available": False,
                        "top_horse": "Alpha",
                    }
                ]
            )
            weekly.to_csv(data_dir / aa.WEEKLY_PREDICTIONS_FILENAME, index=False, encoding="utf-8-sig")
            entries.to_csv(data_dir / aa.AUTO_ENTRIES_FILENAME, index=False, encoding="utf-8-sig")
            feedback.to_csv(data_dir / aa.PREDICTION_FEEDBACK_FILENAME, index=False, encoding="utf-8-sig")

            status = aa.run_free_prediction_harness(data_dir)

            self.assertEqual(status["evaluator"]["pending_due_races"], 0)
            self.assertIn("planner", status)

    def test_weekly_refresh_reason_requires_current_week_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            stale_day = "2026-04-04"
            stale = pd.DataFrame(
                [
                    {
                        "race_id": "202604040101",
                        "race_date": stale_day,
                        "horse": "Alpha",
                        "top_horse": "Alpha",
                    }
                ]
            )
            stale.to_csv(data_dir / aa.WEEKLY_PREDICTIONS_FILENAME, index=False, encoding="utf-8-sig")
            stale.to_csv(data_dir / aa.AUTO_ENTRIES_FILENAME, index=False, encoding="utf-8-sig")

            reason = aa._weekly_predictions_refresh_reason(data_dir, refresh_minutes=999999)

            self.assertIn("今週", reason)


if __name__ == "__main__":
    unittest.main()
