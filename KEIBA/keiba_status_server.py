#!/usr/bin/env python3
"""
keiba_status_server.py — KEIBA ステータス HTTP サーバー (port 8789)
unified_dashboard.html から CORS 越しに参照される。
"""
import csv
import json
import os
import pathlib
import subprocess
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

PORT = 8789
HOST = os.getenv("KEIBA_STATUS_HOST", "127.0.0.1").strip() or "127.0.0.1"
BASE_DIR = pathlib.Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"
SPEC_PATH = BASE_DIR / "docs" / "KEIBA_SPEC_TABLE.md"
ACTION_STATUS_PATH = DATA_DIR / "dashboard_action_status.json"
ACTION_LOCK = threading.Lock()
ACTION_TOKEN = os.getenv("KEIBA_DASHBOARD_ACTION_TOKEN", "").strip()
ACTION_DISABLED = os.getenv("KEIBA_ACTIONS_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}
ACTION_STALE_SEC = 20 * 60

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _read_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: pathlib.Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _compute_hit_rate(feedback_path: pathlib.Path) -> dict:
    try:
        rows = list(csv.DictReader(feedback_path.open(encoding="utf-8-sig")))
    except Exception:
        return {"total": 0, "done": 0, "hits": 0, "hit_rate_pct": None}

    done = [r for r in rows if r.get("result_available") == "True"]
    hits = [r for r in done if r.get("top_horse_hit") == "True"]
    rate = round(len(hits) / len(done) * 100, 1) if done else None

    # 直近20件 WR
    recent = done[-20:] if len(done) >= 20 else done
    recent_hits = sum(1 for r in recent if r.get("top_horse_hit") == "True")
    recent_wr = round(recent_hits / len(recent) * 100, 1) if recent else None

    return {
        "total": len(rows),
        "done": len(done),
        "hits": len(hits),
        "hit_rate_pct": rate,
        "recent_20_wr_pct": recent_wr,
    }


def _read_csv_rows(path: pathlib.Path) -> list[dict]:
    try:
        return list(csv.DictReader(path.open(encoding="utf-8-sig")))
    except Exception:
        return []


def _text(value: object) -> str:
    return str(value or "").strip()


def _parse_race_day(row: dict) -> date | None:
    candidates = [_text(row.get("race_date")), _text(row.get("日付"))]
    race_id_digits = "".join(ch for ch in _text(row.get("race_id") or row.get("レースID")) if ch.isdigit())
    if len(race_id_digits) >= 8:
        candidates.append(race_id_digits[:8])
    for value in candidates:
        if not value:
            continue
        normalized = value.replace("/", "-")
        try:
            return date.fromisoformat(normalized[:10])
        except Exception:
            pass
        if len(value) >= 8 and value[:8].isdigit():
            try:
                return datetime.strptime(value[:8], "%Y%m%d").date()
            except Exception:
                pass
    return None


def _current_week_range(today: date | None = None) -> tuple[date, date]:
    base = today or date.today()
    start = base - timedelta(days=base.weekday())
    return start, start + timedelta(days=6)


def _top_weekly_predictions(weekly_path: pathlib.Path, n: int = 5) -> list:
    rows = _read_csv_rows(weekly_path)
    if not rows:
        return []
    week_start, week_end = _current_week_range()
    scoped_rows = [row for row in rows if (day := _parse_race_day(row)) is not None and week_start <= day <= week_end]
    source_rows = scoped_rows or rows
    out = []
    for r in source_rows[:n]:
        out.append({
            "race_id": r.get("race_id", ""),
            "race_date": r.get("race_date", ""),
            "race_name": r.get("race_name", ""),
            "venue": r.get("venue", ""),
            "grade": r.get("race_grade", ""),
            "top_horse": r.get("top_horse", r.get("single_pick", "")),
            "dark_horse": r.get("dark_horse", ""),
            "single_pick": r.get("single_pick", ""),
            "place_pick": r.get("place_pick", ""),
            "quinella_pick": r.get("quinella_pick", ""),
            "wide_pick": r.get("wide_pick", ""),
            "exacta_pick": r.get("exacta_pick", ""),
            "trio_pick": r.get("trio_pick", ""),
            "trifecta_pick": r.get("trifecta_pick", ""),
            "win_prob": r.get("win_prob", ""),
        })
    return out


def _weekly_scope_summary(weekly_path: pathlib.Path) -> dict:
    rows = _read_csv_rows(weekly_path)
    week_start, week_end = _current_week_range()
    days = [_parse_race_day(row) for row in rows]
    valid_days = [day for day in days if day is not None]
    race_ids = {_text(row.get("race_id")) for row in rows if _text(row.get("race_id"))}
    current_rows = [row for row, day in zip(rows, days) if day is not None and week_start <= day <= week_end]
    current_race_ids = {_text(row.get("race_id")) for row in current_rows if _text(row.get("race_id"))}
    outside_rows = [row for row, day in zip(rows, days) if day is not None and not (week_start <= day <= week_end)]
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "rows": len(rows),
        "races": len(race_ids),
        "current_week_rows": len(current_rows),
        "current_week_races": len(current_race_ids),
        "outside_week_rows": len(outside_rows),
        "outside_week_races": len({_text(row.get("race_id")) for row in outside_rows if _text(row.get("race_id"))}),
        "first_date": min(valid_days).isoformat() if valid_days else "",
        "last_date": max(valid_days).isoformat() if valid_days else "",
        "needs_weekly_refresh": bool(rows and not current_rows),
    }


