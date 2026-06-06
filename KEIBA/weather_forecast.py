from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Tuple

import pandas as pd
import requests


JRA_VENUE_COORDS: Mapping[str, Tuple[float, float]] = {
    "札幌": (43.0686, 141.3508),
    "函館": (41.7688, 140.7288),
    "福島": (37.7608, 140.4747),
    "新潟": (37.9161, 139.0364),
    "東京": (35.6762, 139.6503),
    "中山": (35.7219, 139.9398),
    "中京": (35.1815, 136.9066),
    "京都": (35.0116, 135.7681),
    "阪神": (34.6937, 135.5023),
    "小倉": (33.8830, 130.8753),
}

VENUE_ALIAS: Mapping[str, str] = {
    "札幌": "札幌",
    "函館": "函館",
    "福島": "福島",
    "新潟": "新潟",
    "東京": "東京",
    "中山": "中山",
    "中京": "中京",
    "京都": "京都",
    "阪神": "阪神",
    "小倉": "小倉",
}

FORECAST_HTTP_TIMEOUT_SEC = 8
FORECAST_HTTP_RETRIES = 3
FORECAST_HTTP_RETRY_SLEEP_SEC = 0.8


@dataclass(frozen=True)
class ForecastResult:
    weather: str
    precip_prob: float | None
    temp_max: float | None
    temp_min: float | None
    source: str


def normalize_venue(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for alias, canonical in VENUE_ALIAS.items():
        if alias in text:
            return canonical
    return ""


def race_id_to_date(race_id: Any) -> date | None:
    text = str(race_id or "").strip()
    if len(text) < 8 or (not text[:8].isdigit()):
        return None
    try:
        return datetime.strptime(text[:8], "%Y%m%d").date()
    except Exception:
        return None


def _weathercode_to_label(code: Any, precip_prob: float | None) -> str:
    try:
        wc = int(float(code))
    except Exception:
        wc = -1
    if wc in {71, 73, 75, 77, 85, 86}:
        return "雪"
    if wc in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}:
        return "雨"
    if wc in {1, 2, 3, 45, 48}:
        return "曇"
    if wc == 0:
        return "晴"
    if precip_prob is not None and precip_prob >= 45.0:
        return "雨"
    return "曇"


