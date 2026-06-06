from __future__ import annotations

import json
import re
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

from payout_utils import BET_TYPE_ORDER, normalize_bet_type, normalize_ticket_text
from weather_forecast import enrich_entries_weather_with_forecast, normalize_venue


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

NETKEIBA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

CSV_TEXT_DTYPES: Dict[str, str] = {
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

VENUE_KEYS: Tuple[str, ...] = (
    "venue",
    "place",
    "race_place",
    "racecourse",
    "race_course",
    "course",
    "開催",
    "開催地",
    "競馬場",
    "race_name",
    "name",
)

HTTP_TIMEOUT_SEC = 12
HTTP_RETRIES = 3
HTTP_RETRY_SLEEP_SEC = 1.0
SCRAPER_TIMEOUT_SEC = 18
SCRAPER_RETRIES = 2
SCRAPER_RETRY_SLEEP_SEC = 1.2
TUNING_TIMEOUT_SEC = 900
ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class AutoUpdateReport:
    history_path: Path
    entries_path: Path
    weights_path: Path | None
    history_rows: int
    entries_rows: int
    history_races: int
    weekly_races: int
    tuned: bool
    notes: Tuple[str, ...]


@contextmanager
def _time_limit(seconds: int):
    if seconds <= 0 or not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)

    def _handle_timeout(signum: int, frame: Any) -> None:
        raise TimeoutError(f"timeout>{int(seconds)}s")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _call_with_retry(
    func: Any,
    *,
    attempts: int,
    retry_sleep_sec: float,
    timeout_sec: int = 0,
    on_wait: Callable[[int, int], None] | None = None,
) -> Any:
    def _call_once() -> Any:
        if timeout_sec <= 0:
            return func()

        result_holder: Dict[str, Any] = {}
        error_holder: Dict[str, Exception] = {}
        done = threading.Event()
        start_time = time.monotonic()
        last_notified_second = -1

        def _runner() -> None:
            try:
                result_holder["value"] = func()
            except Exception as exc:
                error_holder["error"] = exc
            finally:
                done.set()

        worker = threading.Thread(target=_runner, daemon=True)
        worker.start()
        while not done.wait(timeout=0.5):
            elapsed = int(time.monotonic() - start_time)
            if elapsed != last_notified_second:
                last_notified_second = elapsed
                if on_wait is not None:
                    on_wait(attempt, elapsed)
            if elapsed >= max(1, int(timeout_sec)):
                raise TimeoutError(f"timeout>{int(timeout_sec)}s")
        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder.get("value")

    last_exc: Exception | None = None
    max_attempts = max(1, int(attempts))
    for attempt in range(1, max_attempts + 1):
        try:
            return _call_once()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            time.sleep(max(0.0, float(retry_sleep_sec)) * attempt)
    if last_exc is None:
        raise RuntimeError("retry_failed")
    raise RuntimeError(f"retry_exhausted:attempts={max_attempts}:last_error={last_exc}") from last_exc


def _build_wait_progress_hook(
    progress_callback: ProgressCallback | None,
    progress_value: float,
    wait_message: str,
    total_attempts: int,
) -> Callable[[int, int], None] | None:
    if progress_callback is None or not wait_message:
        return None

    def _on_wait(attempt: int, elapsed_sec: int) -> None:
        attempt_text = f" / 再試行 {int(attempt)}/{max(1, int(total_attempts))}" if int(attempt) > 1 else ""
        _emit_progress(
            progress_callback,
            progress_value,
            f"{wait_message}{attempt_text} / 応答待ち {int(elapsed_sec)}秒",
        )

    return _on_wait


def _http_get(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    timeout: int = HTTP_TIMEOUT_SEC,
    attempts: int = HTTP_RETRIES,
    progress_callback: ProgressCallback | None = None,
    progress_value: float = 0.0,
    wait_message: str = "",
) -> requests.Response:
    def _request() -> requests.Response:
        try:
            return requests.get(url, headers=headers, params=params, timeout=max(1, int(timeout)))
        except requests.exceptions.SSLError:
            # Some local networks replace netkeiba certificates during filtering.
            # Retry once without verification so the caller can detect block pages
            # instead of silently treating the result as an empty race.
            if "netkeiba.com" not in str(url):
                raise
            try:
                import urllib3  # type: ignore

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
            return requests.get(url, headers=headers, params=params, timeout=max(1, int(timeout)), verify=False)

    return _call_with_retry(
        _request,
        attempts=max(1, int(attempts)),
        retry_sleep_sec=HTTP_RETRY_SLEEP_SEC,
        timeout_sec=max(1, int(timeout)),
        on_wait=_build_wait_progress_hook(progress_callback, progress_value, wait_message, max(1, int(attempts))),
    )


def _keibascraper_call(
    keibascraper: Any,
    method_name: str,
    *args: Any,
    progress_callback: ProgressCallback | None = None,
    progress_value: float = 0.0,
    wait_message: str = "",
) -> Any:
    method = getattr(keibascraper, method_name)
    return _call_with_retry(
        lambda: method(*args),
        attempts=max(1, int(SCRAPER_RETRIES)),
        retry_sleep_sec=SCRAPER_RETRY_SLEEP_SEC,
        timeout_sec=max(1, int(SCRAPER_TIMEOUT_SEC)),
        on_wait=_build_wait_progress_hook(progress_callback, progress_value, wait_message, max(1, int(SCRAPER_RETRIES))),
    )


def _emit_progress(progress_callback: ProgressCallback | None, value: float, message: str) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(max(0.0, min(1.0, float(value))), str(message).strip())
    except Exception:
        return


def _maybe_import_keibascraper() -> Any:
    try:
        import keibascraper  # type: ignore

        return keibascraper
    except Exception as exc:
        raise RuntimeError(
            "keibascraper が未導入です。`pip install keibascraper` を実行してください。"
        ) from exc


def has_keibascraper() -> bool:
    try:
        _maybe_import_keibascraper()
        return True
    except Exception:
        return False


