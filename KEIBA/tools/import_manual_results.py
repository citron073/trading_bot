from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from auto_agent import run_free_prediction_harness
from result_import import import_manual_results


def main() -> None:
    parser = argparse.ArgumentParser(description="手動CSVのレース結果をhistory_auto/prediction_feedbackに反映")
    parser.add_argument("--data-dir", default=str(ROOT_DIR / "data"))
    parser.add_argument("--in", dest="input_path", default="", help="未指定なら data/manual_results.csv")
    parser.add_argument("--refresh-harness", action="store_true", help="反映後に無料ハーネス診断も更新")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    input_path = Path(args.input_path) if args.input_path else None
    report = import_manual_results(data_dir, input_path=input_path)
    print(f"ok={report.ok}")
    print(f"message={report.message}")
    print(f"input_path={report.input_path}")
    print(f"imported_races={report.imported_races}")
    print(f"imported_rows={report.imported_rows}")
    print(f"evaluated={report.evaluated_before}->{report.evaluated_after}")
    print(f"pending={report.pending_before}->{report.pending_after}")
    for warning in report.warnings[-10:]:
        print(f"warning={warning}")
    if args.refresh_harness:
        harness = run_free_prediction_harness(data_dir)
        print(f"harness_message={harness.get('message', '')}")


if __name__ == "__main__":
    main()
