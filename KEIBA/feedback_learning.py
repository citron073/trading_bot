from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Tuple

import numpy as np
import pandas as pd

FEATURE_ARCHIVE_COLUMNS: List[str] = [
    "race_id",
    "race_date",
    "race_name",
    "race_grade",
    "venue",
    "weather",
    "track_condition",
    "distance",
    "field_size",
    "predicted_at",
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

FEATURE_TO_WEIGHT: Dict[str, str] = {
    "horse_win_rate": "horse_win",
    "horse_place_rate": "horse_place",
    "jockey_win_rate": "jockey_win",
    "jockey_place_rate": "jockey_place",
    "trainer_win_rate": "trainer_win",
    "trainer_place_rate": "trainer_place",
    "gate_place_rate": "gate_place",
    "weather_fit": "weather_place",
    "track_fit": "track_place",
    "distance_fit": "distance_fit",
    "form_factor": "form_score",
    "condition_factor": "condition_score",
    "paddock_factor": "paddock_score",
    "weight_diff_factor": "weight_diff_score",
    "odds_shift_factor": "odds_shift_score",
    "market_factor": "market_score",
}

CONDITION_SEGMENT_COLUMNS: List[tuple[str, str]] = [
    ("venue", "venue"),
    ("race_grade", "race_grade"),
    ("weather", "weather"),
    ("track_condition", "track_condition"),
    ("distance_bucket", "distance_bucket"),
    ("field_size_bucket", "field_size_bucket"),
]


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none"} else text


def _normalize_grade(value: Any) -> str:
    text = _to_text(value)
    return text or "未判定"


def _distance_bucket(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    distance = float(numeric)
    if distance <= 1400:
        return "sprint"
    if distance <= 1800:
        return "mile"
    if distance <= 2200:
        return "middle"
    return "long"


def _field_size_bucket(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    field_size = int(float(numeric))
    if field_size <= 10:
        return "small"
    if field_size <= 14:
        return "medium"
    return "large"


def ensure_prediction_feature_columns(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=FEATURE_ARCHIVE_COLUMNS)
    out = frame.copy()
    for column in FEATURE_ARCHIVE_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    return out[FEATURE_ARCHIVE_COLUMNS].copy()


def prepare_prediction_feature_archive(frame: pd.DataFrame | None, *, predicted_at: str | None = None) -> pd.DataFrame:
    out = ensure_prediction_feature_columns(frame)
    if out.empty:
        return out
    out["race_id"] = out["race_id"].map(_to_text)
    out["horse"] = out["horse"].map(_to_text)
    out = out[(out["race_id"] != "") & (out["horse"] != "")].copy()
    stamp = predicted_at or datetime.now().isoformat(timespec="seconds")
    out["predicted_at"] = out["predicted_at"].map(_to_text)
    out.loc[out["predicted_at"] == "", "predicted_at"] = stamp
    return out.reset_index(drop=True)


def upsert_prediction_feature_archive(existing_df: pd.DataFrame | None, fresh_df: pd.DataFrame | None) -> pd.DataFrame:
    existing = prepare_prediction_feature_archive(existing_df)
    fresh = prepare_prediction_feature_archive(fresh_df)
    if fresh.empty:
        return existing
    if existing.empty:
        merged = fresh.copy()
    else:
        existing = existing.copy()
        existing["_key"] = existing[["race_id", "horse"]].astype(str).agg("|".join, axis=1)
        fresh = fresh.copy()
        fresh["_key"] = fresh[["race_id", "horse"]].astype(str).agg("|".join, axis=1)
        keep_existing = existing[~existing["_key"].isin(fresh["_key"])].copy()
        merged = pd.concat([keep_existing.drop(columns=["_key"]), fresh.drop(columns=["_key"])], ignore_index=True)
    if "race_date" in merged.columns:
        merged["_race_date_sort"] = pd.to_datetime(merged["race_date"], errors="coerce")
    else:
        merged["_race_date_sort"] = pd.NaT
    merged = merged.sort_values(["_race_date_sort", "race_id", "predicted_rank"], ascending=[False, False, True], na_position="last")
    merged = merged.drop(columns=["_race_date_sort"], errors="ignore")
    return ensure_prediction_feature_columns(merged).reset_index(drop=True)


def build_feedback_learning_frame(feature_archive_df: pd.DataFrame | None, history_df: pd.DataFrame | None) -> pd.DataFrame:
    features = prepare_prediction_feature_archive(feature_archive_df)
    if features.empty or history_df is None or history_df.empty:
        return pd.DataFrame()
    history = history_df.copy()
    if "race_id" not in history.columns or "horse" not in history.columns or "finish" not in history.columns:
        return pd.DataFrame()
    history["race_id"] = history["race_id"].map(_to_text)
    history["horse"] = history["horse"].map(_to_text)
    history["finish"] = pd.to_numeric(history["finish"], errors="coerce")
    history = history[(history["race_id"] != "") & (history["horse"] != "") & history["finish"].notna()].copy()
    if history.empty:
        return pd.DataFrame()
    merged = features.merge(history[["race_id", "horse", "finish"]], on=["race_id", "horse"], how="inner")
    if merged.empty:
        return merged
    merged["predicted_rank"] = pd.to_numeric(merged["predicted_rank"], errors="coerce")
    merged["win_target"] = (merged["finish"] == 1).astype(float)
    merged["place_target"] = (merged["finish"] <= 3).astype(float)
    if "race_grade" in merged.columns:
        merged["race_grade"] = merged["race_grade"].map(_normalize_grade)
    else:
        merged["race_grade"] = "未判定"
    for col in ["venue", "weather", "track_condition"]:
        if col in merged.columns:
            merged[col] = merged[col].map(_to_text)
        else:
            merged[col] = ""
    if "distance" not in merged.columns:
        merged["distance"] = np.nan
    if "field_size" not in merged.columns:
        merged["field_size"] = np.nan
    merged["distance"] = pd.to_numeric(merged["distance"], errors="coerce")
    merged["field_size"] = pd.to_numeric(merged["field_size"], errors="coerce")
    merged["distance_bucket"] = merged["distance"].map(_distance_bucket)
    merged["field_size_bucket"] = merged["field_size"].map(_field_size_bucket)
    for column in FEATURE_TO_WEIGHT:
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    return merged


def filter_reflection_learning_rows(learning_df: pd.DataFrame | None) -> pd.DataFrame:
    if learning_df is None or learning_df.empty:
        return pd.DataFrame()
    rows = learning_df.copy()
    if "race_id" not in rows.columns or "predicted_rank" not in rows.columns or "win_target" not in rows.columns:
        return pd.DataFrame()
    rows["race_id"] = rows["race_id"].map(_to_text)
    rows["predicted_rank"] = pd.to_numeric(rows["predicted_rank"], errors="coerce")
    rows["win_target"] = pd.to_numeric(rows["win_target"], errors="coerce").fillna(0.0)
    top_rows = rows[rows["predicted_rank"] == 1].copy()
    if top_rows.empty:
        return pd.DataFrame()
    miss_race_ids = top_rows.loc[top_rows["win_target"] < 1.0, "race_id"].tolist()
    miss_race_ids = [race_id for race_id in miss_race_ids if race_id]
    if not miss_race_ids:
        return pd.DataFrame()
    out = rows[rows["race_id"].isin(set(miss_race_ids))].copy()
    if out.empty:
        return out
    out["reflection_focus"] = True
    return out.reset_index(drop=True)


def _compute_feature_adjustments(
    rows: pd.DataFrame,
    *,
    alpha: float,
    top_rank_weight: float = 0.15,
    multiplier_clip: tuple[float, float] | None = None,
) -> tuple[Dict[str, float], List[Dict[str, Any]], int]:
    multipliers: Dict[str, float] = {}
    feature_rows: List[Dict[str, Any]] = []
    top_rank_rows = rows[rows["predicted_rank"] == 1].copy() if "predicted_rank" in rows.columns else pd.DataFrame()

    for feature_name, weight_key in FEATURE_TO_WEIGHT.items():
        if feature_name not in rows.columns:
            continue
        series = pd.to_numeric(rows[feature_name], errors="coerce")
        valid = rows[series.notna()].copy()
        valid[feature_name] = pd.to_numeric(valid[feature_name], errors="coerce")
        if valid.empty:
            continue
        winner_mean = float(valid.loc[valid["win_target"] == 1.0, feature_name].mean()) if (valid["win_target"] == 1.0).any() else np.nan
        loser_mean = float(valid.loc[valid["win_target"] == 0.0, feature_name].mean()) if (valid["win_target"] == 0.0).any() else np.nan
        place_mean = float(valid.loc[valid["place_target"] == 1.0, feature_name].mean()) if (valid["place_target"] == 1.0).any() else np.nan
        out_mean = float(valid.loc[valid["place_target"] == 0.0, feature_name].mean()) if (valid["place_target"] == 0.0).any() else np.nan
        win_signal = 0.0 if (np.isnan(winner_mean) or np.isnan(loser_mean)) else winner_mean - loser_mean
        place_signal = 0.0 if (np.isnan(place_mean) or np.isnan(out_mean)) else place_mean - out_mean
        top_signal = 0.0
        if not top_rank_rows.empty and feature_name in top_rank_rows.columns:
            top_valid = top_rank_rows[pd.to_numeric(top_rank_rows[feature_name], errors="coerce").notna()].copy()
            if not top_valid.empty:
                top_hit_mean = float(top_valid.loc[top_valid["win_target"] == 1.0, feature_name].mean()) if (top_valid["win_target"] == 1.0).any() else np.nan
                top_miss_mean = float(top_valid.loc[top_valid["win_target"] == 0.0, feature_name].mean()) if (top_valid["win_target"] == 0.0).any() else np.nan
                top_signal = 0.0 if (np.isnan(top_hit_mean) or np.isnan(top_miss_mean)) else top_hit_mean - top_miss_mean
        signal = (win_signal * 0.6) + (place_signal * 0.25) + (top_signal * float(top_rank_weight))
        multiplier = float(np.exp(float(alpha) * signal))
        if multiplier_clip is not None:
            multiplier = float(np.clip(multiplier, float(multiplier_clip[0]), float(multiplier_clip[1])))
        multipliers[weight_key] = multiplier
        feature_rows.append(
            {
                "feature": feature_name,
                "weight_key": weight_key,
                "signal": float(signal),
                "multiplier": float(multiplier),
            }
        )

    return multipliers, feature_rows, int(len(top_rank_rows))


def apply_feedback_learning(
    base_weights: Mapping[str, float],
    learning_df: pd.DataFrame | None,
    *,
    alpha: float = 0.45,
    min_rows: int = 30,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    adjusted = {str(key): float(value) for key, value in base_weights.items()}
    if learning_df is None or learning_df.empty or len(learning_df) < int(min_rows):
        return adjusted, {"applied": False, "rows": 0 if learning_df is None else int(len(learning_df)), "reason": "insufficient_rows"}

    rows = learning_df.copy()
    multipliers, feature_rows, top_rank_row_count = _compute_feature_adjustments(rows, alpha=float(alpha))
    for weight_key, multiplier in multipliers.items():
        adjusted[weight_key] = float(np.clip(adjusted.get(weight_key, 0.5) * multiplier, 0.05, 3.5))
    for item in feature_rows:
        item["adjusted_weight"] = float(adjusted[item["weight_key"]])

    return adjusted, {
        "applied": True,
        "rows": int(len(rows)),
        "top_rank_rows": int(top_rank_row_count),
        "alpha": float(alpha),
        "feature_adjustments": feature_rows,
    }


def build_condition_adjustments(
    learning_df: pd.DataFrame | None,
    *,
    alpha: float = 0.22,
    min_rows: int = 120,
    min_races: int = 10,
    min_top_rank_rows: int = 8,
) -> Dict[str, Any]:
    if learning_df is None or learning_df.empty:
        return {"applied": False, "segment_count": 0, "segments": {}}

    rows = learning_df.copy()
    segments: Dict[str, Any] = {}
    summaries: List[Dict[str, Any]] = []

    for column_name, label in CONDITION_SEGMENT_COLUMNS:
        if column_name not in rows.columns:
            continue
        for segment_value, group in rows.groupby(column_name, sort=True, dropna=False):
            value_text = _to_text(segment_value)
            if not value_text:
                continue
            race_count = int(group["race_id"].nunique()) if "race_id" in group.columns else 0
            if len(group) < int(min_rows) or race_count < int(min_races):
                continue
            multipliers, feature_rows, top_rank_rows = _compute_feature_adjustments(
                group,
                alpha=float(alpha),
                multiplier_clip=(0.88, 1.15),
            )
            if top_rank_rows < int(min_top_rank_rows) or not multipliers:
                continue
            segment_key = f"{label}:{value_text}"
            segments[segment_key] = {
                "segment_type": label,
                "segment_value": value_text,
                "rows": int(len(group)),
                "races": int(race_count),
                "top_rank_rows": int(top_rank_rows),
                "multipliers": multipliers,
                "feature_adjustments": feature_rows,
            }
            summaries.append(
                {
                    "segment_key": segment_key,
                    "rows": int(len(group)),
                    "races": int(race_count),
                    "top_rank_rows": int(top_rank_rows),
                }
            )

    return {
        "applied": bool(segments),
        "alpha": float(alpha),
        "segment_count": int(len(segments)),
        "segments": segments,
        "segment_summaries": summaries,
    }
