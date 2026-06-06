from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List

import pandas as pd

from payout_utils import BET_TYPE_ORDER, normalize_bet_type, normalize_ticket_text, prediction_pick_to_ticket

PREDICTION_ARCHIVE_COLUMNS: List[str] = [
    "race_id",
    "race_date",
    "race_name",
    "race_grade",
    "venue",
    "weather",
    "track_condition",
    "distance",
    "field_size",
    "top_horse",
    "top_jockey",
    "top_pop_rank",
    "top_horse_odds",
    "dark_horse",
    "dark_horse_pop",
    "danger_favorite",
    "danger_favorite_pop",
    "spiritual_horse",
    "llm_top_horse",
    "llm_dark_horse",
    "llm_danger_favorite",
    "llm_pick_source",
    "llm_pick_reason",
    "condition_adjustment_count",
    "condition_adjustments",
    "win_prob",
    "place_prob",
    "single_pick",
    "place_pick",
    "quinella_pick",
    "wide_pick",
    "exacta_pick",
    "trio_pick",
    "trifecta_pick",
    "budget_basis_key",
    "budget_basis_label",
    "budget_basis_mode",
    "predicted_at",
]

PREDICTION_COMPARE_COLUMNS: List[str] = [
    column for column in PREDICTION_ARCHIVE_COLUMNS if column != "predicted_at"
]

PREDICTION_FEEDBACK_COLUMNS: List[str] = [
    "race_id",
    "race_date",
    "race_name",
    "race_grade",
    "venue",
    "condition_adjustment_count",
    "condition_adjustments",
    "budget_basis_key",
    "budget_basis_label",
    "budget_basis_mode",
    "predicted_at",
    "result_available",
    "top_horse",
    "llm_top_horse",
    "llm_dark_horse",
    "llm_danger_favorite",
    "llm_pick_source",
    "llm_pick_reason",
    "single_pick",
    "place_pick",
    "quinella_pick",
    "wide_pick",
    "exacta_pick",
    "trio_pick",
    "trifecta_pick",
    "actual_winner",
    "actual_second",
    "actual_third",
    "actual_top3",
    "top_horse_hit",
    "llm_top_hit",
    "llm_disagreement",
    "llm_disagreement_reason",
    "single_hit",
    "place_hit",
    "quinella_hit",
    "wide_hit",
    "exacta_hit",
    "trio_hit",
    "trifecta_hit",
    "winner_odds",
    "place_pick_odds",
    "single_payout_100",
    "place_payout_100",
    "quinella_payout_100",
    "wide_payout_100",
    "exacta_payout_100",
    "trio_payout_100",
    "trifecta_payout_100",
]

PAYOUT_COLUMN_BY_BET_TYPE: Dict[str, str] = {
    "単勝": "single_payout_100",
    "複勝": "place_payout_100",
    "馬連": "quinella_payout_100",
    "ワイド": "wide_payout_100",
    "馬単": "exacta_payout_100",
    "三連複": "trio_payout_100",
    "三連単": "trifecta_payout_100",
}

BET_TYPE_METRICS: Dict[str, Dict[str, str]] = {
    "単勝": {"key_base": "single", "pick": "single_pick", "hit": "single_hit", "payout": "single_payout_100"},
    "複勝": {"key_base": "place", "pick": "place_pick", "hit": "place_hit", "payout": "place_payout_100"},
    "馬連": {"key_base": "quinella", "pick": "quinella_pick", "hit": "quinella_hit", "payout": "quinella_payout_100"},
    "ワイド": {"key_base": "wide", "pick": "wide_pick", "hit": "wide_hit", "payout": "wide_payout_100"},
    "馬単": {"key_base": "exacta", "pick": "exacta_pick", "hit": "exacta_hit", "payout": "exacta_payout_100"},
    "三連複": {"key_base": "trio", "pick": "trio_pick", "hit": "trio_hit", "payout": "trio_payout_100"},
    "三連単": {"key_base": "trifecta", "pick": "trifecta_pick", "hit": "trifecta_hit", "payout": "trifecta_payout_100"},
}


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _to_numeric(value: Any) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def _parse_race_day(race_date: Any, race_id: Any) -> date | None:
    text = _to_text(race_date)
    candidates = [text] if text else []
    race_id_text = _to_text(race_id)
    digits = "".join(ch for ch in race_id_text if ch.isdigit())
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


def _has_pick(value: Any) -> bool:
    return _to_text(value) not in {"", "-"}


def ensure_prediction_archive_columns(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=PREDICTION_ARCHIVE_COLUMNS)
    out = frame.copy()
    for column in PREDICTION_ARCHIVE_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    return out[PREDICTION_ARCHIVE_COLUMNS].copy()


def ensure_prediction_feedback_columns(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=PREDICTION_FEEDBACK_COLUMNS)
    out = frame.copy()
    for column in PREDICTION_FEEDBACK_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    return out[PREDICTION_FEEDBACK_COLUMNS].copy()


