from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence

import pandas as pd

HISTORY_REQUIRED = [
    "race_id",
    "horse",
    "jockey",
    "trainer",
    "weather",
    "track_condition",
    "distance",
    "finish",
]

ENTRY_REQUIRED = ["horse", "jockey", "trainer"]

ALIASES: Mapping[str, Sequence[str]] = {
    "race_id": [
        "race_id",
        "レースID",
        "race_key",
        "RACE_KEY",
        "開催レースID",
        "race",
    ],
    "horse": ["horse", "馬名", "馬", "horse_name", "HORSE_NAME"],
    "jockey": ["jockey", "騎手", "騎手名", "jockey_name", "JOCKEY_NAME"],
    "trainer": ["trainer", "調教師", "trainer_name", "TRAINER_NAME", "厩舎"],
    "weather": ["weather", "天気", "天候", "WEATHER"],
    "track_condition": [
        "track_condition",
        "馬場",
        "馬場状態",
        "馬場コンディション",
        "TRACK_CONDITION",
    ],
    "distance": ["distance", "距離", "距離m", "RACE_DISTANCE", "距離(ｍ)"],
    "finish": ["finish", "着順", "着", "FINISH", "result"],
    "gate": ["gate", "枠", "枠番", "馬番", "post_position", "枠順"],
    "odds": ["odds", "単勝", "単勝オッズ", "win_odds", "WIN_ODDS"],
    "place_odds": ["place_odds", "複勝", "複勝オッズ", "show_odds", "PLACE_ODDS"],
    "form_score": ["form_score", "調子", "近走指数", "form", "FORM_SCORE"],
    "condition_score": [
        "condition_score",
        "状態",
        "馬体気配",
        "condition",
        "CONDITION_SCORE",
    ],
    "weight_diff": [
        "weight_diff",
        "馬体重増減",
        "増減",
        "weight_change",
        "WEIGHT_DIFF",
    ],
    "paddock_score": [
        "paddock_score",
        "パドック評価",
        "パドック",
        "PADDOCK_SCORE",
    ],
    "odds_shift": [
        "odds_shift",
        "オッズ変化",
        "直前オッズ差",
        "ODDS_SHIFT",
    ],
}

WEATHER_MAP = {
    "晴れ": "晴",
    "晴": "晴",
    "曇り": "曇",
    "曇": "曇",
    "小雨": "雨",
    "雨": "雨",
    "雪": "雪",
}

TRACK_MAP = {
    "良": "良",
    "稍": "稍重",
    "稍重": "稍重",
    "重": "重",
    "不": "不良",
    "不良": "不良",
}


def _normalize_column_names(columns: Iterable[str]) -> Dict[str, str]:
    normalized = {}
    for col in columns:
        normalized[str(col).strip().lower()] = str(col)
    return normalized


def _find_source_column(df: pd.DataFrame, canonical: str) -> str | None:
    if canonical in df.columns:
        return canonical
    col_map = _normalize_column_names(df.columns)
    for candidate in ALIASES.get(canonical, []):
        key = str(candidate).strip().lower()
        if key in col_map:
            return col_map[key]
    return None


def _require_columns(out_df: pd.DataFrame, required: Sequence[str], mode: str) -> None:
    missing = [c for c in required if c not in out_df.columns]
    if missing:
        raise ValueError(f"{mode} 用データの必須カラムが不足: {', '.join(missing)}")


def _normalize_weather(value: object) -> str:
    text = str(value).strip()
    if not text or text == "nan":
        return "晴"
    return WEATHER_MAP.get(text, text[:2])


def _normalize_track(value: object) -> str:
    text = str(value).strip()
    if not text or text == "nan":
        return "良"
    return TRACK_MAP.get(text, text)


