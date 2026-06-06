from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict
import urllib.request

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from auto_data_ingest import fetch_auto_data
from auto_agent import run_autonomous_agent_cycle, run_free_prediction_harness
from evaluation import aggregate_prediction_feedback, build_prediction_feedback

DATA_DIR = ROOT_DIR / "data"
MAIN_SECRETS_PATH = ROOT_DIR.parent / "MAIN" / ".streamlit" / "secrets.toml"
STATUS_PATH = DATA_DIR / "auto_cycle_status.json"
CONFIG_PATH = DATA_DIR / "auto_cycle_config.json"
LOCK_PATH = DATA_DIR / "auto_cycle.lock"
PREDICTION_ARCHIVE_PATH = DATA_DIR / "prediction_archive.csv"
PREDICTION_FEEDBACK_PATH = DATA_DIR / "prediction_feedback.csv"
RESULT_FETCH_STATE_PATH = DATA_DIR / "result_fetch_state.json"
NOTIFY_STATE_PATH = DATA_DIR / "notification_policy_state.json"

try:
    from tools.notification_policy import LEVEL_CRITICAL, LEVEL_INFO, LEVEL_WARN, post_ntfy
except ModuleNotFoundError:
    main_dir = ROOT_DIR.parent / "MAIN"
    if str(main_dir) not in sys.path:
        sys.path.insert(0, str(main_dir))
    from tools.notification_policy import LEVEL_CRITICAL, LEVEL_INFO, LEVEL_WARN, post_ntfy  # type: ignore


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KEIBAの結果取得・再学習を定時実行するローカルジョブ")
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--months-back", type=int, default=24)
    parser.add_argument("--weekly-days-ahead", type=int, default=7)
    parser.add_argument("--history-backfill-days", type=int, default=2)
    parser.add_argument("--entries-cache-hours", type=int, default=4)
    parser.add_argument("--weather-cache-hours", type=int, default=6)
    parser.add_argument("--fallback-max-days", type=int, default=120)
    parser.add_argument("--cap-history-races", type=int, default=3000)
    parser.add_argument("--cap-weekly-races", type=int, default=200)
    parser.add_argument("--result-batch-cap", type=int, default=24, help="結果待ちレースを1回で確認する最大件数")
    parser.add_argument("--skip-entries", dest="skip_entries", action="store_true", help="結果取得優先で今週出走表更新をスキップ")
    parser.add_argument("--refresh-entries", dest="skip_entries", action="store_false", help="今週出走表更新も行う")
    parser.add_argument("--no-weather-forecast", dest="auto_forecast_weather", action="store_false")
    parser.add_argument("--run-tuning", dest="run_tuning", action="store_true")
    parser.add_argument("--no-tuning", dest="run_tuning", action="store_false")
    parser.add_argument("--tuning-cooldown-minutes", type=int, default=180)
    parser.add_argument("--tuning-trials", type=int, default=10)
    parser.add_argument("--tuning-val-races", type=int, default=8)
    parser.add_argument("--tuning-simulations", type=int, default=800)
    parser.add_argument("--run-weekly-predictions", dest="run_weekly_predictions", action="store_true")
    parser.add_argument("--no-weekly-predictions", dest="run_weekly_predictions", action="store_false")
    parser.add_argument("--sync-llm-memory", dest="sync_llm_memory", action="store_true")
    parser.add_argument("--no-sync-llm-memory", dest="sync_llm_memory", action="store_false")
    parser.add_argument("--run-llm-review", dest="run_llm_review", action="store_true")
    parser.add_argument("--no-llm-review", dest="run_llm_review", action="store_false")
    parser.add_argument("--run-llm-race-picks", dest="run_llm_race_picks", action="store_true")
    parser.add_argument("--no-llm-race-picks", dest="run_llm_race_picks", action="store_false")
    parser.add_argument("--llm-base-url", default=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--llm-model", default=os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"))
    parser.add_argument("--llm-review-model", default=os.getenv("OLLAMA_REVIEW_MODEL", "qwen2.5:0.5b"))
    parser.add_argument("--llm-timeout-sec", type=int, default=20)
    parser.add_argument("--llm-review-timeout-sec", type=int, default=45)
    parser.add_argument("--max-llm-races", type=int, default=4)
    parser.add_argument("--weekly-simulations", type=int, default=1200)
    parser.add_argument("--weekly-refresh-minutes", type=int, default=180)
    parser.add_argument("--weekly-seed", type=int, default=42)
    parser.set_defaults(
        auto_forecast_weather=True,
        run_tuning=False,
        skip_entries=True,
        run_weekly_predictions=True,
        sync_llm_memory=True,
        run_llm_review=True,
        run_llm_race_picks=True,
    )
    return parser.parse_args()


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_status(**kwargs: Any) -> None:
    payload = _read_json(STATUS_PATH)
    payload.update(kwargs)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(STATUS_PATH, payload)