def prepare_payout_rows(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["race_id", "bet_type", "ticket", "payout"])
    out = frame.copy()
    for column in ["race_id", "bet_type", "ticket", "payout"]:
        if column not in out.columns:
            out[column] = ""
    out["race_id"] = out["race_id"].map(_to_text)
    out["bet_type"] = out["bet_type"].map(normalize_bet_type)
    out["ticket"] = out.apply(lambda row: normalize_ticket_text(row.get("ticket", ""), row.get("bet_type", "")), axis=1)
    out["payout"] = pd.to_numeric(out["payout"], errors="coerce")
    out = out[(out["race_id"] != "") & (out["bet_type"] != "") & (out["ticket"] != "") & out["payout"].notna()].copy()
    return out.reset_index(drop=True)


def prepare_prediction_archive(frame: pd.DataFrame | None, *, predicted_at: str | None = None) -> pd.DataFrame:
    out = ensure_prediction_archive_columns(frame)
    if out.empty:
        return out
    out["race_id"] = out["race_id"].map(_to_text)
    out = out[out["race_id"] != ""].copy()
    timestamp = predicted_at or datetime.now().isoformat(timespec="seconds")
    out["predicted_at"] = out["predicted_at"].map(_to_text)
    out.loc[out["predicted_at"] == "", "predicted_at"] = timestamp
    return out.reset_index(drop=True)


def _same_prediction_row(left: pd.Series, right: pd.Series) -> bool:
    for column in PREDICTION_COMPARE_COLUMNS:
        if _to_text(left.get(column, "")) != _to_text(right.get(column, "")):
            return False
    return True


def upsert_prediction_archive(existing_df: pd.DataFrame | None, fresh_df: pd.DataFrame | None) -> pd.DataFrame:
    existing = prepare_prediction_archive(existing_df)
    fresh = prepare_prediction_archive(fresh_df)
    if fresh.empty:
        return existing
    if existing.empty:
        merged = fresh.copy()
    else:
        keep_existing = existing[~existing["race_id"].isin(fresh["race_id"])].copy()
        merged_rows: List[Dict[str, Any]] = []
        for _, fresh_row in fresh.iterrows():
            race_id = _to_text(fresh_row.get("race_id", ""))
            existing_row = existing[existing["race_id"] == race_id]
            if not existing_row.empty and _same_prediction_row(existing_row.iloc[-1], fresh_row):
                merged_rows.append(existing_row.iloc[-1][PREDICTION_ARCHIVE_COLUMNS].to_dict())
            else:
                merged_rows.append(fresh_row[PREDICTION_ARCHIVE_COLUMNS].to_dict())
        merged = pd.concat([keep_existing, pd.DataFrame(merged_rows)], ignore_index=True)
    if "race_date" in merged.columns:
        merged["_race_date_sort"] = pd.to_datetime(merged["race_date"], errors="coerce")
    else:
        merged["_race_date_sort"] = pd.NaT
    merged = merged.sort_values(["_race_date_sort", "race_id"], ascending=[False, False], na_position="last")
    merged = merged.drop(columns=["_race_date_sort"], errors="ignore")
    return ensure_prediction_archive_columns(merged).reset_index(drop=True)


def _split_pick_text(text: Any) -> List[str]:
    raw = _to_text(text)
    if not raw or raw == "-":
        return []
    return [part.strip() for part in raw.split("-") if part.strip() and part.strip() != "-"]


def _build_history_lookup(history_df: pd.DataFrame | None) -> Dict[str, pd.DataFrame]:
    if history_df is None or history_df.empty:
        return {}
    work = history_df.copy()
    if "race_id" not in work.columns or "horse" not in work.columns or "finish" not in work.columns:
        return {}
    work["race_id"] = work["race_id"].map(_to_text)
    work["horse"] = work["horse"].map(_to_text)
    work["finish_num"] = pd.to_numeric(work["finish"], errors="coerce")
    work = work[(work["race_id"] != "") & (work["horse"] != "") & work["finish_num"].notna()].copy()
    if work.empty:
        return {}
    return {
        race_id: group.sort_values(["finish_num", "horse"], ascending=[True, True]).reset_index(drop=True)
        for race_id, group in work.groupby("race_id", sort=False)
    }


def _pick_finish_horse(frame: pd.DataFrame, finish_value: int) -> str:
    hit = frame[frame["finish_num"] == float(finish_value)]
    if hit.empty:
        return ""
    return _to_text(hit.iloc[0].get("horse", ""))


def _pick_horse_metric(frame: pd.DataFrame, horse_name: str, column_name: str) -> float | None:
    if frame.empty or not horse_name or column_name not in frame.columns:
        return None
    hit = frame[frame["horse"] == horse_name]
    if hit.empty:
        return None
    series = pd.to_numeric(hit[column_name], errors="coerce")
    series = series[series.notna()]
    if series.empty:
        return None
    return float(series.iloc[0])