def _build_data_quality(harness_status: dict) -> dict:
    contract = harness_status.get("contract") if isinstance(harness_status.get("contract"), dict) else {}
    issues = contract.get("issues") if isinstance(contract.get("issues"), list) else []
    shortage_items = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        shortage_items.append(
            {
                "level": _text(issue.get("level")) or "warn",
                "check": _text(issue.get("check")),
                "count": int(issue.get("count") or 0),
                "message": _text(issue.get("message")),
                "action": _text(issue.get("action")),
            }
        )
    return {
        "failed_count": int(contract.get("failed_count") or 0),
        "warned_count": int(contract.get("warned_count") or 0),
        "shortage_items": shortage_items[:8],
    }


def _build_next_action(harness_status: dict, weekly_scope: dict, entry_scope: dict | None = None) -> dict:
    planner = harness_status.get("planner") if isinstance(harness_status.get("planner"), dict) else {}
    action = _text(planner.get("next_action"))
    reason = _text(planner.get("reason"))
    severity = _text(planner.get("severity")) or "info"
    entry_scope = entry_scope or {}
    if entry_scope.get("needs_weekly_refresh"):
        return {
            "action": "今週データ+AI予想更新",
            "reason": "今週範囲の出走表が見つかりません。出走表を更新してからAI予想を作ります。",
            "severity": "warn",
            "skip_actions": ["反省再学習だけ", "学習だけ実行"],
        }
    if weekly_scope.get("needs_weekly_refresh"):
        action = action or "今週AI予想だけ更新"
        reason = "今週範囲の予想が見つかりません。今週AI予想だけ更新を優先してください。"
        severity = "warn"
    return {
        "action": action or "予想を見る",
        "reason": reason or "大きな異常はありません。予想票を確認できます。",
        "severity": severity,
        "skip_actions": planner.get("skip_actions") if isinstance(planner.get("skip_actions"), list) else [],
    }


