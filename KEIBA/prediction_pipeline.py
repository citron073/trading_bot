from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import re
from typing import Dict

import pandas as pd

from evaluation import build_prediction_feedback


_SYNTHETIC_NAME_RE = re.compile(r"^(Horse|Jockey|Trainer)_(\d+)$", re.IGNORECASE)
_AUTO_RACE_ID_RE = re.compile(r"^AUTO(\d{8})$", re.IGNORECASE)

WEEKLY_DISPLAY_TEXT_COLUMNS = (
    "top_horse",
    "top_jockey",
    "single_pick",
    "place_pick",
    "quinella_pick",
    "wide_pick",
    "exacta_pick",
    "trio_pick",
    "trifecta_pick",
    "dark_horse",
    "spiritual_horse",
    "llm_top_horse",
    "llm_dark_horse",
    "llm_danger_favorite",
    "llm_pick_source",
    "llm_pick_reason",
)

WEEKLY_DISPLAY_RENAME_MAP: Dict[str, str] = {
    "race_label": "レース",
    "data_state": "データ状態",
    "race_id": "レースID",
    "race_date": "日付",
    "race_name": "レース名",
    "race_grade": "格付",
    "venue": "開催",
    "weather": "天気予報",
    "track_condition": "馬場",
    "distance": "距離",
    "field_size": "頭数",
    "top_horse": "本命馬",
    "top_jockey": "本命騎手",
    "top_pop_rank": "本命人気",
    "top_horse_odds": "本命単勝オッズ",
    "dark_horse": "大穴候補",
    "dark_horse_pop": "大穴人気",
    "danger_favorite": "危険人気馬",
    "danger_favorite_pop": "危険人気",
    "spiritual_horse": "スピ候補",
    "llm_top_horse": "LLM本命",
    "llm_dark_horse": "LLM穴",
    "llm_danger_favorite": "LLM危険人気",
    "llm_pick_source": "LLMソース",
    "llm_pick_reason": "LLM根拠",
    "condition_adjustment_count": "補正本数",
    "condition_adjustments": "条件補正",
    "odds_shift_alert": "人気急変",
    "win_prob": "勝率",
    "place_prob": "複勝率",
    "single_pick": "単勝候補",
    "place_pick": "複勝候補",
    "quinella_pick": "馬連候補",
    "wide_pick": "ワイド候補",
    "exacta_pick": "馬単候補",
    "trio_pick": "三連複候補",
    "trifecta_pick": "三連単候補",
}


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def _truthy_value(value: object) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y", "hit", "的中", "済", "あり"}


def resolve_update_profile(
    profile_name: str,
    *,
    force_tuning: bool,
    months_back: int,
    weekly_days_ahead: int,
    fallback_max_days: int,
    history_backfill_days: int,
    entries_cache_hours: int,
    auto_tune: bool,
) -> Dict[str, int | bool]:
    base: Dict[str, int | bool] = {
        "months_back": int(months_back),
        "weekly_days_ahead": int(weekly_days_ahead),
        "fallback_max_days": int(fallback_max_days),
        "update_history": True,
        "update_entries": True,
    }
    if profile_name == "高速（最新追記）":
        base.update(
            {
                "incremental": True,
                "full_refresh": False,
                "history_backfill_days": 0,
                "append_only": True,
                "entries_cache_hours": max(2, int(entries_cache_hours)),
                "run_tuning": False,
            }
        )
    elif profile_name == "標準（差分更新）":
        base.update(
            {
                "incremental": True,
                "full_refresh": False,
                "history_backfill_days": int(history_backfill_days),
                "append_only": False,
                "entries_cache_hours": int(entries_cache_hours),
                "run_tuning": bool(auto_tune),
            }
        )
    else:
        base.update(
            {
                "incremental": False,
                "full_refresh": True,
                "history_backfill_days": max(1, int(history_backfill_days)),
                "append_only": False,
                "entries_cache_hours": 0,
                "run_tuning": True,
            }
        )
    if force_tuning:
        base["run_tuning"] = True
    return base