def _read_ntfy_url() -> str:
    """Return ntfy topic URL from auto_cycle_config.json, or "" if not set."""
    cfg = _read_json(CONFIG_PATH)
    url = str(cfg.get("ntfy_url", "") or "").strip()
    if url:
        return url
    # Fallback: read from MAIN secrets.toml if available
    if MAIN_SECRETS_PATH.exists():
        try:
            for line in MAIN_SECRETS_PATH.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("ntfy_topic_url"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        candidate = parts[1].strip().strip('"').strip("'")
                        if candidate and not candidate.startswith("#"):
                            return candidate
        except Exception:
            pass
    return ""


def _send_keiba_ntfy(title: str, body: str, *, priority: str = "default", tags: str = "") -> None:
    """Post a notification to ntfy. Silently skips if ntfy_url is not configured."""
    url = _read_ntfy_url()
    if not url:
        return
    level = LEVEL_INFO
    event_code = ""
    if priority == "high":
        level = LEVEL_CRITICAL
        event_code = "keiba_auto_cycle_error"
    elif "chart_with_" in str(tags or ""):
        level = LEVEL_WARN
    try:
        post_ntfy(
            url,
            title,
            body,
            level=level,
            tags=tags,
            timeout=5.0,
            state_path=NOTIFY_STATE_PATH if event_code else None,
            event_code=event_code,
        )
    except Exception:
        pass


def _write_runtime_config(args: argparse.Namespace) -> None:
    payload = _read_json(CONFIG_PATH)
    payload.update(
        {
            "mode": "local_auto_cycle",
            "months_back": int(args.months_back),
            "weekly_days_ahead": int(args.weekly_days_ahead),
            "history_backfill_days": int(args.history_backfill_days),
            "entries_cache_hours": int(args.entries_cache_hours),
            "weather_cache_hours": int(args.weather_cache_hours),
            "run_tuning": bool(args.run_tuning),
            "skip_entries": bool(args.skip_entries),
            "run_weekly_predictions": bool(args.run_weekly_predictions),
            "sync_llm_memory": bool(args.sync_llm_memory),
            "run_llm_review": bool(args.run_llm_review),
            "run_llm_race_picks": bool(args.run_llm_race_picks),
            "llm_model": str(args.llm_model),
            "llm_review_model": str(args.llm_review_model),
            "llm_timeout_sec": int(args.llm_timeout_sec),
            "llm_review_timeout_sec": int(args.llm_review_timeout_sec),
            "max_llm_races": int(args.max_llm_races),
            "weekly_simulations": int(args.weekly_simulations),
            "weekly_refresh_minutes": int(args.weekly_refresh_minutes),
            "result_batch_cap": int(args.result_batch_cap),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _write_json(CONFIG_PATH, payload)


@contextmanager
def _exclusive_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("already_running")
        fh.write(str(datetime.now().timestamp()))
        fh.flush()
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _build_summary(report: Any) -> str:
    return (
        f"history {int(report.history_rows):,}行 / "
        f"entries {int(report.entries_rows):,}行 / "
        f"履歴 {int(report.history_races):,}R / "
        f"今週 {int(report.weekly_races):,}R / "
        f"学習 {'ON' if bool(report.tuned) else 'OFF'}"
    )


def _parse_race_day(race_date: Any, race_id: Any) -> datetime.date | None:
    text = _to_text(race_date)
    candidates = [text] if text else []
    digits = "".join(ch for ch in _to_text(race_id) if ch.isdigit())
    if len(digits) >= 8:
        candidates.append(digits[:8])
    for candidate in candidates:
        normalized = candidate.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").strip()
        for value in (candidate, normalized):
            if not value:
                continue
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            except Exception:
                pass
            for fmt, width in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
                try:
                    return datetime.strptime(value[:width], fmt).date()
                except Exception:
                    continue
    return None


def _read_csv_if_exists(path: Path) -> Any:
    if not path.exists():
        try:
            import pandas as pd

            return pd.DataFrame()
        except Exception:
            return None
    try:
        import pandas as pd

        return pd.read_csv(path, dtype={"race_id": "string", "race_date": "string"}, low_memory=False)
    except Exception:
        try:
            import pandas as pd

            return pd.DataFrame()
        except Exception:
            return None


def _truthy_value(value: Any) -> bool:
    return _to_text(value).lower() in {"true", "1", "yes", "on"}


def _parse_timestamp_value(value: Any) -> datetime | None:
    text = _to_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _result_fetch_state_path(data_dir: Path) -> Path:
    return Path(data_dir) / RESULT_FETCH_STATE_PATH.name


def _load_result_fetch_state(data_dir: Path) -> Dict[str, Any]:
    payload = _read_json(_result_fetch_state_path(data_dir))
    attempts = payload.get("attempts", {})
    payload["attempts"] = attempts if isinstance(attempts, dict) else {}
    return payload


def _save_result_fetch_state(data_dir: Path, payload: Dict[str, Any]) -> None:
    out = dict(payload) if isinstance(payload, dict) else {"attempts": {}}
    attempts = out.get("attempts", {})
    out["attempts"] = attempts if isinstance(attempts, dict) else {}
    out["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(_result_fetch_state_path(data_dir), out)


def _recent_result_fetch_skip_ids(data_dir: Path, *, cooldown_hours: float = 6.0) -> set[str]:
    state = _load_result_fetch_state(data_dir)
    attempts = state.get("attempts", {})
    if not isinstance(attempts, dict):
        return set()
    out: set[str] = set()
    now_value = datetime.now()
    for race_id, payload in attempts.items():
        if not isinstance(payload, dict):
            continue
        last_attempt = _parse_timestamp_value(payload.get("last_attempted_at", ""))
        if last_attempt is None:
            continue
        now_for_attempt = datetime.now(last_attempt.tzinfo) if last_attempt.tzinfo else now_value
        age_hours = (now_for_attempt - last_attempt).total_seconds() / 3600.0
        if 0 <= age_hours < max(0.1, float(cooldown_hours)):
            race_id_text = _to_text(race_id)
            if race_id_text:
                out.add(race_id_text)
    return out


def _record_result_fetch_attempts(data_dir: Path, race_ids: list[str], *, status: str = "attempted") -> None:
    cleaned = list(dict.fromkeys([_to_text(race_id) for race_id in race_ids if _to_text(race_id)]))
    if not cleaned:
        return
    state = _load_result_fetch_state(data_dir)
    attempts = state.get("attempts", {})
    if not isinstance(attempts, dict):
        attempts = {}
    now_text = datetime.now().isoformat(timespec="seconds")
    for race_id in cleaned:
        existing = attempts.get(race_id, {})
        if not isinstance(existing, dict):
            existing = {}
        attempts[race_id] = {
            "last_attempted_at": now_text,
            "attempt_count": int(existing.get("attempt_count", 0) or 0) + 1,
            "last_status": _to_text(status) or "attempted",
        }
    state["attempts"] = attempts
    state["last_attempted_count"] = int(len(cleaned))
    state["last_attempt_status"] = _to_text(status) or "attempted"
    _save_result_fetch_state(data_dir, state)


def _pending_prediction_race_ids_for_result_update(
    *,
    data_dir: Path,
    cap: int = 3000,
) -> list[str]:
    try:
        import pandas as pd
    except Exception:
        return []
    feedback_path = Path(data_dir) / PREDICTION_FEEDBACK_PATH.name
    archive_path = Path(data_dir) / PREDICTION_ARCHIVE_PATH.name
    work = _read_csv_if_exists(feedback_path)
    if work is None or work.empty:
        work = _read_csv_if_exists(archive_path)
    if work is None or work.empty or "race_id" not in work.columns:
        return []
    work = work.copy()
    work["race_id"] = work["race_id"].map(_to_text)
    work = work[work["race_id"] != ""].copy()
    if "result_available" in work.columns:
        work = work[~work["result_available"].map(_truthy_value)].copy()
    if work.empty:
        return []
    today = datetime.now().date()
    work["_race_day"] = work.apply(lambda row: _parse_race_day(row.get("race_date", ""), row.get("race_id", "")), axis=1)
    work = work[work["_race_day"].map(lambda value: bool(value is not None and value <= today))].copy()
    if work.empty:
        return []
    work = work.sort_values(["_race_day", "race_id"], ascending=[True, True], na_position="last")
    race_ids = list(dict.fromkeys([race_id for race_id in work["race_id"].tolist() if race_id]))
    skip_ids = _recent_result_fetch_skip_ids(Path(data_dir), cooldown_hours=6.0)
    if skip_ids:
        unskipped = [race_id for race_id in race_ids if race_id not in skip_ids]
        race_ids = unskipped or race_ids
    if int(cap) > 0:
        race_ids = race_ids[: int(cap)]
    return race_ids


def _recent_prediction_race_ids_for_result_update(
    *,
    data_dir: Path,
    days_back: int = 2,
    days_ahead: int = 0,
) -> list[str]:
    archive_path = Path(data_dir) / PREDICTION_ARCHIVE_PATH.name
    if not archive_path.exists():
        return []
    try:
        import pandas as pd

        work = pd.read_csv(archive_path, dtype={"race_id": "string", "race_date": "string"}, low_memory=False)
    except Exception:
        return []
    if work.empty or "race_id" not in work.columns:
        return []

    today = datetime.now().date()
    lower = today - timedelta(days=max(0, int(days_back)))
    upper = today + timedelta(days=max(0, int(days_ahead)))
    race_ids: list[str] = []
    for _, row in work.iterrows():
        race_id = _to_text(row.get("race_id", ""))
        if not race_id:
            continue
        race_day = _parse_race_day(row.get("race_date", ""), race_id)
        if race_day is None:
            continue
        if lower <= race_day <= upper and race_id not in race_ids:
            race_ids.append(race_id)
    return race_ids


def _result_update_race_ids_for_cycle(*, data_dir: Path, cap: int = 3000) -> list[str]:
    pending = _pending_prediction_race_ids_for_result_update(data_dir=data_dir, cap=cap)
    if pending:
        return pending
    return _recent_prediction_race_ids_for_result_update(data_dir=data_dir, days_back=2, days_ahead=0)


def _current_week_entry_race_count(data_dir: Path) -> int:
    entries = _read_csv_if_exists(Path(data_dir) / "weekly_entries_auto.csv")
    if entries is None or entries.empty:
        return 0
    week_start = datetime.now().date()
    week_start = week_start - timedelta(days=week_start.weekday())
    week_end = week_start + timedelta(days=6)
    race_ids: list[str] = []
    try:
        for _, row in entries.iterrows():
            race_id = _to_text(row.get("race_id", row.get("レースID", "")))
            race_day = _parse_race_day(row.get("race_date", row.get("日付", "")), race_id)
            if race_id and race_day is not None and week_start <= race_day <= week_end:
                race_ids.append(race_id)
    except Exception:
        return 0
    return len(set(race_ids))


def _sync_prediction_feedback_after_fetch(data_dir: Path) -> Dict[str, Any]:
    try:
        import pandas as pd

        data_dir = Path(data_dir)
        archive_df = _read_csv_if_exists(data_dir / PREDICTION_ARCHIVE_PATH.name)
        history_df = _read_csv_if_exists(data_dir / "history_auto.csv")
        payouts_df = _read_csv_if_exists(data_dir / "payouts_auto.csv")
        if archive_df is None or archive_df.empty:
            return {"ok": False, "message": "採点スキップ: 保存予想なし"}
        feedback_df = build_prediction_feedback(
            archive_df,
            history_df if isinstance(history_df, pd.DataFrame) else pd.DataFrame(),
            payouts_df if isinstance(payouts_df, pd.DataFrame) else pd.DataFrame(),
        )
        feedback_path = data_dir / PREDICTION_FEEDBACK_PATH.name
        if not feedback_df.empty:
            feedback_df.to_csv(feedback_path, index=False, encoding="utf-8-sig")
        summary = aggregate_prediction_feedback(feedback_df)
        return {
            "ok": True,
            "message": (
                f"採点更新: 評価済み {int(summary.get('evaluated_races', 0) or 0):,}件 / "
                f"結果待ち {int(summary.get('pending_races', 0) or 0):,}件"
            ),
            "stored_predictions": int(summary.get("stored_predictions", 0) or 0),
            "evaluated_races": int(summary.get("evaluated_races", 0) or 0),
            "pending_races": int(summary.get("pending_races", 0) or 0),
        }
    except Exception as exc:
        return {"ok": False, "message": f"採点更新失敗: {exc}"}


def _progress_callback(progress_value: float, message: str) -> None:
    pct = max(0, min(100, int(round(float(progress_value) * 100))))
    _update_status(running=True, progress_pct=pct, last_phase=str(message).strip())


def _normalize_llm_base_url(base_url: Any) -> str:
    text = _to_text(base_url) or "http://127.0.0.1:11434"
    return text.rstrip("/")


def _probe_local_llm(base_url: str, *, timeout_sec: float = 1.5) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(f"{_normalize_llm_base_url(base_url)}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=max(0.5, float(timeout_sec))) as resp:
            if int(getattr(resp, "status", 200)) >= 400:
                return False, f"http_{getattr(resp, 'status', '-')}"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _llm_recently_slow(status_before: Dict[str, Any], *, cooldown_minutes: int = 120) -> bool:
    agent = status_before.get("agent", {}) if isinstance(status_before.get("agent"), dict) else {}
    messages = [
        _to_text(status_before.get("last_summary", "")),
        _to_text(agent.get("message", "")),
    ]
    for key in ("llm_review", "weekly_predictions"):
        payload = agent.get(key, {}) if isinstance(agent.get(key), dict) else {}
        messages.append(_to_text(payload.get("message", "")))
    joined = " / ".join(messages).lower()
    if not any(token in joined for token in ("timed out", "timeout", "llm生成失敗", "時間超過")):
        return False
    last_completed = _parse_timestamp_value(status_before.get("last_completed_at", ""))
    if last_completed is None:
        return True
    now_value = datetime.now(last_completed.tzinfo) if last_completed.tzinfo else datetime.now()
    return (now_value - last_completed) < timedelta(minutes=max(1, int(cooldown_minutes)))


def _should_run_tuning(args: argparse.Namespace, status_before: Dict[str, Any], report: Any) -> tuple[bool, str]:
    if not bool(args.run_tuning):
        return (False, "学習OFF設定")

    last_report = status_before.get("report", {}) if isinstance(status_before.get("report"), dict) else {}
    previous_history_rows = int(last_report.get("history_rows", 0) or 0)
    previous_history_races = int(last_report.get("history_races", 0) or 0)
    has_new_history = int(report.history_rows) > previous_history_rows or int(report.history_races) > previous_history_races
    if not has_new_history:
        return (False, "新しい履歴結果なし")

    tuned_at_text = str(status_before.get("last_tuned_at", "") or "").strip()
    if tuned_at_text:
        try:
            tuned_at = datetime.fromisoformat(tuned_at_text.replace("Z", "+00:00"))
            if datetime.now() - tuned_at < timedelta(minutes=max(1, int(args.tuning_cooldown_minutes))):
                return (False, "学習クールダウン中")
        except Exception:
            pass
    return (True, "新しい結果が増えたため反省再学習")


def _run_reflection_tuning(args: argparse.Namespace, data_dir: Path) -> Dict[str, Any]:
    history_path = data_dir / "history_auto.csv"
    weights_path = data_dir / "keiba_best_weights.json"
    feature_archive_path = data_dir / "prediction_feature_archive.csv"
    if not history_path.exists():
        raise RuntimeError(f"history_missing:{history_path}")
    if not feature_archive_path.exists():
        raise RuntimeError(f"feature_archive_missing:{feature_archive_path}")

    cmd = [
        sys.executable,
        str(ROOT_DIR / "tools" / "tune_feature_weights.py"),
        "--history",
        str(history_path),
        "--out",
        str(weights_path),
        "--trials",
        str(max(6, int(args.tuning_trials))),
        "--val-races",
        str(max(4, int(args.tuning_val_races))),
        "--simulations",
        str(max(400, int(args.tuning_simulations))),
        "--prediction-features",
        str(feature_archive_path),
        "--focus",
        "reflection",
    ]
    completed = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        timeout=900,
    )
    parsed: Dict[str, Any] = {"stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in {"feature_rows", "race_count", "reflection_rows"}:
            try:
                parsed[key] = int(float(value))
            except Exception:
                parsed[key] = value
        elif key in {"best_roi", "best_hit_rate"}:
            try:
                parsed[key] = float(value)
            except Exception:
                parsed[key] = value
        else:
            parsed[key] = value
    return parsed


def main() -> None:
    args = _parse_args()
    _write_runtime_config(args)
    data_dir = Path(args.data_dir)
    started_at = datetime.now().isoformat(timespec="seconds")
    status_before = _read_json(STATUS_PATH)
    targeted_race_ids = _result_update_race_ids_for_cycle(
        data_dir=data_dir,
        cap=max(1, min(int(args.cap_history_races), int(args.result_batch_cap))),
    )
    current_week_entry_races = _current_week_entry_race_count(data_dir)
    force_weekly_entries = bool(args.run_weekly_predictions and current_week_entry_races <= 0)
    _update_status(
        running=True,
        last_started_at=started_at,
        last_success=None,
        error="",
        progress_pct=0,
        last_phase="起動",
        targeted_races=int(len(targeted_race_ids)),
        current_week_entry_races=int(current_week_entry_races),
        weekly_entries_forced=bool(force_weekly_entries),
    )
    try:
        with _exclusive_lock(LOCK_PATH):
            fetch_update_history = True
            fetch_update_entries = not bool(args.skip_entries)
            fetch_entries_cache_hours = max(0, int(args.entries_cache_hours))
            fetch_history_backfill_days = int(args.history_backfill_days)
            fetch_cap_history_races = int(args.cap_history_races)
            fetch_history_allowlist = targeted_race_ids or None
            if not targeted_race_ids and bool(args.skip_entries) and not force_weekly_entries:
                # Scheduled runs should stay light when there are no pending
                # results. A broad history scan here can be heavy enough to be
                # killed by launchd/JETSAM before the status file is finalized.
                fetch_update_history = False
                fetch_history_backfill_days = 0
                fetch_cap_history_races = 1
                _update_status(
                    running=True,
                    progress_pct=8,
                    last_phase="結果待ち0件のため履歴取得をスキップ",
                )
            if force_weekly_entries:
                fetch_update_history = False
                fetch_update_entries = True
                fetch_entries_cache_hours = 0
                fetch_history_backfill_days = 0
                fetch_cap_history_races = 1
                fetch_history_allowlist = None
                _update_status(
                    running=True,
                    progress_pct=5,
                    last_phase="今週出走表が0Rのため、履歴取得を後回しにして出走表を優先更新",
                )
            if targeted_race_ids:
                _update_status(
                    running=True,
                    progress_pct=8,
                    last_phase=(
                        f"対象レースを結果待ち/直近予想 {len(targeted_race_ids)} 件に絞り込み "
                        f"(1回上限 {max(1, int(args.result_batch_cap))} 件)"
                    ),
                )
            if force_weekly_entries:
                _update_status(
                    running=True,
                    progress_pct=10,
                    last_phase="今週出走表を優先更新中",
                )
            report = fetch_auto_data(
                data_dir=data_dir,
                months_back=int(args.months_back),
                weekly_days_ahead=int(args.weekly_days_ahead),
                incremental=True,
                full_refresh=False,
                history_backfill_days=fetch_history_backfill_days,
                append_only=False,
                entries_cache_hours=fetch_entries_cache_hours,
                update_history=fetch_update_history,
                update_entries=fetch_update_entries,
                auto_forecast_weather=bool(args.auto_forecast_weather),
                weather_cache_hours=max(0, int(args.weather_cache_hours)),
                fallback_max_days=int(args.fallback_max_days),
                cap_history_races=fetch_cap_history_races,
                cap_weekly_races=int(args.cap_weekly_races),
                run_tuning=False,
                tuning_trials=int(args.tuning_trials),
                tuning_val_races=int(args.tuning_val_races),
                tuning_simulations=int(args.tuning_simulations),
                history_race_id_allowlist=fetch_history_allowlist,
                progress_callback=_progress_callback,
            )
    except RuntimeError as exc:
        if str(exc) == "already_running":
            _update_status(
                running=False,
                last_completed_at=datetime.now().isoformat(timespec="seconds"),
                last_success=True,
                last_summary="別ジョブが動作中のためスキップ",
                notes=["skip=already_running"],
                error="",
            )
            return
        _update_status(
            running=False,
            last_completed_at=datetime.now().isoformat(timespec="seconds"),
            last_success=False,
            last_summary="自動運用でエラー",
            error=str(exc),
        )
        _send_keiba_ntfy("🐎 KEIBA エラー", f"自動サイクル失敗: {exc}", priority="high", tags="warning")
        raise SystemExit(1) from exc
    except Exception as exc:
        _update_status(
            running=False,
            last_completed_at=datetime.now().isoformat(timespec="seconds"),
            last_success=False,
            last_summary="自動運用でエラー",
            error=str(exc),
        )
        _send_keiba_ntfy("🐎 KEIBA エラー", f"自動サイクル失敗: {exc}", priority="high", tags="warning")
        raise SystemExit(1) from exc

    _update_status(running=True, progress_pct=94, last_phase="予想と結果を自動採点")
    feedback_payload = _sync_prediction_feedback_after_fetch(Path(args.data_dir))
    feedback_summary_text = str(feedback_payload.get("message", "") or "").strip()
    remaining_targeted_ids: list[str] = []
    if targeted_race_ids:
        feedback_after = _read_csv_if_exists(Path(args.data_dir) / PREDICTION_FEEDBACK_PATH.name)
        if feedback_after is not None and not feedback_after.empty and {"race_id", "result_available"}.issubset(set(feedback_after.columns)):
            feedback_after = feedback_after.copy()
            feedback_after["race_id"] = feedback_after["race_id"].map(_to_text)
            remaining_targeted_ids = (
                feedback_after[
                    feedback_after["race_id"].isin(targeted_race_ids)
                    & (~feedback_after["result_available"].map(_truthy_value))
                ]["race_id"]
                .map(_to_text)
                .tolist()
            )
        _record_result_fetch_attempts(
            Path(args.data_dir),
            remaining_targeted_ids or targeted_race_ids,
            status="pending_after_attempt" if remaining_targeted_ids else "attempted",
        )

    should_tune, tune_reason = _should_run_tuning(args, status_before, report)
    tuning_payload: Dict[str, Any] = {}
    if should_tune:
        try:
            _update_status(running=True, progress_pct=96, last_phase="反省再学習")
            tuning_payload = _run_reflection_tuning(args, Path(args.data_dir))
            tuning_summary = (
                f"反省再学習 ON / 対象 {int(tuning_payload.get('race_count', 0)):,}R / "
                f"反省 {int(tuning_payload.get('reflection_rows', 0)):,}行"
            )
        except Exception as exc:
            tuning_summary = f"反省再学習失敗: {exc}"
    else:
        tuning_summary = f"反省再学習スキップ: {tune_reason}"

    summary = _build_summary(report)
    agent_payload: Dict[str, Any] = {}
    llm_available, llm_probe_message = _probe_local_llm(
        str(args.llm_base_url),
        timeout_sec=min(2.0, max(0.5, float(args.llm_timeout_sec))),
    )
    llm_slow_cooldown = _llm_recently_slow(status_before)
    effective_run_llm_review = bool(args.run_llm_review and llm_available and not llm_slow_cooldown)
    effective_run_llm_race_picks = bool(args.run_llm_race_picks and llm_available and not llm_slow_cooldown)
    # Review prompts include recent results and weekly picks; 6 seconds caused
    # repeated local LLM timeouts on small Ollama models. Keep a bounded window
    # so the cycle still finishes predictably.
    effective_llm_timeout = min(max(8, int(args.llm_timeout_sec)), 30)
    effective_llm_review_timeout = min(max(12, int(args.llm_review_timeout_sec)), 60)
    llm_policy_text = (
        "LLM軽量: 前回タイムアウトのため今回スキップ"
        if llm_slow_cooldown
        else ("LLM軽量: 未接続のためスキップ" if not llm_available else "LLM軽量: 接続OK")
    )
    try:
        _update_status(running=True, progress_pct=98, last_phase="自律エージェント")
        agent_payload = run_autonomous_agent_cycle(
            Path(args.data_dir),
            cycle_summary=f"{summary} / {feedback_summary_text or '採点更新なし'} / {tuning_summary}",
            generate_predictions=bool(args.run_weekly_predictions),
            sync_memory=bool(args.sync_llm_memory),
            run_llm_review=effective_run_llm_review,
            run_llm_race_picks=effective_run_llm_race_picks,
            llm_base_url=str(args.llm_base_url),
            llm_model=str(args.llm_model),
            llm_review_model=str(args.llm_review_model),
            llm_timeout_sec=int(effective_llm_timeout),
            llm_review_timeout_sec=int(effective_llm_review_timeout),
            weekly_simulations=int(args.weekly_simulations),
            weekly_seed=int(args.weekly_seed),
            weekly_refresh_minutes=int(args.weekly_refresh_minutes),
            max_llm_races=max(0, int(args.max_llm_races)),
        )
        agent_payload["llm_policy"] = {
            "available": bool(llm_available),
            "probe": str(llm_probe_message),
            "slow_cooldown": bool(llm_slow_cooldown),
            "run_review": bool(effective_run_llm_review),
            "run_race_picks": bool(effective_run_llm_race_picks),
            "model": str(args.llm_model),
            "review_model": str(args.llm_review_model),
            "timeout_sec": int(effective_llm_timeout),
            "review_timeout_sec": int(effective_llm_review_timeout),
            "max_llm_races": int(max(0, int(args.max_llm_races))),
        }
        agent_summary = str(agent_payload.get("message", "") or "").strip()
    except Exception as exc:
        agent_payload = {"ok": False, "message": f"自律エージェント失敗: {exc}", "llm_policy": {"probe": llm_probe_message}}
        agent_summary = str(agent_payload["message"])
    harness_payload: Dict[str, Any] = {}
    try:
        _update_status(running=True, progress_pct=99, last_phase="無料ハーネス診断")
        harness_payload = run_free_prediction_harness(Path(args.data_dir))
    except Exception as exc:
        harness_payload = {"ok": False, "message": f"無料ハーネス診断失敗: {exc}"}
    full_summary = f"{summary} / {feedback_summary_text or '採点更新なし'} / {tuning_summary}"
    if agent_summary:
        full_summary = f"{full_summary} / {agent_summary}"
    if llm_policy_text:
        full_summary = f"{full_summary} / {llm_policy_text}"
    if str(harness_payload.get("message", "") or "").strip():
        full_summary = f"{full_summary} / {str(harness_payload.get('message', '')).strip()}"
    _update_status(
        running=False,
        last_completed_at=datetime.now().isoformat(timespec="seconds"),
        last_success=True,
        last_summary=full_summary,
        error="",
        progress_pct=100,
        last_phase="完了",
        report={
            "history_rows": int(report.history_rows),
            "entries_rows": int(report.entries_rows),
            "history_races": int(report.history_races),
            "weekly_races": int(report.weekly_races),
            "tuned": bool(report.tuned),
            "weights_path": str(report.weights_path) if report.weights_path else "",
        },
        notes=list(report.notes[-12:]) if getattr(report, "notes", None) else [],
        last_tuning_summary=tuning_summary,
        last_tuned_at=datetime.now().isoformat(timespec="seconds") if should_tune and "失敗" not in tuning_summary else status_before.get("last_tuned_at", ""),
        tuning=tuning_payload,
        feedback_sync=feedback_payload,
        agent=agent_payload,
        prediction_harness=harness_payload,
    )
    print(full_summary)

    # ntfy 通知 — 週次予想が新規生成された場合のみ送信（スキップ時は送らない）
    wp = agent_payload.get("weekly_predictions", {}) if isinstance(agent_payload.get("weekly_predictions"), dict) else {}
    pred_refreshed = not bool(wp.get("skipped")) and bool(wp.get("ok"))
    if pred_refreshed:
        weekly_races = int(report.weekly_races) if hasattr(report, "weekly_races") else 0
        feedback_path = Path(args.data_dir) / PREDICTION_FEEDBACK_PATH.name
        hit_line = ""
        if feedback_path.exists():
            try:
                import csv as _csv
                with feedback_path.open(encoding="utf-8") as _fh:
                    _rows = list(_csv.DictReader(_fh))
                _done = [r for r in _rows if str(r.get("result_available", "")).lower() == "true"]
                _hits = [r for r in _done if str(r.get("top_horse_hit", "")).lower() == "true"]
                if _done:
                    hit_line = f"\n1着的中率: {len(_hits)}/{len(_done)} ({len(_hits)/len(_done)*100:.1f}%)"
            except Exception:
                pass
        ntfy_body = f"今週予想生成完了: {weekly_races}R{hit_line}\n{wp.get('message', '').strip() or ''}"
        _send_keiba_ntfy("🐎 KEIBA 予想完了", ntfy_body.strip(), tags="horse")

    # WR変化通知 — 直近20件 vs 前20件 で ±5%pt 以上変化したら通知
    _notify_wr_delta_if_needed(Path(args.data_dir), status_before)


def _compute_wr(rows: list, *, key_hit: str = "top_horse_hit") -> tuple[int, int] | None:
    """Return (hits, total) from completed-result rows. None if too few rows."""
    done = [r for r in rows if str(r.get("result_available", "")).lower() == "true"]
    if len(done) < 5:
        return None
    hits = sum(1 for r in done if str(r.get(key_hit, "")).lower() == "true")
    return hits, len(done)


def _notify_wr_delta_if_needed(data_dir: Path, status_before: Dict[str, Any]) -> None:
    """Compare latest 20 vs previous 20 completed predictions; notify if WR shifts ≥5pt."""
    feedback_path = data_dir / PREDICTION_FEEDBACK_PATH.name
    if not feedback_path.exists():
        return
    try:
        import csv as _csv
        with feedback_path.open(encoding="utf-8") as _fh:
            all_rows = list(_csv.DictReader(_fh))
        done = [r for r in all_rows if str(r.get("result_available", "")).lower() == "true"]
        window = 20
        if len(done) < window * 2:
            return
        recent = done[-window:]
        prev = done[-window * 2:-window]
        r_hits = sum(1 for r in recent if str(r.get("top_horse_hit", "")).lower() == "true")
        p_hits = sum(1 for r in prev if str(r.get("top_horse_hit", "")).lower() == "true")
        r_wr = r_hits / window * 100
        p_wr = p_hits / window * 100
        delta = r_wr - p_wr
        threshold = 5.0
        if abs(delta) < threshold:
            return
        # Check we haven't already notified for this same delta in the previous cycle
        last_notified_wr = float(status_before.get("_last_notified_recent_wr", -999) or -999)
        if abs(r_wr - last_notified_wr) < 1.0:
            return
        _update_status(_last_notified_recent_wr=round(r_wr, 1))
        arrow = "📈" if delta > 0 else "📉"
        title = f"🐎 KEIBA 的中率変化 {arrow}"
        body = (
            f"直近{window}件: {r_hits}/{window} ({r_wr:.1f}%)\n"
            f"前{window}件:  {p_hits}/{window} ({p_wr:.1f}%)\n"
            f"変化: {delta:+.1f}pt"
        )
        priority = "high" if abs(delta) >= 10 else "default"
        _send_keiba_ntfy(title, body, priority=priority, tags="chart_with_upwards_trend" if delta > 0 else "chart_with_downwards_trend")
    except Exception:
        pass


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            exit_code = code
        elif code is None:
            exit_code = 0
        else:
            exit_code = 1
    except Exception:
        exit_code = 1
        raise
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            # keibascraper / requests 周りの内部スレッドが居残ることがあるため、
            # ワンショットの自動サイクルは最後に明示終了する。
            os._exit(int(exit_code))
