from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import predictor as kp


class TuneKeibaFeatureWeightsTest(unittest.TestCase):
    def test_tune_script_generates_weight_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            history_path = base / "history.csv"
            out_path = base / "best_weights.json"

            history = kp.generate_sample_history(seed=30, n_races=40)
            history.to_csv(history_path, index=False)

            import subprocess

            subprocess.run(
                [
                    "python3",
                    "tools/tune_feature_weights.py",
                    "--history",
                    str(history_path),
                    "--out",
                    str(out_path),
                    "--trials",
                    "3",
                    "--val-races",
                    "8",
                    "--simulations",
                    "300",
                    "--seed",
                    "31",
                ],
                cwd=str(Path(__file__).resolve().parents[1]),
                check=True,
            )

            self.assertTrue(out_path.exists())
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertIn("best_weights", payload)
            self.assertIn("best_eval", payload)
            self.assertIn("form_score", payload["best_weights"])


if __name__ == "__main__":
    unittest.main()