def humanize_auto_update_note(note: object) -> str:
    text = _text(note)
    if not text:
        return ""
    if text.startswith("history_mode=allowlist:"):
        return f"結果待ちレースだけ取得しました ({text.split(':', 1)[-1]}件)"
    if text.startswith("history_mode="):
        return ""
    if text.startswith("weekly_cache_hit:"):
        return "再試行中: 出走表キャッシュを使ったため最新取得は省略しました"
    if text == "weekly_entries_reused_existing":
        return "軽量実行: 今週出走表は既存キャッシュをそのまま使いました"
    if text.startswith("history_up_to_date:skip_fetch"):
        return "再試行不要: 履歴は最新のため取得を省略しました"
    if text.startswith("history_race_ids_fallback_count="):
        return f"再試行中: 代替経路で履歴レースIDを補完しました ({text.split('=', 1)[-1]}件)"
    if text.startswith("weekly_race_ids_fallback_count="):
        return f"再試行中: 代替経路で今週レースIDを補完しました ({text.split('=', 1)[-1]}件)"
    if text.startswith("history_append_skip_existing="):
        return f"再試行不要: 既存履歴をスキップしました ({text.split('=', 1)[-1]}件)"
    if text.startswith("weather_forecast_failed:"):
        return "最終失敗: 天気予報の取得に失敗しました"
    if text.startswith("tune_failed:"):
        detail = text.split(":", 1)[-1]
        if "timeout" in detail.lower():
            return "最終失敗: 再学習がタイムアウトしました"
        return "最終失敗: 再学習に失敗しました"
    if text.startswith("history_skip:"):
        parts = text.split(":", 2)
        race_id = parts[1] if len(parts) > 1 else "-"
        detail = parts[2] if len(parts) > 2 else ""
        if "retry_exhausted" in detail and "timeout" in detail.lower():
            return f"最終失敗: 履歴取得 {race_id} はタイムアウト後の再試行でも取得できませんでした"
        if "retry_exhausted" in detail:
            return f"最終失敗: 履歴取得 {race_id} は再試行後も失敗しました"
        if "timeout" in detail.lower():
            return f"タイムアウト: 履歴取得 {race_id} の応答待ちを打ち切りました"
        return f"最終失敗: 履歴取得 {race_id} をスキップしました"
    if text.startswith("history_fetch_failed:"):
        race_id = text.split(":", 1)[-1] or "-"
        return f"最終失敗: 履歴取得 {race_id} は結果/出走表の両方で取得できませんでした"
    if text.startswith("history_empty_result:"):
        race_id = text.split(":", 1)[-1] or "-"
        return f"結果未反映: {race_id} は取得できましたが着順データが空でした"
    if text.startswith("weekly_load_skip:"):
        parts = text.split(":", 2)
        race_id = parts[1] if len(parts) > 1 else "-"
        detail = parts[2] if len(parts) > 2 else ""
        if "retry_exhausted" in detail and "timeout" in detail.lower():
            return f"最終失敗: 出走表取得 {race_id} はタイムアウト後の再試行でも取得できませんでした"
        if "retry_exhausted" in detail:
            return f"最終失敗: 出走表取得 {race_id} は再試行後も失敗しました"
        if "timeout" in detail.lower():
            return f"タイムアウト: 出走表取得 {race_id} の応答待ちを打ち切りました"
        return f"最終失敗: 出走表取得 {race_id} をスキップしました"
    if text.startswith("weekly_netkeiba_html_fallback:"):
        parts = text.split(":")
        race_id = parts[1] if len(parts) > 1 else "-"
        return f"再試行中: {race_id} は HTML 側へフォールバックして取得しました"
    if text.startswith("weekly_netkeiba_html_overlay:"):
        parts = text.split(":")
        race_id = parts[1] if len(parts) > 1 else "-"
        return f"再試行中: {race_id} は HTML から距離・開催情報を補完しました"
    if "retry_exhausted" in text and "timeout" in text.lower():
        return "最終失敗: タイムアウト後の再試行でも完了しませんでした"
    if "retry_exhausted" in text:
        return "最終失敗: 再試行後も取得できませんでした"
    if "timeout" in text.lower():
        return "タイムアウト: 応答待ちを打ち切りました"
    return text