def _build_llm_disagreement_reason(prediction: pd.Series | Dict[str, Any]) -> str:
    top_horse = _to_text(prediction.get("top_horse", ""))
    llm_top_horse = _to_text(prediction.get("llm_top_horse", ""))
    if not top_horse or not llm_top_horse or top_horse == llm_top_horse:
        return ""
    reasons: List[str] = []
    llm_dark = _to_text(prediction.get("llm_dark_horse", ""))
    llm_danger = _to_text(prediction.get("llm_danger_favorite", ""))
    if llm_dark and llm_dark == llm_top_horse:
        reasons.append("LLMは穴候補を本命視")
    if llm_danger and llm_danger == top_horse:
        reasons.append("LLMはデータ本命を危険視")
    top_pop_rank = _to_numeric(prediction.get("top_pop_rank"))
    if top_pop_rank is not None and top_pop_rank <= 3:
        reasons.append("上位人気から外している")
    adjustment_count = _to_numeric(prediction.get("condition_adjustment_count"))
    if adjustment_count is not None and adjustment_count >= 2:
        reasons.append(f"条件補正{int(adjustment_count)}本を重視")
    if not reasons:
        reasons.append("候補の見方が分かれた")
    return " / ".join(reasons[:2])


def build_prediction_feedback(
    prediction_archive_df: pd.DataFrame | None,
    history_df: pd.DataFrame | None,
    payouts_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    archive = prepare_prediction_archive(prediction_archive_df)
    if archive.empty:
        return ensure_prediction_feedback_columns(pd.DataFrame())

    history_lookup = _build_history_lookup(history_df)
    payout_rows = prepare_payout_rows(payouts_df)
    payout_lookup: Dict[tuple[str, str, str], float] = {}
    if not payout_rows.empty:
        payout_lookup = {
            (_to_text(row["race_id"]), normalize_bet_type(row["bet_type"]), _to_text(row["ticket"])): float(row["payout"])
            for _, row in payout_rows.iterrows()
        }
    rows: List[Dict[str, Any]] = []
    for _, prediction in archive.iterrows():
        race_id = _to_text(prediction.get("race_id", ""))
        race_history = history_lookup.get(race_id, pd.DataFrame())
        result_available = False
        actual_winner = ""
        actual_second = ""
        actual_third = ""
        actual_top3_text = ""
        winner_odds = None
        place_pick_odds = None
        single_payout_100 = None
        place_payout_100 = None
        quinella_payout_100 = None
        wide_payout_100 = None
        exacta_payout_100 = None
        trio_payout_100 = None
        trifecta_payout_100 = None

        top3 = pd.DataFrame()
        top3_names: List[str] = []
        horse_to_gate: Dict[str, str] = {}
        if not race_history.empty:
            top3 = race_history[race_history["finish_num"] <= 3].copy()
            actual_winner = _pick_finish_horse(race_history, 1)
            actual_second = _pick_finish_horse(race_history, 2)
            actual_third = _pick_finish_horse(race_history, 3)
            top3_names = [horse for horse in [actual_winner, actual_second, actual_third] if horse]
            result_available = bool(actual_winner)
            actual_top3_text = " / ".join(top3_names) if top3_names else ""
            winner_odds = _pick_horse_metric(race_history, actual_winner, "odds") if actual_winner else None
            if "gate" in race_history.columns:
                gate_frame = race_history[["horse", "gate"]].copy()
                gate_frame["horse"] = gate_frame["horse"].map(_to_text)
                gate_frame["gate"] = pd.to_numeric(gate_frame["gate"], errors="coerce")
                gate_frame = gate_frame[gate_frame["horse"] != ""]
                horse_to_gate = {
                    str(row["horse"]): str(int(float(row["gate"])))
                    for _, row in gate_frame.iterrows()
                    if pd.notna(row["gate"])
                }

        top_horse = _to_text(prediction.get("top_horse", ""))
        llm_top_horse = _to_text(prediction.get("llm_top_horse", ""))
        llm_dark_horse = _to_text(prediction.get("llm_dark_horse", ""))
        llm_danger_favorite = _to_text(prediction.get("llm_danger_favorite", ""))
        llm_pick_source = _to_text(prediction.get("llm_pick_source", ""))
        llm_pick_reason = _to_text(prediction.get("llm_pick_reason", ""))
        single_pick = _to_text(prediction.get("single_pick", "")) or top_horse
        place_pick = _to_text(prediction.get("place_pick", "")) or top_horse
        quinella_pick = _to_text(prediction.get("quinella_pick", ""))
        wide_pick = _to_text(prediction.get("wide_pick", ""))
        exacta_pick = _to_text(prediction.get("exacta_pick", ""))
        trio_pick = _to_text(prediction.get("trio_pick", ""))
        trifecta_pick = _to_text(prediction.get("trifecta_pick", ""))

        top_horse_hit = bool(result_available and top_horse and top_horse == actual_winner)
        llm_top_hit = bool(result_available and llm_top_horse and llm_top_horse == actual_winner)
        llm_disagreement = bool(top_horse and llm_top_horse and top_horse != llm_top_horse)
        llm_disagreement_reason = _to_text(prediction.get("llm_disagreement_reason", "")) or _build_llm_disagreement_reason(prediction)
        single_hit = bool(result_available and single_pick and single_pick == actual_winner)
        place_hit = bool(result_available and place_pick and place_pick in top3_names)

        quinella_parts = _split_pick_text(quinella_pick)
        wide_parts = _split_pick_text(wide_pick)
        exacta_parts = _split_pick_text(exacta_pick)
        trio_parts = _split_pick_text(trio_pick)
        trifecta_parts = _split_pick_text(trifecta_pick)

        quinella_hit = bool(result_available and len(quinella_parts) == 2 and set(quinella_parts) == set(top3_names[:2]))
        wide_hit = bool(result_available and len(wide_parts) == 2 and set(wide_parts).issubset(set(top3_names)))
        exacta_hit = bool(result_available and len(exacta_parts) == 2 and exacta_parts == top3_names[:2])
        trio_hit = bool(result_available and len(trio_parts) == 3 and set(trio_parts) == set(top3_names))
        trifecta_hit = bool(result_available and len(trifecta_parts) == 3 and trifecta_parts == top3_names)

        if result_available and _has_pick(single_pick):
            if single_hit:
                single_payout_100 = float(winner_odds) * 100.0 if winner_odds is not None else None
                if single_payout_100 is None and single_pick == top_horse:
                    fallback_odds = _to_numeric(prediction.get("top_horse_odds"))
                    if fallback_odds is not None:
                        single_payout_100 = fallback_odds * 100.0
            else:
                single_payout_100 = 0.0

        if result_available and _has_pick(place_pick):
            if place_hit:
                place_pick_odds = _pick_horse_metric(top3, place_pick, "place_odds")
                place_payout_100 = float(place_pick_odds) * 100.0 if place_pick_odds is not None else None
            else:
                place_payout_100 = 0.0

        predicted_ticket_map = {
            "単勝": prediction_pick_to_ticket(single_pick, "単勝", horse_to_gate),
            "複勝": prediction_pick_to_ticket(place_pick, "複勝", horse_to_gate),
            "馬連": prediction_pick_to_ticket(quinella_pick, "馬連", horse_to_gate),
            "ワイド": prediction_pick_to_ticket(wide_pick, "ワイド", horse_to_gate),
            "馬単": prediction_pick_to_ticket(exacta_pick, "馬単", horse_to_gate),
            "三連複": prediction_pick_to_ticket(trio_pick, "三連複", horse_to_gate),
            "三連単": prediction_pick_to_ticket(trifecta_pick, "三連単", horse_to_gate),
        }
        payout_values = {
            bet_type: payout_lookup.get((race_id, bet_type, ticket))
            for bet_type, ticket in predicted_ticket_map.items()
            if ticket
        }
        if payout_values.get("単勝") is not None:
            single_payout_100 = float(payout_values["単勝"])
        if payout_values.get("複勝") is not None:
            place_payout_100 = float(payout_values["複勝"])
        quinella_payout_100 = float(payout_values["馬連"]) if payout_values.get("馬連") is not None else (0.0 if result_available and _has_pick(quinella_pick) else None)
        wide_payout_100 = float(payout_values["ワイド"]) if payout_values.get("ワイド") is not None else (0.0 if result_available and _has_pick(wide_pick) else None)
        exacta_payout_100 = float(payout_values["馬単"]) if payout_values.get("馬単") is not None else (0.0 if result_available and _has_pick(exacta_pick) else None)
        trio_payout_100 = float(payout_values["三連複"]) if payout_values.get("三連複") is not None else (0.0 if result_available and _has_pick(trio_pick) else None)
        trifecta_payout_100 = float(payout_values["三連単"]) if payout_values.get("三連単") is not None else (0.0 if result_available and _has_pick(trifecta_pick) else None)

        rows.append(
            {
                "race_id": race_id,
                "race_date": _to_text(prediction.get("race_date", "")),
                "race_name": _to_text(prediction.get("race_name", "")),
                "race_grade": _to_text(prediction.get("race_grade", "")),
                "venue": _to_text(prediction.get("venue", "")),
                "condition_adjustment_count": _to_text(prediction.get("condition_adjustment_count", "")),
                "condition_adjustments": _to_text(prediction.get("condition_adjustments", "")),
                "budget_basis_key": _to_text(prediction.get("budget_basis_key", "")),
                "budget_basis_label": _to_text(prediction.get("budget_basis_label", "")),
                "budget_basis_mode": _to_text(prediction.get("budget_basis_mode", "")),
                "predicted_at": _to_text(prediction.get("predicted_at", "")),
                "result_available": result_available,
                "top_horse": top_horse,
                "llm_top_horse": llm_top_horse,
                "llm_dark_horse": llm_dark_horse,
                "llm_danger_favorite": llm_danger_favorite,
                "llm_pick_source": llm_pick_source,
                "llm_pick_reason": llm_pick_reason,
                "single_pick": single_pick,
                "place_pick": place_pick,
                "quinella_pick": quinella_pick,
                "wide_pick": wide_pick,
                "exacta_pick": exacta_pick,
                "trio_pick": trio_pick,
                "trifecta_pick": trifecta_pick,
                "actual_winner": actual_winner,
                "actual_second": actual_second,
                "actual_third": actual_third,
                "actual_top3": actual_top3_text,
                "top_horse_hit": top_horse_hit,
                "llm_top_hit": llm_top_hit,
                "llm_disagreement": llm_disagreement,
                "llm_disagreement_reason": llm_disagreement_reason,
                "single_hit": single_hit,
                "place_hit": place_hit,
                "quinella_hit": quinella_hit,
                "wide_hit": wide_hit,
                "exacta_hit": exacta_hit,
                "trio_hit": trio_hit,
                "trifecta_hit": trifecta_hit,
                "winner_odds": winner_odds,
                "place_pick_odds": place_pick_odds,
                "single_payout_100": single_payout_100,
                "place_payout_100": place_payout_100,
                "quinella_payout_100": quinella_payout_100,
                "wide_payout_100": wide_payout_100,
                "exacta_payout_100": exacta_payout_100,
                "trio_payout_100": trio_payout_100,
                "trifecta_payout_100": trifecta_payout_100,
            }
        )

    feedback = pd.DataFrame(rows)
    return ensure_prediction_feedback_columns(feedback)


def aggregate_prediction_feedback(feedback_df: pd.DataFrame | None) -> Dict[str, Any]:
    feedback = ensure_prediction_feedback_columns(feedback_df)
    total_predictions = int(len(feedback))
    evaluated = feedback[feedback["result_available"].astype(str).str.lower().isin(["true", "1"])].copy()
    if "result_available" in feedback.columns and feedback["result_available"].dtype == bool:
        evaluated = feedback[feedback["result_available"]].copy()
    unevaluated = feedback.drop(index=evaluated.index, errors="ignore").copy()
    today = datetime.now().date()
    if not unevaluated.empty:
        race_days = unevaluated.apply(
            lambda row: _parse_race_day(row.get("race_date", ""), row.get("race_id", "")),
            axis=1,
        )
        pending_mask = race_days.map(lambda value: bool(value is not None and value <= today))
        upcoming_mask = race_days.map(lambda value: bool(value is not None and value > today))
        pending_races = int(pending_mask.sum())
        upcoming_races = int(upcoming_mask.sum())
        undated_predictions = int((~pending_mask & ~upcoming_mask).sum())
    else:
        pending_races = 0
        upcoming_races = 0
        undated_predictions = 0

    def _hit_rate(column_name: str) -> float | None:
        if evaluated.empty or column_name not in evaluated.columns:
            return None
        series = evaluated[column_name].astype(str).str.lower().isin(["true", "1"])
        if column_name in evaluated.columns and evaluated[column_name].dtype == bool:
            series = evaluated[column_name].astype(bool)
        return float(series.mean()) if len(series) else None

    def _roi(column_name: str, pick_column: str) -> tuple[float | None, float | None]:
        if evaluated.empty or column_name not in evaluated.columns or pick_column not in evaluated.columns:
            return (None, None)
        target = evaluated[evaluated[pick_column].map(_has_pick)].copy()
        if target.empty:
            return (None, None)
        payout = pd.to_numeric(target[column_name], errors="coerce")
        known = float(payout.notna().mean()) if len(payout) else None
        total_stake = float(len(target) * 100)
        if total_stake <= 0:
            return (None, known)
        total_return = float(payout.fillna(0).sum())
        return (total_return / total_stake, known)

    single_roi, single_roi_coverage = _roi("single_payout_100", "single_pick")
    place_roi, place_roi_coverage = _roi("place_payout_100", "place_pick")
    quinella_roi, quinella_roi_coverage = _roi("quinella_payout_100", "quinella_pick")
    wide_roi, wide_roi_coverage = _roi("wide_payout_100", "wide_pick")
    exacta_roi, exacta_roi_coverage = _roi("exacta_payout_100", "exacta_pick")
    trio_roi, trio_roi_coverage = _roi("trio_payout_100", "trio_pick")
    trifecta_roi, trifecta_roi_coverage = _roi("trifecta_payout_100", "trifecta_pick")

    return {
        "stored_predictions": total_predictions,
        "evaluated_races": int(len(evaluated)),
        "pending_races": int(pending_races),
        "upcoming_races": int(upcoming_races),
        "undated_predictions": int(undated_predictions),
        "top_horse_hit_rate": _hit_rate("top_horse_hit"),
        "single_hit_rate": _hit_rate("single_hit"),
        "place_hit_rate": _hit_rate("place_hit"),
        "quinella_hit_rate": _hit_rate("quinella_hit"),
        "wide_hit_rate": _hit_rate("wide_hit"),
        "exacta_hit_rate": _hit_rate("exacta_hit"),
        "trio_hit_rate": _hit_rate("trio_hit"),
        "trifecta_hit_rate": _hit_rate("trifecta_hit"),
        "single_roi": single_roi,
        "single_roi_coverage": single_roi_coverage,
        "place_roi": place_roi,
        "place_roi_coverage": place_roi_coverage,
        "quinella_roi": quinella_roi,
        "quinella_roi_coverage": quinella_roi_coverage,
        "wide_roi": wide_roi,
        "wide_roi_coverage": wide_roi_coverage,
        "exacta_roi": exacta_roi,
        "exacta_roi_coverage": exacta_roi_coverage,
        "trio_roi": trio_roi,
        "trio_roi_coverage": trio_roi_coverage,
        "trifecta_roi": trifecta_roi,
        "trifecta_roi_coverage": trifecta_roi_coverage,
    }


def build_condition_adjustment_performance_table(feedback_df: pd.DataFrame | None) -> pd.DataFrame:
    feedback = ensure_prediction_feedback_columns(feedback_df)
    if feedback.empty:
        return pd.DataFrame(
            columns=[
                "補正本数",
                "評価済みレース",
                "本命的中率",
                "単勝的中率",
                "複勝的中率",
                "単勝回収率",
                "複勝回収率",
            ]
        )

    evaluated = feedback[feedback["result_available"].astype(str).str.lower().isin(["true", "1"])].copy()
    if "result_available" in feedback.columns and feedback["result_available"].dtype == bool:
        evaluated = feedback[feedback["result_available"]].copy()
    if evaluated.empty:
        return pd.DataFrame(
            columns=[
                "補正本数",
                "評価済みレース",
                "本命的中率",
                "単勝的中率",
                "複勝的中率",
                "単勝回収率",
                "複勝回収率",
            ]
        )

    work = evaluated.copy()
    work["condition_adjustment_count_num"] = pd.to_numeric(work["condition_adjustment_count"], errors="coerce").fillna(0).astype(int)

    def _bucket(value: int) -> str:
        if value <= 0:
            return "0本"
        if value == 1:
            return "1本"
        if value == 2:
            return "2本"
        return "3本以上"

    work["補正本数"] = work["condition_adjustment_count_num"].map(_bucket)
    rows: List[Dict[str, Any]] = []
    for bucket_name, group in work.groupby("補正本数", sort=False):
        single_payout = pd.to_numeric(group["single_payout_100"], errors="coerce")
        place_payout = pd.to_numeric(group["place_payout_100"], errors="coerce")
        rows.append(
            {
                "補正本数": bucket_name,
                "評価済みレース": int(len(group)),
                "本命的中率": float(group["top_horse_hit"].astype(bool).mean()) if len(group) else None,
                "単勝的中率": float(group["single_hit"].astype(bool).mean()) if len(group) else None,
                "複勝的中率": float(group["place_hit"].astype(bool).mean()) if len(group) else None,
                "単勝回収率": float(single_payout.fillna(0).sum() / (len(group) * 100)) if len(group) else None,
                "複勝回収率": float(place_payout.fillna(0).sum() / (len(group) * 100)) if len(group) else None,
            }
        )
    order = {"0本": 0, "1本": 1, "2本": 2, "3本以上": 3}
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["_sort"] = out["補正本数"].map(lambda value: order.get(_to_text(value), 99))
    return out.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)


