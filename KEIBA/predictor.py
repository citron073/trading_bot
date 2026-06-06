from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, MutableMapping, Sequence, Tuple

import numpy as np
import pandas as pd

WEATHER_OPTIONS: Tuple[str, ...] = ("晴", "曇", "雨", "雪")
TRACK_OPTIONS: Tuple[str, ...] = ("良", "稍重", "重", "不良")

DEFAULT_FEATURE_WEIGHTS: Mapping[str, float] = {
    "horse_win": 1.70,
    "horse_place": 1.35,
    "jockey_win": 1.10,
    "jockey_place": 0.70,
    "trainer_win": 0.90,
    "trainer_place": 0.60,
    "weather_place": 0.80,
    "track_place": 0.80,
    "gate_place": 0.50,
    "distance_fit": 0.80,
    "form_score": 0.80,
    "condition_score": 0.90,
    "paddock_score": 0.70,
    "weight_diff_score": 0.40,
    "odds_shift_score": 0.40,
    "market_score": 0.55,
}

REQUIRED_HISTORY_COLUMNS: Tuple[str, ...] = (
    "race_id",
    "horse",
    "jockey",
    "trainer",
    "weather",
    "track_condition",
    "distance",
    "finish",
)

REQUIRED_ENTRY_COLUMNS: Tuple[str, ...] = ("horse", "jockey", "trainer")


@dataclass(frozen=True)
class PredictionResult:
    horse_predictions: pd.DataFrame
    bet_recommendations: Dict[str, pd.DataFrame]
    budget_plan: pd.DataFrame


@dataclass(frozen=True)
class _Context:
    weather: str
    track_condition: str
    distance: float


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _smoothed_rate(successes: float, total: float, prior_rate: float, alpha: float) -> float:
    if total <= 0:
        return prior_rate
    return (successes + prior_rate * alpha) / (total + alpha)


def _ensure_columns(df: pd.DataFrame, required: Sequence[str], kind: str) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{kind} に必須カラムが不足しています: {', '.join(missing)}")


