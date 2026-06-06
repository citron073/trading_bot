from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd

from evaluation import build_prediction_feedback


MANUAL_RESULTS_FILENAME = "manual_results.csv"
RESULT_IMPORT_STATUS_FILENAME = "result_import_status.json"


@dataclass(frozen=True)
class ManualResultImportReport:
    ok: bool
    input_path: Path
    imported_races: int
    imported_rows: int
    history_rows: int
    evaluated_before: int
    evaluated_after: int
    pending_before: int
    pending_after: int
    message: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "input_path": str(self.input_path),
            "imported_races": int(self.imported_races),
            "imported_rows": int(self.imported_rows),
            "history_rows": int(self.history_rows),
            "evaluated_before": int(self.evaluated_before),
            "evaluated_after": int(self.evaluated_after),
            "pending_before": int(self.pending_before),
            "pending_after": int(self.pending_after),
            "message": self.message,
            "warnings": list(self.warnings),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
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


def _first(row: Mapping[str, Any], names: Iterable[str], default: Any = "") -> Any:
    for name in names:
        if name in row:
            value = row.get(name)
            if _to_text(value):
                return value
    return default


def _to_float(value: Any, default: float = float("nan")) -> float:
    try:
        parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        return default if pd.isna(parsed) else float(parsed)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        return default if pd.isna(parsed) else int(float(parsed))
    except Exception:
        return default


def _split_gate_and_horse(value: Any) -> tuple[float, str]:
    text = _to_text(value)
    if not text:
        return float("nan"), ""
    match = re.match(r"^\s*(\d{1,2})\s*(?:番|号|[#-])?\s*(.+?)\s*$", text)
    if match:
        return float(match.group(1)), match.group(2).strip()
    return float("nan"), text


def _finish_row(row: Mapping[str, Any], finish: int) -> Dict[str, Any] | None:
    prefixes = {
        1: ("winner", "first", "1st", "一着", "1着"),
        2: ("second", "2nd", "二着", "2着"),
        3: ("third", "3rd", "三着", "3着"),
    }[finish]
    horse_value = _first(row, [*prefixes, f"finish{finish}_horse", f"horse{finish}", f"{finish}_horse"])
    gate_value = _first(row, [f"{prefix}_gate" for prefix in prefixes] + [f"gate{finish}", f"{finish}_gate"], "")
    jockey = _first(row, [f"{prefix}_jockey" for prefix in prefixes] + [f"jockey{finish}", f"{finish}_jockey"], "")
    odds = _first(row, [f"{prefix}_odds" for prefix in prefixes] + [f"odds{finish}", f"{finish}_odds"], "")
    place_odds = _first(row, [f"{prefix}_place_odds" for prefix in prefixes] + [f"place_odds{finish}", f"{finish}_place_odds"], "")

    gate, horse = _split_gate_and_horse(horse_value)
    explicit_gate = _to_float(gate_value, float("nan"))
    if pd.notna(explicit_gate):
        gate = explicit_gate
    if not horse:
        return None

    return {
        "race_id": _to_text(_first(row, ["race_id", "レースID", "id"])),
        "horse": horse,
        "jockey": _to_text(jockey),
        "trainer": _to_text(_first(row, ["trainer", "調教師"], "")),
        "weather": _to_text(_first(row, ["weather", "天気", "天候"], "晴")) or "晴",
        "track_condition": _to_text(_first(row, ["track_condition", "馬場", "馬場状態"], "良")) or "良",
        "distance": _to_float(_first(row, ["distance", "距離"], 1600), 1600.0),
        "finish": int(finish),
        "gate": gate,
        "odds": _to_float(odds, float("nan")),
        "place_odds": _to_float(place_odds, float("nan")),
        "form_score": 50.0,
        "condition_score": 50.0,
        "weight_diff": 0.0,
        "paddock_score": 50.0,
        "odds_shift": 0.0,
        "venue": _to_text(_first(row, ["venue", "開催", "開催場所"], "")),
        "race_name": _to_text(_first(row, ["race_name", "レース名"], "")),
        "race_date": _to_text(_first(row, ["race_date", "date", "日付", "開催日"], "")),
        "popularity": _to_int(_first(row, [f"{prefix}_popularity" for prefix in prefixes] + [f"popularity{finish}", f"{finish}_popularity"], 0), 0),
        "source": "manual_result_csv",
    }


