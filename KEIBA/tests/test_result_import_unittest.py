from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

import result_import as ri


class ManualResultImportTests(unittest.TestCase):
    def test_manual_result_rows_from_frame_supports_winner_second_third(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "race_id": "202605021211",
                    "race_date": "2026-05-31",
                    "venue": "東京",
                    "race_name": "日本ダービー",
                    "weather": "晴",
                    "track_condition": "良",
                    "distance": "2400",
                    "winner": "5番 ロブチェン",
                    "winner_jockey": "横山武史",
                    "second": "8番 ダノンシーマ",
                    "third": "3番 サンプルスター",
                }
            ]
        )

        rows = ri.manual_result_rows_from_frame(frame)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows.iloc[0]["race_id"], "202605021211")
        self.assertEqual(rows.iloc[0]["horse"], "ロブチェン")
        self.assertEqual(float(rows.iloc[0]["gate"]), 5.0)
        self.assertEqual(int(rows.iloc[0]["finish"]), 1)
        self.assertEqual(rows.iloc[0]["jockey"], "横山武史")
        self.assertEqual(rows.iloc[0]["race_name"], "日本ダービー")

    def test_import_manual_results_updates_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            pd.DataFrame(
                [
                    {
                        "race_id": "R1",
                        "race_date": "2026-05-31",
                        "race_name": "テストS",
                        "venue": "東京",
                        "top_horse": "A",
                        "single_pick": "A",
                        "place_pick": "A",
                        "quinella_pick": "A-B",
                        "wide_pick": "A-B",
                        "exacta_pick": "A-B",
                        "trio_pick": "A-B-C",
                        "trifecta_pick": "A-B-C",
                    }
                ]
            ).to_csv(data_dir / "prediction_archive.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "race_id": "R1",
                        "race_date": "2026-05-31",
                        "venue": "東京",
                        "winner": "1番 A",
                        "second": "2番 B",
                        "third": "3番 C",
                    }
                ]
            ).to_csv(data_dir / "manual_results.csv", index=False)

            report = ri.import_manual_results(data_dir)
            feedback = pd.read_csv(data_dir / "prediction_feedback.csv")

            self.assertTrue(report.ok)
            self.assertEqual(report.imported_races, 1)
            self.assertEqual(report.evaluated_after, 1)
            self.assertTrue(bool(feedback.iloc[0]["result_available"]))
            self.assertEqual(feedback.iloc[0]["actual_winner"], "A")
            self.assertTrue((data_dir / "result_import_status.json").exists())


if __name__ == "__main__":
    unittest.main()
