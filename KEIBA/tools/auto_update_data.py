from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from auto_data_ingest import fetch_auto_data


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="今週レース+過去レースを自動取得してKEIBA/dataに反映")
    parser.add_argument("--data-dir", default=str(ROOT_DIR / "data"), help="出力先ディレクトリ")
    parser.add_argument("--months-back", type=int, default=24, help="過去何ヶ月分を取得するか")
    parser.add_argument("--weekly-days-ahead", type=int, default=7, help="先何日分の出走表を取得するか")
    parser.add_argument("--incremental", dest="incremental", action="store_true", help="差分更新を有効にする（推奨）")
    parser.add_argument("--no-incremental", dest="incremental", action="store_false", help="差分更新を無効にする")
    parser.add_argument("--full-refresh", action="store_true", help="履歴をフル再取得する")
    parser.add_argument("--history-backfill-days", type=int, default=14, help="差分更新時に巻き戻す日数")
    parser.add_argument("--append-only", action="store_true", help="履歴を新規分だけ追記（既存race_idは再取得しない）")
    parser.add_argument("--entries-cache-hours", type=int, default=0, help="指定時間以内なら出走表更新をスキップ")
    parser.add_argument("--skip-history", action="store_true", help="履歴更新をスキップする")
    parser.add_argument("--skip-entries", action="store_true", help="出走表更新をスキップする")
    parser.add_argument("--no-weather-forecast", dest="auto_forecast_weather", action="store_false", help="天気予報の自動取得を無効化")
    parser.add_argument("--weather-cache-hours", type=int, default=6, help="天気予報キャッシュ時間（時間）")
    parser.add_argument("--fallback-max-days", type=int, default=120, help="代替取得時に遡る最大日数")
    parser.add_argument("--cap-history-races", type=int, default=3000, help="履歴取得レース上限")
    parser.add_argument("--cap-weekly-races", type=int, default=200, help="今週取得レース上限")
    parser.add_argument("--run-tuning", action="store_true", help="取得後に重み最適化も実行")
    parser.add_argument("--tuning-trials", type=int, default=40)
    parser.add_argument("--tuning-val-races", type=int, default=30)
    parser.add_argument("--tuning-simulations", type=int, default=1500)
    parser.add_argument(
        "--fast-weekly",
        action="store_true",
        help="今週出走表のみを最速更新（skip-history/incremental/append-only/no-tuning を自動適用）",
    )
    parser.set_defaults(incremental=True, auto_forecast_weather=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    incremental = bool(args.incremental)
    full_refresh = bool(args.full_refresh)
    history_backfill_days = int(args.history_backfill_days)
    append_only = bool(args.append_only)
    entries_cache_hours = max(0, int(args.entries_cache_hours))
    run_tuning = bool(args.run_tuning)
    update_history = (not bool(args.skip_history))
    update_entries = (not bool(args.skip_entries))

    if bool(args.fast_weekly):
        incremental = True
        full_refresh = False
        history_backfill_days = 0
        append_only = True
        run_tuning = False
        update_history = False
        entries_cache_hours = max(1, entries_cache_hours)

    try:
        report = fetch_auto_data(
            data_dir=Path(args.data_dir),
            months_back=int(args.months_back),
            weekly_days_ahead=int(args.weekly_days_ahead),
            incremental=incremental,
            full_refresh=full_refresh,
            history_backfill_days=history_backfill_days,
            append_only=append_only,
            entries_cache_hours=entries_cache_hours,
            update_history=update_history,
            update_entries=update_entries,
            auto_forecast_weather=bool(args.auto_forecast_weather),
            weather_cache_hours=max(0, int(args.weather_cache_hours)),
            fallback_max_days=int(args.fallback_max_days),
            cap_history_races=int(args.cap_history_races),
            cap_weekly_races=int(args.cap_weekly_races),
            run_tuning=run_tuning,
            tuning_trials=int(args.tuning_trials),
            tuning_val_races=int(args.tuning_val_races),
            tuning_simulations=int(args.tuning_simulations),
        )
    except RuntimeError as exc:
        print(f"error={exc}")
        raise SystemExit(1) from exc

    print(f"history_path={report.history_path}")
    print(f"entries_path={report.entries_path}")
    print(f"history_rows={report.history_rows}")
    print(f"entries_rows={report.entries_rows}")
    print(f"history_races={report.history_races}")
    print(f"weekly_races={report.weekly_races}")
    print(f"tuned={report.tuned}")
    if report.weights_path is not None:
        print(f"weights_path={report.weights_path}")
    if report.notes:
        for note in report.notes[-10:]:
            print(f"note={note}")


if __name__ == "__main__":
    main()
