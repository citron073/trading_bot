from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "normalize_csv.py"
    spec = importlib.util.spec_from_file_location("normalize_csv", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("normalize_csv.py をロードできません")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NormalizeKeibaCsvTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def test_normalize_history_with_japanese_columns(self) -> None:
        raw = pd.DataFrame(
            {
                "レースID": ["R001", "R001", "R001"],
                "馬名": ["A", "B", "C"],
                "騎手": ["J1", "J2", "J3"],
                "調教師": ["T1", "T2", "T3"],
                "天候": ["晴れ", "晴れ", "晴れ"],
                "馬場状態": ["良", "良", "良"],
                "距離": [1600, 1600, 1600],
                "着順": [1, 2, 3],
                "単勝オッズ": [2.3, 4.2, 8.5],
                "複勝オッズ": [1.2, 1.8, 2.5],
                "枠番": [1, 2, 3],
            }
        )
        out = self.mod._normalize_history(raw)

        self.assertEqual(list(out.columns[:8]), [
            "race_id",
            "horse",
            "jockey",
            "trainer",
            "weather",
            "track_condition",
            "distance",
            "finish",
        ])
        self.assertEqual(len(out), 3)
        self.assertEqual(out.loc[0, "weather"], "晴")
        self.assertEqual(out.loc[0, "track_condition"], "良")

    def test_normalize_entries_defaults(self) -> None:
        raw = pd.DataFrame(
            {
                "馬": ["A", "B"],
                "騎手名": ["J1", "J2"],
                "厩舎": ["T1", "T2"],
                "単勝": [3.1, 5.4],
            }
        )
        out = self.mod._normalize_entries(raw, default_weather="曇", default_track="稍重", default_distance=1800)

        self.assertEqual(len(out), 2)
        self.assertTrue({"horse", "jockey", "trainer", "weather", "track_condition", "distance"}.issubset(out.columns))
        self.assertEqual(out.loc[0, "weather"], "曇")
        self.assertEqual(out.loc[0, "track_condition"], "稍重")
        self.assertEqual(float(out.loc[0, "distance"]), 1800.0)

    def test_cli_history_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            src = base / "raw.csv"
            dst = base / "norm.csv"
            pd.DataFrame(
                {
                    "レースID": ["R10"],
                    "馬名": ["X"],
                    "騎手": ["J"],
                    "調教師": ["T"],
                    "天候": ["雨"],
                    "馬場状態": ["不"],
                    "距離": [1400],
                    "着順": [1],
                }
            ).to_csv(src, index=False)

            # Execute main path by temporarily patching argv.
            import sys

            argv = sys.argv[:]
            try:
                sys.argv = [
                    "normalize_csv.py",
                    "--mode",
                    "history",
                    "--in",
                    str(src),
                    "--out",
                    str(dst),
                ]
                self.mod.main()
            finally:
                sys.argv = argv

            self.assertTrue(dst.exists())
            got = pd.read_csv(dst)
            self.assertEqual(got.loc[0, "track_condition"], "不良")


if __name__ == "__main__":
    unittest.main()