def collect_auto_update_status_lines(notes: object, *, limit: int = 6) -> list[str]:
    if not isinstance(notes, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for note in notes:
        line = humanize_auto_update_note(note)
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out[: max(1, int(limit))]


def feedback_new_result_count(before_summary: Dict[str, object] | None, after_summary: Dict[str, object] | None) -> int:
    before_summary = before_summary if isinstance(before_summary, dict) else {}
    after_summary = after_summary if isinstance(after_summary, dict) else {}
    try:
        before_count = int(before_summary.get("evaluated_races", 0) or 0)
    except Exception:
        before_count = 0
    try:
        after_count = int(after_summary.get("evaluated_races", 0) or 0)
    except Exception:
        after_count = 0
    return max(0, after_count - before_count)


def _numeric(value: object) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def feedback_summary_delta_text(before: Dict[str, object] | None, after: Dict[str, object] | None) -> str:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return ""
    parts: list[str] = []

    def _delta_int(key: str, label: str) -> None:
        before_value = int(before.get(key, 0) or 0)
        after_value = int(after.get(key, 0) or 0)
        diff = after_value - before_value
        if diff:
            parts.append(f"{label} {before_value:,}->{after_value:,} ({diff:+,})")

    def _delta_rate(key: str, label: str) -> None:
        before_value = _numeric(before.get(key))
        after_value = _numeric(after.get(key))
        if before_value is None or after_value is None:
            return
        diff = after_value - before_value
        if abs(diff) < 1e-9:
            return
        parts.append(f"{label} {before_value:.1%}->{after_value:.1%} ({diff:+.1%})")

    def _delta_roi(key: str, label: str) -> None:
        before_value = _numeric(before.get(key))
        after_value = _numeric(after.get(key))
        if before_value is None or after_value is None:
            return
        diff = after_value - before_value
        if abs(diff) < 1e-9:
            return
        parts.append(f"{label} {before_value:.0%}->{after_value:.0%} ({diff:+.0%})")

    _delta_int("evaluated_races", "評価済み")
    _delta_int("pending_races", "結果待ち")
    _delta_rate("top_horse_hit_rate", "本命勝率")
    _delta_rate("single_hit_rate", "単勝的中率")
    _delta_rate("place_hit_rate", "複勝的中率")
    _delta_roi("single_roi", "単勝回収率")
    _delta_roi("place_roi", "複勝回収率")
    return " / ".join(parts)


def feedback_summary_delta_snapshot(before: Dict[str, object] | None, after: Dict[str, object] | None) -> Dict[str, object]:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {}
    snapshot: Dict[str, object] = {}

    def _delta_int(key: str, label: str) -> None:
        before_value = int(before.get(key, 0) or 0)
        after_value = int(after.get(key, 0) or 0)
        diff = after_value - before_value
        snapshot[key] = {
            "label": label,
            "before": before_value,
            "after": after_value,
            "diff": diff,
            "text": f"{before_value:,}->{after_value:,} ({diff:+,})",
            "after_text": f"{after_value:,}",
            "delta_text": f"{diff:+,}",
        }

    def _delta_rate(key: str, label: str) -> None:
        before_value = _numeric(before.get(key))
        after_value = _numeric(after.get(key))
        if before_value is None or after_value is None:
            return
        diff = after_value - before_value
        snapshot[key] = {
            "label": label,
            "before": before_value,
            "after": after_value,
            "diff": diff,
            "text": f"{before_value:.1%}->{after_value:.1%} ({diff:+.1%})",
            "after_text": f"{after_value:.1%}",
            "delta_text": f"{diff:+.1%}",
        }

    def _delta_roi(key: str, label: str) -> None:
        before_value = _numeric(before.get(key))
        after_value = _numeric(after.get(key))
        if before_value is None or after_value is None:
            return
        diff = after_value - before_value
        snapshot[key] = {
            "label": label,
            "before": before_value,
            "after": after_value,
            "diff": diff,
            "text": f"{before_value:.0%}->{after_value:.0%} ({diff:+.0%})",
            "after_text": f"{after_value:.0%}",
            "delta_text": f"{diff:+.0%}",
        }

    _delta_int("evaluated_races", "評価済み")
    _delta_int("pending_races", "結果待ち")
    _delta_rate("top_horse_hit_rate", "本命勝率")
    _delta_rate("single_hit_rate", "単勝的中率")
    _delta_rate("place_hit_rate", "複勝的中率")
    _delta_roi("single_roi", "単勝回収率")
    _delta_roi("place_roi", "複勝回収率")
    return snapshot


def normalize_race_ids(values: object) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    return [race_id for race_id in (_text(value) for value in values) if race_id]


def remaining_targeted_result_ids(feedback_df: pd.DataFrame | None, targeted_race_ids: object) -> list[str]:
    targeted = normalize_race_ids(targeted_race_ids)
    if not targeted or not isinstance(feedback_df, pd.DataFrame) or feedback_df.empty:
        return []
    if "race_id" not in feedback_df.columns or "result_available" not in feedback_df.columns:
        return []
    work = feedback_df.copy()
    work["race_id_text"] = work["race_id"].map(_text)
    targeted_set = set(targeted)
    mask = work["race_id_text"].isin(targeted_set) & (~work["result_available"].map(_truthy_value))
    return [race_id for race_id in work.loc[mask, "race_id_text"].tolist() if race_id]


def result_fetch_attempt_status(new_result_count: int) -> str:
    try:
        count = int(new_result_count)
    except Exception:
        count = 0
    return "pending_after_attempt" if count <= 0 else "partial_after_attempt"


def result_refresh_notice_text(*, history_rows: object, history_races: object, learned: bool) -> str:
    suffix = "再学習済み" if learned else "学習なし"
    prefix = "結果更新完了" if learned else "結果取得完了"
    return f"{prefix}: history {history_rows}行 / 履歴レース {history_races} / {suffix}"


def result_refresh_outcome_summary(*, history_rows: object, history_races: object, learned: bool) -> str:
    suffix = "再学習済み" if learned else "学習なし"
    return f"履歴 {history_rows:,}行 / 履歴レース {history_races:,} / {suffix}"


def result_refresh_summary_detail(*, new_result_count: int, history_rows: object, history_races: object) -> str:
    return (
        f"新規結果 {int(new_result_count):,}件 / "
        f"history {history_rows}行 / "
        f"履歴レース {history_races} / "
        "今週出走表は既存キャッシュを維持"
    )


def result_refresh_chip(new_result_count: int) -> str:
    return f"新規結果 {int(new_result_count):,}件" if int(new_result_count) > 0 else "新規結果なし"


def _parse_date_text(value: object) -> date | None:
    text = _text(value)
    if not text or text in {"-", "nan", "None"}:
        return None
    normalized = text.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").strip()
    for candidate in (text, normalized):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
        except Exception:
            pass
        for fmt, width in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
            try:
                return datetime.strptime(candidate[:width], fmt).date()
            except Exception:
                pass
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except Exception:
            return None
    return None


def _current_week_bounds(today: date | None = None) -> tuple[date, date]:
    ref = today or datetime.now().date()
    week_start = ref - timedelta(days=ref.weekday())
    return week_start, week_start + timedelta(days=6)


def _parse_race_day_from_row(
    row: pd.Series,
    *,
    race_id_col: str = "race_id",
    race_date_col: str = "race_date",
    fetched_col: str = "fetched_date",
) -> date | None:
    race_date = _parse_date_text(row.get(race_date_col, ""))
    if race_date is not None:
        return race_date
    rid = _text(row.get(race_id_col, ""))
    digits = re.sub(r"\D", "", rid)
    if len(digits) >= 8:
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except Exception:
            pass
    return _parse_date_text(row.get(fetched_col, ""))


def filter_current_week(
    frame: pd.DataFrame,
    *,
    today: date | None = None,
    race_id_col: str = "race_id",
    race_date_col: str = "race_date",
    fetched_col: str = "fetched_date",
) -> pd.DataFrame:
    if frame.empty:
        return frame
    week_start, week_end = _current_week_bounds(today)
    work = frame.copy()
    race_days = work.apply(
        lambda row: _parse_race_day_from_row(
            row,
            race_id_col=race_id_col,
            race_date_col=race_date_col,
            fetched_col=fetched_col,
        ),
        axis=1,
    )
    filtered = work[race_days.map(lambda d: bool(d is not None and week_start <= d <= week_end))].copy()
    filtered.attrs["week_start"] = week_start.isoformat()
    filtered.attrs["week_end"] = week_end.isoformat()
    return filtered


def ensure_weekly_prediction_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    defaults: Dict[str, object] = {
        "place_pick": "-",
        "wide_pick": "-",
        "trio_pick": "-",
        "trifecta_pick": "-",
        "exacta_pick": "-",
        "danger_favorite": "-",
        "danger_favorite_pop": "-",
        "llm_top_horse": "-",
        "llm_dark_horse": "-",
        "llm_danger_favorite": "-",
        "llm_pick_source": "-",
        "llm_pick_reason": "-",
    }
    for key, default in defaults.items():
        if key not in out.columns:
            out[key] = default
    return out


def prepare_weekly_predictions_preview(frame: pd.DataFrame, *, today: date | None = None) -> pd.DataFrame:
    return ensure_weekly_prediction_columns(filter_current_week(frame, today=today))


def coerce_weekly_display_text_columns(
    frame: pd.DataFrame,
    *,
    columns: tuple[str, ...] = WEEKLY_DISPLAY_TEXT_COLUMNS,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].map(_text)
    return out


def rename_weekly_display_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.rename(columns=WEEKLY_DISPLAY_RENAME_MAP)


def prepare_weekly_display_columns(frame: pd.DataFrame) -> pd.DataFrame:
    return rename_weekly_display_columns(coerce_weekly_display_text_columns(frame))


def save_weekly_predictions(
    frame: pd.DataFrame,
    path: Path,
    *,
    encoding: str = "utf-8-sig",
) -> pd.DataFrame:
    out = ensure_weekly_prediction_columns(frame)
    if out.empty:
        return out
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding=encoding)
    return out