def _to_float_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    for key in HISTORY_REQUIRED + [
        "gate",
        "odds",
        "place_odds",
        "form_score",
        "condition_score",
        "weight_diff",
        "paddock_score",
        "odds_shift",
    ]:
        src = _find_source_column(df, key)
        if src is not None:
            out[key] = df[src]

    _require_columns(out, HISTORY_REQUIRED, "history")

    out["race_id"] = out["race_id"].astype(str).str.strip()
    out["horse"] = out["horse"].astype(str).str.strip()
    out["jockey"] = out["jockey"].astype(str).str.strip()
    out["trainer"] = out["trainer"].astype(str).str.strip()
    out["weather"] = out["weather"].map(_normalize_weather)
    out["track_condition"] = out["track_condition"].map(_normalize_track)
    out["distance"] = _to_float_series(out["distance"])
    out["finish"] = _to_float_series(out["finish"])

    for col in [
        "gate",
        "odds",
        "place_odds",
        "form_score",
        "condition_score",
        "weight_diff",
        "paddock_score",
        "odds_shift",
    ]:
        if col in out.columns:
            out[col] = _to_float_series(out[col])

    if "form_score" not in out.columns:
        out["form_score"] = 50.0
    if "condition_score" not in out.columns:
        out["condition_score"] = 50.0
    if "weight_diff" not in out.columns:
        out["weight_diff"] = 0.0
    if "paddock_score" not in out.columns:
        out["paddock_score"] = 50.0
    if "odds_shift" not in out.columns:
        out["odds_shift"] = 0.0

    out = out.dropna(subset=["horse", "jockey", "trainer", "distance", "finish"]).copy()
    out = out[(out["horse"] != "") & (out["jockey"] != "") & (out["trainer"] != "")]
    return out


def _normalize_entries(df: pd.DataFrame, default_weather: str, default_track: str, default_distance: int) -> pd.DataFrame:
    out = pd.DataFrame()
    for key in ENTRY_REQUIRED + [
        "weather",
        "track_condition",
        "distance",
        "gate",
        "odds",
        "place_odds",
        "form_score",
        "condition_score",
        "weight_diff",
        "paddock_score",
        "odds_shift",
    ]:
        src = _find_source_column(df, key)
        if src is not None:
            out[key] = df[src]

    _require_columns(out, ENTRY_REQUIRED, "entries")

    out["horse"] = out["horse"].astype(str).str.strip()
    out["jockey"] = out["jockey"].astype(str).str.strip()
    out["trainer"] = out["trainer"].astype(str).str.strip()

    if "weather" not in out.columns:
        out["weather"] = default_weather
    else:
        out["weather"] = out["weather"].map(_normalize_weather)

    if "track_condition" not in out.columns:
        out["track_condition"] = default_track
    else:
        out["track_condition"] = out["track_condition"].map(_normalize_track)

    if "distance" not in out.columns:
        out["distance"] = float(default_distance)
    else:
        out["distance"] = _to_float_series(out["distance"]).fillna(float(default_distance))

    for col in [
        "gate",
        "odds",
        "place_odds",
        "form_score",
        "condition_score",
        "weight_diff",
        "paddock_score",
        "odds_shift",
    ]:
        if col in out.columns:
            out[col] = _to_float_series(out[col])

    if "form_score" not in out.columns:
        out["form_score"] = 50.0
    if "condition_score" not in out.columns:
        out["condition_score"] = 50.0
    if "weight_diff" not in out.columns:
        out["weight_diff"] = 0.0
    if "paddock_score" not in out.columns:
        out["paddock_score"] = 50.0
    if "odds_shift" not in out.columns:
        out["odds_shift"] = 0.0

    out = out[(out["horse"] != "") & (out["jockey"] != "") & (out["trainer"] != "")].copy()
    out = out.reset_index(drop=True)
    return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="JRA/NAR由来CSVを keiba_dashboard 用フォーマットに正規化します。"
    )
    parser.add_argument("--mode", choices=["history", "entries"], required=True)
    parser.add_argument("--in", dest="input_csv", required=True, help="入力CSV")
    parser.add_argument("--out", dest="output_csv", required=True, help="出力CSV")
    parser.add_argument("--encoding", default="utf-8", help="入力CSVエンコーディング")
    parser.add_argument("--default-weather", default="晴", help="entriesモードでのデフォルト天気")
    parser.add_argument("--default-track", default="良", help="entriesモードでのデフォルト馬場")
    parser.add_argument("--default-distance", type=int, default=1600, help="entriesモードでのデフォルト距離")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    input_path = Path(args.input_csv)
    output_path = Path(args.output_csv)

    if not input_path.exists():
        raise FileNotFoundError(f"入力CSVが見つかりません: {input_path}")

    df = pd.read_csv(input_path, encoding=args.encoding)
    if args.mode == "history":
        out = _normalize_history(df)
    else:
        out = _normalize_entries(
            df,
            default_weather=args.default_weather,
            default_track=args.default_track,
            default_distance=args.default_distance,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"mode={args.mode}")
    print(f"in={input_path}")
    print(f"out={output_path}")
    print(f"rows={len(out)}")
    print(f"columns={','.join(out.columns.tolist())}")


if __name__ == "__main__":
    main()