def build_condition_segment_performance_table(feedback_df: pd.DataFrame | None) -> pd.DataFrame:
    feedback = ensure_prediction_feedback_columns(feedback_df)
    if feedback.empty:
        return pd.DataFrame(
            columns=[
                "条件補正",
                "評価済みレース",
                "本命的中率",
                "単勝的中率",
                "単勝回収率",
            ]
        )

    evaluated = feedback[feedback["result_available"].astype(str).str.lower().isin(["true", "1"])].copy()
    if "result_available" in feedback.columns and feedback["result_available"].dtype == bool:
        evaluated = feedback[feedback["result_available"]].copy()
    if evaluated.empty:
        return pd.DataFrame(
            columns=[
                "条件補正",
                "評価済みレース",
                "本命的中率",
                "単勝的中率",
                "単勝回収率",
            ]
        )

    rows: List[Dict[str, Any]] = []
    for _, row in evaluated.iterrows():
        segments = [part.strip() for part in _to_text(row.get("condition_adjustments", "")).split("/") if part.strip()]
        if not segments:
            continue
        for segment in segments:
            rows.append(
                {
                    "条件補正": segment,
                    "top_horse_hit": bool(row.get("top_horse_hit", False)),
                    "single_hit": bool(row.get("single_hit", False)),
                    "single_payout_100": _to_numeric(row.get("single_payout_100")),
                }
            )
    detail = pd.DataFrame(rows)
    if detail.empty:
        return pd.DataFrame(
            columns=[
                "条件補正",
                "評価済みレース",
                "本命的中率",
                "単勝的中率",
                "単勝回収率",
            ]
        )

    out_rows: List[Dict[str, Any]] = []
    for segment_name, group in detail.groupby("条件補正", sort=False):
        single_payout = pd.to_numeric(group["single_payout_100"], errors="coerce")
        out_rows.append(
            {
                "条件補正": segment_name,
                "評価済みレース": int(len(group)),
                "本命的中率": float(group["top_horse_hit"].astype(bool).mean()) if len(group) else None,
                "単勝的中率": float(group["single_hit"].astype(bool).mean()) if len(group) else None,
                "単勝回収率": float(single_payout.fillna(0).sum() / (len(group) * 100)) if len(group) else None,
            }
        )
    out = pd.DataFrame(out_rows)
    if out.empty:
        return out
    return out.sort_values(["評価済みレース", "本命的中率"], ascending=[False, False]).reset_index(drop=True)