def merge_selected_weekly_prediction(
    current_weekly: pd.DataFrame | None,
    refreshed: pd.DataFrame,
    race_id: object,
) -> pd.DataFrame:
    selected_race_id = _text(race_id)
    if current_weekly is None or current_weekly.empty:
        merged = refreshed.copy()
    else:
        work = current_weekly.copy()
        if selected_race_id and "race_id" in work.columns:
            race_ids = work["race_id"].fillna("").astype(str).str.strip()
            work = work[race_ids != selected_race_id].copy()
        merged = pd.concat([work, refreshed], ignore_index=True)

    merged = ensure_weekly_prediction_columns(merged)
    if "race_id" in merged.columns:
        merged["race_id"] = merged["race_id"].fillna("").astype(str).str.strip()
        merged = merged.sort_values("race_id").reset_index(drop=True)
    return merged


def _race_number_from_id(value: object) -> int:
    match = re.search(r"(\d{2})$", _text(value))
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def sort_program_order_frame(
    frame: pd.DataFrame,
    *,
    race_id_col: str,
    race_date_col: str,
    venue_col: str = "",
    ascending_day: bool = True,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    work = frame.copy()
    work["_sort_day"] = work.apply(lambda row: _parse_date_text(row.get(race_date_col, "")) or date.min, axis=1)
    work["_sort_race_no"] = work[race_id_col].map(_race_number_from_id) if race_id_col in work.columns else 0
    sort_cols = ["_sort_day"]
    ascending = [ascending_day]
    if venue_col and venue_col in work.columns:
        work["_sort_venue"] = work[venue_col].fillna("").astype(str).str.strip()
        sort_cols.append("_sort_venue")
        ascending.append(True)
    sort_cols.append("_sort_race_no")
    ascending.append(True)
    return work.sort_values(sort_cols, ascending=ascending).drop(
        columns=["_sort_day", "_sort_race_no", "_sort_venue"],
        errors="ignore",
    ).reset_index(drop=True)


def weekly_notice_row(frame: pd.DataFrame, preferred_race_id: object = "") -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=object)
    preferred = _text(preferred_race_id)
    if preferred and "race_id" in frame.columns:
        subset = frame[frame["race_id"].fillna("").astype(str).str.strip() == preferred]
        if not subset.empty:
            return subset.iloc[0]
    work = frame.copy()
    if "race_id" in work.columns:
        work = sort_program_order_frame(work, race_id_col="race_id", race_date_col="race_date", venue_col="venue")
    return work.iloc[0]