def _first_nonempty(row: Mapping[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    for key in keys:
        if key in row:
            value = row.get(key)
            if value is not None and str(value).strip() not in ("", "nan", "None"):
                return value
    return default


def _normalize_weather(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return "晴"
    return WEATHER_MAP.get(text, text[:2])


def _normalize_track(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return "良"
    return TRACK_MAP.get(text, text)


def _extract_distance(value: Any, fallback: float = 1600.0) -> float:
    if value is None:
        return fallback
    text = str(value)
    m = re.search(r"(\d{3,4})", text)
    if m:
        return float(m.group(1))
    try:
        return float(value)
    except Exception:
        return fallback


def _extract_venue(race_meta: Mapping[str, Any]) -> str:
    raw = _first_nonempty(race_meta, VENUE_KEYS, "")
    return normalize_venue(raw)


def _normalize_race_date_text(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return ""
    m = re.search(r"(\d{4})[/-]?(\d{2})[/-]?(\d{2})", text)
    if not m:
        return text
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _to_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _iter_months(from_day: date, to_day: date) -> Iterable[Tuple[int, int]]:
    y, m = from_day.year, from_day.month
    while True:
        yield y, m
        if y == to_day.year and m == to_day.month:
            break
        m += 1
        if m > 12:
            m = 1
            y += 1


def _race_id_to_date(race_id: str) -> date | None:
    m = re.match(r"^(\d{8})", str(race_id))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except Exception:
        return None


def _list_race_ids(
    keibascraper: Any,
    from_day: date,
    to_day: date,
    cap: int,
    *,
    progress_callback: ProgressCallback | None = None,
    progress_start: float = 0.0,
    progress_span: float = 0.0,
    phase_label: str = "レース一覧を確認",
) -> List[str]:
    ids: List[str] = []
    month_points = list(_iter_months(from_day, to_day))
    for month_idx, (year, month) in enumerate(month_points, start=1):
        if progress_span > 0:
            month_progress = progress_start + (progress_span * ((month_idx - 1) / max(1, len(month_points))))
            _emit_progress(progress_callback, month_progress, f"{phase_label} {month_idx}/{max(1, len(month_points))}ヶ月")
        else:
            month_progress = progress_start
        try:
            race_ids = _keibascraper_call(
                keibascraper,
                "race_list",
                year,
                month,
                progress_callback=progress_callback,
                progress_value=month_progress,
                wait_message=f"{phase_label} {year}/{month:02d}",
            )
        except Exception:
            continue
        for rid in race_ids:
            rid_s = str(rid)
            d = _race_id_to_date(rid_s)
            if d is None:
                continue
            if from_day <= d <= to_day:
                ids.append(rid_s)
                if len(ids) >= cap:
                    return ids
    return ids


def _list_race_ids_netkeiba_daily(from_day: date, to_day: date, cap: int) -> List[str]:
    return [row["race_id"] for row in _list_race_meta_netkeiba_daily(from_day, to_day, cap)]


def _list_race_meta_netkeiba_daily(
    from_day: date,
    to_day: date,
    cap: int,
    *,
    progress_callback: ProgressCallback | None = None,
    progress_start: float = 0.0,
    progress_span: float = 0.0,
    phase_label: str = "レース一覧を確認",
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen: set[str] = set()
    current = from_day
    total_days = max(1, (to_day - from_day).days + 1)
    day_idx = 0
    while current <= to_day:
        day_idx += 1
        day_progress = progress_start + (progress_span * ((day_idx - 1) / total_days)) if progress_span > 0 else progress_start
        _emit_progress(progress_callback, day_progress, f"{phase_label} {day_idx}/{total_days}日")
        date_text = current.strftime("%Y%m%d")
        candidate_urls = [
            f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_text}",
            f"https://race.netkeiba.com/top/race_list.html?kaisai_date={date_text}",
        ]
        html = ""
        for url in candidate_urls:
            try:
                resp = _http_get(
                    url,
                    headers=NETKEIBA_HEADERS,
                    timeout=HTTP_TIMEOUT_SEC,
                    progress_callback=progress_callback,
                    progress_value=day_progress,
                    wait_message=f"{phase_label} {current.strftime('%Y/%m/%d')}",
                )
                resp.raise_for_status()
                html = resp.text
                if "race_id=" in html or "/race/" in html:
                    break
            except Exception:
                html = ""
                continue
        if not html:
            current += timedelta(days=1)
            continue

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = str(a.get("href", ""))
            ids_in_href = re.findall(r"/race/(?:shutuba|result)\.html\?race_id=(\d{12})", href)
            if (not ids_in_href) and ("/race/" in href):
                ids_in_href = re.findall(r"race_id=(\d{12})", href)
            if not ids_in_href:
                continue
            race_name = a.get_text(" ", strip=True)
            for race_id in ids_in_href:
                if race_id in seen:
                    continue
                seen.add(race_id)
                rows.append(
                    {
                        "race_id": race_id,
                        "race_date": current.isoformat(),
                        "race_name": race_name,
                    }
                )
                if len(rows) >= cap:
                    return rows
        current += timedelta(days=1)
    return rows


def _looks_synthetic_name(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    return bool(re.match(r"^(Horse|Jockey|Trainer)_\d+$", t))


def _looks_synthetic_entries(rows: Sequence[Mapping[str, Any]]) -> bool:
    if not rows:
        return True
    check_rows = list(rows[: min(4, len(rows))])
    if not check_rows:
        return True
    synthetic_count = 0
    for row in check_rows:
        horse = str(row.get("horse", "")).strip()
        jockey = str(row.get("jockey", "")).strip()
        if _looks_synthetic_name(horse) or _looks_synthetic_name(jockey):
            synthetic_count += 1
    return synthetic_count >= max(1, len(check_rows) // 2)


def _looks_synthetic_df(df: pd.DataFrame) -> bool:
    if df.empty:
        return True
    if "horse" not in df.columns:
        return False
    if "jockey" in df.columns:
        mini = df[["horse", "jockey"]].head(4).to_dict(orient="records")
    else:
        mini = df[["horse"]].head(4).to_dict(orient="records")
    return _looks_synthetic_entries(mini)


def _prune_weekly_entries(df: pd.DataFrame, today: date, days_back: int = 1, days_ahead: int = 21) -> pd.DataFrame:
    if df.empty or "race_id" not in df.columns:
        return df
    out = df.copy()
    lower = today - timedelta(days=max(0, int(days_back)))
    upper = today + timedelta(days=max(1, int(days_ahead)))
    lower_fetch = today - timedelta(days=max(1, int(days_ahead)))

    keep_mask: List[bool] = []
    for _, row in out.iterrows():
        rid = str(row.get("race_id", "")).strip()

        fetched_text = str(row.get("fetched_date", "")).strip()
        fetched_day: date | None = None
        if fetched_text:
            try:
                fetched_day = datetime.strptime(fetched_text[:10], "%Y-%m-%d").date()
            except Exception:
                fetched_day = None
        if fetched_day is not None:
            keep_mask.append(lower_fetch <= fetched_day <= today)
            continue

        auto_m = re.match(r"^AUTO(\d{8})$", rid, flags=re.IGNORECASE)
        if auto_m:
            horse = str(row.get("horse", "")).strip()
            jockey = str(row.get("jockey", "")).strip()
            if _looks_synthetic_name(horse) or _looks_synthetic_name(jockey):
                keep_mask.append(False)
                continue
            try:
                auto_day = datetime.strptime(auto_m.group(1), "%Y%m%d").date()
            except Exception:
                auto_day = None
            if auto_day is not None:
                keep_mask.append(lower <= auto_day <= upper)
                continue

        # Non-AUTO race_id often does not embed calendar date (e.g. JRA format),
        # so when fetched_date is missing we keep the row to avoid false pruning.
        keep_mask.append(True)

    if len(keep_mask) != len(out):
        return out
    return out.loc[keep_mask].reset_index(drop=True)


def _extract_race_meta_text(soup: BeautifulSoup) -> str:
    selectors = [
        "div.RaceData01",
        "div.RaceData02",
        "div.RaceList_Item02",
        "div.RaceName",
    ]
    parts: List[str] = []
    for sel in selectors:
        for node in soup.select(sel):
            txt = node.get_text(" ", strip=True)
            if txt:
                parts.append(txt)
    return " ".join(parts)


def _extract_meta_from_text(meta_text: str) -> Tuple[str, str, float]:
    weather = "晴"
    track = "良"
    distance = 1600.0

    m_weather = re.search(r"天候\s*:\s*([^\s/]+)", meta_text)
    if m_weather:
        weather = _normalize_weather(m_weather.group(1))

    m_track = re.search(r"馬場\s*:\s*([^\s/]+)", meta_text)
    if m_track:
        track = _normalize_track(m_track.group(1))

    distance = _extract_distance(meta_text, fallback=1600.0)
    return weather, track, distance


def _extract_venue_from_soup(soup: BeautifulSoup) -> str:
    texts = []
    for sel in ("h1", "h2", "title", "div.RaceNum", "div.RaceName", "div.RaceData02"):
        for node in soup.select(sel):
            txt = node.get_text(" ", strip=True)
            if txt:
                texts.append(txt)
    whole = " ".join(texts)
    return normalize_venue(whole)


def _extract_race_name_from_soup(soup: BeautifulSoup) -> str:
    for sel in ("h1.RaceName", "div.RaceName", "h1", "title"):
        node = soup.select_one(sel)
        if node is None:
            continue
        txt = node.get_text(" ", strip=True)
        if txt:
            return re.sub(r"\s+", " ", txt).strip()
    return ""


def _entry_rows_from_netkeiba_html(race_id: str, html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    meta_text = _extract_race_meta_text(soup)
    weather, track, distance = _extract_meta_from_text(meta_text)
    venue = _extract_venue_from_soup(soup)
    race_name = _extract_race_name_from_soup(soup)

    rows: List[Dict[str, Any]] = []
    tr_nodes = soup.select("table.Shutuba_Table tbody tr")
    if not tr_nodes:
        tr_nodes = soup.select("table.RaceTable01 tbody tr")

    for tr in tr_nodes:
        horse_node = tr.select_one("span.HorseName a") or tr.select_one("td.HorseInfo a") or tr.select_one("td.Horse a")
        jockey_node = tr.select_one("td.Jockey a") or tr.select_one("td.Jockey")
        trainer_node = tr.select_one("td.Trainer a") or tr.select_one("td.Trainer")
        if horse_node is None:
            # fallback: horse profile links usually include /horse/
            for a in tr.select("a[href]"):
                href = str(a.get("href", ""))
                if "/horse/" in href:
                    horse_node = a
                    break
        if jockey_node is None:
            for a in tr.select("a[href]"):
                href = str(a.get("href", ""))
                if "/jockey/" in href:
                    jockey_node = a
                    break

        horse = horse_node.get_text(strip=True) if horse_node is not None else ""
        jockey = jockey_node.get_text(strip=True) if jockey_node is not None else ""
        trainer = trainer_node.get_text(strip=True) if trainer_node is not None else ""
        if not horse:
            continue

        gate_node = tr.select_one("td.Umaban") or tr.select_one("td[class*='Umaban']") or tr.select_one("td.Waku")
        gate = _to_float(gate_node.get_text(strip=True) if gate_node is not None else float("nan"), float("nan"))
        # safer numeric extraction by text
        if pd.isna(gate):
            raw_gate = tr.get_text(" ", strip=True)
            m_gate = re.search(r"\b(\d{1,2})\b", raw_gate)
            gate = float(m_gate.group(1)) if m_gate else float("nan")

        odds_txt = (tr.select_one("td.Odds") or tr.select_one("td[class*='Odds']"))
        odds = _to_float(odds_txt.get_text(strip=True) if odds_txt else float("nan"))
        pop_txt = tr.select_one("td.Popular") or tr.select_one("td[class*='Popular']") or tr.select_one("td[class*='Ninki']")
        popularity = _to_int(pop_txt.get_text(strip=True) if pop_txt is not None else 0, 0)

        row = {
            "race_id": race_id,
            "horse": horse,
            "jockey": jockey,
            "trainer": trainer,
            "weather": weather,
            "track_condition": track,
            "distance": distance,
            "venue": venue,
            "race_name": race_name,
            "gate": gate,
            "odds": odds,
            "place_odds": float("nan"),
            "popularity": popularity,
            "form_score": 50.0,
            "condition_score": 50.0,
            "weight_diff": 0.0,
            "paddock_score": 50.0,
            "odds_shift": 0.0,
        }
        rows.append(row)
    return rows


def _entry_rows_from_netkeiba_page(
    race_id: str,
    race_date: str = "",
    *,
    progress_callback: ProgressCallback | None = None,
    progress_value: float = 0.0,
    wait_message: str = "",
) -> List[Dict[str, Any]]:
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    try:
        resp = _http_get(
            url,
            headers=NETKEIBA_HEADERS,
            timeout=HTTP_TIMEOUT_SEC,
            progress_callback=progress_callback,
            progress_value=progress_value,
            wait_message=wait_message or f"出走表取得 {race_id}",
        )
        resp.raise_for_status()
    except Exception:
        return []
    try:
        encoding = getattr(resp, "apparent_encoding", None) or getattr(resp, "encoding", None) or "utf-8"
        html = resp.content.decode(encoding, errors="replace")
        rows = _entry_rows_from_netkeiba_html(race_id, html)
    except Exception:
        return []
    if race_date:
        for row in rows:
            if not str(row.get("race_date", "")).strip():
                row["race_date"] = race_date
    return rows


def _decode_response_html(resp: requests.Response) -> str:
    encoding = getattr(resp, "apparent_encoding", None) or getattr(resp, "encoding", None) or "utf-8"
    return resp.content.decode(encoding, errors="replace")


def _is_netkeiba_block_page(html: str, final_url: str = "") -> bool:
    text = str(html or "")
    url = str(final_url or "")
    return (
        "block.wifi-cloud2.jp" in url
        or "本サービスのポリシーに反するサイト" in text
        or "ブロックさせて頂きました" in text
    )


def _history_rows_from_netkeiba_result_html(race_id: str, html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    meta_text = _extract_race_meta_text(soup)
    weather, track, distance = _extract_meta_from_text(meta_text)
    venue = _extract_venue_from_soup(soup)
    race_name = _extract_race_name_from_soup(soup)

    tr_nodes = soup.select("table.RaceTable01 tbody tr")
    if not tr_nodes:
        tr_nodes = soup.select("table.ResultTable tbody tr")
    if not tr_nodes:
        tr_nodes = soup.select("table[class*='RaceTable'] tbody tr")

    rows: List[Dict[str, Any]] = []
    for tr in tr_nodes:
        horse_node = (
            tr.select_one("span.HorseName a")
            or tr.select_one("td.Horse_Info a")
            or tr.select_one("td.HorseInfo a")
            or tr.select_one("td.Horse a")
        )
        if horse_node is None:
            for a in tr.select("a[href]"):
                if "/horse/" in str(a.get("href", "")):
                    horse_node = a
                    break
        horse = horse_node.get_text(strip=True) if horse_node is not None else ""
        if not horse:
            continue

        rank_node = tr.select_one("td.Rank") or tr.select_one("td[class*='Rank']")
        finish = _to_int(rank_node.get_text(strip=True) if rank_node is not None else "", 0)
        if finish <= 0:
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            for cell in cells[:3]:
                finish = _to_int(cell, 0)
                if finish > 0:
                    break
        if finish <= 0:
            continue

        jockey_node = tr.select_one("td.Jockey a") or tr.select_one("td.Jockey") or tr.select_one("td[class*='Jockey'] a")
        trainer_node = tr.select_one("td.Trainer a") or tr.select_one("td.Trainer") or tr.select_one("td[class*='Trainer'] a")
        gate_node = tr.select_one("td.Umaban") or tr.select_one("td[class*='Umaban']")
        odds_node = tr.select_one("td.Odds") or tr.select_one("td[class*='Odds']")
        pop_node = tr.select_one("td.Popular") or tr.select_one("td[class*='Popular']") or tr.select_one("td[class*='Ninki']")

        rows.append(
            {
                "race_id": race_id,
                "horse": horse,
                "jockey": jockey_node.get_text(strip=True) if jockey_node is not None else "",
                "trainer": trainer_node.get_text(strip=True) if trainer_node is not None else "",
                "weather": weather,
                "track_condition": track,
                "distance": distance,
                "finish": finish,
                "gate": _to_float(gate_node.get_text(strip=True) if gate_node is not None else float("nan"), float("nan")),
                "odds": _to_float(odds_node.get_text(strip=True) if odds_node is not None else float("nan")),
                "place_odds": float("nan"),
                "form_score": 50.0,
                "condition_score": 50.0,
                "weight_diff": 0.0,
                "paddock_score": 50.0,
                "odds_shift": 0.0,
                "venue": venue,
                "race_name": race_name,
                "race_date": "",
                "popularity": _to_int(pop_node.get_text(strip=True) if pop_node is not None else 0, 0),
            }
        )
    return rows


def _history_rows_from_netkeiba_result_page(
    race_id: str,
    *,
    progress_callback: ProgressCallback | None = None,
    progress_value: float = 0.0,
    wait_message: str = "",
) -> Tuple[List[Dict[str, Any]], str]:
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    try:
        resp = _http_get(
            url,
            headers=NETKEIBA_HEADERS,
            timeout=HTTP_TIMEOUT_SEC,
            progress_callback=progress_callback,
            progress_value=progress_value,
            wait_message=wait_message or f"結果HTML取得 {race_id}",
        )
        resp.raise_for_status()
    except Exception as exc:
        return [], f"netkeiba_result_fetch_failed:{type(exc).__name__}"
    html = _decode_response_html(resp)
    if _is_netkeiba_block_page(html, getattr(resp, "url", "")):
        return [], "netkeiba_result_blocked"
    rows = _history_rows_from_netkeiba_result_html(race_id, html)
    if not rows:
        return [], "netkeiba_result_empty"
    return rows, "netkeiba_result_html"


def _overlay_entry_meta(
    rows: Sequence[Mapping[str, Any]],
    race_date: str = "",
    race_name: str = "",
    html_rows: Sequence[Mapping[str, Any]] | None = None,
    meta_rows: Sequence[Mapping[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    out = [dict(row) for row in rows]
    if not out:
        return out

    meta_row: Mapping[str, Any] = {}
    if meta_rows:
        meta_row = meta_rows[0]

    meta_distance = _extract_distance(
        _first_nonempty(meta_row, ["distance", "距離", "race_course"], ""),
        fallback=float("nan"),
    )
    meta_weather = _normalize_weather(_first_nonempty(meta_row, ["weather", "天候"], ""))
    meta_track = _normalize_track(_first_nonempty(meta_row, ["track_condition", "track", "馬場状態", "馬場"], ""))
    meta_venue = _extract_venue(meta_row)

    html_row: Mapping[str, Any] = html_rows[0] if html_rows else {}
    base_row: Mapping[str, Any] = out[0]
    html_distance = _to_float(html_row.get("distance", float("nan")), float("nan"))
    row_distance = _to_float(base_row.get("distance", float("nan")), float("nan"))
    html_weather = str(html_row.get("weather", "")).strip()
    row_weather = str(base_row.get("weather", "")).strip()
    html_track = str(html_row.get("track_condition", "")).strip()
    row_track = str(base_row.get("track_condition", "")).strip()
    html_venue = str(html_row.get("venue", "")).strip()
    row_venue = str(base_row.get("venue", "")).strip()
    html_race_name = str(html_row.get("race_name", "")).strip()
    row_race_name = str(base_row.get("race_name", "")).strip()

    chosen_distance = html_distance
    if pd.isna(chosen_distance):
        chosen_distance = row_distance
    if pd.isna(chosen_distance):
        chosen_distance = meta_distance
    chosen_weather = html_weather or row_weather or meta_weather
    chosen_track = html_track or row_track or meta_track
    chosen_venue = html_venue or row_venue or meta_venue
    chosen_race_name = html_race_name or row_race_name or str(race_name or "").strip()

    for row in out:
        if race_date:
            row["race_date"] = race_date
        if chosen_race_name:
            row["race_name"] = chosen_race_name
        if chosen_venue:
            row["venue"] = chosen_venue
        if chosen_weather:
            row["weather"] = chosen_weather
        if chosen_track:
            row["track_condition"] = chosen_track
        if not pd.isna(chosen_distance):
            row["distance"] = chosen_distance
    return out


def _payload_sections(payload: Any) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    race_rows: Any = []
    entry_rows: Any = []
    if isinstance(payload, Mapping):
        race_rows = payload.get("race", []) or []
        entry_rows = payload.get("entry", []) or []
    elif isinstance(payload, (tuple, list)):
        if len(payload) >= 2:
            race_rows = payload[0] if payload[0] is not None else []
            entry_rows = payload[1] if payload[1] is not None else []

    def _normalize_rows(rows: Any) -> List[Mapping[str, Any]]:
        if rows is None:
            return []
        if isinstance(rows, pd.DataFrame):
            return rows.to_dict(orient="records")
        if isinstance(rows, Mapping):
            return [rows]
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, Mapping)]
        if isinstance(rows, tuple):
            return [r for r in rows if isinstance(r, Mapping)]
        return []

    return _normalize_rows(race_rows), _normalize_rows(entry_rows)


def _entry_rows_from_payload(race_id: str, payload: Any) -> List[Dict[str, Any]]:
    race_rows, entry_rows = _payload_sections(payload)

    race_meta = race_rows[0] if race_rows else {}
    weather = _normalize_weather(_first_nonempty(race_meta, ["weather", "天候"], "晴"))
    track = _normalize_track(
        _first_nonempty(race_meta, ["track_condition", "track", "馬場状態", "馬場"], "良")
    )
    distance = _extract_distance(_first_nonempty(race_meta, ["distance", "距離", "race_course"], 1600))
    venue = _extract_venue(race_meta)
    race_name = str(_first_nonempty(race_meta, ["race_name", "name", "レース名"], "")).strip()
    race_date = _normalize_race_date_text(_first_nonempty(race_meta, ["race_date", "date", "開催日", "日時"], ""))

    out: List[Dict[str, Any]] = []
    for row in entry_rows:
        horse = str(_first_nonempty(row, ["horse_name", "horse", "馬名"], "")).strip()
        jockey = str(_first_nonempty(row, ["jockey", "jockey_name", "騎手"], "")).strip()
        trainer = str(_first_nonempty(row, ["trainer", "trainer_name", "調教師"], "")).strip()
        if not horse:
            continue
        out.append(
            {
                "race_id": race_id,
                "horse": horse,
                "jockey": jockey,
                "trainer": trainer,
                "weather": weather,
                "track_condition": track,
                "distance": distance,
                "venue": venue,
                "race_name": race_name,
                "race_date": race_date,
                "gate": _to_float(_first_nonempty(row, ["frame_number", "frame", "枠", "horse_number", "馬番"], float("nan"))),
                "odds": _to_float(_first_nonempty(row, ["odds", "win_odds", "単勝"], float("nan"))),
                "place_odds": _to_float(_first_nonempty(row, ["place_odds", "複勝"], float("nan"))),
                "popularity": _to_int(_first_nonempty(row, ["popularity", "popular", "人気", "ninki"], 0), 0),
                "form_score": _to_float(_first_nonempty(row, ["form_score", "調子"], 50.0), 50.0),
                "condition_score": _to_float(_first_nonempty(row, ["condition_score", "状態"], 50.0), 50.0),
                "weight_diff": _to_float(_first_nonempty(row, ["weight_diff", "増減", "馬体重増減"], 0.0), 0.0),
                "paddock_score": _to_float(_first_nonempty(row, ["paddock_score", "パドック"], 50.0), 50.0),
                "odds_shift": 0.0,
            }
        )
    return out


def _history_rows_from_payload(race_id: str, payload: Any) -> List[Dict[str, Any]]:
    rows = _entry_rows_from_payload(race_id, payload)
    _, entry_rows = _payload_sections(payload)

    out: List[Dict[str, Any]] = []
    for base, entry in zip(rows, entry_rows):
        finish = _to_int(_first_nonempty(entry, ["rank", "finish", "着順"], 0), 0)
        if finish <= 0:
            continue
        row = dict(base)
        row["finish"] = finish
        row["odds"] = _to_float(_first_nonempty(entry, ["odds", "win_odds", "単勝"], row["odds"]))
        row["place_odds"] = _to_float(_first_nonempty(entry, ["place_odds", "複勝"], row["place_odds"]))
        row["odds_shift"] = _to_float(_first_nonempty(entry, ["odds_shift", "直前オッズ差"], 0.0), 0.0)
        out.append(row)
    return out


def _parse_payout_value(value: Any) -> float:
    text = str(value).replace(",", "").replace("円", "").strip()
    if not text:
        return float("nan")
    m = re.search(r"(\d+)", text)
    if not m:
        return float("nan")
    return float(m.group(1))


def _payout_rows_from_payload(race_id: str, payload: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def _visit(node: Any, current_bet_type: str = "") -> None:
        if isinstance(node, Mapping):
            detected_bet_type = normalize_bet_type(
                _first_nonempty(node, ["bet_type", "type", "券種", "式別", "kind", "name"], "")
            )
            active_bet_type = detected_bet_type or current_bet_type
            payout_value = _first_nonempty(node, ["payout", "payoff", "refund", "払戻", "配当"], None)
            ticket_value = _first_nonempty(
                node,
                ["ticket", "numbers", "number", "horse_number", "horse_numbers", "馬番", "組番", "combination", "result"],
                None,
            )
            popularity_value = _first_nonempty(node, ["popularity", "ninki", "人気"], None)
            if active_bet_type and payout_value not in (None, "") and ticket_value not in (None, ""):
                ticket_text = normalize_ticket_text(ticket_value, active_bet_type)
                payout_amount = _parse_payout_value(payout_value)
                if ticket_text and pd.notna(payout_amount):
                    rows.append(
                        {
                            "race_id": race_id,
                            "bet_type": active_bet_type,
                            "ticket": ticket_text,
                            "payout": payout_amount,
                            "popularity": _to_int(popularity_value, 0),
                            "source": "payload",
                        }
                    )
            for key, value in node.items():
                next_bet_type = active_bet_type or normalize_bet_type(key)
                _visit(value, next_bet_type)
        elif isinstance(node, (list, tuple)):
            for item in node:
                _visit(item, current_bet_type)

    _visit(payload)
    if not rows:
        return []
    out = pd.DataFrame(rows)
    out["_bet_order"] = out["bet_type"].map(lambda value: BET_TYPE_ORDER.index(value) if value in BET_TYPE_ORDER else 99)
    out = out.sort_values(["_bet_order", "ticket"]).drop(columns=["_bet_order"])
    out = out.drop_duplicates(subset=["race_id", "bet_type", "ticket"], keep="last")
    return out.to_dict(orient="records")


def _payout_rows_from_netkeiba_result_html(race_id: str, html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, Any]] = []
    for table in soup.find_all("table"):
        current_bet_type = ""
        for tr in table.find_all("tr"):
            cells = [re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip() for cell in tr.find_all(["th", "td"])]
            cells = [cell for cell in cells if cell]
            if not cells:
                continue
            bet_type_candidate = normalize_bet_type(cells[0])
            rest = cells[1:] if bet_type_candidate else cells
            if bet_type_candidate:
                current_bet_type = bet_type_candidate
            if not current_bet_type or len(rest) < 2:
                continue
            ticket_text = normalize_ticket_text(rest[0], current_bet_type)
            payout_amount = _parse_payout_value(rest[1])
            popularity_value = _to_int(rest[2], 0) if len(rest) > 2 else 0
            if ticket_text and pd.notna(payout_amount):
                rows.append(
                    {
                        "race_id": race_id,
                        "bet_type": current_bet_type,
                        "ticket": ticket_text,
                        "payout": payout_amount,
                        "popularity": popularity_value,
                        "source": "netkeiba_html",
                    }
                )
    if not rows:
        return []
    out = pd.DataFrame(rows)
    out["_bet_order"] = out["bet_type"].map(lambda value: BET_TYPE_ORDER.index(value) if value in BET_TYPE_ORDER else 99)
    out = out.sort_values(["_bet_order", "ticket"]).drop(columns=["_bet_order"])
    out = out.drop_duplicates(subset=["race_id", "bet_type", "ticket"], keep="last")
    return out.to_dict(orient="records")


def _payout_rows_from_netkeiba_result_page(
    race_id: str,
    *,
    progress_callback: ProgressCallback | None = None,
    progress_value: float = 0.0,
    wait_message: str = "",
) -> List[Dict[str, Any]]:
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    try:
        resp = _http_get(
            url,
            headers=NETKEIBA_HEADERS,
            timeout=HTTP_TIMEOUT_SEC,
            progress_callback=progress_callback,
            progress_value=progress_value,
            wait_message=wait_message or f"払戻取得 {race_id}",
        )
        resp.raise_for_status()
    except Exception:
        return []
    return _payout_rows_from_netkeiba_result_html(race_id, resp.text)


def _dedupe_rows(df: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    missing = [k for k in keys if k not in out.columns]
    if missing:
        return out.reset_index(drop=True)
    out["_dedupe_key"] = out[keys].astype(str).agg("|".join, axis=1)
    out = out.drop_duplicates(subset=["_dedupe_key"], keep="last").drop(columns=["_dedupe_key"])
    return out.reset_index(drop=True)


def _replace_rows_by_race_ids(existing_df: pd.DataFrame, fresh_df: pd.DataFrame) -> pd.DataFrame:
    if existing_df.empty:
        return fresh_df.reset_index(drop=True)
    if fresh_df.empty:
        return existing_df.reset_index(drop=True)
    if "race_id" not in existing_df.columns or "race_id" not in fresh_df.columns:
        return pd.concat([existing_df, fresh_df], ignore_index=True)
    fresh_ids = {
        str(rid).strip()
        for rid in fresh_df["race_id"].dropna().astype(str).tolist()
        if str(rid).strip()
    }
    if not fresh_ids:
        return pd.concat([existing_df, fresh_df], ignore_index=True)
    existing_race_ids = existing_df["race_id"].astype("string").fillna("").astype(str).str.strip()
    keep_existing = existing_df[~existing_race_ids.isin(fresh_ids)].copy()
    return pd.concat([keep_existing, fresh_df], ignore_index=True).reset_index(drop=True)


def _load_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=CSV_TEXT_DTYPES, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _load_first_existing(paths: Sequence[Path]) -> Tuple[pd.DataFrame, Path | None]:
    for p in paths:
        df = _load_if_exists(p)
        if not df.empty:
            return df, p
    return pd.DataFrame(), None


def _max_race_date_from_history(history_df: pd.DataFrame) -> date | None:
    if history_df.empty or "race_id" not in history_df.columns:
        return None
    parsed = [
        _race_id_to_date(str(rid))
        for rid in history_df["race_id"].dropna().astype(str).tolist()
    ]
    dates = [d for d in parsed if d is not None]
    if not dates:
        return None
    return max(dates)


def _file_age_hours(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime)
    except Exception:
        return None
    delta = datetime.now() - modified
    return max(0.0, delta.total_seconds() / 3600.0)


def fetch_auto_data(
    data_dir: Path,
    *,
    months_back: int = 24,
    weekly_days_ahead: int = 7,
    incremental: bool = True,
    full_refresh: bool = False,
    history_backfill_days: int = 14,
    append_only: bool = False,
    entries_cache_hours: int = 0,
    update_history: bool = True,
    update_entries: bool = True,
    auto_forecast_weather: bool = True,
    weather_cache_hours: int = 6,
    fallback_max_days: int = 120,
    cap_history_races: int = 3000,
    cap_weekly_races: int = 200,
    run_tuning: bool = False,
    tuning_trials: int = 40,
    tuning_val_races: int = 30,
    tuning_simulations: int = 1500,
    history_race_id_allowlist: Sequence[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> AutoUpdateReport:
    data_dir.mkdir(parents=True, exist_ok=True)
    _emit_progress(progress_callback, 0.02, "更新の準備中")

    history_path = data_dir / "history_auto.csv"
    entries_path = data_dir / "weekly_entries_auto.csv"
    payouts_path = data_dir / "payouts_auto.csv"
    weights_path = data_dir / "keiba_best_weights.json"
    feature_archive_path = data_dir / "prediction_feature_archive.csv"

    history_existing = _load_if_exists(history_path)
    entries_existing = _load_if_exists(entries_path)
    payouts_existing = _load_if_exists(payouts_path)
    _emit_progress(progress_callback, 0.08, "既存データを読み込み")
    if not entries_existing.empty:
        entries_existing = _prune_weekly_entries(entries_existing, date.today())

    keibascraper = None
    if update_history or update_entries:
        keibascraper = _maybe_import_keibascraper()
    _emit_progress(progress_callback, 0.12, "取得元を初期化")

    today = date.today()
    base_from_history = today - timedelta(days=max(30, months_back * 30))
    from_history = base_from_history
    to_history = today
    notes: List[str] = []

    history_rows: List[Dict[str, Any]] = []
    weekly_rows: List[Dict[str, Any]] = []
    payout_rows: List[Dict[str, Any]] = []
    history_race_ids: List[str] = []
    weekly_race_ids: List[str] = []
    weekly_meta_by_race_id: Dict[str, Dict[str, str]] = {}

    if update_history:
        _emit_progress(progress_callback, 0.18, "履歴レース一覧を確認")
        explicit_history_race_ids = []
        if history_race_id_allowlist is not None:
            explicit_history_race_ids = [str(rid).strip() for rid in history_race_id_allowlist if str(rid).strip()]
            explicit_history_race_ids = list(dict.fromkeys(explicit_history_race_ids))
        latest = _max_race_date_from_history(history_existing)
        if explicit_history_race_ids:
            history_race_ids = explicit_history_race_ids[: max(1, int(cap_history_races))]
            notes.append(f"history_mode=allowlist:{len(history_race_ids)}")
            _emit_progress(progress_callback, 0.22, f"履歴レース一覧を確認 対象 {len(history_race_ids)} レース")
        elif incremental and (not full_refresh):
            if latest is not None:
                backfill_days = max(0 if append_only else 1, int(history_backfill_days))
                from_history = max(base_from_history, latest - timedelta(days=backfill_days))
                mode_name = "append" if append_only else "incremental"
                notes.append(f"history_mode={mode_name}:{from_history.isoformat()}-{to_history.isoformat()}")
            else:
                notes.append("history_mode=incremental:fallback_full_window")
        else:
            notes.append(f"history_mode=full:{from_history.isoformat()}-{to_history.isoformat()}")

        history_fetch_skipped = False
        if explicit_history_race_ids:
            pass
        elif latest is not None and append_only and latest >= to_history:
            notes.append("history_up_to_date:skip_fetch")
            history_fetch_skipped = True
        else:
            history_race_ids = _list_race_ids(
                keibascraper,
                from_history,
                to_history,
                cap=cap_history_races,
                progress_callback=progress_callback,
                progress_start=0.18,
                progress_span=0.06,
                phase_label="履歴レース一覧を確認",
            )
            if not history_race_ids:
                fb_from = from_history
                if (to_history - from_history).days > max(1, fallback_max_days):
                    fb_from = to_history - timedelta(days=max(1, fallback_max_days))
                    notes.append(f"history_fallback_window_limited:{fb_from.isoformat()}-{to_history.isoformat()}")
                history_meta_rows = _list_race_meta_netkeiba_daily(
                    fb_from,
                    to_history,
                    cap=cap_history_races,
                    progress_callback=progress_callback,
                    progress_start=0.22,
                    progress_span=0.06,
                    phase_label="履歴レース一覧を代替取得",
                )
                history_race_ids = [row["race_id"] for row in history_meta_rows]
                notes.append(f"history_race_ids_fallback_count={len(history_race_ids)}")

        if not history_fetch_skipped:
            if append_only and (not history_existing.empty) and ("race_id" in history_existing.columns):
                existing_ids = set(history_existing["race_id"].dropna().astype(str).tolist())
                before = len(history_race_ids)
                history_race_ids = [rid for rid in history_race_ids if rid not in existing_ids]
                skipped = before - len(history_race_ids)
                if skipped > 0:
                    notes.append(f"history_append_skip_existing={skipped}")

            for race_idx, rid in enumerate(history_race_ids, start=1):
                history_ratio = 0.26 + (0.30 * (race_idx / max(1, len(history_race_ids))))
                _emit_progress(progress_callback, history_ratio, f"履歴結果を取得中 {race_idx}/{max(1, len(history_race_ids))}")
                try:
                    payload = _keibascraper_call(
                        keibascraper,
                        "load",
                        "result",
                        rid,
                        progress_callback=progress_callback,
                        progress_value=history_ratio,
                        wait_message=f"履歴結果を取得中 {race_idx}/{max(1, len(history_race_ids))}",
                    )
                except Exception:
                    try:
                        payload = _keibascraper_call(
                            keibascraper,
                            "load",
                            "entry",
                            rid,
                            progress_callback=progress_callback,
                            progress_value=history_ratio,
                            wait_message=f"履歴結果を代替取得中 {race_idx}/{max(1, len(history_race_ids))}",
                        )
                    except Exception:
                        notes.append(f"history_fetch_failed:{rid}")
                        continue
                try:
                    parsed_history_rows = _history_rows_from_payload(rid, payload)
                    if not parsed_history_rows:
                        parsed_history_rows, html_status = _history_rows_from_netkeiba_result_page(
                            rid,
                            progress_callback=progress_callback,
                            progress_value=history_ratio,
                            wait_message=f"結果HTMLを取得中 {race_idx}/{max(1, len(history_race_ids))}",
                        )
                        if parsed_history_rows:
                            notes.append(f"history_html_result:{rid}:{len(parsed_history_rows)}")
                        else:
                            notes.append(f"history_empty_result:{rid}:{html_status}")
                    history_rows.extend(parsed_history_rows)
                    race_payout_rows = _payout_rows_from_payload(rid, payload)
                    if not race_payout_rows:
                        race_payout_rows = _payout_rows_from_netkeiba_result_page(
                            rid,
                            progress_callback=progress_callback,
                            progress_value=history_ratio,
                            wait_message=f"払戻を取得中 {race_idx}/{max(1, len(history_race_ids))}",
                        )
                    payout_rows.extend(race_payout_rows)
                except Exception as exc:
                    notes.append(f"history_skip:{rid}:{exc}")
        _emit_progress(progress_callback, 0.56, "履歴結果の取得が完了")

    update_entries_now = bool(update_entries)
    if update_entries_now and entries_cache_hours > 0 and (not full_refresh):
        age_h = _file_age_hours(entries_path)
        if age_h is not None and age_h < float(entries_cache_hours):
            update_entries_now = False
            notes.append(f"weekly_cache_hit:{age_h:.2f}h<{entries_cache_hours}h")

    if update_entries_now:
        _emit_progress(progress_callback, 0.60, "今週レース一覧を確認")
        weekly_from = today
        weekly_to = today + timedelta(days=max(1, weekly_days_ahead))
        weekly_race_ids = _list_race_ids(
            keibascraper,
            weekly_from,
            weekly_to,
            cap=cap_weekly_races,
            progress_callback=progress_callback,
            progress_start=0.60,
            progress_span=0.04,
            phase_label="今週レース一覧を確認",
        )
        if not weekly_race_ids:
            weekly_meta_rows = _list_race_meta_netkeiba_daily(
                weekly_from,
                weekly_to,
                cap=cap_weekly_races,
                progress_callback=progress_callback,
                progress_start=0.62,
                progress_span=0.04,
                phase_label="今週レース一覧を代替取得",
            )
            weekly_race_ids = [row["race_id"] for row in weekly_meta_rows]
            weekly_meta_by_race_id = {row["race_id"]: row for row in weekly_meta_rows}
            notes.append(f"weekly_race_ids_fallback_count={len(weekly_race_ids)}")

        for race_idx, rid in enumerate(weekly_race_ids, start=1):
            weekly_ratio = 0.68 + (0.16 * (race_idx / max(1, len(weekly_race_ids))))
            _emit_progress(progress_callback, weekly_ratio, f"今週出走表を取得中 {race_idx}/{max(1, len(weekly_race_ids))}")
            race_meta = weekly_meta_by_race_id.get(rid, {})
            race_date_meta = str(race_meta.get("race_date", "")).strip()
            race_name_meta = str(race_meta.get("race_name", "")).strip()
            parsed_rows: List[Dict[str, Any]] = []
            try:
                payload = _keibascraper_call(
                    keibascraper,
                    "load",
                    "entry",
                    rid,
                    progress_callback=progress_callback,
                    progress_value=weekly_ratio,
                    wait_message=f"今週出走表を取得中 {race_idx}/{max(1, len(weekly_race_ids))}",
                )
                parsed_rows = _entry_rows_from_payload(rid, payload)
            except Exception as exc:
                notes.append(f"weekly_load_skip:{rid}:{exc}")
                parsed_rows = []

            synthetic_rows = _looks_synthetic_entries(parsed_rows) if parsed_rows else False
            if (not parsed_rows) or synthetic_rows:
                fallback_rows = _entry_rows_from_netkeiba_page(
                    rid,
                    race_date=race_date_meta,
                    progress_callback=progress_callback,
                    progress_value=weekly_ratio,
                    wait_message=f"今週出走表を代替取得中 {race_idx}/{max(1, len(weekly_race_ids))}",
                )
                if fallback_rows:
                    parsed_rows = fallback_rows
                    notes.append(f"weekly_netkeiba_html_fallback:{rid}:{len(fallback_rows)}")
                elif synthetic_rows:
                    notes.append(f"weekly_skip_synthetic:{rid}")
                    parsed_rows = []
            elif race_date_meta or race_name_meta:
                html_rows = _entry_rows_from_netkeiba_page(
                    rid,
                    race_date=race_date_meta,
                    progress_callback=progress_callback,
                    progress_value=weekly_ratio,
                    wait_message=f"今週出走表を補完中 {race_idx}/{max(1, len(weekly_race_ids))}",
                )
                if html_rows:
                    parsed_rows = _overlay_entry_meta(
                        parsed_rows,
                        race_date=race_date_meta,
                        race_name=race_name_meta,
                        html_rows=html_rows,
                        meta_rows=_payload_sections(payload)[0],
                    )
                    notes.append(f"weekly_netkeiba_html_overlay:{rid}")

            if not parsed_rows:
                notes.append(f"weekly_parse_skip:{rid}:no_rows")
                continue
            for row in parsed_rows:
                if race_date_meta and (not str(row.get("race_date", "")).strip()):
                    row["race_date"] = race_date_meta
                if race_name_meta and (not str(row.get("race_name", "")).strip()):
                    row["race_name"] = race_name_meta
            weekly_rows.extend(parsed_rows)
        _emit_progress(progress_callback, 0.84, "今週出走表の取得が完了")

    _emit_progress(progress_callback, 0.88, "取得結果を整理")
    history_new = pd.DataFrame(history_rows)
    weekly_new = pd.DataFrame(weekly_rows)
    weekly_effective = weekly_new.copy()
    if not weekly_new.empty:
        weekly_new["fetched_date"] = today.isoformat()

    if history_new.empty and history_existing.empty:
        fallback_history, src = _load_first_existing(
            [
                data_dir / "jra_history_normalized.csv",
                data_dir / "jra_history_raw.csv",
            ]
        )
        if not fallback_history.empty:
            history_new = fallback_history.copy()
            notes.append(f"history_local_fallback={src}")

    if weekly_new.empty and entries_existing.empty:
        fallback_entries, src = _load_first_existing(
            [
                data_dir / "jra_entries_normalized.csv",
                data_dir / "jra_entries_raw.csv",
            ]
        )
        if not fallback_entries.empty:
            if _looks_synthetic_df(fallback_entries):
                notes.append(f"weekly_local_fallback_skipped_synthetic={src}")
            else:
                weekly_new = fallback_entries.copy()
                if "race_id" not in weekly_new.columns:
                    weekly_new["race_id"] = f"AUTO{today.strftime('%Y%m%d')}"
                weekly_new["fetched_date"] = today.isoformat()
                notes.append(f"weekly_local_fallback={src}")

    if not history_new.empty:
        history_new = _dedupe_rows(history_new, ["race_id", "horse"])
    if not history_existing.empty:
        history_new = _replace_rows_by_race_ids(history_existing, history_new)
    if update_entries:
        if not weekly_new.empty:
            weekly_new = _dedupe_rows(weekly_new, ["race_id", "horse"])
        if not entries_existing.empty:
            weekly_new = _replace_rows_by_race_ids(entries_existing, weekly_new)
        weekly_effective = weekly_new.copy()
    else:
        weekly_effective = entries_existing.copy()
        if not entries_existing.empty:
            notes.append("weekly_entries_reused_existing")
    payout_new = pd.DataFrame(payout_rows)
    if not payout_new.empty:
        payout_new = _dedupe_rows(payout_new, ["race_id", "bet_type", "ticket"])
    if not payouts_existing.empty:
        payout_new = _replace_rows_by_race_ids(payouts_existing, payout_new)

    if not history_new.empty:
        history_sort_cols = [c for c in ["race_id", "finish", "horse"] if c in history_new.columns]
        if history_sort_cols:
            history_new = history_new.sort_values(history_sort_cols)
        history_new.to_csv(history_path, index=False, encoding="utf-8-sig")

    if update_entries and not weekly_new.empty:
        if "race_id" not in weekly_new.columns:
            weekly_new["race_id"] = f"AUTO{today.strftime('%Y%m%d')}"
        if "fetched_date" not in weekly_new.columns:
            weekly_new["fetched_date"] = today.isoformat()
        else:
            weekly_new["fetched_date"] = weekly_new["fetched_date"].fillna(today.isoformat()).astype(str)
        weekly_new = _dedupe_rows(weekly_new, ["race_id", "horse"])
        if auto_forecast_weather:
            try:
                weekly_new, forecast_notes = enrich_entries_weather_with_forecast(
                    weekly_new,
                    cache_path=data_dir / "weather_forecast_cache.json",
                    cache_hours=max(0, int(weather_cache_hours)),
                )
                notes.extend(forecast_notes)
            except Exception as exc:
                notes.append(f"weather_forecast_failed:{exc}")
        weekly_sort_cols = [c for c in ["race_id", "horse"] if c in weekly_new.columns]
        if weekly_sort_cols:
            weekly_new = weekly_new.sort_values(weekly_sort_cols)
        weekly_new.to_csv(entries_path, index=False, encoding="utf-8-sig")
        weekly_effective = weekly_new.copy()

    if not payout_new.empty:
        payout_sort_cols = [c for c in ["race_id", "bet_type", "ticket"] if c in payout_new.columns]
        if payout_sort_cols:
            payout_new = payout_new.sort_values(payout_sort_cols)
        payout_new.to_csv(payouts_path, index=False, encoding="utf-8-sig")
    _emit_progress(progress_callback, 0.92, "CSV保存を反映")

    tuned = False
    if run_tuning and history_path.exists():
        _emit_progress(progress_callback, 0.95, "重みを再学習")
        cmd = [
            sys.executable,
            str((Path(__file__).resolve().parent / "tools" / "tune_feature_weights.py")),
            "--history",
            str(history_path),
            "--out",
            str(weights_path),
            "--trials",
            str(int(tuning_trials)),
            "--val-races",
            str(int(tuning_val_races)),
            "--simulations",
            str(int(tuning_simulations)),
            "--prediction-features",
            str(feature_archive_path),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=max(60, int(TUNING_TIMEOUT_SEC)),
            )
            tuned = True
        except Exception as exc:
            notes.append(f"tune_failed:{exc}")
    _emit_progress(progress_callback, 0.99, "最終集計を作成")

    history_count = len(history_new) if not history_new.empty else 0
    entries_count = len(weekly_effective) if not weekly_effective.empty else 0
    history_race_count = int(history_new["race_id"].nunique()) if (not history_new.empty and "race_id" in history_new.columns) else 0
    weekly_race_count = int(weekly_effective["race_id"].nunique()) if (not weekly_effective.empty and "race_id" in weekly_effective.columns) else 0

    report = AutoUpdateReport(
        history_path=history_path,
        entries_path=entries_path,
        weights_path=weights_path if tuned else None,
        history_rows=history_count,
        entries_rows=entries_count,
        history_races=history_race_count,
        weekly_races=weekly_race_count,
        tuned=tuned,
        notes=tuple(notes[-50:]),
    )
    _emit_progress(progress_callback, 1.0, "更新完了")
    return report


def read_weights_json(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
