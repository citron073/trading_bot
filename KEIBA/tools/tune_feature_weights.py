from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Dict, List, Mapping

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from feedback_learning import (
    apply_feedback_learning,
    build_condition_adjustments,
    build_feedback_learning_frame,
    filter_reflection_learning_rows,
)
from predictor import get_default_feature_weights, predict_race, prepare_history_dataframe


@dataclass(frozen=True)
class EvalResult:
    roi: float
    hit_rate: float
    bets: int
    profit: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="競馬予想モデルの特徴量重みを回収率ベースで探索します")
    parser.add_argument("--history", required=True, help="正規化済み履歴CSV")
    parser.add_argument("--out", required=True, help="ベスト重みJSON出力先")
    parser.add_argument("--trials", type=int, default=40, help="探索回数")
    parser.add_argument("--val-races", type=int, default=30, help="検証レース数")
    parser.add_argument("--simulations", type=int, default=1500, help="1レース予測シミュレーション回数")
    parser.add_argument("--seed", type=int, default=42, help="乱数シード")
    parser.add_argument("--prediction-features", default="", help="予測特徴量アーカイブCSV（任意）")
    parser.add_argument("--feedback-alpha", type=float, default=0.45, help="差分学習の反映強度")
    parser.add_argument("--focus", choices=("all", "reflection"), default="all", help="差分学習の対象。reflection は外れレース優先")
    return parser.parse_args()


def _pick_eval_races(history: pd.DataFrame, n_races: int) -> List[str]:
    race_ids = history["race_id"].astype(str).dropna().unique().tolist()
    race_ids = sorted(race_ids)
    if len(race_ids) <= 3:
        raise ValueError("履歴レース数が少なすぎます（最低4レース以上必要）")
    return race_ids[-min(n_races, len(race_ids) - 1) :]


def _evaluate(
    history: pd.DataFrame,
    eval_races: List[str],
    weights: Mapping[str, float],
    simulations: int,
    seed: int,
    condition_adjustments: Mapping[str, object] | None = None,
) -> EvalResult:
    bets = 0
    hits = 0
    profit = 0.0

    for idx, race_id in enumerate(eval_races):
        race_df = history[history["race_id"].astype(str) == race_id].copy()
        train_df = history[history["race_id"].astype(str) != race_id].copy()
        if race_df.empty or train_df.empty:
            continue

        first = race_df.iloc[0]
        weather = str(first.get("weather", "晴"))
        track_condition = str(first.get("track_condition", "良"))
        distance = float(first.get("distance", 1600.0))

        result = predict_race(
            history_df=train_df,
            entries_df=race_df,
            weather=weather,
            track_condition=track_condition,
            distance=distance,
            simulations=simulations,
            seed=seed + idx,
            budget=0,
            feature_weights=weights,
            condition_adjustments=condition_adjustments,
            venue=str(first.get("venue", "")),
            race_grade=str(first.get("race_grade", first.get("grade", "未判定"))),
        )
        if result.horse_predictions.empty:
            continue

        top_horse = str(result.horse_predictions.iloc[0]["馬"])
        actual_rows = race_df[race_df["horse"].astype(str) == top_horse]
        if actual_rows.empty:
            continue

        bets += 1
        actual_finish = float(actual_rows.iloc[0].get("finish", np.nan))
        odds = float(actual_rows.iloc[0].get("odds", np.nan))

        if actual_finish == 1:
            hits += 1
            if np.isfinite(odds) and odds > 1.0:
                profit += odds - 1.0
        else:
            profit -= 1.0

    if bets == 0:
        return EvalResult(roi=-1.0, hit_rate=0.0, bets=0, profit=0.0)

    roi = profit / bets
    hit_rate = hits / bets
    return EvalResult(roi=roi, hit_rate=hit_rate, bets=bets, profit=profit)


def _sample_weights(rng: np.random.Generator, base: Mapping[str, float]) -> Dict[str, float]:
    weights = {k: float(v) for k, v in base.items()}
    tune_keys = [
        "weather_place",
        "track_place",
        "distance_fit",
        "form_score",
        "condition_score",
        "paddock_score",
        "weight_diff_score",
        "odds_shift_score",
        "market_score",
    ]
    for key in tune_keys:
        scale = float(np.exp(rng.normal(0.0, 0.28)))
        weights[key] = max(0.05, min(3.5, weights[key] * scale))
    return weights