def _build_cycle_health(status: dict) -> dict:
    running = bool(status.get("running"))
    progress = int(status.get("progress_pct") or 0)
    updated_at = _text(status.get("updated_at"))
    updated_dt = _parse_dt(updated_at)
    age_sec = None
    if updated_dt:
        try:
            age_sec = max(0, int((datetime.now(updated_dt.tzinfo) - updated_dt).total_seconds()))
        except Exception:
            age_sec = None
    stale = bool(running and age_sec is not None and age_sec > 15 * 60)
    if stale:
        state = "stale"
        label = "停止疑い"
        message = f"自動サイクルが {progress}% / {status.get('last_phase', '-')} のまま {age_sec // 60}分以上更新されていません。"
    elif running:
        state = "running"
        label = "実行中"
        message = _text(status.get("last_phase")) or "自動サイクル実行中"
    elif status.get("last_success") is False:
        state = "error"
        label = "エラー"
        message = _text(status.get("error")) or _text(status.get("last_summary")) or "前回実行でエラー"
    else:
        state = "ok"
        label = "正常"
        message = _text(status.get("last_summary")) or "自動サイクルは停止中です。必要な時だけ更新してください。"
    return {
        "state": state,
        "label": label,
        "message": message,
        "progress_pct": progress,
        "updated_at": updated_at,
        "age_sec": age_sec,
        "last_phase": _text(status.get("last_phase")),
    }


def _classify_weekly_update_failure(notes: list[str] | tuple[str, ...] | None, message: str = "") -> dict:
    note_text = " ".join(_text(note) for note in (notes or []))
    full = f"{note_text} {_text(message)}".lower()
    if "timeout" in full or "timed out" in full or "urlopen" in full or "connection" in full:
        category = "通信失敗"
        detail = "取得元への接続または応答待ちで失敗した可能性があります。少し時間を置いて再実行してください。"
    elif "parse_skip" in full or "no_rows" in full or "synthetic" in full or "html" in full and "0" in full:
        category = "解析失敗"
        detail = "ページは取得できた可能性がありますが、出走表として読み取れませんでした。取得元ページ構造の変化が疑われます。"
    elif "fallback_count=0" in full or "今週の出走表を取得できません" in full or "race_ids_fallback_count=0" in full:
        category = "取得元未更新"
        detail = "無料取得元に今週レースがまだ出ていない、または対象日程が空の可能性があります。"
    else:
        category = "未分類"
        detail = "取得ログだけでは原因を特定できません。notesとerrorを確認してください。"
    return {
        "category": category,
        "detail": detail,
        "notes": list(notes or [])[-12:],
        "raw_message": _text(message),
    }


def _action_status(**updates: Any) -> dict:
    payload = _read_json(ACTION_STATUS_PATH)
    payload.update(updates)
    if updates.get("ok") is True or (updates.get("running") is True and updates.get("ok") is None):
        payload.pop("failure", None)
        payload.pop("stale", None)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(ACTION_STATUS_PATH, payload)
    return payload


def _action_age_sec(status: dict) -> int | None:
    stamp = _parse_dt(status.get("updated_at") or status.get("started_at"))
    if not stamp:
        return None
    try:
        return max(0, int((datetime.now(stamp.tzinfo) - stamp).total_seconds()))
    except Exception:
        return None


def _normalize_action_status(status: dict) -> dict:
    if not isinstance(status, dict) or not status:
        return {}
    if status.get("ok") is True and ("failure" in status or status.get("progress_pct") in (None, "")):
        out = dict(status)
        out.pop("failure", None)
        out.pop("stale", None)
        out["progress_pct"] = 100
        _write_json(ACTION_STATUS_PATH, out)
        return out
    if not bool(status.get("running")):
        return status
    age_sec = _action_age_sec(status)
    if age_sec is None or age_sec < ACTION_STALE_SEC:
        out = dict(status)
        out["age_sec"] = age_sec
        return out
    failure = status.get("failure") if isinstance(status.get("failure"), dict) else _classify_weekly_update_failure(
        status.get("update_report", {}).get("notes", []) if isinstance(status.get("update_report"), dict) else [],
        _text(status.get("message")),
    )
    out = dict(status)
    out.update(
        {
            "running": False,
            "ok": False,
            "stale": True,
            "age_sec": age_sec,
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "message": (
                f"{_text(status.get('label')) or '実行中処理'} が {age_sec // 60}分以上進捗更新されませんでした。"
                "停止疑いとして扱います。"
            ),
            "failure": {
                **failure,
                "category": failure.get("category") or "停止疑い",
                "detail": failure.get("detail") or "処理が長時間更新されませんでした。",
            },
        }
    )
    _write_json(ACTION_STATUS_PATH, out)
    return out