def _normalize_label(value: object, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _normalize_condition_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text and text.lower() not in {"nan", "none"} else default


def _distance_bucket(distance: float) -> str:
    if distance <= 1400:
        return "sprint"
    if distance <= 1800:
        return "mile"
    if distance <= 2200:
        return "middle"
    return "long"


def _field_size_bucket(field_size: int) -> str:
    if field_size <= 10:
        return "small"
    if field_size <= 14:
        return "medium"
    return "large"


def resolve_feature_weights_for_context(
    base_weights: Mapping[str, float] | None,
    *,
    weather: str,
    track_condition: str,
    distance: float,
    field_size: int,
    venue: str = "",
    race_grade: str = "",
    condition_adjustments: Mapping[str, Any] | None = None,
) -> tuple[Dict[str, float], List[str]]:
    weights = dict(DEFAULT_FEATURE_WEIGHTS)
    if base_weights:
        for key, value in base_weights.items():
            if key in weights:
                weights[key] = float(value)

    if not condition_adjustments:
        return weights, []

    segments_payload = condition_adjustments.get("segments") if isinstance(condition_adjustments, Mapping) else None
    if not isinstance(segments_payload, Mapping):
        return weights, []

    segment_keys: List[str] = []
    venue_text = _normalize_condition_text(venue)
    race_grade_text = _normalize_condition_text(race_grade, "未判定") or "未判定"
    weather_text = _normalize_condition_text(weather)
    track_text = _normalize_condition_text(track_condition)
    distance_bucket = _distance_bucket(float(distance))
    field_bucket = _field_size_bucket(int(field_size))

    if venue_text:
        segment_keys.append(f"venue:{venue_text}")
    if race_grade_text:
        segment_keys.append(f"race_grade:{race_grade_text}")
    if weather_text:
        segment_keys.append(f"weather:{weather_text}")
    if track_text:
        segment_keys.append(f"track_condition:{track_text}")
    segment_keys.append(f"distance_bucket:{distance_bucket}")
    segment_keys.append(f"field_size_bucket:{field_bucket}")

    applied_segments: List[str] = []
    for segment_key in segment_keys:
        segment_payload = segments_payload.get(segment_key)
        if not isinstance(segment_payload, Mapping):
            continue
        multipliers = segment_payload.get("multipliers")
        if not isinstance(multipliers, Mapping):
            continue
        applied_segments.append(segment_key)
        for weight_key, multiplier in multipliers.items():
            if weight_key not in weights:
                continue
            try:
                weights[weight_key] = float(np.clip(float(weights[weight_key]) * float(multiplier), 0.05, 3.5))
            except Exception:
                continue

    return weights, applied_segments


def prepare_history_dataframe(history_df: pd.DataFrame) -> pd.DataFrame:
    _ensure_columns(history_df, REQUIRED_HISTORY_COLUMNS, "履歴データ")
    df = history_df.copy()
    df["horse"] = df["horse"].astype(str).str.strip()
    df["jockey"] = df["jockey"].astype(str).str.strip()
    df["trainer"] = df["trainer"].astype(str).str.strip()
    df["weather"] = df["weather"].map(lambda x: _normalize_label(x, "晴"))
    df["track_condition"] = df["track_condition"].map(lambda x: _normalize_label(x, "良"))
    df["distance"] = pd.to_numeric(df["distance"], errors="coerce")
    df["finish"] = pd.to_numeric(df["finish"], errors="coerce")
    df = df.dropna(subset=["horse", "jockey", "trainer", "distance", "finish"]).copy()

    optional_defaults = {
        "odds": np.nan,
        "place_odds": np.nan,
        "gate": np.nan,
        "form_score": 50.0,
        "condition_score": 50.0,
        "weight_diff": 0.0,
        "paddock_score": 50.0,
        "odds_shift": 0.0,
    }
    for col, default in optional_defaults.items():
        if col not in df.columns:
            df[col] = default

    for col in (
        "odds",
        "place_odds",
        "gate",
        "form_score",
        "condition_score",
        "weight_diff",
        "paddock_score",
        "odds_shift",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["win"] = (df["finish"] == 1).astype(float)
    df["place"] = (df["finish"] <= 3).astype(float)
    return df


def prepare_entries_dataframe(
    entries_df: pd.DataFrame,
    weather: str,
    track_condition: str,
    distance: float,
) -> pd.DataFrame:
    _ensure_columns(entries_df, REQUIRED_ENTRY_COLUMNS, "出走馬データ")
    df = entries_df.copy()
    df["horse"] = df["horse"].astype(str).str.strip()
    df["jockey"] = df["jockey"].astype(str).str.strip()
    df["trainer"] = df["trainer"].astype(str).str.strip()

    defaults: Mapping[str, object] = {
        "weather": weather,
        "track_condition": track_condition,
        "distance": distance,
        "gate": np.nan,
        "odds": np.nan,
        "place_odds": np.nan,
        "form_score": 50.0,
        "condition_score": 50.0,
        "weight_diff": 0.0,
        "paddock_score": 50.0,
        "odds_shift": 0.0,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    df["weather"] = df["weather"].map(lambda x: _normalize_label(x, weather))
    df["track_condition"] = df["track_condition"].map(lambda x: _normalize_label(x, track_condition))
    for col in (
        "distance",
        "gate",
        "odds",
        "place_odds",
        "form_score",
        "condition_score",
        "weight_diff",
        "paddock_score",
        "odds_shift",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["distance"] = df["distance"].fillna(distance)
    df["form_score"] = df["form_score"].fillna(50.0)
    df["condition_score"] = df["condition_score"].fillna(50.0)
    df["weight_diff"] = df["weight_diff"].fillna(0.0)
    df["paddock_score"] = df["paddock_score"].fillna(50.0)
    df["odds_shift"] = df["odds_shift"].fillna(0.0)
    df = df[df["horse"] != ""].copy()
    if df.empty:
        raise ValueError("出走馬データが空です")
    return df


def _build_stats(history_df: pd.DataFrame) -> Dict[str, object]:
    global_win = float(history_df["win"].mean())
    global_place = float(history_df["place"].mean())

    horse_group = history_df.groupby("horse").agg(
        horse_wins=("win", "sum"),
        horse_places=("place", "sum"),
        horse_count=("win", "count"),
        horse_distance_mean=("distance", "mean"),
        horse_distance_std=("distance", "std"),
    )
    jockey_group = history_df.groupby("jockey").agg(
        jockey_wins=("win", "sum"),
        jockey_places=("place", "sum"),
        jockey_count=("win", "count"),
    )
    trainer_group = history_df.groupby("trainer").agg(
        trainer_wins=("win", "sum"),
        trainer_places=("place", "sum"),
        trainer_count=("win", "count"),
    )

    horse_weather_group = history_df.groupby(["horse", "weather"]).agg(
        wins=("win", "sum"),
        places=("place", "sum"),
        count=("win", "count"),
    )
    horse_track_group = history_df.groupby(["horse", "track_condition"]).agg(
        wins=("win", "sum"),
        places=("place", "sum"),
        count=("win", "count"),
    )
    gate_group = history_df.dropna(subset=["gate"]).groupby("gate").agg(
        wins=("win", "sum"),
        places=("place", "sum"),
        count=("win", "count"),
    )

    return {
        "global_win": global_win,
        "global_place": global_place,
        "horse_group": horse_group,
        "jockey_group": jockey_group,
        "trainer_group": trainer_group,
        "horse_weather_group": horse_weather_group,
        "horse_track_group": horse_track_group,
        "gate_group": gate_group,
    }


def _lookup_group_rate(
    group: pd.DataFrame,
    key: object,
    success_col: str,
    count_col: str,
    prior_rate: float,
    alpha: float,
) -> float:
    if key in group.index:
        row = group.loc[key]
        return _smoothed_rate(float(row[success_col]), float(row[count_col]), prior_rate, alpha)
    return prior_rate


def _lookup_pair_group_rate(
    group: pd.DataFrame,
    key: Tuple[object, object],
    success_col: str,
    count_col: str,
    prior_rate: float,
    alpha: float,
) -> float:
    if key in group.index:
        row = group.loc[key]
        return _smoothed_rate(float(row[success_col]), float(row[count_col]), prior_rate, alpha)
    return prior_rate


def _distance_fit(horse_row: pd.Series | None, target_distance: float) -> float:
    if horse_row is None:
        return 0.5
    mean = float(horse_row.get("horse_distance_mean", np.nan))
    std = float(horse_row.get("horse_distance_std", np.nan))
    if math.isnan(mean):
        return 0.5
    if math.isnan(std) or std < 1.0:
        std = 220.0
    span = max(180.0, std * 1.4)
    diff = abs(target_distance - mean)
    return _clamp(1.0 - diff / span, 0.0, 1.0)


def _market_feature(odds: float) -> float:
    if math.isnan(odds) or odds <= 0:
        return 0.5
    return 1.0 / (1.0 + math.exp((odds - 4.0) / 2.2))


def _weight_diff_feature(weight_diff: float) -> float:
    # Race-day body-weight change around 0kg is treated as neutral-best.
    if math.isnan(weight_diff):
        return 0.5
    return _clamp(1.0 - (abs(weight_diff) / 14.0), 0.0, 1.0)


def _odds_shift_feature(odds_shift: float) -> float:
    # Negative shift = odds shortened (market support).
    if math.isnan(odds_shift):
        return 0.5
    return 1.0 / (1.0 + math.exp(odds_shift / 1.8))


def _compute_strengths(
    entries_df: pd.DataFrame,
    stats: Mapping[str, object],
    context: _Context,
    feature_weights: Mapping[str, float],
) -> Tuple[np.ndarray, List[MutableMapping[str, float]]]:
    horse_group = stats["horse_group"]
    jockey_group = stats["jockey_group"]
    trainer_group = stats["trainer_group"]
    horse_weather_group = stats["horse_weather_group"]
    horse_track_group = stats["horse_track_group"]
    gate_group = stats["gate_group"]

    global_win = float(stats["global_win"])
    global_place = float(stats["global_place"])

    strengths: List[float] = []
    details: List[MutableMapping[str, float]] = []

    for _, row in entries_df.iterrows():
        horse = row["horse"]
        jockey = row["jockey"]
        trainer = row["trainer"]

        horse_row = horse_group.loc[horse] if horse in horse_group.index else None
        horse_win = _lookup_group_rate(horse_group, horse, "horse_wins", "horse_count", global_win, alpha=10.0)
        horse_place = _lookup_group_rate(horse_group, horse, "horse_places", "horse_count", global_place, alpha=10.0)

        jockey_win = _lookup_group_rate(jockey_group, jockey, "jockey_wins", "jockey_count", global_win, alpha=16.0)
        jockey_place = _lookup_group_rate(jockey_group, jockey, "jockey_places", "jockey_count", global_place, alpha=16.0)

        trainer_win = _lookup_group_rate(trainer_group, trainer, "trainer_wins", "trainer_count", global_win, alpha=18.0)
        trainer_place = _lookup_group_rate(
            trainer_group,
            trainer,
            "trainer_places",
            "trainer_count",
            global_place,
            alpha=18.0,
        )

        weather_place = _lookup_pair_group_rate(
            horse_weather_group,
            (horse, context.weather),
            "places",
            "count",
            horse_place,
            alpha=8.0,
        )
        track_place = _lookup_pair_group_rate(
            horse_track_group,
            (horse, context.track_condition),
            "places",
            "count",
            horse_place,
            alpha=8.0,
        )

        gate_value = row.get("gate", np.nan)
        if math.isnan(float(gate_value)):
            gate_place = global_place
        else:
            gate_key = float(gate_value)
            gate_place = _lookup_group_rate(gate_group, gate_key, "places", "count", global_place, alpha=14.0)

        distance_fit = _distance_fit(horse_row, float(row.get("distance", context.distance)))
        form_score = _clamp(float(row.get("form_score", 50.0)) / 100.0, 0.0, 1.0)
        condition_score = _clamp(float(row.get("condition_score", 50.0)) / 100.0, 0.0, 1.0)
        paddock_score = _clamp(float(row.get("paddock_score", 50.0)) / 100.0, 0.0, 1.0)
        weight_diff_score = _weight_diff_feature(float(row.get("weight_diff", 0.0)))
        odds_shift_score = _odds_shift_feature(float(row.get("odds_shift", 0.0)))
        market_score = _market_feature(float(row.get("odds", np.nan)))

        raw_score = (
            float(feature_weights["horse_win"]) * horse_win
            + float(feature_weights["horse_place"]) * horse_place
            + float(feature_weights["jockey_win"]) * jockey_win
            + float(feature_weights["jockey_place"]) * jockey_place
            + float(feature_weights["trainer_win"]) * trainer_win
            + float(feature_weights["trainer_place"]) * trainer_place
            + float(feature_weights["weather_place"]) * weather_place
            + float(feature_weights["track_place"]) * track_place
            + float(feature_weights["gate_place"]) * gate_place
            + float(feature_weights["distance_fit"]) * distance_fit
            + float(feature_weights["form_score"]) * form_score
            + float(feature_weights["condition_score"]) * condition_score
            + float(feature_weights["paddock_score"]) * paddock_score
            + float(feature_weights["weight_diff_score"]) * weight_diff_score
            + float(feature_weights["odds_shift_score"]) * odds_shift_score
            + float(feature_weights["market_score"]) * market_score
        )
        strength = max(raw_score, 1e-6)
        strengths.append(strength)

        details.append(
            {
                "horse_win_rate": horse_win,
                "horse_place_rate": horse_place,
                "jockey_win_rate": jockey_win,
                "jockey_place_rate": jockey_place,
                "trainer_win_rate": trainer_win,
                "trainer_place_rate": trainer_place,
                "gate_place_rate": gate_place,
                "weather_fit": weather_place,
                "track_fit": track_place,
                "distance_fit": distance_fit,
                "form_factor": form_score,
                "condition_factor": condition_score,
                "paddock_factor": paddock_score,
                "weight_diff_factor": weight_diff_score,
                "odds_shift_factor": odds_shift_score,
                "market_factor": market_score,
            }
        )

    strengths_np = np.asarray(strengths, dtype=float)
    # Temperature scaling: keeps favorites but avoids one-horse domination.
    strengths_np = np.power(strengths_np / np.mean(strengths_np), 1.05)
    return strengths_np, details


def simulate_finish_orders(strengths: Sequence[float], simulations: int, seed: int) -> np.ndarray:
    values = np.asarray(strengths, dtype=float)
    if values.ndim != 1:
        raise ValueError("strengths は1次元配列で指定してください")
    if len(values) < 2:
        raise ValueError("2頭以上が必要です")
    if simulations < 100:
        raise ValueError("simulations は100以上を推奨します")

    values = np.clip(values, 1e-8, None)
    rng = np.random.default_rng(seed)
    utility = np.log(values)[None, :] + rng.gumbel(size=(simulations, len(values)))
    return np.argsort(-utility, axis=1)


def _pair_baselines(n_horses: int) -> Mapping[str, float]:
    c2 = n_horses * (n_horses - 1) / 2
    c3 = n_horses * (n_horses - 1) * (n_horses - 2) / 6 if n_horses >= 3 else 1.0
    return {
        "単勝": 1.0 / n_horses,
        "複勝": min(3.0 / n_horses, 1.0),
        "馬連": 1.0 / c2,
        "ワイド": (3.0 / c2) if n_horses >= 3 else 0.0,
        "馬単": 1.0 / (n_horses * (n_horses - 1)),
        "三連複": (1.0 / c3) if n_horses >= 3 else 0.0,
        "三連単": (1.0 / (n_horses * (n_horses - 1) * (n_horses - 2))) if n_horses >= 3 else 0.0,
    }


def _top_rows(df: pd.DataFrame, n: int = 8) -> pd.DataFrame:
    if df.empty:
        return df
    return df.head(n).reset_index(drop=True)


def _combo_table(
    counts: Counter,
    total: int,
    labels: Sequence[str],
    ordered: bool,
    baseline: float,
    top_k: int,
) -> pd.DataFrame:
    if not counts:
        return pd.DataFrame(columns=["組み合わせ", "的中確率", "理論オッズ", "推奨度"])

    rows = []
    for combo, count in counts.items():
        prob = count / total
        combo_text = "-".join(labels[i] for i in combo) if ordered else "-".join(sorted(labels[i] for i in combo))
        rows.append(
            {
                "組み合わせ": combo_text,
                "的中確率": prob,
                "理論オッズ": (1.0 / prob) if prob > 0 else np.inf,
                "推奨度": (prob / baseline) if baseline > 0 else 0.0,
            }
        )

    out = pd.DataFrame(rows).sort_values(["的中確率", "推奨度"], ascending=False)
    return _top_rows(out, top_k)


def _build_budget_plan(
    tables: Mapping[str, pd.DataFrame],
    budget: float,
    bet_units: int,
) -> pd.DataFrame:
    if budget <= 0:
        return pd.DataFrame(columns=["券種", "買い目", "推奨金額", "根拠スコア"])

    picks = []
    for bet_type, table in tables.items():
        if table.empty:
            continue
        limit = min(2, len(table))
        for _, row in table.head(limit).iterrows():
            score = float(row.get("推奨度", 0.0))
            if score <= 0:
                continue
            pick_name = str(row.get("馬", row.get("組み合わせ", "")))
            picks.append({"券種": bet_type, "買い目": pick_name, "根拠スコア": score})

    if not picks:
        return pd.DataFrame(columns=["券種", "買い目", "推奨金額", "根拠スコア"])

    scores = np.array([p["根拠スコア"] for p in picks], dtype=float)
    weights = scores / scores.sum()
    unit = max(float(bet_units), 100.0)
    allocations = np.round((budget * weights) / unit) * unit
    for idx, pick in enumerate(picks):
        pick["推奨金額"] = float(max(0.0, allocations[idx]))

    plan = pd.DataFrame(picks)
    plan = plan[plan["推奨金額"] > 0].sort_values("推奨金額", ascending=False).reset_index(drop=True)
    return plan


def predict_race(
    history_df: pd.DataFrame,
    entries_df: pd.DataFrame,
    weather: str,
    track_condition: str,
    distance: float,
    simulations: int = 12000,
    seed: int = 42,
    budget: float = 10000.0,
    bet_units: int = 100,
    feature_weights: Mapping[str, float] | None = None,
    condition_adjustments: Mapping[str, Any] | None = None,
    venue: str = "",
    race_grade: str = "",
) -> PredictionResult:
    history = prepare_history_dataframe(history_df)
    entries = prepare_entries_dataframe(entries_df, weather, track_condition, distance)

    context = _Context(weather=weather, track_condition=track_condition, distance=float(distance))
    stats = _build_stats(history)
    weights, applied_segments = resolve_feature_weights_for_context(
        feature_weights,
        weather=weather,
        track_condition=track_condition,
        distance=float(distance),
        field_size=int(len(entries)),
        venue=venue,
        race_grade=race_grade,
        condition_adjustments=condition_adjustments,
    )
    strengths, details = _compute_strengths(entries, stats, context, weights)
    orders = simulate_finish_orders(strengths, simulations=simulations, seed=seed)

    n_horses = len(entries)
    baselines = _pair_baselines(n_horses)

    win_probs = np.bincount(orders[:, 0], minlength=n_horses) / simulations
    place_slots = min(3, n_horses)
    place_counts = np.zeros(n_horses, dtype=float)
    for slot in range(place_slots):
        place_counts += np.bincount(orders[:, slot], minlength=n_horses)
    place_probs = place_counts / simulations

    horses = entries["horse"].tolist()
    jockeys = entries["jockey"].astype(str).tolist()
    trainers = entries["trainer"].astype(str).tolist()
    odds_values = pd.to_numeric(entries.get("odds", pd.Series(np.nan, index=entries.index)), errors="coerce")
    place_odds_values = pd.to_numeric(
        entries.get("place_odds", pd.Series(np.nan, index=entries.index)),
        errors="coerce",
    )
    gate_values = pd.to_numeric(entries.get("gate", pd.Series(np.nan, index=entries.index)), errors="coerce")

    horse_rows: List[MutableMapping[str, float | str]] = []
    for idx, horse in enumerate(horses):
        odds = float(odds_values.iloc[idx]) if idx < len(odds_values) else np.nan
        place_odds = float(place_odds_values.iloc[idx]) if idx < len(place_odds_values) else np.nan
        win_ev = (win_probs[idx] * odds - 1.0) if (not math.isnan(odds) and odds > 1.0) else np.nan
        place_ev = (place_probs[idx] * place_odds - 1.0) if (not math.isnan(place_odds) and place_odds > 1.0) else np.nan

        row: MutableMapping[str, float | str] = {
            "馬": horse,
            "馬番": "" if (idx >= len(gate_values) or math.isnan(float(gate_values.iloc[idx]))) else str(int(float(gate_values.iloc[idx]))),
            "騎手": jockeys[idx] if idx < len(jockeys) else "",
            "調教師": trainers[idx] if idx < len(trainers) else "",
            "勝率": float(win_probs[idx]),
            "複勝率": float(place_probs[idx]),
            "理論単勝オッズ": (1.0 / win_probs[idx]) if win_probs[idx] > 0 else np.inf,
            "単勝オッズ": odds,
            "単勝期待値": win_ev,
            "複勝オッズ": place_odds,
            "複勝期待値": place_ev,
            "勝率比": float(win_probs[idx] / baselines["単勝"]),
            "複勝率比": float(place_probs[idx] / baselines["複勝"]),
        }
        row.update(details[idx])
        if applied_segments:
            row["条件補正"] = " / ".join(applied_segments)
        horse_rows.append(row)

    horse_predictions = pd.DataFrame(horse_rows).sort_values(
        ["勝率", "複勝率"],
        ascending=False,
    )
    horse_predictions = horse_predictions.reset_index(drop=True)

    single_table = horse_predictions[
        ["馬", "騎手", "勝率", "単勝オッズ", "単勝期待値", "理論単勝オッズ", "勝率比"]
    ].rename(columns={"勝率": "的中確率", "勝率比": "推奨度", "理論単勝オッズ": "理論オッズ"})
    place_table = horse_predictions[
        ["馬", "騎手", "複勝率", "複勝オッズ", "複勝期待値", "複勝率比"]
    ].rename(columns={"複勝率": "的中確率", "複勝率比": "推奨度"})
    place_table["理論オッズ"] = place_table["的中確率"].map(lambda p: (1.0 / p) if p > 0 else np.inf)
    place_table = place_table[["馬", "騎手", "的中確率", "複勝オッズ", "複勝期待値", "理論オッズ", "推奨度"]]

    exacta_counter: Counter = Counter()
    quinella_counter: Counter = Counter()
    wide_counter: Counter = Counter()
    trifecta_counter: Counter = Counter()
    trio_counter: Counter = Counter()

    if n_horses >= 2:
        for race_order in orders:
            first, second = int(race_order[0]), int(race_order[1])
            exacta_counter[(first, second)] += 1
            quinella_counter[tuple(sorted((first, second)))] += 1
            if n_horses >= 3:
                third = int(race_order[2])
                trifecta_counter[(first, second, third)] += 1
                trio_counter[tuple(sorted((first, second, third)))] += 1
                wide_counter[tuple(sorted((first, second)))] += 1
                wide_counter[tuple(sorted((first, third)))] += 1
                wide_counter[tuple(sorted((second, third)))] += 1

    recommendations: Dict[str, pd.DataFrame] = {
        "単勝": _top_rows(single_table, 8),
        "複勝": _top_rows(place_table.sort_values("的中確率", ascending=False), 8),
        "馬連": _combo_table(
            quinella_counter,
            simulations,
            horses,
            ordered=False,
            baseline=baselines["馬連"],
            top_k=8,
        ),
        "ワイド": _combo_table(
            wide_counter,
            simulations,
            horses,
            ordered=False,
            baseline=baselines["ワイド"],
            top_k=8,
        ),
        "馬単": _combo_table(
            exacta_counter,
            simulations,
            horses,
            ordered=True,
            baseline=baselines["馬単"],
            top_k=8,
        ),
        "三連複": _combo_table(
            trio_counter,
            simulations,
            horses,
            ordered=False,
            baseline=baselines["三連複"],
            top_k=8,
        ),
        "三連単": _combo_table(
            trifecta_counter,
            simulations,
            horses,
            ordered=True,
            baseline=baselines["三連単"],
            top_k=8,
        ),
    }

    budget_plan = _build_budget_plan(recommendations, budget=budget, bet_units=bet_units)
    return PredictionResult(
        horse_predictions=horse_predictions,
        bet_recommendations=recommendations,
        budget_plan=budget_plan,
    )


def generate_sample_history(seed: int = 7, n_races: int = 280) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    horse_names = [f"Horse_{idx:02d}" for idx in range(1, 25)]
    jockey_names = [f"Jockey_{idx:02d}" for idx in range(1, 12)]
    trainer_names = [f"Trainer_{idx:02d}" for idx in range(1, 10)]

    horse_skill = {h: float(rng.normal(0.0, 0.9)) for h in horse_names}
    horse_weather_bias = {h: {w: float(rng.normal(0.0, 0.35)) for w in WEATHER_OPTIONS} for h in horse_names}
    horse_track_bias = {h: {t: float(rng.normal(0.0, 0.30)) for t in TRACK_OPTIONS} for h in horse_names}

    jockey_skill = {j: float(rng.normal(0.0, 0.45)) for j in jockey_names}
    trainer_skill = {t: float(rng.normal(0.0, 0.40)) for t in trainer_names}

    rows = []
    for race_no in range(1, n_races + 1):
        field_size = int(rng.integers(10, 17))
        weather = str(rng.choice(WEATHER_OPTIONS, p=[0.45, 0.30, 0.22, 0.03]))
        if weather == "雨":
            track = str(rng.choice(TRACK_OPTIONS, p=[0.20, 0.33, 0.32, 0.15]))
        elif weather == "雪":
            track = str(rng.choice(TRACK_OPTIONS, p=[0.10, 0.30, 0.35, 0.25]))
        else:
            track = str(rng.choice(TRACK_OPTIONS, p=[0.58, 0.26, 0.12, 0.04]))

        distance = int(rng.choice([1200, 1400, 1600, 1800, 2000, 2200, 2400], p=[0.14, 0.16, 0.21, 0.20, 0.16, 0.09, 0.04]))
        selected_horses = list(rng.choice(horse_names, size=field_size, replace=False))

        abilities = []
        row_meta = []
        for gate, horse in enumerate(selected_horses, start=1):
            jockey = str(rng.choice(jockey_names))
            trainer = str(rng.choice(trainer_names))
            dist_bias = -abs(distance - float(rng.choice([1400, 1600, 1800, 2000]))) / 1000.0
            form_score = float(_clamp(58 + horse_skill[horse] * 10 + rng.normal(0, 8), 20, 95))
            condition_score = float(_clamp(form_score + rng.normal(0, 7), 10, 98))
            weight_diff = float(np.clip(rng.normal(0, 5), -16, 16))
            paddock_score = float(_clamp(condition_score + rng.normal(0, 6), 5, 98))
            ability = (
                horse_skill[horse]
                + horse_weather_bias[horse][weather]
                + horse_track_bias[horse][track]
                + jockey_skill[jockey]
                + trainer_skill[trainer]
                + dist_bias
                + (paddock_score - 50.0) / 90.0
                - abs(weight_diff) / 35.0
                + rng.normal(0, 0.30)
            )
            abilities.append(ability)
            row_meta.append(
                {
                    "horse": horse,
                    "jockey": jockey,
                    "trainer": trainer,
                    "gate": gate,
                    "form_score": form_score,
                    "condition_score": condition_score,
                    "weight_diff": weight_diff,
                    "paddock_score": paddock_score,
                }
            )

        abilities_np = np.asarray(abilities)
        order = np.argsort(-abilities_np)
        odds_base = np.exp(-(abilities_np - abilities_np.mean()))
        odds = np.clip(1.2 + odds_base * rng.uniform(1.4, 4.8, size=field_size), 1.1, 70.0)

        race_id = f"R{race_no:04d}"
        for finish_idx, horse_idx in enumerate(order, start=1):
            meta = row_meta[int(horse_idx)]
            win_odds = float(odds[int(horse_idx)])
            place_odds = float(np.clip(1.05 + win_odds / 3.5 + rng.normal(0, 0.10), 1.0, 18.0))
            rows.append(
                {
                    "race_id": race_id,
                    "horse": meta["horse"],
                    "jockey": meta["jockey"],
                    "trainer": meta["trainer"],
                    "weather": weather,
                    "track_condition": track,
                    "distance": distance,
                    "gate": meta["gate"],
                    "odds": round(win_odds, 2),
                    "place_odds": round(place_odds, 2),
                    "finish": finish_idx,
                    "form_score": round(meta["form_score"], 1),
                    "condition_score": round(meta["condition_score"], 1),
                    "weight_diff": round(meta["weight_diff"], 1),
                    "paddock_score": round(meta["paddock_score"], 1),
                    "odds_shift": 0.0,
                }
            )

    return pd.DataFrame(rows)


def generate_sample_entries(
    history_df: pd.DataFrame,
    weather: str,
    track_condition: str,
    distance: int,
    field_size: int = 12,
    seed: int = 11,
) -> pd.DataFrame:
    if field_size < 2:
        raise ValueError("field_size は2以上を指定してください")

    history = prepare_history_dataframe(history_df)
    rng = np.random.default_rng(seed)

    horse_stats = history.groupby("horse").agg(
        recent_finish=("finish", "mean"),
        races=("finish", "count"),
        jockey=("jockey", "last"),
        trainer=("trainer", "last"),
        odds=("odds", "mean"),
        place_odds=("place_odds", "mean"),
    )
    horse_stats = horse_stats.sort_values(["recent_finish", "races"], ascending=[True, False])
    candidates = horse_stats.head(max(field_size * 2, 20)).index.tolist()
    picked = list(rng.choice(candidates, size=min(field_size, len(candidates)), replace=False))

    rows = []
    for idx, horse in enumerate(picked, start=1):
        stat = horse_stats.loc[horse]
        base_form = _clamp(100.0 - float(stat["recent_finish"]) * 10.0, 25.0, 90.0)
        form_score = _clamp(float(base_form + rng.normal(0.0, 6.0)), 10.0, 95.0)
        condition_score = _clamp(float(form_score + rng.normal(0.0, 8.0)), 10.0, 98.0)
        paddock_score = _clamp(float(condition_score + rng.normal(0.0, 6.0)), 5.0, 98.0)
        weight_diff = float(np.clip(rng.normal(0, 4.5), -14, 14))
        odds_shift = float(np.clip(rng.normal(0, 1.2), -4.0, 4.0))
        odds = max(1.1, float(stat["odds"]) + float(rng.normal(0.0, 1.6)))
        place_odds = max(1.0, float(stat["place_odds"]) + float(rng.normal(0.0, 0.25)))

        rows.append(
            {
                "horse": horse,
                "jockey": str(stat["jockey"]),
                "trainer": str(stat["trainer"]),
                "weather": weather,
                "track_condition": track_condition,
                "distance": distance,
                "gate": idx,
                "odds": round(odds, 2),
                "place_odds": round(place_odds, 2),
                "form_score": round(form_score, 1),
                "condition_score": round(condition_score, 1),
                "weight_diff": round(weight_diff, 1),
                "paddock_score": round(paddock_score, 1),
                "odds_shift": round(odds_shift, 2),
            }
        )

    return pd.DataFrame(rows)


def export_template_csv() -> Tuple[pd.DataFrame, pd.DataFrame]:
    history = generate_sample_history(seed=1, n_races=24)
    entries = generate_sample_entries(
        history,
        weather="晴",
        track_condition="良",
        distance=1600,
        field_size=10,
        seed=2,
    )
    return history, entries


def get_default_feature_weights() -> Dict[str, float]:
    return {k: float(v) for k, v in DEFAULT_FEATURE_WEIGHTS.items()}