def _format_date_text(value: object) -> str:
    parsed = _parse_date_text(value)
    return parsed.strftime("%Y/%m/%d") if parsed else "-"


def _format_race_label(race_id: object, venue: object = "", race_date: object = "", race_name: object = "") -> str:
    rid = _text(race_id)
    if not rid:
        return "-"
    venue_text = _text(venue)
    race_name_text = _text(race_name)
    race_date_text = _format_date_text(race_date)
    if race_date_text == "-":
        race_date_text = ""
    auto_match = _AUTO_RACE_ID_RE.match(rid)
    if auto_match and not race_date_text:
        try:
            race_date_text = datetime.strptime(auto_match.group(1), "%Y%m%d").strftime("%Y/%m/%d")
        except ValueError:
            race_date_text = auto_match.group(1)
    parts: list[str] = []
    if race_date_text:
        parts.append(race_date_text)
    if venue_text and venue_text not in {"-", "nan", "None"}:
        parts.append(venue_text)
    if race_name_text and race_name_text not in {"-", "nan", "None"}:
        parts.append(race_name_text)
    parts.append(f"[{rid}]")
    return " ".join(parts).strip()


def _render_single_name(value: object) -> str:
    text = _text(value)
    if not text:
        return "-"
    match = _SYNTHETIC_NAME_RE.match(text)
    if not match:
        return text
    role = match.group(1).lower()
    num = match.group(2).zfill(2)
    label = {"horse": "馬", "jockey": "騎手", "trainer": "調教師"}.get(role, "候補")
    return f"{label}{num}（仮）"