def _append_action_log(message: str, **extra: Any) -> dict:
    payload = _read_json(ACTION_STATUS_PATH)
    logs = payload.get("logs") if isinstance(payload.get("logs"), list) else []
    logs.append(
        {
            "at": datetime.now().isoformat(timespec="seconds"),
            "message": _text(message),
            **extra,
        }
    )
    payload["logs"] = logs[-30:]
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(ACTION_STATUS_PATH, payload)
    return payload


def _is_action_running(status: dict) -> bool:
    status = _normalize_action_status(status)
    if not bool(status.get("running")):
        return False
    started = _parse_dt(status.get("started_at") or status.get("updated_at"))
    if not started:
        return True
    # Avoid a stale status file blocking dashboard operation after a restart.
    return (datetime.now(started.tzinfo) - started).total_seconds() < 60 * 60 * 3


def _run_weekly_predictions_action() -> None:
    if not ACTION_LOCK.acquire(blocking=False):
        _action_status(
            running=True,
            ok=False,
            action="weekly_predictions",
            message="今週AI予想だけ更新はすでに実行中です。",
        )
        return
    try:
        _action_status(
            running=True,
            ok=None,
            action="weekly_predictions",
            label="今週AI予想だけ更新",
            started_at=datetime.now().isoformat(timespec="seconds"),
            message="今週出走表を確認しています。",
            logs=[],
        )
        _append_action_log("今週出走表の範囲を確認")
        from auto_agent import generate_weekly_predictions, run_free_prediction_harness
        from auto_data_ingest import fetch_auto_data

        progress_memory = {"bucket": -1, "message": ""}

        def _action_progress(progress_value: float, message: str) -> None:
            pct = max(0, min(100, int(round(float(progress_value) * 100))))
            clean_message = _text(message) or "更新中"
            _action_status(
                running=True,
                ok=None,
                action="weekly_predictions",
                progress_pct=pct,
                message=f"{clean_message} ({pct}%)",
            )
            bucket = pct // 5
            if bucket != progress_memory["bucket"] or clean_message != progress_memory["message"]:
                progress_memory["bucket"] = bucket
                progress_memory["message"] = clean_message
                _append_action_log(clean_message, progress_pct=pct)

        entries_scope = _weekly_scope_summary(DATA_DIR / "weekly_entries_auto.csv")
        update_report = {}
        if int(entries_scope.get("current_week_races", 0) or 0) <= 0:
            _append_action_log("今週出走表が0Rのため、軽量更新を開始")
            _action_status(
                running=True,
                ok=None,
                action="weekly_predictions",
                label="今週データ+AI予想更新",
                message="今週の出走表が古いため、最新出走表を軽量更新中です。",
            )
            report_obj = fetch_auto_data(
                data_dir=DATA_DIR,
                months_back=1,
                weekly_days_ahead=7,
                incremental=True,
                full_refresh=False,
                history_backfill_days=0,
                append_only=False,
                entries_cache_hours=0,
                update_history=False,
                update_entries=True,
                auto_forecast_weather=True,
                weather_cache_hours=6,
                fallback_max_days=14,
                cap_history_races=1,
                cap_weekly_races=120,
                run_tuning=False,
                progress_callback=_action_progress,
            )
            update_report = {
                "entries_rows": int(getattr(report_obj, "entries_rows", 0) or 0),
                "weekly_races": int(getattr(report_obj, "weekly_races", 0) or 0),
                "notes": list(getattr(report_obj, "notes", ()) or ()),
            }
            _append_action_log(
                "出走表の軽量更新が完了",
                entries_rows=update_report.get("entries_rows"),
                weekly_races=update_report.get("weekly_races"),
            )
            entries_scope = _weekly_scope_summary(DATA_DIR / "weekly_entries_auto.csv")
            if int(entries_scope.get("current_week_races", 0) or 0) <= 0:
                failure = _classify_weekly_update_failure(update_report.get("notes", []), "今週の出走表を取得できませんでした")
                _action_status(
                    running=False,
                    ok=False,
                    action="weekly_predictions",
                    label="今週データ+AI予想更新",
                    completed_at=datetime.now().isoformat(timespec="seconds"),
                    message=f"今週の出走表を取得できませんでした: {failure['category']}",
                    update_report=update_report,
                    failure=failure,
                )
                raise RuntimeError("今週の出走表を取得できませんでした。取得元の更新待ち、または無料取得元の応答失敗です。")

        _append_action_log("AI予想生成を開始")
        _action_status(
            running=True,
            ok=None,
            action="weekly_predictions",
            label="今週AI予想だけ更新",
            progress_pct=85,
            message="今週AI予想をバックグラウンドで更新中です。",
            update_report=update_report,
        )

        report = generate_weekly_predictions(DATA_DIR, simulations_per_race=800, seed=42, llm_enabled=False)
        _append_action_log("AI予想生成が完了", rows=report.get("rows"))
        harness = run_free_prediction_harness(DATA_DIR)
        _append_action_log("無料ハーネス診断が完了")
        _action_status(
            running=False,
            ok=bool(report.get("ok")),
            action="weekly_predictions",
            label="今週AI予想だけ更新",
            progress_pct=100,
            completed_at=datetime.now().isoformat(timespec="seconds"),
            message=str(report.get("message", "")),
            report=report,
            update_report=update_report,
            harness_message=str(harness.get("message", "")),
        )
    except Exception as exc:
        current = _read_json(ACTION_STATUS_PATH)
        failure = current.get("failure") if isinstance(current.get("failure"), dict) else _classify_weekly_update_failure(
            current.get("update_report", {}).get("notes", []) if isinstance(current.get("update_report"), dict) else [],
            str(exc),
        )
        _action_status(
            running=False,
            ok=False,
            action="weekly_predictions",
            label="今週AI予想だけ更新",
            completed_at=datetime.now().isoformat(timespec="seconds"),
            message=f"今週AI予想だけ更新に失敗: {exc}",
            failure=failure,
        )
    finally:
        ACTION_LOCK.release()


