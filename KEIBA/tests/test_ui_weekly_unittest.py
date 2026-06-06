from __future__ import annotations

import unittest

import pandas as pd

from ui_weekly import (
    build_reader_ticket_frame,
    detail_selector_options,
    graded_focus_columns,
    normalize_weekly_alignment,
    program_order_columns,
    resolve_detail_selector_race_id,
    weekly_detail_columns,
    weekly_main_columns,
    weekly_overview_columns,
)


class UiPredictionTests(unittest.TestCase):
    def test_normalize_weekly_alignment_keeps_valid_value(self) -> None:
        options = ("すべて", "別軸を上に集める", "別軸だけ")

        self.assertEqual(normalize_weekly_alignment("別軸だけ", options), "別軸だけ")

    def test_normalize_weekly_alignment_falls_back_to_first_option(self) -> None:
        options = ("すべて", "別軸を上に集める", "別軸だけ")

        self.assertEqual(normalize_weekly_alignment("不明", options), "すべて")
        self.assertEqual(normalize_weekly_alignment(None, options), "すべて")

    def test_weekly_columns_keep_only_existing_columns_in_display_order(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "三連単候補": "A-B-C",
                    "レース": "中京 1R",
                    "本命馬": "A",
                    "LLM別軸理由": "穴候補",
                    "レースID": "R1",
                }
            ]
        )

        self.assertEqual(weekly_main_columns(frame), ["レース", "本命馬", "三連単候補"])
        self.assertEqual(weekly_detail_columns(frame), ["レース", "本命馬", "LLM別軸理由", "三連単候補", "レースID"])

    def test_weekly_overview_columns_keep_only_existing_columns_in_display_order(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "レースID": "R1",
                    "注目馬": "A / B",
                    "レース": "中京 1R",
                    "開催": "中京",
                    "馬場": "良",
                }
            ]
        )

        self.assertEqual(weekly_overview_columns(frame), ["レース", "開催", "注目馬", "馬場", "レースID"])

    def test_program_order_columns_keep_only_existing_columns_in_display_order(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "レースID": "R1",
                    "三連単候補": "A-B-C",
                    "レース順": "1R",
                    "本命馬": "A",
                    "人気急変": "あり",
                }
            ]
        )

        self.assertEqual(program_order_columns(frame), ["レース順", "本命馬", "三連単候補", "人気急変", "レースID"])

    def test_graded_focus_columns_keep_only_existing_columns_in_display_order(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "レースID": "R1",
                    "三連単候補": "A-B-C",
                    "レース": "G1 Race",
                    "注目馬": "A / B",
                    "本命人気": "1番人気",
                }
            ]
        )

        self.assertEqual(graded_focus_columns(frame), ["レース", "本命人気", "三連単候補", "注目馬", "レースID"])

    def test_build_reader_ticket_frame_uses_top_horse_fallbacks(self) -> None:
        row = pd.Series(
            {
                "本命馬": "A",
                "馬連候補": "A-B",
                "三連単候補": "A-B-C",
            }
        )

        out = build_reader_ticket_frame(row, to_text=lambda value: "" if value is None else str(value).strip())

        self.assertEqual(out["券種"].tolist(), ["単勝", "複勝", "馬連", "ワイド", "三連複", "三連単"])
        self.assertEqual(out.loc[out["券種"] == "単勝", "候補"].iloc[0], "A")
        self.assertEqual(out.loc[out["券種"] == "複勝", "候補"].iloc[0], "A")
        self.assertEqual(out.loc[out["券種"] == "馬連", "候補"].iloc[0], "A-B")
        self.assertEqual(out.loc[out["券種"] == "三連単", "候補"].iloc[0], "A-B-C")

    def test_detail_selector_options_and_current_resolution(self) -> None:
        frame = pd.DataFrame(
            [
                {"race_id": " R2 ", "label": "中京 2R"},
                {"race_id": "R1", "label": ""},
            ]
        )
        to_text = lambda value: "" if value is None else str(value).strip()

        ids, labels = detail_selector_options(frame, to_text=to_text)

        self.assertEqual(ids, ["R2", "R1"])
        self.assertEqual(labels, {"R2": "中京 2R", "R1": "R1"})
        self.assertEqual(resolve_detail_selector_race_id(ids, "R1", to_text=to_text), "R1")
        self.assertEqual(resolve_detail_selector_race_id(ids, "missing", to_text=to_text), "R2")


if __name__ == "__main__":
    unittest.main()