def _cache_load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cache_save(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_get(cache: Mapping[str, Any], key: str, now: datetime, max_age_h: int) -> Dict[str, Any] | None:
    entry = cache.get(key)
    if not isinstance(entry, dict):
        return None
    fetched_at = entry.get("fetched_at")
    if not isinstance(fetched_at, str):
        return None
    try:
        ts = datetime.fromisoformat(fetched_at)
    except Exception:
        return None
    if (now - ts) > timedelta(hours=max(0, int(max_age_h))):
        return None
    return entry


def _fetch_daily_forecast(
    lat: float,
    lon: float,
    target_date: date,
    *,
    timeout: int = FORECAST_HTTP_TIMEOUT_SEC,
) -> ForecastResult | None:
    params = {
        "latitude": float(lat),
        "longitude": float(lon),
        "timezone": "Asia/Tokyo",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "daily": "weather_code,precipitation_probability_max,temperature_2m_max,temperature_2m_min",
    }
    last_exc: Exception | None = None
    data: Dict[str, Any] | None = None
    for attempt in range(1, max(1, int(FORECAST_HTTP_RETRIES)) + 1):
        try:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params=params,
                timeout=max(1, int(timeout or FORECAST_HTTP_TIMEOUT_SEC)),
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            last_exc = exc
            if attempt >= max(1, int(FORECAST_HTTP_RETRIES)):
                raise
            time.sleep(float(FORECAST_HTTP_RETRY_SLEEP_SEC) * attempt)
    if data is None:
        if last_exc is not None:
            raise last_exc
        return None
    daily = data.get("daily", {})

    weather_codes = daily.get("weather_code") or daily.get("weathercode") or []
    precip_probs = daily.get("precipitation_probability_max") or []
    max_temps = daily.get("temperature_2m_max") or []
    min_temps = daily.get("temperature_2m_min") or []

    if not weather_codes:
        return None

    code = weather_codes[0]
    precip = float(precip_probs[0]) if precip_probs else None
    temp_max = float(max_temps[0]) if max_temps else None
    temp_min = float(min_temps[0]) if min_temps else None
    return ForecastResult(
        weather=_weathercode_to_label(code, precip),
        precip_prob=precip,
        temp_max=temp_max,
        temp_min=temp_min,
        source="open-meteo",
    )


def enrich_entries_weather_with_forecast(
    entries_df: pd.DataFrame,
    *,
    cache_path: Path,
    cache_hours: int = 6,
    fetcher: Callable[[float, float, date], ForecastResult | None] | None = None,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, List[str]]:
    if entries_df.empty:
        return entries_df, ["weather_forecast_skip:empty_entries"]

    out = entries_df.copy()
    if "race_id" not in out.columns:
        return out, ["weather_forecast_skip:no_race_id"]

    if "venue" not in out.columns:
        out["venue"] = ""
    out["venue"] = out["venue"].map(normalize_venue)

    race_dates = out["race_id"].map(race_id_to_date)
    out["_race_date"] = race_dates

    fetch = fetcher if fetcher is not None else _fetch_daily_forecast
    now_dt = now or datetime.now()
    cache = _cache_load(cache_path)
    cache_dirty = False
    notes: List[str] = []

    applied = 0
    skipped_no_venue = 0
    skipped_past = 0
    fetch_failed = 0
    cache_hits = 0

    grouped = out.groupby("race_id", dropna=False)
    for race_id, race_df in grouped:
        idx = race_df.index
        race_date = race_df["_race_date"].dropna()
        target_date = race_date.iloc[0] if len(race_date) > 0 else date.today()
        if target_date < date.today():
            skipped_past += 1
            continue

        venue_value = normalize_venue(race_df["venue"].dropna().iloc[0] if len(race_df["venue"].dropna()) > 0 else "")
        if not venue_value:
            skipped_no_venue += 1
            continue
        coords = JRA_VENUE_COORDS.get(venue_value)
        if coords is None:
            skipped_no_venue += 1
            continue

        cache_key = f"{venue_value}:{target_date.isoformat()}"
        cache_entry = _cache_get(cache, cache_key, now=now_dt, max_age_h=max(0, int(cache_hours)))
        forecast: ForecastResult | None = None
        if cache_entry is not None:
            forecast = ForecastResult(
                weather=str(cache_entry.get("weather", "曇")),
                precip_prob=float(cache_entry["precip_prob"]) if cache_entry.get("precip_prob") is not None else None,
                temp_max=float(cache_entry["temp_max"]) if cache_entry.get("temp_max") is not None else None,
                temp_min=float(cache_entry["temp_min"]) if cache_entry.get("temp_min") is not None else None,
                source=str(cache_entry.get("source", "cache")),
            )
            cache_hits += 1
        else:
            try:
                forecast = fetch(float(coords[0]), float(coords[1]), target_date)
            except Exception:
                fetch_failed += 1
                forecast = None
            if forecast is not None:
                cache[cache_key] = {
                    "fetched_at": now_dt.isoformat(),
                    "venue": venue_value,
                    "target_date": target_date.isoformat(),
                    "weather": forecast.weather,
                    "precip_prob": forecast.precip_prob,
                    "temp_max": forecast.temp_max,
                    "temp_min": forecast.temp_min,
                    "source": forecast.source,
                }
                cache_dirty = True

        if forecast is None:
            continue

        out.loc[idx, "weather"] = forecast.weather
        out.loc[idx, "weather_source"] = "forecast"
        out.loc[idx, "forecast_precip_prob"] = forecast.precip_prob
        out.loc[idx, "forecast_temp_max_c"] = forecast.temp_max
        out.loc[idx, "forecast_temp_min_c"] = forecast.temp_min
        applied += 1

    if cache_dirty:
        _cache_save(cache_path, cache)

    out = out.drop(columns=["_race_date"])
    notes.append(f"weather_forecast_applied_races={applied}")
    if cache_hits > 0:
        notes.append(f"weather_forecast_cache_hits={cache_hits}")
    if skipped_no_venue > 0:
        notes.append(f"weather_forecast_skip_no_venue={skipped_no_venue}")
    if skipped_past > 0:
        notes.append(f"weather_forecast_skip_past={skipped_past}")
    if fetch_failed > 0:
        notes.append(f"weather_forecast_fetch_failed={fetch_failed}")

    return out, notes