def main() -> None:
    args = _parse_args()

    history_raw = pd.read_csv(Path(args.history))
    history = prepare_history_dataframe(history_raw)
    eval_races = _pick_eval_races(history, n_races=args.val_races)

    rng = np.random.default_rng(args.seed)
    base_weights = get_default_feature_weights()

    best_weights = dict(base_weights)
    best_eval = _evaluate(history, eval_races, best_weights, args.simulations, args.seed)

    for trial in range(1, int(args.trials) + 1):
        candidate = _sample_weights(rng, base_weights)
        result = _evaluate(history, eval_races, candidate, args.simulations, args.seed + trial * 100)

        if (result.roi > best_eval.roi) or (
            np.isclose(result.roi, best_eval.roi) and result.hit_rate > best_eval.hit_rate
        ):
            best_eval = result
            best_weights = candidate

    feedback_meta: Dict[str, object] = {"applied": False, "rows": 0}
    condition_adjustments: Dict[str, object] = {}
    learning_race_count = 0
    feature_archive_path = Path(str(args.prediction_features)).expanduser() if str(args.prediction_features).strip() else None
    if feature_archive_path is not None and feature_archive_path.exists():
        try:
            feature_archive = pd.read_csv(feature_archive_path)
            learning_frame = build_feedback_learning_frame(feature_archive, history_raw)
            reflection_rows = 0
            if args.focus == "reflection":
                reflection_frame = filter_reflection_learning_rows(learning_frame)
                if not reflection_frame.empty:
                    learning_frame = reflection_frame
                    reflection_rows = int(len(reflection_frame))
            learning_race_count = int(learning_frame["race_id"].nunique()) if (not learning_frame.empty and "race_id" in learning_frame.columns) else 0
            adjusted_weights, feedback_meta = apply_feedback_learning(
                best_weights,
                learning_frame,
                alpha=float(args.feedback_alpha),
            )
            if feedback_meta.get("applied"):
                condition_adjustments = build_condition_adjustments(learning_frame)
                adjusted_eval = _evaluate(
                    history,
                    eval_races,
                    adjusted_weights,
                    args.simulations,
                    args.seed + 9999,
                    condition_adjustments if condition_adjustments.get("applied") else None,
                )
                feedback_meta = {
                    **feedback_meta,
                    "focus": str(args.focus),
                    "reflection_rows": int(reflection_rows),
                    "selected": True,
                    "condition_segment_count": int(condition_adjustments.get("segment_count", 0)),
                    "base_eval": {
                        "roi": float(best_eval.roi),
                        "hit_rate": float(best_eval.hit_rate),
                    },
                    "adjusted_eval": {
                        "roi": float(adjusted_eval.roi),
                        "hit_rate": float(adjusted_eval.hit_rate),
                    },
                }
                best_weights = adjusted_weights
                best_eval = adjusted_eval
        except Exception as exc:
            feedback_meta = {"applied": False, "rows": 0, "error": str(exc)}

    output = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "history_rows": int(len(history)),
        "eval_races": eval_races,
        "trials": int(args.trials),
        "simulations": int(args.simulations),
        "best_eval": {
            "roi": float(best_eval.roi),
            "hit_rate": float(best_eval.hit_rate),
            "bets": int(best_eval.bets),
            "profit": float(best_eval.profit),
        },
        "base_weights": base_weights,
        "best_weights": best_weights,
        "feedback_learning": feedback_meta,
        "condition_adjustments": condition_adjustments,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"history_rows={len(history)}")
    print(f"eval_races={len(eval_races)}")
    print(f"feature_rows={int(feedback_meta.get('rows', 0))}")
    print(f"reflection_rows={int(feedback_meta.get('reflection_rows', 0))}")
    print(f"race_count={int(learning_race_count)}")
    print(f"best_roi={best_eval.roi:.4f}")
    print(f"best_hit_rate={best_eval.hit_rate:.4f}")
    print(f"out={out_path}")


if __name__ == "__main__":
    main()