def manual_result_rows_from_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    rows: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for idx, raw_row in frame.fillna("").iterrows():
        row = raw_row.to_dict()
        race_id = _to_text(_first(row, ["race_id", "レースID", "id"]))
        if not race_id:
            warnings.append(f"row={idx}:race_id_missing")
            continue
        for finish in (1, 2, 3):
            item = _finish_row(row, finish)
            if item is not None:
                rows.append(item)
    if not rows:
        out = pd.DataFrame()
    else:
        out = pd.DataFrame(rows)
        out = out[out["race_id"].map(_to_text) != ""].copy()
        out = out.drop_duplicates(subset=["race_id", "finish"], keep="last")
    out.attrs["warnings"] = tuple(warnings)
    return out.reset_index(drop=True)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, low_memory=False)


def _truthy(value: Any) -> bool:
    return _to_text(value).lower() in {"true", "1", "yes", "on", "済"}


def _feedback_counts(frame: pd.DataFrame) -> tuple[int, int]:
    if frame.empty or "result_available" not in frame.columns:
        return 0, 0
    done = int(frame["result_available"].map(_truthy).sum())
    pending = int(len(frame) - done)
    return done, pending


def _replace_history_races(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if fresh.empty:
        return existing.copy()
    if existing.empty or "race_id" not in existing.columns:
        return fresh.copy().reset_index(drop=True)
    fresh_ids = set(fresh["race_id"].map(_to_text).tolist())
    keep = existing[~existing["race_id"].map(_to_text).isin(fresh_ids)].copy()
    return pd.concat([keep, fresh], ignore_index=True).reset_index(drop=True)


def import_manual_results(data_dir: Path, input_path: Path | None = None) -> ManualResultImportReport:
    data_dir = Path(data_dir)
    input_path = Path(input_path) if input_path is not None else data_dir / MANUAL_RESULTS_FILENAME
    status_path = data_dir / RESULT_IMPORT_STATUS_FILENAME
    if not input_path.exists():
        report = ManualResultImportReport(
            ok=False,
            input_path=input_path,
            imported_races=0,
            imported_rows=0,
            history_rows=int(len(_read_csv(data_dir / "history_auto.csv"))),
            evaluated_before=0,
            evaluated_after=0,
            pending_before=0,
            pending_after=0,
            message=f"{input_path.name} がありません。race_id,winner,second,third のCSVを data/ に置いてください。",
        )
        status_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    manual_df = _read_csv(input_path)
    fresh_history = manual_result_rows_from_frame(manual_df)
    warnings = tuple(fresh_history.attrs.get("warnings", ()))

    history_path = data_dir / "history_auto.csv"
    archive_path = data_dir / "prediction_archive.csv"
    feedback_path = data_dir / "prediction_feedback.csv"
    payouts_path = data_dir / "payouts_auto.csv"

    before_feedback = _read_csv(feedback_path)
    evaluated_before, pending_before = _feedback_counts(before_feedback)

    history_existing = _read_csv(history_path)
    if fresh_history.empty:
        report = ManualResultImportReport(
            ok=False,
            input_path=input_path,
            imported_races=0,
            imported_rows=0,
            history_rows=int(len(history_existing)),
            evaluated_before=evaluated_before,
            evaluated_after=evaluated_before,
            pending_before=pending_before,
            pending_after=pending_before,
            message="手動結果CSVから有効な着順を読み取れませんでした。",
            warnings=warnings,
        )
        status_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    merged_history = _replace_history_races(history_existing, fresh_history)
    sort_cols = [c for c in ["race_id", "finish", "horse"] if c in merged_history.columns]
    if sort_cols:
        merged_history = merged_history.sort_values(sort_cols).reset_index(drop=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    merged_history.to_csv(history_path, index=False, encoding="utf-8-sig")

    feedback = build_prediction_feedback(_read_csv(archive_path), merged_history, _read_csv(payouts_path))
    feedback.to_csv(feedback_path, index=False, encoding="utf-8-sig")
    evaluated_after, pending_after = _feedback_counts(feedback)

    imported_races = int(fresh_history["race_id"].map(_to_text).nunique()) if "race_id" in fresh_history.columns else 0
    report = ManualResultImportReport(
        ok=True,
        input_path=input_path,
        imported_races=imported_races,
        imported_rows=int(len(fresh_history)),
        history_rows=int(len(merged_history)),
        evaluated_before=evaluated_before,
        evaluated_after=evaluated_after,
        pending_before=pending_before,
        pending_after=pending_after,
        message=(
            f"手動結果CSVを反映: {imported_races}R / {len(fresh_history)}行 "
            f"/ 評価済み {evaluated_before}->{evaluated_after} / 結果待ち {pending_before}->{pending_after}"
        ),
        warnings=warnings,
    )
    status_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return report
