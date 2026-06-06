from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import streamlit as st

DEFAULT_CSV_TEXT_DTYPES: Dict[str, str] = {
    "race_id": "string",
    "horse": "string",
    "jockey": "string",
    "trainer": "string",
    "venue": "string",
    "race_name": "string",
    "race_date": "string",
    "weather": "string",
    "track_condition": "string",
    "fetched_date": "string",
}

DATA_LAYOUT_DIRS = ("runtime", "archive", "cache", "models")
PARQUET_CACHE_MIN_BYTES = int(os.getenv("KEIBA_PARQUET_CACHE_MIN_BYTES", str(1024 * 1024)))


def ensure_data_layout(data_dir: Path) -> Dict[str, Path]:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    out: Dict[str, Path] = {}
    for name in DATA_LAYOUT_DIRS:
        path = data_dir / name
        path.mkdir(parents=True, exist_ok=True)
        out[name] = path
    return out


def file_signature(path: Path) -> tuple[int, int]:
    try:
        stat = Path(path).stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except Exception:
        return 0, -1


def parquet_cache_path_for_csv(path: Path) -> Path | None:
    path = Path(path)
    if path.suffix.lower() != ".csv":
        return None
    if path.parent.name == "cache":
        return None
    return path.parent / "cache" / f"{path.stem}.parquet"


def parquet_cache_status(path: Path) -> Dict[str, Any]:
    path = Path(path)
    cache_path = parquet_cache_path_for_csv(path)
    if cache_path is None:
        return {"enabled": False, "path": "", "exists": False, "fresh": False, "size": 0}
    csv_mtime_ns, csv_size = file_signature(path)
    cache_mtime_ns, cache_size = file_signature(cache_path)
    return {
        "enabled": bool(csv_size >= PARQUET_CACHE_MIN_BYTES),
        "path": str(cache_path),
        "exists": cache_path.exists(),
        "fresh": bool(cache_path.exists() and cache_mtime_ns >= csv_mtime_ns and csv_size >= 0),
        "size": max(0, int(cache_size)),
        "source_size": max(0, int(csv_size)),
    }


@st.cache_data(ttl=120, show_spinner=False)
def _read_csv_cached(path_text: str, mtime_ns: int, size_bytes: int) -> pd.DataFrame:
    del mtime_ns, size_bytes
    path = Path(path_text)
    cache_path = parquet_cache_path_for_csv(path)
    if cache_path is not None and path.exists() and path.stat().st_size >= PARQUET_CACHE_MIN_BYTES:
        try:
            if cache_path.exists() and cache_path.stat().st_mtime_ns >= path.stat().st_mtime_ns:
                return pd.read_parquet(cache_path)
        except Exception:
            pass
        frame = pd.read_csv(path, dtype=DEFAULT_CSV_TEXT_DTYPES, low_memory=False)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(cache_path, index=False)
        except Exception:
            pass
        return frame
    return pd.read_csv(path, dtype=DEFAULT_CSV_TEXT_DTYPES, low_memory=False)


def read_csv_if_exists(path: Path) -> pd.DataFrame | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        mtime_ns, size_bytes = file_signature(path)
        return _read_csv_cached(str(path), mtime_ns, size_bytes).copy()
    except Exception:
        return None


def read_json_if_exists(path: Path) -> Dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def frames_equal_for_storage(left: pd.DataFrame | None, right: pd.DataFrame | None) -> bool:
    if left is None:
        return right is None or right.empty
    if right is None:
        return left.empty
    left_work = left.copy().reset_index(drop=True)
    right_work = right.copy().reset_index(drop=True)
    if list(left_work.columns) != list(right_work.columns):
        return False
    if left_work.shape != right_work.shape:
        return False
    try:
        left_norm = left_work.astype("string").fillna("")
        right_norm = right_work.astype("string").fillna("")
        return bool(left_norm.equals(right_norm))
    except Exception:
        return False


def write_csv_if_changed(path: Path, frame: pd.DataFrame) -> bool:
    existing = read_csv_if_exists(path)
    if frames_equal_for_storage(existing, frame):
        return False
    write_csv(path, frame)
    return True