def start_allowed_action(action: str) -> dict:
    action = _text(action)
    current = _read_json(ACTION_STATUS_PATH)
    if _is_action_running(current):
        return {
            "ok": False,
            "accepted": False,
            "message": f"別の処理が実行中です: {current.get('label') or current.get('action')}",
            "status": current,
        }
    if action == "restart_local_auto":
        return restart_local_auto_cycle_if_stale()
    if action == "manual_results_import":
        return import_manual_results_action()
    if action != "weekly_predictions":
        return {"ok": False, "accepted": False, "message": "許可されていないアクションです。"}
    thread = threading.Thread(target=_run_weekly_predictions_action, daemon=True)
    thread.start()
    return {
        "ok": True,
        "accepted": True,
        "message": "今週AI予想だけ更新をバックグラウンド開始しました。",
        "status": _read_json(ACTION_STATUS_PATH),
    }


def import_manual_results_action() -> dict:
    try:
        from auto_agent import run_free_prediction_harness
        from result_import import import_manual_results

        _action_status(
            running=True,
            ok=None,
            action="manual_results_import",
            label="手動結果CSV取り込み",
            progress_pct=20,
            message="data/manual_results.csv を確認しています。",
        )
        report = import_manual_results(DATA_DIR)
        harness = run_free_prediction_harness(DATA_DIR)
        payload = _action_status(
            running=False,
            ok=bool(report.ok),
            action="manual_results_import",
            label="手動結果CSV取り込み",
            progress_pct=100,
            completed_at=datetime.now().isoformat(timespec="seconds"),
            message=report.message,
            report=report.to_dict(),
            harness_message=str(harness.get("message", "")),
        )
        return {"ok": bool(report.ok), "accepted": True, "message": report.message, "status": payload}
    except Exception as exc:
        payload = _action_status(
            running=False,
            ok=False,
            action="manual_results_import",
            label="手動結果CSV取り込み",
            completed_at=datetime.now().isoformat(timespec="seconds"),
            message=f"手動結果CSV取り込みに失敗: {exc}",
        )
        return {"ok": False, "accepted": True, "message": payload.get("message"), "status": payload}


