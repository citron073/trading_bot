from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from prediction_pipeline import (
    collect_auto_update_status_lines,
    feedback_new_result_count,
    feedback_summary_delta_snapshot,
    feedback_summary_delta_text,
    humanize_auto_update_note,
    merge_selected_weekly_prediction,
    normalize_race_ids,
    prepare_weekly_display_columns,
    prepare_weekly_predictions_preview,
    remaining_targeted_result_ids,
    result_fetch_attempt_status,
    result_refresh_chip,
    result_refresh_notice_text,
    result_refresh_outcome_summary,
    result_refresh_summary_detail,
    resolve_update_profile,
    save_weekly_predictions,
    weekly_notice_message,
    weekly_notice_row,
)


class PredictionPipelineTests(unittest.TestCase):
    def test_resolve_fast_update_profile_keeps_history_append_only(self) -> None:
        params = resolve_update_profile(
            "高速（最新追記）",
            force_tuning=False,
            months_back=24,
            weekly_days_ahead=7,
            fallback_max_days=120,
            history_backfill_days=14,
            entries_cache_hours=1,
            auto_tune=True,
        )

        self.assertTrue(params["incremental"])
        self.assertFalse(params["full_refresh"])
        self.assertTrue(params["append_only"])
        self.assertEqual(params["history_backfill_days"], 0)
        self.assertEqual(params["entries_cache_hours"], 2)
        self.assertFalse(params["run_tuning"])

    def test_resolve_standard_profile_respects_auto_tune(self) -> None:
        params = resolve_update_profile(
            "標準（差分更新）",
            force_tuning=False,
            months_back=12,
            weekly_days_ahead=5,
            fallback_max_days=90,
            history_backfill_days=10,
            entries_cache_hours=3,
            auto_tune=True,
        )

        self.assertTrue(params["incremental"])
        self.assertFalse(params["full_refresh"])
        self.assertFalse(params["append_only"])
        self.assertEqual(params["history_backfill_days"], 10)
        self.assertEqual(params["entries_cache_hours"], 3)
        self.assertTrue(params["run_tuning"])

    def test_resolve_profile_force_tuning_overrides_fast_mode(self) -> None:
        params = resolve_update_profile(
            "高速（最新追記）",
            force_tuning=True,
            months_back=24,
            weekly_days_ahead=7,
            fallback_max_days=120,
            history_backfill_days=14,
            entries_cache_hours=4,
            auto_tune=False,
        )

        self.assertTrue(params["run_tuning"])

    def test_humanize_auto_update_note_for_timeout(self) -> None:
        self.assertEqual(
            humanize_auto_update_note("history_skip:R202604190101:retry_exhausted_timeout"),
            "最終失敗: 履歴取得 R202604190101 はタイムアウト後の再試行でも取得できませんでした",
        )

    def test_collect_auto_update_status_lines_deduplicates_and_hides_internal_mode(self) -> None:
        lines = collect_auto_update_status_lines(
            [
                "history_mode=weekly",
                "weekly_entries_reused_existing",
                "weekly_entries_reused_existing",
                "weekly_race_ids_fallback_count=12",
            ]
        )

        self.assertEqual(
            lines,
            [
                "軽量実行: 今週出走表は既存キャッシュをそのまま使いました",
                "再試行中: 代替経路で今週レースIDを補完しました (12件)",
            ],
        )

    def test_feedback_new_result_count_never_negative(self) -> None:
        self.assertEqual(feedback_new_result_count({"evaluated_races": 5}, {"evaluated_races": 8}), 3)
        self.assertEqual(feedback_new_result_count({"evaluated_races": 8}, {"evaluated_races": 5}), 0)
        self.assertEqual(feedback_new_result_count(None, {"evaluated_races": "2"}), 2)

    def test_feedback_summary_delta_text_and_snapshot(self) -> None:
        before = {
            "evaluated_races": 5,
            "pending_races": 10,
            "top_horse_hit_rate": 0.2,
            "single_roi": 0.5,
        }
        after = {
            "evaluated_races": 8,
            "pending_races": 7,
            "top_horse_hit_rate": 0.25,
            "single_roi": 0.75,
        }

        text = feedback_summary_delta_text(before, after)
        snapshot = feedback_summary_delta_snapshot(before, after)

        self.assertIn("評価済み 5->8 (+3)", text)
        self.assertIn("結果待ち 10->7 (-3)", text)
        self.assertIn("本命勝率 20.0%->25.0% (+5.0%)", text)
        self.assertEqual(snapshot["evaluated_races"]["diff"], 3)
        self.assertEqual(snapshot["pending_races"]["diff"], -3)

    def test_remaining_targeted_result_ids_filters_only_pending_targets(self) -> None:
        feedback = pd.DataFrame(
            [
                {"race_id": "R1", "result_available": True},
                {"race_id": "R2", "result_available": False},
                {"race_id": "R3", "result_available": "済"},
                {"race_id": "R4", "result_available": ""},
            ]
        )

        self.assertEqual(remaining_targeted_result_ids(feedback, ["R1", "R2", "R3", "R4", ""]), ["R2", "R4"])

    def test_normalize_race_ids_and_result_fetch_attempt_status(self) -> None:
        self.assertEqual(normalize_race_ids([" R1 ", "", None, "R2"]), ["R1", "R2"])
        self.assertEqual(normalize_race_ids("R1"), [])
        self.assertEqual(result_fetch_attempt_status(0), "pending_after_attempt")
        self.assertEqual(result_fetch_attempt_status(2), "partial_after_attempt")

    def test_result_refresh_text_helpers(self) -> None:
        self.assertEqual(
            result_refresh_notice_text(history_rows=100, history_races=12, learned=False),
            "結果取得完了: history 100行 / 履歴レース 12 / 学習なし",
        )
        self.assertEqual(
            result_refresh_notice_text(history_rows=100, history_races=12, learned=True),
            "結果更新完了: history 100行 / 履歴レース 12 / 再学習済み",
        )
        self.assertEqual(
            result_refresh_outcome_summary(history_rows=100, history_races=12, learned=True),
            "履歴 100行 / 履歴レース 12 / 再学習済み",
        )
        self.assertEqual(result_refresh_chip(0), "新規結果なし")
        self.assertEqual(result_refresh_chip(3), "新規結果 3件")
        self.assertIn(
            "今週出走表は既存キャッシュを維持",
            result_refresh_summary_detail(new_result_count=3, history_rows=100, history_races=12),
        )

    def test_prepare_weekly_predictions_preview_filters_week_and_adds_defaults(self) -> None:
        frame = pd.DataFrame(
            [
                {"race_id": "R202604200101", "race_date": "2026-04-20", "top_horse": "Horse_01"},
                {"race_id": "R202604270101", "race_date": "2026-04-27", "top_horse": "Horse_02"},
            ]
        )

        out = prepare_weekly_predictions_preview(frame, today=date(2026, 4, 22))

        self.assertEqual(out["race_id"].tolist(), ["R202604200101"])
        self.assertIn("trifecta_pick", out.columns)
        self.assertEqual(out.iloc[0]["trifecta_pick"], "-")

    def test_prepare_weekly_display_columns_renames_and_coerces_text(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "race_id": "R202604200101",
                    "race_label": "中京 1R",
                    "top_horse": None,
                    "top_jockey": "Jockey A",
                    "win_prob": 0.123,
                    "llm_pick_reason": float("nan"),
                }
            ]
        )

        out = prepare_weekly_display_columns(frame)

        self.assertIn("レースID", out.columns)
        self.assertIn("レース", out.columns)
        self.assertIn("本命馬", out.columns)
        self.assertIn("勝率", out.columns)
        self.assertEqual(out.iloc[0]["本命馬"], "")
        self.assertEqual(out.iloc[0]["本命騎手"], "Jockey A")
        self.assertEqual(out.iloc[0]["LLM根拠"], "")
        self.assertEqual(out.iloc[0]["勝率"], 0.123)

    def test_merge_selected_weekly_prediction_replaces_target_and_sorts(self) -> None:
        current = pd.DataFrame(
            [
                {"race_id": "R202604200103", "top_horse": "Old"},
                {"race_id": "R202604200101", "top_horse": "Keep"},
            ]
        )
        refreshed = pd.DataFrame([{"race_id": "R202604200103", "top_horse": "New"}])

        out = merge_selected_weekly_prediction(current, refreshed, "R202604200103")

        self.assertEqual(out["race_id"].tolist(), ["R202604200101", "R202604200103"])
        self.assertEqual(out.loc[out["race_id"] == "R202604200103", "top_horse"].iloc[0], "New")
        self.assertIn("trifecta_pick", out.columns)

    def test_save_weekly_predictions_writes_normalized_csv(self) -> None:
        frame = pd.DataFrame([{"race_id": "R202604200101", "top_horse": "Horse_01"}])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "weekly.csv"
            out = save_weekly_predictions(frame, path)
            loaded = pd.read_csv(path)

        self.assertEqual(out["race_id"].tolist(), ["R202604200101"])
        self.assertIn("trifecta_pick", loaded.columns)
        self.assertEqual(loaded.iloc[0]["trifecta_pick"], "-")

    def test_weekly_notice_row_prefers_selected_race_then_program_order(self) -> None:
        frame = pd.DataFrame(
            [
                {"race_id": "R202604200112", "race_date": "2026-04-20", "venue": "中京", "top_horse": "A"},
                {"race_id": "R202604200101", "race_date": "2026-04-20", "venue": "中京", "top_horse": "B"},
            ]
        )

        self.assertEqual(weekly_notice_row(frame, "R202604200112")["top_horse"], "A")
        self.assertEqual(weekly_notice_row(frame)["top_horse"], "B")

    def test_weekly_notice_message_renders_synthetic_names(self) -> None:
        row = {
            "race_id": "AUTO20260420",
            "race_date": "2026-04-20",
            "venue": "中京",
            "top_horse": "Horse_01",
            "dark_horse": "Horse_12",
            "trifecta_pick": "Horse_01-Horse_02-Horse_12",
        }

        message = weekly_notice_message("今週AI予想を更新", row)

        self.assertIn("2026/04/20 中京 [AUTO20260420]", message)
        self.assertIn("本命 馬01（仮）", message)
        self.assertIn("三連単 馬01（仮）-馬02（仮）-馬12（仮）", message)


if __name__ == "__main__":
    unittest.main()
