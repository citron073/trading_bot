from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import socket
from typing import Any, Dict, Iterable, List, Tuple
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

from auto_data_ingest import read_weights_json
from evaluation import aggregate_prediction_feedback, upsert_prediction_archive
from feedback_learning import upsert_prediction_feature_archive
from llm_memory import append_jsonl_with_compaction
from predictor import predict_race

DATA_DIRNAME = "data"
AUTO_HISTORY_FILENAME = "history_auto.csv"
AUTO_ENTRIES_FILENAME = "weekly_entries_auto.csv"
AUTO_WEIGHTS_FILENAME = "keiba_best_weights.json"
WEEKLY_PREDICTIONS_FILENAME = "weekly_predictions_auto.csv"
PREDICTION_ARCHIVE_FILENAME = "prediction_archive.csv"
PREDICTION_FEEDBACK_FILENAME = "prediction_feedback.csv"
PREDICTION_FEATURE_ARCHIVE_FILENAME = "prediction_feature_archive.csv"
LOCAL_LLM_MEMORY_FILENAME = "local_llm_keiba_memory.jsonl"
AUTO_IMPROVE_STATE_FILENAME = "auto_improve_state.json"
AUTO_AGENT_STATUS_FILENAME = "auto_agent_status.json"
AUTO_AGENT_REPORT_FILENAME = "auto_agent_report.json"
AUTO_AGENT_REPORT_MD_FILENAME = "auto_agent_report.md"
FREE_HARNESS_STATUS_FILENAME = "prediction_harness_status.json"
LOCAL_LLM_MEMORY_MAX_ACTIVE_ROWS = 12000
LOCAL_LLM_MEMORY_MAX_ACTIVE_BYTES = 16 * 1024 * 1024
WEEKLY_PREDICTION_REFRESH_MINUTES_DEFAULT = 180

LOCAL_LLM_BASE_URL_DEFAULT = "http://127.0.0.1:11434"
LOCAL_LLM_MODEL_DEFAULT = "qwen2.5:1.5b"
AUTO_AGENT_MAX_LLM_RACES_DEFAULT = 12

_RACE_GRADE_ALIASES: Dict[str, str] = {
    "高松宮記念": "G1",
    "大阪杯": "G1",
    "桜花賞": "G1",
    "皐月賞": "G1",
    "NHKマイルC": "G1",
    "オークス": "G1",
    "日本ダービー": "G1",
    "安田記念": "G1",
    "宝塚記念": "G1",
    "秋華賞": "G1",
    "菊花賞": "G1",
    "ジャパンC": "G1",
    "有馬記念": "G1",
    "ホープフルS": "G1",
    "金鯱賞": "G2",
    "阪神大賞典": "G2",
    "スプリングS": "G2",
    "弥生賞ディープインパクト記念": "G2",
    "ファルコンS": "G3",
    "フラワーC": "G3",
    "愛知杯": "G3",
}


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none"} else text