def restart_local_auto_cycle_if_stale() -> dict:
    status = _read_json(DATA_DIR / "auto_cycle_status.json")
    health = _build_cycle_health(status)
    if health.get("state") != "stale":
        return {
            "ok": False,
            "accepted": False,
            "message": "自動サイクルは停止疑いではないため、再起動しませんでした。",
            "cycle_health": health,
        }
    config = _read_json(DATA_DIR / "auto_cycle_config.json")
    label = _text(config.get("label")) or "com.ouroboros.keiba.localauto"
    uid = str(os.getuid())
    cmd = ["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
        ok = completed.returncode == 0
        payload = _action_status(
            running=False,
            ok=ok,
            action="restart_local_auto",
            label="自動サイクル再起動",
            completed_at=datetime.now().isoformat(timespec="seconds"),
            message="自動サイクル再起動を要求しました。" if ok else "自動サイクル再起動要求に失敗しました。",
            report={
                "label": label,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip()[-1000:],
                "stderr": completed.stderr.strip()[-1000:],
            },
        )
        return {"ok": ok, "accepted": ok, "message": payload.get("message"), "status": payload}
    except Exception as exc:
        payload = _action_status(
            running=False,
            ok=False,
            action="restart_local_auto",
            label="自動サイクル再起動",
            completed_at=datetime.now().isoformat(timespec="seconds"),
            message=f"自動サイクル再起動要求に失敗: {exc}",
        )
        return {"ok": False, "accepted": False, "message": payload.get("message"), "status": payload}


def _line_count(path: pathlib.Path) -> int:
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _check_item(name: str, ok: bool, detail: str = "", severity: str = "WARN") -> dict:
    return {
        "name": name,
        "ok": bool(ok),
        "severity": "OK" if ok else severity,
        "detail": detail,
    }


def _parse_dt(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _build_spec_alignment(status: dict, harness_status: dict | None = None) -> dict:
    """Lightweight self-check for the integrated dashboard.

    Keep this read-only and dependency-free so the status API stays safe even
    when the Streamlit app or auto cycle is unhealthy.
    """
    checks = []

    checks.append(_check_item("KEIBAスペック表", SPEC_PATH.exists(), str(SPEC_PATH)))
    checks.append(
        _check_item(
            "統合ダッシュボード",
            (REPO_DIR / "MAIN" / "tools" / "unified_dashboard.html").exists(),
            "MAIN/tools/unified_dashboard.html",
        )
    )
    checks.append(_check_item("KEIBA本体UI", (BASE_DIR / "app.py").exists(), "KEIBA/app.py"))
    checks.append(_check_item("ステータスAPI", (BASE_DIR / "keiba_status_server.py").exists(), "KEIBA/keiba_status_server.py"))

    ui_modules = ["ui_weekly.py", "ui_sidebar.py", "ui_archive.py", "ui_prediction.py"]
    missing_ui = [name for name in ui_modules if not (BASE_DIR / name).exists()]
    checks.append(
        _check_item(
            "UI分割モジュール",
            not missing_ui,
            "missing: " + ", ".join(missing_ui) if missing_ui else "weekly/sidebar/archive/prediction",
        )
    )

    app_lines = _line_count(BASE_DIR / "app.py")
    checks.append(
        _check_item(
            "app.py段階分割",
            app_lines <= 12000,
            f"{app_lines:,} lines。大きいが互換優先で段階分割中",
            severity="INFO",
        )
    )

    layout_dirs = ["runtime", "archive", "cache", "models"]
    missing_dirs = [name for name in layout_dirs if not (DATA_DIR / name).is_dir()]
    checks.append(
        _check_item(
            "data用途別ディレクトリ",
            not missing_dirs,
            "missing: " + ", ".join(missing_dirs) if missing_dirs else "runtime/archive/cache/models",
        )
    )

    root_csvs = sorted(path.name for path in DATA_DIR.glob("*.csv"))
    checks.append(
        _check_item(
            "CSV互換配置",
            True,
            f"data直下CSV {len(root_csvs)}件。互換維持のため正本CSVは残す",
        )
    )
    checks.append(
        _check_item(
            "Parquetキャッシュ",
            (DATA_DIR / "cache" / "history_auto.parquet").exists(),
            "data/cache/history_auto.parquet",
            severity="INFO",
        )
    )

    public_status = _read_json(DATA_DIR / "public_tunnel_status.json")
    public_health = _read_json(DATA_DIR / "public_health_status.json")
    status_url = str(public_status.get("public_url", "") or "")
    health_url = str(public_health.get("public_url", "") or "")
    if status_url and health_url:
        status_time = _parse_dt(public_status.get("updated_at") or public_status.get("started_at"))
        health_time = _parse_dt(public_health.get("checked_at"))
        health_is_stale = bool(status_time and health_time and health_time < status_time)
        urls_match = status_url == health_url
        checks.append(
            _check_item(
                "公開URL状態同期",
                urls_match or health_is_stale,
                "public_tunnel_status と public_health_status のURLが一致"
                if urls_match
                else "health結果が古いため最新URLは public_tunnel_status を優先"
                if health_is_stale
                else "public_tunnel_status と public_health_status のURLが不一致",
                severity="INFO" if health_is_stale else "WARN",
            )
        )

    harness = harness_status if isinstance(harness_status, dict) and harness_status else {}
    if not harness:
        harness = status.get("prediction_harness") if isinstance(status.get("prediction_harness"), dict) else {}
    if harness:
        harness_runtime_ok = bool(harness.get("runtime_ok")) or bool(harness.get("generated_at"))
        harness_contract_ok = bool(harness.get("ok"))
        checks.append(
            _check_item(
                "無料ハーネス診断",
                harness_runtime_ok,
                str(harness.get("message", "")),
                severity="INFO" if harness_runtime_ok and not harness_contract_ok else "WARN",
            )
        )

    warn_count = sum(1 for item in checks if item.get("severity") == "WARN")
    fail_count = sum(1 for item in checks if item.get("severity") == "FAIL")
    info_count = sum(1 for item in checks if item.get("severity") == "INFO")
    ok_count = sum(1 for item in checks if item.get("severity") == "OK")
    overall = "WARN" if warn_count or fail_count else "OK"

    return {
        "status": overall,
        "summary": f"OK {ok_count} / WARN {warn_count} / INFO {info_count}",
        "spec_path": str(SPEC_PATH),
        "checks": checks,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_status() -> dict:
    now = datetime.now()
    status = _read_json(DATA_DIR / "auto_cycle_status.json")
    config = _read_json(DATA_DIR / "auto_cycle_config.json")
    harness_status = _read_json(DATA_DIR / "prediction_harness_status.json")
    feedback_stats = _compute_hit_rate(DATA_DIR / "prediction_feedback.csv")
    weekly_path = DATA_DIR / "weekly_predictions_auto.csv"
    entries_path = DATA_DIR / "weekly_entries_auto.csv"
    top_preds = _top_weekly_predictions(weekly_path)
    weekly_scope = _weekly_scope_summary(weekly_path)
    entry_scope = _weekly_scope_summary(entries_path)
    data_quality = _build_data_quality(harness_status)
    next_action = _build_next_action(harness_status, weekly_scope, entry_scope)
    action_status = _normalize_action_status(_read_json(ACTION_STATUS_PATH))
    result_import_status = _read_json(DATA_DIR / "result_import_status.json")
    cycle_health = _build_cycle_health(status)

    report = status.get("report", {})

    payload = {
        "ok": True,
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_jst": now.strftime("%Y-%m-%d %H:%M:%S"),
        "actions_disabled": ACTION_DISABLED,
        "running": status.get("running", False),
        "last_started_at": status.get("last_started_at"),
        "last_completed_at": status.get("last_completed_at"),
        "last_success": status.get("last_success"),
        "last_phase": status.get("last_phase"),
        "last_summary": status.get("last_summary", ""),
        "progress_pct": status.get("progress_pct", 0),
        "interval_sec": config.get("interval_sec", 1800),
        "llm_model": config.get("llm_model", ""),
        "history_rows": report.get("history_rows", 0),
        "history_races": report.get("history_races", 0),
        "weekly_races": report.get("weekly_races", 0),
        "predictions": feedback_stats,
        "top_weekly_predictions": top_preds,
        "prediction_harness": harness_status or status.get("prediction_harness", {}),
        "next_action": next_action,
        "data_quality": data_quality,
        "weekly_scope": weekly_scope,
        "entry_scope": entry_scope,
        "action_status": action_status,
        "result_import_status": result_import_status,
        "cycle_health": cycle_health,
    }
    payload["spec_alignment"] = _build_spec_alignment(status, harness_status)
    return payload


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-KEIBA-Action-Token",
    "Cache-Control": "no-store",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default access log

    def _send(self, code: int, body: bytes, content_type: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/keiba-status.json", "/"):
            try:
                data = build_status()
                body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
                self._send(200, body)
            except Exception as e:
                err = json.dumps({"ok": False, "error": str(e)}).encode()
                self._send(500, err)
        elif path == "/health":
            self._send(200, b'{"ok":true}')
        elif path == "/keiba-action-status.json":
            body = json.dumps(_normalize_action_status(_read_json(ACTION_STATUS_PATH)), ensure_ascii=False, indent=2).encode("utf-8")
            self._send(200, body)
        elif path == "/cycle-health.json":
            body = json.dumps(_build_cycle_health(_read_json(DATA_DIR / "auto_cycle_status.json")), ensure_ascii=False, indent=2).encode("utf-8")
            self._send(200, body)
        else:
            self._send(404, b'{"ok":false,"error":"not found"}')

    def _action_authorized(self) -> bool:
        client_host = str((self.client_address or ("", 0))[0] or "")
        client_is_loopback = client_host in {"127.0.0.1", "::1", "localhost"}
        if not ACTION_TOKEN:
            return client_is_loopback
        bearer = self.headers.get("Authorization", "")
        explicit = self.headers.get("X-KEIBA-Action-Token", "")
        return bearer == f"Bearer {ACTION_TOKEN}" or explicit == ACTION_TOKEN

    def do_POST(self):
        if ACTION_DISABLED:
            self._send(403, b'{"ok":false,"error":"actions disabled"}')
            return
        if not self._action_authorized():
            self._send(403, b'{"ok":false,"error":"forbidden"}')
            return
        path = self.path.split("?")[0]
        if path == "/actions/weekly-predictions":
            result = start_allowed_action("weekly_predictions")
            code = 202 if result.get("accepted") else 409
            body = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
            self._send(code, body)
        elif path == "/actions/restart-local-auto":
            result = start_allowed_action("restart_local_auto")
            code = 202 if result.get("accepted") else 409
            body = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
            self._send(code, body)
        elif path == "/actions/import-manual-results":
            result = start_allowed_action("manual_results_import")
            code = 202 if result.get("accepted") else 409
            body = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
            self._send(code, body)
        else:
            self._send(404, b'{"ok":false,"error":"not found"}')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    server = HTTPServer((HOST, PORT), Handler)
    print(f"[keiba_status_server] listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
