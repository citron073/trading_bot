from __future__ import annotations

from functools import lru_cache
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List


def _file_signature(path: Path) -> tuple[int, int]:
    try:
        stat = Path(path).stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except Exception:
        return 0, -1


@lru_cache(maxsize=64)
def _read_jsonl_tail_cached(
    path_text: str,
    mtime_ns: int,
    size_bytes: int,
    limit: int,
    max_bytes: int,
) -> tuple[str, ...]:
    del mtime_ns
    if size_bytes <= 0:
        return tuple()
    path = Path(path_text)
    lines_out: List[str] = []
    try:
        with path.open("rb") as handle:
            start = max(0, int(size_bytes) - max(4096, int(max_bytes)))
            handle.seek(start)
            chunk = handle.read()
        lines = chunk.splitlines()
        if start > 0 and lines:
            lines = lines[1:]
        for raw_line in lines:
            if raw_line.strip():
                lines_out.append(raw_line.decode("utf-8"))
    except Exception:
        return tuple()
    return tuple(lines_out[-max(1, int(limit)) :])


def read_jsonl_tail(path: Path, limit: int = 200) -> List[Dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        mtime_ns, size_bytes = _file_signature(path)
        max_bytes = max(256 * 1024, int(limit) * 8192)
        rows: List[Dict[str, Any]] = []
        for line in _read_jsonl_tail_cached(str(path), mtime_ns, size_bytes, max(1, int(limit)), max_bytes):
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
        return rows[-max(1, int(limit)) :]
    except Exception:
        return []


def _archive_monthly_jsonl(path: Path, raw: bytes) -> None:
    archive_dir = path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    month = datetime.now().strftime("%Y%m")
    archive_path = archive_dir / f"{path.stem}_{month}{path.suffix}"
    try:
        raw_lines = [line for line in raw.splitlines() if line.strip()]
        if not raw_lines:
            return
        if archive_path.exists():
            existing = set(line for line in archive_path.read_bytes().splitlines() if line.strip())
            new_lines = [line for line in raw_lines if line not in existing]
            if not new_lines:
                return
            with archive_path.open("ab") as fh:
                fh.write(b"\n".join(new_lines) + b"\n")
        else:
            archive_path.write_bytes(b"\n".join(raw_lines) + b"\n")
    except Exception:
        pass


def compact_jsonl_tail_if_needed(path: Path, *, max_rows: int, max_bytes: int) -> bool:
    path = Path(path)
    if not path.exists():
        return False
    try:
        if path.stat().st_size <= max(4096, int(max_bytes)):
            return False
        raw = path.read_bytes()
        _archive_monthly_jsonl(path, raw)
        lines = raw.splitlines()[-max(1, int(max_rows)) :]
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_bytes(b"\n".join(lines) + (b"\n" if lines else b""))
        tmp_path.replace(path)
        _read_jsonl_tail_cached.cache_clear()
        return True
    except Exception:
        return False


def append_jsonl_with_compaction(
    path: Path,
    payload: Dict[str, Any],
    *,
    max_rows: int,
    max_bytes: int,
) -> None:
    if not isinstance(payload, dict) or not payload:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    compact_jsonl_tail_if_needed(path, max_rows=max_rows, max_bytes=max_bytes)
    _read_jsonl_tail_cached.cache_clear()