def build_bet_type_performance_table(feedback_df: pd.DataFrame | None) -> pd.DataFrame:
    summary = aggregate_prediction_feedback(feedback_df)
    rows: List[Dict[str, Any]] = []
    for bet_type in BET_TYPE_ORDER:
        key_base = BET_TYPE_METRICS[bet_type]["key_base"]
        rows.append(
            {
                "券種": bet_type,
                "的中率": summary.get(f"{key_base}_hit_rate"),
                "回収率": summary.get(f"{key_base}_roi"),
                "払戻既知率": summary.get(f"{key_base}_roi_coverage"),
            }
        )
    return pd.DataFrame(rows)


def build_bet_type_feedback_rows(feedback_df: pd.DataFrame | None) -> pd.DataFrame:
    feedback = ensure_prediction_feedback_columns(feedback_df)
    if feedback.empty:
        return pd.DataFrame(
            columns=[
                "race_id",
                "race_date",
                "race_name",
                "race_grade",
                "venue",
                "budget_basis_key",
                "budget_basis_label",
                "budget_basis_mode",
                "predicted_at",
                "bet_type",
                "pick",
                "hit",
                "payout_100",
                "payout_known",
                "result_available",
                "actual_top3",
            ]
        )

    rows: List[Dict[str, Any]] = []
    for _, row in feedback.iterrows():
        actual_top3 = _to_text(row.get("actual_top3", ""))
        if not actual_top3:
            actual_top3 = " / ".join(
                [horse for horse in [_to_text(row.get("actual_winner", "")), _to_text(row.get("actual_second", "")), _to_text(row.get("actual_third", ""))] if horse]
            )
        for bet_type in BET_TYPE_ORDER:
            meta = BET_TYPE_METRICS[bet_type]
            pick_text = _to_text(row.get(meta["pick"], ""))
            if not _has_pick(pick_text):
                continue
            payout_value = _to_numeric(row.get(meta["payout"]))
            rows.append(
                {
                    "race_id": _to_text(row.get("race_id", "")),
                    "race_date": _to_text(row.get("race_date", "")),
                    "race_name": _to_text(row.get("race_name", "")),
                    "race_grade": _to_text(row.get("race_grade", "")),
                    "venue": _to_text(row.get("venue", "")),
                    "budget_basis_key": _to_text(row.get("budget_basis_key", "")),
                    "budget_basis_label": _to_text(row.get("budget_basis_label", "")),
                    "budget_basis_mode": _to_text(row.get("budget_basis_mode", "")),
                    "predicted_at": _to_text(row.get("predicted_at", "")),
                    "bet_type": bet_type,
                    "pick": pick_text,
                    "hit": bool(str(row.get(meta["hit"], "")).lower() in {"true", "1"}) if not isinstance(row.get(meta["hit"], ""), bool) else bool(row.get(meta["hit"], False)),
                    "payout_100": payout_value,
                    "payout_known": payout_value is not None,
                    "result_available": bool(str(row.get("result_available", "")).lower() in {"true", "1"}) if not isinstance(row.get("result_available", ""), bool) else bool(row.get("result_available", False)),
                    "actual_top3": actual_top3,
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["_race_date_sort"] = pd.to_datetime(out["race_date"], errors="coerce")
    out = out.sort_values(["_race_date_sort", "race_id", "bet_type"], ascending=[False, False, True], na_position="last")
    return out.drop(columns=["_race_date_sort"]).reset_index(drop=True)


def build_budget_basis_performance_table(feedback_df: pd.DataFrame | None) -> pd.DataFrame:
    feedback = ensure_prediction_feedback_columns(feedback_df)
    if feedback.empty:
        return pd.DataFrame(
            columns=[
                "配分基準",
                "採用モード",
                "評価済みレース",
                "本命的中率",
                "単勝的中率",
                "複勝的中率",
                "単勝回収率",
                "複勝回収率",
            ]
        )

    evaluated = feedback[feedback["result_available"].astype(str).str.lower().isin(["true", "1"])].copy()
    if "result_available" in feedback.columns and feedback["result_available"].dtype == bool:
        evaluated = feedback[feedback["result_available"]].copy()
    if evaluated.empty:
        return pd.DataFrame(
            columns=[
                "配分基準",
                "採用モード",
                "評価済みレース",
                "本命的中率",
                "単勝的中率",
                "複勝的中率",
                "単勝回収率",
                "複勝回収率",
            ]
        )

    work = evaluated.copy()
    work["配分基準"] = work["budget_basis_label"].map(_to_text).replace("", "未記録")
    work["採用モード"] = work["budget_basis_mode"].map(_to_text).replace("", "未記録")
    rows: List[Dict[str, Any]] = []
    for (basis_label, basis_mode), group in work.groupby(["配分基準", "採用モード"], sort=False):
        single_payout = pd.to_numeric(group["single_payout_100"], errors="coerce")
        place_payout = pd.to_numeric(group["place_payout_100"], errors="coerce")
        rows.append(
            {
                "配分基準": basis_label,
                "採用モード": basis_mode,
                "評価済みレース": int(len(group)),
                "本命的中率": float(group["top_horse_hit"].astype(bool).mean()) if len(group) else None,
                "単勝的中率": float(group["single_hit"].astype(bool).mean()) if len(group) else None,
                "複勝的中率": float(group["place_hit"].astype(bool).mean()) if len(group) else None,
                "単勝回収率": float(single_payout.fillna(0).sum() / (len(group) * 100)) if len(group) else None,
                "複勝回収率": float(place_payout.fillna(0).sum() / (len(group) * 100)) if len(group) else None,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["単勝回収率", "本命的中率", "評価済みレース"], ascending=[False, False, False], na_position="last").reset_index(drop=True)


def build_llm_disagreement_performance_table(feedback_df: pd.DataFrame | None) -> pd.DataFrame:
    feedback = ensure_prediction_feedback_columns(feedback_df)
    if feedback.empty:
        return pd.DataFrame(
            columns=[
                "区分",
                "評価済みレース",
                "データ本命勝率",
                "LLM本命勝率",
                "LLM優勢差",
            ]
        )

    evaluated = feedback[feedback["result_available"].astype(str).str.lower().isin(["true", "1"])].copy()
    if "result_available" in feedback.columns and feedback["result_available"].dtype == bool:
        evaluated = feedback[feedback["result_available"]].copy()
    if evaluated.empty or "llm_disagreement" not in evaluated.columns:
        return pd.DataFrame(
            columns=[
                "区分",
                "評価済みレース",
                "データ本命勝率",
                "LLM本命勝率",
                "LLM優勢差",
            ]
        )

    work = evaluated.copy()
    disagreement_mask = work["llm_disagreement"].astype(str).str.lower().isin(["true", "1"])
    if work["llm_disagreement"].dtype == bool:
        disagreement_mask = work["llm_disagreement"].astype(bool)
    work = work[disagreement_mask].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "区分",
                "評価済みレース",
                "データ本命勝率",
                "LLM本命勝率",
                "LLM優勢差",
            ]
        )

    def _classify_reason_bucket(value: Any) -> str:
        parts = [_to_text(part) for part in _to_text(value).split("/") if _to_text(part)]
        if any("穴候補" in part for part in parts):
            return "穴寄り"
        if any("危険視" in part for part in parts):
            return "危険視"
        if any("市場" in part or "人気" in part for part in parts):
            return "人気逆張り"
        if any("条件補正" in part for part in parts):
            return "補正重視"
        return "見方差"

    work["区分"] = work["llm_disagreement_reason"].map(_classify_reason_bucket)
    rows: List[Dict[str, Any]] = []

    def _append_row(label: str, group: pd.DataFrame) -> None:
        if group.empty:
            return
        data_hit = float(group["top_horse_hit"].astype(bool).mean()) if "top_horse_hit" in group.columns else None
        llm_hit = float(group["llm_top_hit"].astype(bool).mean()) if "llm_top_hit" in group.columns else None
        edge = None
        if data_hit is not None and llm_hit is not None:
            edge = float(llm_hit) - float(data_hit)
        rows.append(
            {
                "区分": label,
                "評価済みレース": int(len(group)),
                "データ本命勝率": data_hit,
                "LLM本命勝率": llm_hit,
                "LLM優勢差": edge,
            }
        )

    _append_row("別軸全体", work)
    for reason_name, group in work.groupby("区分", sort=False):
        _append_row(_to_text(reason_name) or "見方差", group)

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    order = {"別軸全体": 0, "穴寄り": 1, "危険視": 2, "人気逆張り": 3, "補正重視": 4, "見方差": 5}
    out["_sort"] = out["区分"].map(lambda value: order.get(_to_text(value), 99))
    return out.sort_values(["_sort", "評価済みレース"], ascending=[True, False]).drop(columns=["_sort"]).reset_index(drop=True)