def render_name_text(value: object) -> str:
    text = _text(value)
    if not text:
        return "-"
    if " / " in text:
        return " / ".join(
            token if token.startswith("... +") else _render_single_name(token)
            for token in (part.strip() for part in text.split(" / "))
        )
    if "-" in text:
        return "-".join(_render_single_name(token) for token in text.split("-"))
    return _render_single_name(text)


def weekly_notice_message(prefix: str, row: pd.Series | Dict[str, object]) -> str:
    favorite = render_name_text(row.get("top_horse", row.get("本命馬", "-")))
    longshot = render_name_text(row.get("dark_horse", row.get("大穴候補", "-")))
    trifecta = render_name_text(row.get("trifecta_pick", row.get("三連単候補", "-")))
    race_label = _text(row.get("race_label", row.get("レース", "")))
    if not race_label:
        race_label = _format_race_label(
            row.get("race_id", row.get("レースID", "")),
            row.get("venue", row.get("開催", "")),
            row.get("race_date", row.get("日付", "")),
            row.get("race_name", row.get("レース名", "")),
        )
    return f"{prefix}: {race_label} / 本命 {favorite} / 大穴 {longshot} / 三連単 {trifecta}"


def read_feedback_source_csv(path: Path, *, dtype: Dict[str, str] | None = None) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=dtype, low_memory=False)
    except Exception:
        return pd.DataFrame()


def build_prediction_feedback_from_paths(
    archive_path: Path,
    history_path: Path,
    payouts_path: Path,
    *,
    dtype: Dict[str, str] | None = None,
) -> pd.DataFrame:
    return build_prediction_feedback(
        read_feedback_source_csv(archive_path, dtype=dtype),
        read_feedback_source_csv(history_path, dtype=dtype),
        read_feedback_source_csv(payouts_path, dtype=dtype),
    )