def _trim_text_list(values: Iterable[str], *, max_items: int = 1600) -> List[str]:
    cleaned = [_to_text(value) for value in values if _to_text(value)]
    if len(cleaned) <= max(1, int(max_items)):
        return cleaned
    return cleaned[-max(1, int(max_items)) :]


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _file_mtime(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except Exception:
        return 0.0


def _race_id_set(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "race_id" not in frame.columns:
        return set()
    return set(frame["race_id"].map(_to_text).loc[lambda s: s != ""].tolist())


def _current_week_race_count(frame: pd.DataFrame) -> int:
    if frame.empty or "race_id" not in frame.columns:
        return 0
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    work = frame.copy()
    days = work.apply(lambda row: _parse_prediction_race_day(row.get("race_date", ""), row.get("race_id", "")), axis=1)
    work["_race_day"] = days
    current = work[work["_race_day"].map(lambda day: bool(day is not None and week_start <= day <= week_end))].copy()
    if current.empty:
        return 0
    return int(current["race_id"].map(_to_text).replace("", np.nan).dropna().nunique())


def _weekly_predictions_refresh_reason(data_dir: Path, *, refresh_minutes: int) -> str:
    entries_path = data_dir / AUTO_ENTRIES_FILENAME
    weights_path = data_dir / AUTO_WEIGHTS_FILENAME
    output_path = data_dir / WEEKLY_PREDICTIONS_FILENAME
    if not output_path.exists():
        return "予想CSVなし"

    prediction_df = _read_csv_if_exists(output_path)
    entries_df = _read_csv_if_exists(entries_path)
    if prediction_df.empty:
        return "予想CSVが空"
    if entries_df.empty:
        return "出走表なし"
    if _current_week_race_count(entries_df) <= 0:
        return "今週の出走表がありません"
    if _current_week_race_count(prediction_df) <= 0:
        return "今週の予想がありません"

    prediction_ids = _race_id_set(prediction_df)
    entry_ids = _race_id_set(entries_df)
    if entry_ids and prediction_ids != entry_ids:
        missing = len(entry_ids - prediction_ids)
        extra = len(prediction_ids - entry_ids)
        return f"出走表と予想レースが不一致 (不足{missing} / 余分{extra})"

    source_mtime = max(_file_mtime(entries_path), _file_mtime(weights_path))
    output_mtime = _file_mtime(output_path)
    if source_mtime > output_mtime:
        return "出走表または重みが予想より新しい"

    age_seconds = max(0.0, datetime.now().timestamp() - output_mtime)
    if age_seconds > max(10, int(refresh_minutes)) * 60:
        return f"予想作成から{int(age_seconds // 60)}分経過"
    return ""


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    append_jsonl_with_compaction(
        path,
        payload,
        max_rows=LOCAL_LLM_MEMORY_MAX_ACTIVE_ROWS,
        max_bytes=LOCAL_LLM_MEMORY_MAX_ACTIVE_BYTES,
    )


def _normalize_local_llm_base_url(base_url: str) -> str:
    text = _to_text(base_url) or LOCAL_LLM_BASE_URL_DEFAULT
    return text.rstrip("/")


def _normalize_budget_basis_key(value: Any) -> str:
    text = _to_text(value)
    if text in {"trend", "analog", "base"}:
        return text
    if "今週傾向" in text:
        return "trend"
    if "類似個体" in text:
        return "analog"
    if "ベース" in text:
        return "base"
    return ""


def _format_budget_basis_label(value: Any) -> str:
    key = _normalize_budget_basis_key(value)
    return {
        "trend": "今週傾向反映",
        "analog": "類似個体補正",
        "base": "ベース配分",
    }.get(key, "未選択")


def _extract_feature_weights_from_payload(payload: Dict[str, Any] | None) -> Dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("best_weights", payload)
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, float] = {}
    for key, value in raw.items():
        try:
            out[str(key)] = float(value)
        except Exception:
            continue
    return out


def _extract_condition_adjustments_from_payload(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("condition_adjustments", {})
    return raw if isinstance(raw, dict) else {}


def _infer_race_grade(race_name: Any) -> str:
    text = _to_text(race_name)
    if not text:
        return "未判定"
    upper = text.upper()
    if "G1" in upper:
        return "G1"
    if "G2" in upper:
        return "G2"
    if "G3" in upper:
        return "G3"
    for alias, grade in _RACE_GRADE_ALIASES.items():
        if alias in text:
            return grade
    return "未判定"


def _extract_condition_adjustment_labels(result: Any) -> List[str]:
    frame = getattr(result, "horse_predictions", pd.DataFrame())
    if frame is None or frame.empty or "条件補正" not in frame.columns:
        return []
    labels: List[str] = []
    for value in frame["条件補正"].tolist():
        for part in _to_text(value).split("/"):
            label = _to_text(part)
            if label and label not in labels:
                labels.append(label)
    return labels


def _format_condition_adjustment_summary(labels: Iterable[str]) -> str:
    cleaned = [_to_text(label) for label in labels if _to_text(label)]
    return " / ".join(cleaned[:4]) if cleaned else "-"


def _popularity_rank_for_horse(entries_df: pd.DataFrame, horse_name: str) -> tuple[int | None, float | None]:
    if entries_df.empty or "horse" not in entries_df.columns:
        return None, None
    horse_text = _to_text(horse_name)
    work = entries_df.copy()
    work["horse"] = work["horse"].map(_to_text)
    hit = work[work["horse"] == horse_text].head(1)
    odds_value = None
    if "odds" in work.columns:
        odds_series = pd.to_numeric(work["odds"], errors="coerce")
        if not hit.empty:
            hit_odds = pd.to_numeric(hit["odds"], errors="coerce")
            odds_value = None if hit_odds.empty or pd.isna(hit_odds.iloc[0]) else float(hit_odds.iloc[0])
        ranked = work.loc[odds_series.notna() & (odds_series > 0), ["horse"]].copy()
        ranked["odds"] = odds_series[odds_series.notna() & (odds_series > 0)].astype(float).values
        if not ranked.empty:
            ranked = ranked.sort_values(["odds", "horse"], ascending=[True, True]).reset_index(drop=True)
            ranked["pop_rank"] = ranked["odds"].rank(method="min", ascending=True).astype(int)
            match = ranked[ranked["horse"] == horse_text]
            if not match.empty:
                return int(match.iloc[0]["pop_rank"]), odds_value
    if "popularity" in work.columns and not hit.empty:
        pop = pd.to_numeric(hit["popularity"], errors="coerce")
        if not pop.empty and pd.notna(pop.iloc[0]):
            return int(float(pop.iloc[0])), odds_value
    return None, odds_value


def _build_prediction_feature_rows(
    result: Any,
    *,
    race_id: Any,
    race_date: Any,
    race_name: Any,
    race_grade: Any,
    venue: Any,
    weather: Any,
    track_condition: Any,
    distance: Any,
    field_size: Any,
) -> pd.DataFrame:
    frame = getattr(result, "horse_predictions", pd.DataFrame())
    if frame is None or frame.empty:
        return pd.DataFrame()
    work = frame.copy().reset_index(drop=True)
    work.insert(0, "predicted_rank", work.index + 1)
    work = work.rename(
        columns={
            "馬": "horse",
            "騎手": "jockey",
            "勝率": "predicted_win_prob",
            "複勝率": "predicted_place_prob",
        }
    )
    keep_cols = [
        "horse",
        "jockey",
        "predicted_rank",
        "predicted_win_prob",
        "predicted_place_prob",
        "horse_win_rate",
        "horse_place_rate",
        "jockey_win_rate",
        "jockey_place_rate",
        "trainer_win_rate",
        "trainer_place_rate",
        "gate_place_rate",
        "weather_fit",
        "track_fit",
        "distance_fit",
        "form_factor",
        "condition_factor",
        "paddock_factor",
        "weight_diff_factor",
        "odds_shift_factor",
        "market_factor",
    ]
    keep_cols = [col for col in keep_cols if col in work.columns]
    out = work[keep_cols].copy()
    out.insert(0, "race_id", _to_text(race_id))
    out.insert(1, "race_date", _to_text(race_date))
    out.insert(2, "race_name", _to_text(race_name))
    out.insert(3, "race_grade", _to_text(race_grade))
    out.insert(4, "venue", _to_text(venue))
    out.insert(5, "weather", _to_text(weather))
    out.insert(6, "track_condition", _to_text(track_condition))
    distance_value = pd.to_numeric(pd.Series([distance]), errors="coerce").iloc[0]
    field_size_value = pd.to_numeric(pd.Series([field_size]), errors="coerce").iloc[0]
    out.insert(7, "distance", "" if pd.isna(distance_value) else float(distance_value))
    out.insert(8, "field_size", "" if pd.isna(field_size_value) else int(float(field_size_value)))
    out.insert(9, "predicted_at", datetime.now().isoformat(timespec="seconds"))
    return out


def _choose_dark_horse(horse_predictions: pd.DataFrame, entries_df: pd.DataFrame, top_horse: str) -> tuple[str, str]:
    if horse_predictions.empty:
        return "-", "-"
    candidates = horse_predictions.copy()
    candidates["pop_rank"] = candidates["馬"].map(lambda horse: _popularity_rank_for_horse(entries_df, horse)[0])
    dark = candidates[(pd.to_numeric(candidates["pop_rank"], errors="coerce") >= 6) & (candidates["馬"] != top_horse)]
    if dark.empty:
        dark = candidates[candidates["馬"] != top_horse]
    if dark.empty:
        return "-", "-"
    row = dark.iloc[0]
    return _to_text(row.get("馬", "-")) or "-", _to_text(row.get("pop_rank", "-")) or "-"


def _choose_danger_favorite(horse_predictions: pd.DataFrame, entries_df: pd.DataFrame, top_horse: str) -> tuple[str, str]:
    if entries_df.empty or "horse" not in entries_df.columns:
        return "-", "-"
    odds_frame = entries_df.copy()
    odds_frame["horse"] = odds_frame["horse"].map(_to_text)
    odds_frame["odds"] = pd.to_numeric(odds_frame.get("odds"), errors="coerce")
    odds_frame = odds_frame[odds_frame["horse"] != ""]
    odds_frame = odds_frame[odds_frame["odds"].notna() & (odds_frame["odds"] > 0)].copy()
    if odds_frame.empty:
        return "-", "-"
    odds_frame = odds_frame.sort_values(["odds", "horse"], ascending=[True, True]).reset_index(drop=True)
    odds_frame["pop_rank"] = odds_frame["odds"].rank(method="min", ascending=True).astype(int)
    favorite = odds_frame.iloc[0]
    favorite_horse = _to_text(favorite.get("horse", "-"))
    if favorite_horse and favorite_horse != top_horse:
        return favorite_horse, _to_text(favorite.get("pop_rank", "-")) or "-"
    secondary = odds_frame[odds_frame["horse"] != top_horse]
    if secondary.empty:
        return "-", "-"
    row = secondary.iloc[0]
    return _to_text(row.get("horse", "-")) or "-", _to_text(row.get("pop_rank", "-")) or "-"


def _pick_from_table(table: pd.DataFrame, column: str) -> str:
    if table is None or table.empty or column not in table.columns:
        return "-"
    return _to_text(table.iloc[0].get(column, "-")) or "-"


def _first_text_from_frame(frame: pd.DataFrame, column: str, default: str = "-") -> str:
    if frame is None or frame.empty or column not in frame.columns:
        return default
    try:
        series = frame[column].dropna().map(_to_text)
        series = series[series != ""]
    except Exception:
        return default
    if series.empty:
        return default
    return _to_text(series.iloc[0]) or default


def _build_ranked_candidates(result: Any, entries_df: pd.DataFrame) -> pd.DataFrame:
    frame = getattr(result, "horse_predictions", pd.DataFrame())
    if frame is None or frame.empty:
        return pd.DataFrame()
    work = frame.copy().reset_index(drop=True)
    work["horse"] = work.get("馬", pd.Series([""] * len(work))).map(_to_text)
    work["win_prob"] = pd.to_numeric(work.get("勝率"), errors="coerce")
    work["place_prob"] = pd.to_numeric(work.get("複勝率"), errors="coerce")
    work["pop_rank"] = work["horse"].map(lambda horse: _popularity_rank_for_horse(entries_df, horse)[0])
    work["odds"] = work["horse"].map(lambda horse: _popularity_rank_for_horse(entries_df, horse)[1])
    work["pred_rank"] = np.arange(1, len(work) + 1)
    return work


def _candidate_lines(frame: pd.DataFrame, *, limit: int = 3) -> List[str]:
    if frame.empty:
        return ["- 候補なし"]
    lines: List[str] = []
    for _, row in frame.head(max(1, int(limit))).iterrows():
        pop_text = "-" if pd.isna(pd.to_numeric(pd.Series([row.get("pop_rank")]), errors="coerce").iloc[0]) else f"{int(float(row.get('pop_rank')))}番人気"
        odds_text = "-" if pd.isna(pd.to_numeric(pd.Series([row.get("odds")]), errors="coerce").iloc[0]) else f"{float(row.get('odds')):.1f}"
        win_text = "-" if pd.isna(pd.to_numeric(pd.Series([row.get("win_prob")]), errors="coerce").iloc[0]) else f"{float(row.get('win_prob')):.2%}"
        lines.append(
            " / ".join(
                [
                    f"馬={_to_text(row.get('horse', '-'))}",
                    f"人気={pop_text}",
                    f"単勝={odds_text}",
                    f"勝率={win_text}",
                ]
            )
        )
    return lines or ["- 候補なし"]


def _build_llm_race_pick_prompt(
    *,
    race_label: str,
    weather: str,
    track_condition: str,
    distance: Any,
    top_candidates: List[str],
    longshot_candidates: List[str],
    danger_candidates: List[str],
) -> str:
    distance_num = pd.to_numeric(pd.Series([distance]), errors="coerce").iloc[0]
    distance_text = "-" if pd.isna(distance_num) else f"{int(float(distance_num))}m"
    return (
        "あなたは競馬予想の補助AIです。候補一覧だけを見て、各ラベルに1頭ずつ選んでください。\n"
        "ルール:\n"
        "- 出力はちょうど4行\n"
        "- 各行は 本命:, 大穴:, 危険人気:, 理由: で開始\n"
        "- 馬名は候補一覧にあるものだけ\n"
        "- 危険人気 は人気先行で危うい馬を1頭\n\n"
        f"レース: {race_label}\n"
        f"天気: {weather}\n"
        f"馬場: {track_condition}\n"
        f"距離: {distance_text}\n\n"
        "本命候補:\n"
        f"{chr(10).join(top_candidates)}\n\n"
        "大穴候補:\n"
        f"{chr(10).join(longshot_candidates)}\n\n"
        "危険人気候補:\n"
        f"{chr(10).join(danger_candidates)}\n"
    )


def _run_local_llm_text(*, base_url: str, model: str, timeout_sec: int, prompt: str, temperature: float = 0.2) -> str:
    payload = {
        "model": _to_text(model) or LOCAL_LLM_MODEL_DEFAULT,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": float(temperature)},
    }
    req = urllib.request.Request(
        f"{_normalize_local_llm_base_url(base_url)}/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    text = _to_text(body.get("response", "")) if isinstance(body, dict) else ""
    if not text:
        raise ValueError("ローカルLLMの応答が空です")
    return text


def _extract_pick_from_labeled_text(text: str, label: str, allowed_names: Iterable[str]) -> str:
    allowed = [_to_text(name) for name in allowed_names if _to_text(name)]
    for line in text.splitlines():
        normalized = _to_text(line)
        if not normalized.startswith(label):
            continue
        value = normalized.split(":", 1)[1].strip() if ":" in normalized else ""
        for name in allowed:
            if name and name in value:
                return name
    return ""


def _generate_llm_race_picks(
    *,
    race_label: str,
    weather: str,
    track_condition: str,
    distance: Any,
    ranked_candidates: pd.DataFrame,
    base_url: str,
    model: str,
    timeout_sec: int,
) -> Dict[str, str]:
    if ranked_candidates.empty:
        return {
            "llm_top_horse": "-",
            "llm_dark_horse": "-",
            "llm_danger_favorite": "-",
            "llm_pick_source": "fallback",
            "llm_pick_reason": "候補不足",
        }
    top_candidates_df = ranked_candidates.sort_values(["pred_rank", "win_prob"], ascending=[True, False]).head(3).copy()
    longshot_df = ranked_candidates[pd.to_numeric(ranked_candidates["pop_rank"], errors="coerce") >= 6].copy()
    if longshot_df.empty:
        longshot_df = ranked_candidates[ranked_candidates["pred_rank"] >= 3].copy()
    if longshot_df.empty:
        longshot_df = ranked_candidates.copy()
    danger_df = ranked_candidates.sort_values(["pop_rank", "odds", "pred_rank"], ascending=[True, True, True], na_position="last").head(3).copy()
    prompt = _build_llm_race_pick_prompt(
        race_label=race_label,
        weather=weather,
        track_condition=track_condition,
        distance=distance,
        top_candidates=_candidate_lines(top_candidates_df),
        longshot_candidates=_candidate_lines(longshot_df),
        danger_candidates=_candidate_lines(danger_df),
    )
    text = _run_local_llm_text(
        base_url=base_url,
        model=model,
        timeout_sec=timeout_sec,
        prompt=prompt,
        temperature=0.18,
    )
    top_allowed = top_candidates_df["horse"].tolist()
    long_allowed = longshot_df["horse"].tolist()
    danger_allowed = danger_df["horse"].tolist()
    llm_top = _extract_pick_from_labeled_text(text, "本命", top_allowed) or _to_text(top_candidates_df.iloc[0].get("horse", "-")) or "-"
    llm_dark = _extract_pick_from_labeled_text(text, "大穴", long_allowed) or _to_text(longshot_df.iloc[0].get("horse", "-")) or "-"
    llm_danger = _extract_pick_from_labeled_text(text, "危険人気", danger_allowed) or _to_text(danger_df.iloc[0].get("horse", "-")) or "-"
    reason = ""
    for line in text.splitlines():
        normalized = _to_text(line)
        if normalized.startswith("理由"):
            reason = normalized.split(":", 1)[1].strip() if ":" in normalized else ""
            break
    return {
        "llm_top_horse": llm_top,
        "llm_dark_horse": llm_dark,
        "llm_danger_favorite": llm_danger,
        "llm_pick_source": "llm",
        "llm_pick_reason": reason or "ローカルLLMの候補選別",
    }


def _sync_prediction_feature_archive(data_dir: Path, frame: pd.DataFrame) -> pd.DataFrame:
    feature_path = data_dir / PREDICTION_FEATURE_ARCHIVE_FILENAME
    existing = _read_csv_if_exists(feature_path)
    merged = upsert_prediction_feature_archive(existing, frame)
    if not merged.empty:
        _write_csv(feature_path, merged)
    return merged


def _build_prediction_archive_rows(rows: List[Dict[str, Any]], *, budget_basis_key: str, budget_basis_label: str, budget_basis_mode: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["budget_basis_key"] = budget_basis_key
    frame["budget_basis_label"] = budget_basis_label
    frame["budget_basis_mode"] = budget_basis_mode
    frame["predicted_at"] = datetime.now().isoformat(timespec="seconds")
    return frame


def _load_budget_basis_snapshot(data_dir: Path) -> tuple[str, str, str]:
    state = _read_json(data_dir / AUTO_IMPROVE_STATE_FILENAME)
    auto_enabled = bool(state.get("budget_basis_auto_enabled", True))
    if auto_enabled:
        basis_key = _to_text(state.get("last_auto_budget_basis", "")) or "trend"
        return basis_key, {
            "trend": "今週傾向反映",
            "analog": "類似個体補正",
            "base": "ベース配分",
        }.get(basis_key, "今週傾向反映"), "auto"
    basis_key = _to_text(state.get("last_manual_budget_basis", "")) or "base"
    return basis_key, {
        "trend": "今週傾向反映",
        "analog": "類似個体補正",
        "base": "ベース配分",
    }.get(basis_key, "ベース配分"), "manual"


def generate_weekly_predictions(
    data_dir: Path,
    *,
    simulations_per_race: int = 2500,
    seed: int = 42,
    llm_enabled: bool = False,
    llm_base_url: str = LOCAL_LLM_BASE_URL_DEFAULT,
    llm_model: str = LOCAL_LLM_MODEL_DEFAULT,
    llm_timeout_sec: int = 10,
    max_llm_races: int = AUTO_AGENT_MAX_LLM_RACES_DEFAULT,
) -> Dict[str, Any]:
    history_path = data_dir / AUTO_HISTORY_FILENAME
    entries_path = data_dir / AUTO_ENTRIES_FILENAME
    output_path = data_dir / WEEKLY_PREDICTIONS_FILENAME
    archive_path = data_dir / PREDICTION_ARCHIVE_FILENAME
    history_df = _read_csv_if_exists(history_path)
    entries_df = _read_csv_if_exists(entries_path)
    if history_df.empty:
        return {"ok": False, "message": f"履歴データがありません: {history_path}", "rows": 0}
    if entries_df.empty:
        return {"ok": False, "message": f"今週出走データがありません: {entries_path}", "rows": 0}

    model_payload = read_weights_json(data_dir / AUTO_WEIGHTS_FILENAME)
    feature_weights = _extract_feature_weights_from_payload(model_payload)
    condition_adjustments = _extract_condition_adjustments_from_payload(model_payload)

    feature_frames: List[pd.DataFrame] = []
    rows: List[Dict[str, Any]] = []
    llm_failure_reason = ""
    llm_processed = 0
    for index, (race_id, race_entries) in enumerate(entries_df.groupby("race_id", sort=True)):
        race_entries = race_entries.copy()
        if len(race_entries) < 2:
            continue
        weather_value = _first_text_from_frame(race_entries, "weather", "晴") or "晴"
        track_value = _first_text_from_frame(race_entries, "track_condition", "良") or "良"
        distance_series = pd.to_numeric(race_entries.get("distance", pd.Series([1600])), errors="coerce").dropna()
        distance_value = float(distance_series.iloc[0]) if not distance_series.empty else 1600.0
        venue_value = _first_text_from_frame(race_entries, "venue", "-") or "-"
        race_name_value = _first_text_from_frame(race_entries, "race_name", "-") or "-"
        race_date_value = _first_text_from_frame(race_entries, "race_date", "")
        race_grade_value = _infer_race_grade(race_name_value)

        result = predict_race(
            history_df=history_df,
            entries_df=race_entries,
            weather=weather_value,
            track_condition=track_value,
            distance=distance_value,
            simulations=max(500, int(simulations_per_race)),
            seed=int(seed) + index,
            budget=0.0,
            bet_units=100,
            feature_weights=feature_weights,
            condition_adjustments=condition_adjustments,
            venue=venue_value,
            race_grade=race_grade_value,
        )
        if result.horse_predictions.empty:
            continue

        ranked_candidates = _build_ranked_candidates(result, race_entries)
        feature_frames.append(
            _build_prediction_feature_rows(
                result,
                race_id=race_id,
                race_date=race_date_value,
                race_name=race_name_value,
                race_grade=race_grade_value,
                venue=venue_value,
                weather=weather_value,
                track_condition=track_value,
                distance=distance_value,
                field_size=len(race_entries),
            )
        )
        top = result.horse_predictions.iloc[0]
        top_horse = _to_text(top.get("馬", "-")) or "-"
        top_pop_rank, top_odds = _popularity_rank_for_horse(race_entries, top_horse)
        dark_horse, dark_pop = _choose_dark_horse(result.horse_predictions, race_entries, top_horse)
        danger_horse, danger_pop = _choose_danger_favorite(result.horse_predictions, race_entries, top_horse)
        llm_pick_payload = {
            "llm_top_horse": top_horse,
            "llm_dark_horse": dark_horse,
            "llm_danger_favorite": danger_horse,
            "llm_pick_source": "fallback",
            "llm_pick_reason": "データ予想を使用",
        }
        if llm_enabled and llm_processed < max(0, int(max_llm_races)):
            try:
                llm_pick_payload = _generate_llm_race_picks(
                    race_label=" / ".join(item for item in [race_date_value, venue_value, race_name_value or _to_text(race_id)] if _to_text(item)),
                    weather=weather_value,
                    track_condition=track_value,
                    distance=distance_value,
                    ranked_candidates=ranked_candidates,
                    base_url=llm_base_url,
                    model=llm_model,
                    timeout_sec=max(3, int(llm_timeout_sec)),
                )
                llm_processed += 1
            except Exception as exc:
                llm_failure_reason = str(exc)
                llm_enabled = False
        rows.append(
            {
                "race_id": _to_text(race_id),
                "race_date": race_date_value,
                "race_name": race_name_value,
                "race_grade": race_grade_value,
                "venue": venue_value,
                "weather": weather_value,
                "track_condition": track_value,
                "distance": distance_value,
                "field_size": int(len(race_entries)),
                "top_horse": top_horse,
                "top_jockey": _to_text(top.get("騎手", "-")) or "-",
                "top_pop_rank": top_pop_rank if top_pop_rank is not None else "",
                "top_horse_odds": top_odds if top_odds is not None else "",
                "dark_horse": dark_horse,
                "dark_horse_pop": dark_pop,
                "danger_favorite": danger_horse,
                "danger_favorite_pop": danger_pop,
                "spiritual_horse": "-",
                "llm_top_horse": llm_pick_payload.get("llm_top_horse", "-"),
                "llm_dark_horse": llm_pick_payload.get("llm_dark_horse", "-"),
                "llm_danger_favorite": llm_pick_payload.get("llm_danger_favorite", "-"),
                "llm_pick_source": llm_pick_payload.get("llm_pick_source", "fallback"),
                "llm_pick_reason": llm_pick_payload.get("llm_pick_reason", "-"),
                "condition_adjustment_count": int(len(_extract_condition_adjustment_labels(result))),
                "condition_adjustments": _format_condition_adjustment_summary(_extract_condition_adjustment_labels(result)),
                "win_prob": float(pd.to_numeric(pd.Series([top.get("勝率")]), errors="coerce").iloc[0] or 0.0),
                "place_prob": float(pd.to_numeric(pd.Series([top.get("複勝率")]), errors="coerce").iloc[0] or 0.0),
                "single_pick": _pick_from_table(result.bet_recommendations.get("単勝", pd.DataFrame()), "馬"),
                "place_pick": _pick_from_table(result.bet_recommendations.get("複勝", pd.DataFrame()), "馬"),
                "quinella_pick": _pick_from_table(result.bet_recommendations.get("馬連", pd.DataFrame()), "組み合わせ"),
                "wide_pick": _pick_from_table(result.bet_recommendations.get("ワイド", pd.DataFrame()), "組み合わせ"),
                "exacta_pick": _pick_from_table(result.bet_recommendations.get("馬単", pd.DataFrame()), "組み合わせ"),
                "trio_pick": _pick_from_table(result.bet_recommendations.get("三連複", pd.DataFrame()), "組み合わせ"),
                "trifecta_pick": _pick_from_table(result.bet_recommendations.get("三連単", pd.DataFrame()), "組み合わせ"),
            }
        )

    weekly_df = pd.DataFrame(rows).sort_values("race_id").reset_index(drop=True) if rows else pd.DataFrame()
    if not weekly_df.empty:
        _write_csv(output_path, weekly_df)
        if feature_frames:
            _sync_prediction_feature_archive(data_dir, pd.concat(feature_frames, ignore_index=True))
        budget_basis_key, budget_basis_label, budget_basis_mode = _load_budget_basis_snapshot(data_dir)
        fresh_archive = _build_prediction_archive_rows(
            rows,
            budget_basis_key=budget_basis_key,
            budget_basis_label=budget_basis_label,
            budget_basis_mode=budget_basis_mode,
        )
        merged_archive = upsert_prediction_archive(_read_csv_if_exists(archive_path), fresh_archive)
        if not merged_archive.empty:
            _write_csv(archive_path, merged_archive)
    message = f"今週AI予想 {len(weekly_df):,}レース更新" if not weekly_df.empty else "今週AI予想の対象レースなし"
    if llm_processed > 0:
        message += f" / LLM列 {llm_processed}レース更新"
    elif llm_failure_reason:
        message += f" / LLM列はスキップ ({llm_failure_reason})"
    return {
        "ok": True,
        "message": message,
        "rows": int(len(weekly_df)),
        "output_path": str(output_path),
        "llm_rows": int(llm_processed),
    }


def _feedback_row_key(row: pd.Series) -> str:
    return f"{_to_text(row.get('race_id', ''))}::{_to_text(row.get('predicted_at', ''))}"


def _load_auto_improve_state(data_dir: Path) -> Dict[str, Any]:
    payload = _read_json(data_dir / AUTO_IMPROVE_STATE_FILENAME)
    payload["memory_synced_keys"] = _trim_text_list(list(payload.get("memory_synced_keys", [])))
    return payload


def _save_auto_improve_state(data_dir: Path, payload: Dict[str, Any]) -> None:
    out = dict(payload) if isinstance(payload, dict) else {}
    out["memory_synced_keys"] = _trim_text_list(list(out.get("memory_synced_keys", [])))
    out["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(data_dir / AUTO_IMPROVE_STATE_FILENAME, out)


def _build_feedback_memory_payload(row: pd.Series) -> Dict[str, Any]:
    top_hit = bool(row.get("top_horse_hit"))
    llm_disagreement = bool(row.get("llm_disagreement"))
    llm_top_hit = bool(row.get("llm_top_hit"))
    llm_top_horse = _to_text(row.get("llm_top_horse", ""))
    llm_reason = _to_text(row.get("llm_disagreement_reason", ""))
    miss_tags: List[str] = []
    if not top_hit:
        pop_rank = pd.to_numeric(pd.Series([row.get("top_pop_rank")]), errors="coerce").iloc[0]
        if pd.notna(pop_rank) and int(float(pop_rank)) <= 3:
            miss_tags.append("人気ズレ")
        if int(float(pd.to_numeric(pd.Series([row.get("condition_adjustment_count")]), errors="coerce").fillna(0).iloc[0])) <= 0:
            miss_tags.append("補正不足")
        if "重" in _to_text(row.get("track_condition", "")) or "不良" in _to_text(row.get("track_condition", "")):
            miss_tags.append("馬場注意")
    status_label = "LLM別軸ヒット" if llm_disagreement and llm_top_hit else ("本命ヒット" if top_hit else "本命外れ")
    summary_text = (
        f"{status_label} / "
        f"本命={_to_text(row.get('top_horse', '-'))} / "
        + (f"LLM本命={llm_top_horse} / " if llm_top_horse else "")
        + f"勝ち馬={_to_text(row.get('actual_winner', '-'))}"
        + (f" / LLM要因={llm_reason}" if llm_reason else "")
    )
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "race_id": _to_text(row.get("race_id", "")),
        "race_label": " / ".join(
            item for item in [
                _to_text(row.get("race_date", "")),
                _to_text(row.get("venue", "")),
                _to_text(row.get("race_name", "")),
            ] if item
        ),
        "summary": summary_text,
        "miss_tags": "/".join(miss_tags) if miss_tags else (status_label if status_label != "本命外れ" else "外れ"),
        "preferred_bets": _to_text(row.get("budget_basis_label", "")),
        "avoid_bets": _to_text(row.get("condition_adjustments", "")),
    }


def sync_feedback_memory(data_dir: Path) -> Dict[str, Any]:
    feedback_df = _read_csv_if_exists(data_dir / PREDICTION_FEEDBACK_FILENAME)
    if feedback_df.empty or "result_available" not in feedback_df.columns:
        return {"ok": True, "message": "結果フィードバックなし", "rows_added": 0}
    result_mask = feedback_df["result_available"].map(lambda value: str(value).strip().lower() in {"true", "1", "yes", "on"})
    work = feedback_df[result_mask].copy()
    if work.empty:
        return {"ok": True, "message": "結果確定データなし", "rows_added": 0}
    work["feedback_key"] = work.apply(_feedback_row_key, axis=1)
    state = _load_auto_improve_state(data_dir)
    synced_keys = set(_trim_text_list(list(state.get("memory_synced_keys", []))))
    new_rows = work[~work["feedback_key"].isin(synced_keys)].copy()
    if new_rows.empty:
        return {"ok": True, "message": "LLMメモ追記なし", "rows_added": 0}
    memory_path = data_dir / LOCAL_LLM_MEMORY_FILENAME
    added = 0
    for _, row in new_rows.iterrows():
        _append_jsonl(memory_path, _build_feedback_memory_payload(row))
        synced_keys.add(_to_text(row.get("feedback_key", "")))
        added += 1
    state["memory_synced_keys"] = list(synced_keys)
    state["last_memory_sync_at"] = datetime.now().isoformat(timespec="seconds")
    state["last_memory_sync_count"] = int(added)
    _save_auto_improve_state(data_dir, state)
    return {"ok": True, "message": f"LLM学習メモ {added}件追記", "rows_added": int(added)}


def _format_rate(value: Any) -> str:
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "-" if pd.isna(num) else f"{float(num):.1%}"


def _format_roi(value: Any) -> str:
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "-" if pd.isna(num) else f"{float(num):.0%}"


def _build_recent_feedback_lines(feedback_df: pd.DataFrame, limit: int = 5) -> str:
    if feedback_df.empty:
        return "- 直近結果なし"
    work = feedback_df.copy()
    for col in ["race_date", "predicted_at"]:
        if col in work.columns:
            work[col] = work[col].map(_to_text)
    sort_cols = [col for col in ["race_date", "predicted_at", "race_id"] if col in work.columns]
    if sort_cols:
        work = work.sort_values(sort_cols, ascending=[False] * len(sort_cols))
    lines: List[str] = []
    for _, row in work.head(max(1, int(limit))).iterrows():
        lines.append(
            " / ".join(
                [
                    f"レース={_to_text(row.get('race_name', '-')) or _to_text(row.get('race_id', '-'))}",
                    f"本命={_to_text(row.get('top_horse', '-'))}",
                    f"勝ち馬={_to_text(row.get('actual_winner', '-'))}",
                    f"本命結果={'的中' if str(row.get('top_horse_hit', '')).lower() in {'true', '1'} else '外れ'}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- 直近結果なし"


def _build_weekly_prediction_lines(weekly_df: pd.DataFrame, limit: int = 6) -> str:
    if weekly_df.empty:
        return "- 今週予想なし"
    lines: List[str] = []
    for _, row in weekly_df.head(max(1, int(limit))).iterrows():
        distance = pd.to_numeric(pd.Series([row.get("distance")]), errors="coerce").iloc[0]
        distance_text = "-" if pd.isna(distance) else f"{int(float(distance))}m"
        lines.append(
            " / ".join(
                [
                    f"レース={_to_text(row.get('race_name', '-')) or _to_text(row.get('race_id', '-'))}",
                    f"開催={_to_text(row.get('venue', '-'))}",
                    f"距離={distance_text}",
                    f"本命={_to_text(row.get('top_horse', '-'))}",
                    f"大穴={_to_text(row.get('dark_horse', '-'))}",
                    f"単勝={_to_text(row.get('single_pick', '-'))}",
                    f"三連単={_to_text(row.get('trifecta_pick', '-'))}",
                ]
            )
        )
    return "\n".join(lines)


def _build_weekly_disagreement_lines(weekly_df: pd.DataFrame, limit: int = 5) -> str:
    if weekly_df.empty:
        return "- 別軸レースなし"
    work = weekly_df.copy()
    if "top_horse" not in work.columns or "llm_top_horse" not in work.columns:
        return "- 別軸レースなし"
    work["top_horse"] = work["top_horse"].map(_to_text)
    work["llm_top_horse"] = work["llm_top_horse"].map(_to_text)
    work = work[
        (work["top_horse"] != "")
        & (work["llm_top_horse"] != "")
        & (work["top_horse"] != "-")
        & (work["llm_top_horse"] != "-")
        & (work["top_horse"] != work["llm_top_horse"])
    ].copy()
    if work.empty:
        return "- 別軸レースなし"
    lines: List[str] = []
    for _, row in work.head(max(1, int(limit))).iterrows():
        distance = pd.to_numeric(pd.Series([row.get("distance")]), errors="coerce").iloc[0]
        distance_text = "-" if pd.isna(distance) else f"{int(float(distance))}m"
        lines.append(
            " / ".join(
                [
                    f"レース={_to_text(row.get('race_name', '-')) or _to_text(row.get('race_id', '-'))}",
                    f"開催={_to_text(row.get('venue', '-'))}",
                    f"距離={distance_text}",
                    f"データ本命={_to_text(row.get('top_horse', '-'))}",
                    f"LLM本命={_to_text(row.get('llm_top_horse', '-'))}",
                    f"LLM穴={_to_text(row.get('llm_dark_horse', '-'))}",
                    f"LLM危険={_to_text(row.get('llm_danger_favorite', '-'))}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- 別軸レースなし"


def _build_disagreement_hit_lines(feedback_df: pd.DataFrame, limit: int = 5) -> str:
    if feedback_df.empty:
        return "- 別軸ヒットなし"
    work = feedback_df.copy()
    if "result_available" in work.columns:
        if work["result_available"].dtype == bool:
            work = work[work["result_available"]].copy()
        else:
            work = work[work["result_available"].map(lambda value: _to_text(value).lower() in {"true", "1"})].copy()
    if "llm_disagreement" in work.columns:
        if work["llm_disagreement"].dtype == bool:
            work = work[work["llm_disagreement"]].copy()
        else:
            work = work[work["llm_disagreement"].map(lambda value: _to_text(value).lower() in {"true", "1"})].copy()
    if "llm_top_hit" in work.columns:
        if work["llm_top_hit"].dtype == bool:
            work = work[work["llm_top_hit"]].copy()
        else:
            work = work[work["llm_top_hit"].map(lambda value: _to_text(value).lower() in {"true", "1"})].copy()
    if work.empty:
        return "- 別軸ヒットなし"
    sort_cols = [col for col in ["race_date", "predicted_at", "race_id"] if col in work.columns]
    if sort_cols:
        work = work.sort_values(sort_cols, ascending=[False] * len(sort_cols))
    lines: List[str] = []
    for _, row in work.head(max(1, int(limit))).iterrows():
        lines.append(
            " / ".join(
                [
                    f"レース={_to_text(row.get('race_name', '-')) or _to_text(row.get('race_id', '-'))}",
                    f"開催={_to_text(row.get('venue', '-'))}",
                    f"データ本命={_to_text(row.get('top_horse', '-'))}",
                    f"LLM本命={_to_text(row.get('llm_top_horse', '-'))}",
                    f"勝ち馬={_to_text(row.get('actual_winner', '-'))}",
                    f"理由={_to_text(row.get('llm_disagreement_reason', '-'))}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- 別軸ヒットなし"


def _run_local_llm_review(*, base_url: str, model: str, timeout_sec: int, prompt: str) -> str:
    payload = {
        "model": _to_text(model) or LOCAL_LLM_MODEL_DEFAULT,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.25},
    }
    req = urllib.request.Request(
        f"{_normalize_local_llm_base_url(base_url)}/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    text = _to_text(body.get("response", "")) if isinstance(body, dict) else ""
    if not text:
        raise ValueError("ローカルLLMの応答が空です")
    return text


def build_autonomous_review_prompt(
    *,
    cycle_summary: str,
    feedback_summary: Dict[str, Any],
    recent_feedback_text: str,
    weekly_predictions_text: str,
    weekly_disagreement_text: str,
    disagreement_hit_text: str,
) -> str:
    return (
        "あなたは競馬予想アプリの自律改善エージェントです。以下のログだけを根拠に、短い運用メモを日本語で作成してください。\n"
        "出力ルール:\n"
        "- ちょうど7行\n"
        "- 各行は 必ず 現況:, 反省:, 今週本線:, 次アクション:, 注意:, 標準配分:, 券種方針: で開始\n"
        "- 断定しすぎない\n"
        "- データにない情報を作らない\n\n"
        f"今回の更新サマリ:\n{cycle_summary}\n\n"
        "結果集計:\n"
        f"- 保存予想数={int(feedback_summary.get('stored_predictions', 0))}\n"
        f"- 評価済み={int(feedback_summary.get('evaluated_races', 0))}\n"
        f"- 結果待ち={int(feedback_summary.get('pending_races', 0))}\n"
        f"- 本命勝率={_format_rate(feedback_summary.get('top_horse_hit_rate'))}\n"
        f"- 単勝回収率={_format_roi(feedback_summary.get('single_roi'))}\n"
        f"- 複勝回収率={_format_roi(feedback_summary.get('place_roi'))}\n\n"
        f"直近の結果:\n{recent_feedback_text}\n\n"
        f"今週の予想:\n{weekly_predictions_text}\n"
        f"\nLLM別軸レース:\n{weekly_disagreement_text}\n"
        f"\nLLM別軸ヒット:\n{disagreement_hit_text}\n"
    )


def _extract_labeled_line(text: str, label: str) -> str:
    for line in text.splitlines():
        normalized = _to_text(line)
        if normalized.startswith(label):
            return normalized.split(":", 1)[1].strip() if ":" in normalized else ""
    return ""


def _extract_bets_from_text(text: str) -> Tuple[List[str], List[str]]:
    recommended: List[str] = []
    avoid: List[str] = []
    bet_types = ["単勝", "複勝", "馬連", "ワイド", "馬単", "三連複", "三連単"]
    for bet in bet_types:
        if bet in text and bet not in recommended:
            recommended.append(bet)
    for bet in bet_types:
        if any(token in text for token in [f"避け {bet}", f"抑え {bet}", f"回避 {bet}", f"{bet}は抑え"]):
            avoid.append(bet)
    return recommended[:3], avoid[:3]


def run_autonomous_llm_review(
    data_dir: Path,
    *,
    cycle_summary: str,
    base_url: str = LOCAL_LLM_BASE_URL_DEFAULT,
    model: str = LOCAL_LLM_MODEL_DEFAULT,
    timeout_sec: int = 12,
) -> Dict[str, Any]:
    feedback_df = _read_csv_if_exists(data_dir / PREDICTION_FEEDBACK_FILENAME)
    weekly_df = _read_csv_if_exists(data_dir / WEEKLY_PREDICTIONS_FILENAME)
    feedback_summary = aggregate_prediction_feedback(feedback_df)
    prompt = build_autonomous_review_prompt(
        cycle_summary=cycle_summary,
        feedback_summary=feedback_summary,
        recent_feedback_text=_build_recent_feedback_lines(feedback_df),
        weekly_predictions_text=_build_weekly_prediction_lines(weekly_df),
        weekly_disagreement_text=_build_weekly_disagreement_lines(weekly_df),
        disagreement_hit_text=_build_disagreement_hit_lines(feedback_df),
    )
    report: Dict[str, Any] = {
        "ok": False,
        "message": "",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "prompt_excerpt": prompt[:800],
        "budget_basis_key": "",
        "budget_basis_label": "",
        "recommended_bets": [],
        "avoid_bets": [],
    }
    try:
        text = _run_local_llm_review(
            base_url=base_url,
            model=model,
            timeout_sec=max(3, int(timeout_sec)),
            prompt=prompt,
        )
    except urllib.error.URLError as exc:
        report["message"] = f"LLM未接続: {exc}"
        return report
    except (TimeoutError, socket.timeout) as exc:
        report["ok"] = True
        report["skipped"] = True
        report["skip_reason"] = "timeout"
        report["detail"] = str(exc)
        report["message"] = "LLMレビューは時間内に完了しなかったためスキップ"
        return report
    except Exception as exc:
        report["message"] = f"LLM生成失敗: {exc}"
        return report

    report["ok"] = True
    report["message"] = "LLM自律レビューを更新"
    report["text"] = text
    basis_text = _extract_labeled_line(text, "標準配分")
    basis_key = _normalize_budget_basis_key(basis_text)
    report["budget_basis_key"] = basis_key
    report["budget_basis_label"] = _format_budget_basis_label(basis_key) if basis_key else ""
    recommended_bets, avoid_bets = _extract_bets_from_text(_extract_labeled_line(text, "券種方針"))
    report["recommended_bets"] = recommended_bets
    report["avoid_bets"] = avoid_bets
    report_path = data_dir / AUTO_AGENT_REPORT_FILENAME
    report_md_path = data_dir / AUTO_AGENT_REPORT_MD_FILENAME
    _write_json(report_path, report)
    report_md_path.write_text(text + "\n", encoding="utf-8")
    return report


def _parse_prediction_race_day(race_date: Any, race_id: Any) -> datetime.date | None:
    candidates: List[str] = []
    text = _to_text(race_date)
    if text:
        candidates.append(text)
    race_id_digits = "".join(ch for ch in _to_text(race_id) if ch.isdigit())
    if len(race_id_digits) >= 8:
        candidates.append(race_id_digits[:8])
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


def _truthy_cell(value: Any) -> bool:
    return _to_text(value).lower() in {"true", "1", "yes", "on"}


def _blankish_cell(value: Any, *, zero_is_blank: bool = False, undecided_is_blank: bool = False) -> bool:
    text = _to_text(value)
    blank_values = {"", "-", "nan", "none"}
    if zero_is_blank:
        blank_values.update({"0", "0.0"})
    if undecided_is_blank:
        blank_values.add("未判定")
    return text.lower() in blank_values


def _count_blankish(frame: pd.DataFrame, column: str, *, zero_is_blank: bool = False, undecided_is_blank: bool = False) -> int:
    if frame.empty:
        return 0
    if column not in frame.columns:
        return int(len(frame))
    return int(
        frame[column]
        .map(lambda value: _blankish_cell(value, zero_is_blank=zero_is_blank, undecided_is_blank=undecided_is_blank))
        .sum()
    )


def _split_ticket_parts(value: Any) -> List[str]:
    text = _to_text(value)
    if not text or text == "-":
        return []
    return [
        part
        for part in re.split(r"[-ー－–—/／,、\s]+", text)
        if _to_text(part) and _to_text(part) != "-"
    ]


def _invalid_ticket_count(frame: pd.DataFrame, column: str, min_parts: int) -> int:
    if frame.empty:
        return 0
    if column not in frame.columns:
        return int(len(frame))
    return int(frame[column].map(lambda value: len(_split_ticket_parts(value)) < int(min_parts)).sum())


def _prediction_date_scope(frame: pd.DataFrame) -> Dict[str, Any]:
    if frame.empty:
        return {"unique_days": 0, "today_races": 0, "past_races": 0, "future_races": 0, "date_span_days": 0}
    today = datetime.now().date()
    days = frame.apply(lambda row: _parse_prediction_race_day(row.get("race_date", ""), row.get("race_id", "")), axis=1)
    valid_days = [day for day in days.tolist() if day is not None]
    if not valid_days:
        return {"unique_days": 0, "today_races": 0, "past_races": 0, "future_races": 0, "date_span_days": 0}
    return {
        "unique_days": int(len(set(valid_days))),
        "first_date": min(valid_days).isoformat(),
        "last_date": max(valid_days).isoformat(),
        "today_races": int(sum(1 for day in valid_days if day == today)),
        "past_races": int(sum(1 for day in valid_days if day < today)),
        "future_races": int(sum(1 for day in valid_days if day > today)),
        "date_span_days": int((max(valid_days) - min(valid_days)).days + 1),
    }


def _pending_due_feedback_count(frame: pd.DataFrame) -> int:
    work = _pending_due_feedback_frame(frame)
    if work.empty or "race_id" not in work.columns:
        return 0
    return int(work["race_id"].map(_to_text).replace("", np.nan).dropna().nunique())


def _pending_due_feedback_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "race_id" not in frame.columns:
        return pd.DataFrame()
    today = datetime.now().date()
    work = frame.copy()
    if "result_available" in work.columns:
        work = work[~work["result_available"].map(_truthy_cell)].copy()
    work["_race_day"] = work.apply(lambda row: _parse_prediction_race_day(row.get("race_date", ""), row.get("race_id", "")), axis=1)
    due_mask = work["_race_day"].map(lambda day: bool(day is not None and day <= today)).fillna(False).astype(bool)
    work = work.loc[due_mask].copy()
    return work.reset_index(drop=True)


def _add_contract_issue(
    issues: List[Dict[str, Any]],
    *,
    level: str,
    check: str,
    message: str,
    count: int = 0,
    action: str = "",
) -> None:
    issues.append(
        {
            "level": _to_text(level) or "warn",
            "check": _to_text(check),
            "message": _to_text(message),
            "count": int(count),
            "action": _to_text(action),
        }
    )


def _build_free_harness_planner(
    *,
    weekly_rows: int,
    entries_races: int,
    contract_failed: int,
    contract_warned: int,
    pending_due: int,
    feedback_summary: Dict[str, Any],
    popularity_missing: int,
    odds_missing: int,
) -> Dict[str, Any]:
    evaluated = int(feedback_summary.get("evaluated_races", 0) or 0)
    top_hit_rate = float(feedback_summary.get("top_horse_hit_rate", 0.0) or 0.0)
    if entries_races <= 0:
        return {
            "next_action": "最新だけ更新",
            "reason": "出走表が空です。まず無料の自動取得で今週データを作る段階です。",
            "severity": "error",
            "skip_actions": ["反省再学習だけ", "学習だけ実行", "予想を見る"],
        }
    if weekly_rows <= 0:
        return {
            "next_action": "今週AI予想だけ更新",
            "reason": "出走表はありますが、予想CSVが空です。先に予想を生成します。",
            "severity": "error",
            "skip_actions": ["反省再学習だけ", "学習だけ実行", "結果取得→履歴更新→再学習"],
        }
    if pending_due > 0:
        return {
            "next_action": "結果取得だけ",
            "reason": f"結果確認できるレースが {pending_due:,} 件あります。予想を増やす前に採点して学習材料へ回します。",
            "severity": "warn",
            "skip_actions": ["最新だけ更新", "学習だけ実行"],
        }
    if contract_failed > 0:
        return {
            "next_action": "今週AI予想だけ更新",
            "reason": f"予想票の必須チェックで {contract_failed:,} 件ひっかかっています。まず予想票を作り直します。",
            "severity": "error",
            "skip_actions": ["反省再学習だけ", "学習だけ実行"],
        }
    if popularity_missing >= max(3, int(weekly_rows * 0.4)) or odds_missing >= max(3, int(weekly_rows * 0.4)):
        return {
            "next_action": "最新だけ更新",
            "reason": "人気またはオッズが足りないレースが多いです。出走表だけ高速更新してから予想を見るのが安全です。",
            "severity": "warn",
            "skip_actions": ["反省再学習だけ", "学習だけ実行"],
        }
    if evaluated >= 8 and top_hit_rate < 0.32:
        return {
            "next_action": "反省再学習だけ",
            "reason": f"評価済み {evaluated:,} 件に対して本命勝率が {_format_rate(top_hit_rate)} です。外れ優先で重みを見直す段階です。",
            "severity": "warn",
            "skip_actions": ["最新だけ更新", "結果取得→履歴更新→再学習"],
        }
    if contract_warned > 0:
        return {
            "next_action": "予想を見る",
            "reason": f"必須項目は揃っていますが、注意チェックが {contract_warned:,} 件あります。買う前に人気・オッズを確認します。",
            "severity": "info",
            "skip_actions": ["学習だけ実行", "結果取得→履歴更新→再学習"],
        }
    return {
        "next_action": "予想を見る",
        "reason": "情報取得、予想、採点の流れは大きく崩れていません。今はレース単位で予想票を確認する段階です。",
        "severity": "ok",
        "skip_actions": ["最新だけ更新", "学習だけ実行", "結果取得→履歴更新→再学習"],
    }


def run_free_prediction_harness(data_dir: Path) -> Dict[str, Any]:
    """外部APIなしで、予想生成・採点・次アクションを分離して診断する軽量ハーネス。"""
    data_dir = Path(data_dir)
    weekly_df = _read_csv_if_exists(data_dir / WEEKLY_PREDICTIONS_FILENAME)
    entries_df = _read_csv_if_exists(data_dir / AUTO_ENTRIES_FILENAME)
    feedback_df = _read_csv_if_exists(data_dir / PREDICTION_FEEDBACK_FILENAME)
    history_df = _read_csv_if_exists(data_dir / AUTO_HISTORY_FILENAME)

    weekly_rows = int(len(weekly_df))
    weekly_races = int(weekly_df["race_id"].map(_to_text).nunique()) if not weekly_df.empty and "race_id" in weekly_df.columns else 0
    entries_races = int(entries_df["race_id"].map(_to_text).nunique()) if not entries_df.empty and "race_id" in entries_df.columns else 0
    feedback_summary = aggregate_prediction_feedback(feedback_df)
    pending_due = _pending_due_feedback_count(feedback_df)
    pending_due_df = _pending_due_feedback_frame(feedback_df)
    history_ids = _race_id_set(history_df)
    pending_due_ids = (
        pending_due_df["race_id"].map(_to_text).replace("", np.nan).dropna().drop_duplicates().tolist()
        if not pending_due_df.empty and "race_id" in pending_due_df.columns
        else []
    )
    pending_missing_history_ids = [race_id for race_id in pending_due_ids if race_id not in history_ids]
    pending_due_examples: List[Dict[str, Any]] = []
    if not pending_due_df.empty:
        example_cols = [c for c in ["race_id", "race_date", "venue", "race_name", "top_horse"] if c in pending_due_df.columns]
        examples = pending_due_df.drop_duplicates(subset=["race_id"]).tail(8)
        for _, row in examples.iterrows():
            item = {col: _to_text(row.get(col, "")) for col in example_cols}
            rid = item.get("race_id", "")
            item["history_status"] = "history_auto未反映" if rid and rid not in history_ids else "history_auto確認済み"
            pending_due_examples.append(item)

    issues: List[Dict[str, Any]] = []
    if weekly_df.empty:
        _add_contract_issue(issues, level="error", check="予想CSV", message="今週予想が空です。", action="今週AI予想だけ更新")
    if entries_df.empty:
        _add_contract_issue(issues, level="error", check="出走表CSV", message="出走表が空です。", action="最新だけ更新")

    required_columns = {
        "race_id": "レースID",
        "race_date": "開催日",
        "venue": "開催場所",
        "top_horse": "本命馬",
        "dark_horse": "大穴",
        "single_pick": "単勝",
        "place_pick": "複勝",
        "quinella_pick": "馬連",
        "wide_pick": "ワイド",
        "trio_pick": "三連複",
        "trifecta_pick": "三連単",
    }
    missing_required_total = 0
    for column, label in required_columns.items():
        count = _count_blankish(weekly_df, column)
        missing_required_total += count
        if count:
            _add_contract_issue(
                issues,
                level="error",
                check=label,
                message=f"{label} が未入力の予想が {count:,} 件あります。",
                count=count,
                action="今週AI予想だけ更新",
            )

    soft_required_columns = {
        "race_name": "レース名",
        "top_jockey": "本命騎手",
    }
    for column, label in soft_required_columns.items():
        count = _count_blankish(weekly_df, column)
        missing_required_total += count
        if count:
            _add_contract_issue(
                issues,
                level="warn",
                check=label,
                message=f"{label} が未入力の予想が {count:,} 件あります。予想は表示できますが、買う前に確認してください。",
                count=count,
                action="予想を見る",
            )

    ticket_requirements = {
        "single_pick": ("単勝", 1),
        "place_pick": ("複勝", 1),
        "quinella_pick": ("馬連", 2),
        "wide_pick": ("ワイド", 2),
        "exacta_pick": ("馬単", 2),
        "trio_pick": ("三連複", 3),
        "trifecta_pick": ("三連単", 3),
    }
    invalid_ticket_total = 0
    ticket_status: List[Dict[str, Any]] = []
    for column, (label, min_parts) in ticket_requirements.items():
        count = _invalid_ticket_count(weekly_df, column, min_parts)
        invalid_ticket_total += count
        ticket_status.append({"bet_type": label, "invalid": int(count), "required_parts": int(min_parts)})
        if count:
            _add_contract_issue(
                issues,
                level="error",
                check=f"{label}の買い目",
                message=f"{label} の買い目が不足している予想が {count:,} 件あります。",
                count=count,
                action="今週AI予想だけ更新",
            )

    popularity_missing = _count_blankish(weekly_df, "top_pop_rank", zero_is_blank=True)
    odds_missing = _count_blankish(weekly_df, "top_horse_odds", zero_is_blank=True)
    grade_missing = _count_blankish(weekly_df, "race_grade", undecided_is_blank=True)
    if popularity_missing:
        _add_contract_issue(
            issues,
            level="warn",
            check="人気",
            message=f"本命の人気順位が未取得のレースが {popularity_missing:,} 件あります。",
            count=popularity_missing,
            action="最新だけ更新",
        )
    if odds_missing:
        _add_contract_issue(
            issues,
            level="warn",
            check="単勝オッズ",
            message=f"本命の単勝オッズが未取得のレースが {odds_missing:,} 件あります。",
            count=odds_missing,
            action="最新だけ更新",
        )
    if grade_missing:
        _add_contract_issue(
            issues,
            level="warn",
            check="格付け",
            message=f"G1/G2/G3などの格付けが未判定のレースが {grade_missing:,} 件あります。",
            count=grade_missing,
            action="予想を見る",
        )

    date_scope = _prediction_date_scope(weekly_df)
    if int(date_scope.get("date_span_days", 0) or 0) > 8:
        _add_contract_issue(
            issues,
            level="warn",
            check="表示期間",
            message=(
                f"予想CSVの日付範囲が {date_scope.get('first_date', '-')}〜{date_scope.get('last_date', '-')} "
                f"({int(date_scope.get('date_span_days', 0))}日分) あります。"
            ),
            count=int(date_scope.get("date_span_days", 0) or 0),
            action="今週AI予想だけ更新",
        )

    failed_count = int(sum(1 for issue in issues if issue.get("level") == "error"))
    warned_count = int(sum(1 for issue in issues if issue.get("level") == "warn"))
    planner = _build_free_harness_planner(
        weekly_rows=weekly_rows,
        entries_races=entries_races,
        contract_failed=failed_count,
        contract_warned=warned_count,
        pending_due=pending_due,
        feedback_summary=feedback_summary,
        popularity_missing=popularity_missing,
        odds_missing=odds_missing,
    )
    status = {
        "ok": failed_count == 0,
        "runtime_ok": True,
        "free_local": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generator": {
            "weekly_rows": weekly_rows,
            "weekly_races": weekly_races,
            "entries_rows": int(len(entries_df)),
            "entries_races": entries_races,
            "date_scope": date_scope,
            "popularity_missing": int(popularity_missing),
            "odds_missing": int(odds_missing),
            "grade_missing": int(grade_missing),
        },
        "evaluator": {
            "stored_predictions": int(feedback_summary.get("stored_predictions", 0) or 0),
            "evaluated_races": int(feedback_summary.get("evaluated_races", 0) or 0),
            "pending_races": int(feedback_summary.get("pending_races", 0) or 0),
            "pending_due_races": int(pending_due),
            "pending_due_missing_history_races": int(len(pending_missing_history_ids)),
            "pending_due_examples": pending_due_examples,
            "upcoming_races": int(feedback_summary.get("upcoming_races", 0) or 0),
            "top_horse_hit_rate": float(feedback_summary.get("top_horse_hit_rate", 0.0) or 0.0),
            "single_hit_rate": float(feedback_summary.get("single_hit_rate", 0.0) or 0.0),
            "place_hit_rate": float(feedback_summary.get("place_hit_rate", 0.0) or 0.0),
            "trio_hit_rate": float(feedback_summary.get("trio_hit_rate", 0.0) or 0.0),
            "trifecta_hit_rate": float(feedback_summary.get("trifecta_hit_rate", 0.0) or 0.0),
        },
        "contract": {
            "passed": failed_count == 0,
            "failed_count": failed_count,
            "warned_count": warned_count,
            "missing_required_total": int(missing_required_total),
            "invalid_ticket_total": int(invalid_ticket_total),
            "ticket_status": ticket_status,
            "issues": issues[:20],
        },
        "planner": planner,
        "message": f"無料ローカル診断: 次は `{planner.get('next_action', '-')}` / {planner.get('reason', '')}",
    }
    _write_json(data_dir / FREE_HARNESS_STATUS_FILENAME, status)
    return status


def run_autonomous_agent_cycle(
    data_dir: Path,
    *,
    cycle_summary: str,
    generate_predictions: bool = True,
    sync_memory: bool = True,
    run_llm_review: bool = True,
    run_llm_race_picks: bool = True,
    llm_base_url: str = LOCAL_LLM_BASE_URL_DEFAULT,
    llm_model: str = LOCAL_LLM_MODEL_DEFAULT,
    llm_review_model: str = "",
    llm_timeout_sec: int = 12,
    llm_review_timeout_sec: int | None = None,
    weekly_simulations: int = 1200,
    weekly_seed: int = 42,
    weekly_refresh_minutes: int = WEEKLY_PREDICTION_REFRESH_MINUTES_DEFAULT,
    max_llm_races: int = AUTO_AGENT_MAX_LLM_RACES_DEFAULT,
) -> Dict[str, Any]:
    data_dir = Path(data_dir)
    status_path = data_dir / AUTO_AGENT_STATUS_FILENAME
    status: Dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "generate_predictions": bool(generate_predictions),
        "sync_memory": bool(sync_memory),
        "run_llm_review": bool(run_llm_review),
        "run_llm_race_picks": bool(run_llm_race_picks),
        "llm_model": _to_text(llm_model) or LOCAL_LLM_MODEL_DEFAULT,
        "llm_review_model": _to_text(llm_review_model) or (_to_text(llm_model) or LOCAL_LLM_MODEL_DEFAULT),
        "weekly_refresh_minutes": int(weekly_refresh_minutes),
        "max_llm_races": int(max_llm_races),
        "weekly_predictions": {},
        "memory_sync": {},
        "llm_review": {},
        "basis_recommendation": {},
        "message": "",
    }
    if sync_memory:
        status["memory_sync"] = sync_feedback_memory(data_dir)
    if generate_predictions:
        refresh_reason = _weekly_predictions_refresh_reason(
            data_dir,
            refresh_minutes=max(10, int(weekly_refresh_minutes)),
        )
        if refresh_reason:
            status["weekly_predictions"] = generate_weekly_predictions(
                data_dir,
                simulations_per_race=int(weekly_simulations),
                seed=int(weekly_seed),
                llm_enabled=bool(run_llm_race_picks),
                llm_base_url=llm_base_url,
                llm_model=llm_model,
                llm_timeout_sec=int(llm_timeout_sec),
                max_llm_races=max(0, int(max_llm_races)),
            )
            if isinstance(status["weekly_predictions"], dict):
                status["weekly_predictions"]["refresh_reason"] = refresh_reason
        else:
            existing = _read_csv_if_exists(data_dir / WEEKLY_PREDICTIONS_FILENAME)
            status["weekly_predictions"] = {
                "ok": True,
                "skipped": True,
                "message": f"今週AI予想は最新のため再作成スキップ ({len(existing):,}レース)",
                "rows": int(len(existing)),
                "llm_rows": 0,
            }
    if run_llm_review:
        status["llm_review"] = run_autonomous_llm_review(
            data_dir,
            cycle_summary=cycle_summary,
            base_url=llm_base_url,
            model=_to_text(llm_review_model) or llm_model,
            timeout_sec=int(llm_review_timeout_sec if llm_review_timeout_sec is not None else llm_timeout_sec),
        )
        if isinstance(status["llm_review"], dict):
            basis_key = _normalize_budget_basis_key(status["llm_review"].get("budget_basis_key", ""))
            if basis_key:
                status["basis_recommendation"] = {
                    "budget_basis_key": basis_key,
                    "budget_basis_label": _format_budget_basis_label(basis_key),
                    "recommended_bets": list(status["llm_review"].get("recommended_bets", [])),
                    "avoid_bets": list(status["llm_review"].get("avoid_bets", [])),
                    "reason": _extract_labeled_line(_to_text(status["llm_review"].get("text", "")), "次アクション")
                    or _extract_labeled_line(_to_text(status["llm_review"].get("text", "")), "標準配分"),
                }
    message_parts: List[str] = []
    for key in ("memory_sync", "weekly_predictions", "llm_review"):
        payload = status.get(key, {})
        if isinstance(payload, dict) and _to_text(payload.get("message", "")):
            message_parts.append(_to_text(payload.get("message", "")))
    status["message"] = " / ".join(message_parts)
    status["completed_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(status_path, status)
    return status
