from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import weather_forecast as wf


class WeatherForecastTest(unittest.TestCase):
    def test_normalize_venue(self) -> None:
        self.assertEqual(wf.normalize_venue("東京競馬場"), "東京")
        self.assertEqual(wf.normalize_venue("中山 芝"), "中山")
        self.assertEqual(wf.normalize_venue("unknown"), "")

    def test_enrich_entries_weather(self) -> None:
        target_day = date.today() + timedelta(days=1)
        race_id = target_day.strftime("%Y%m%d") + "0101"
        entries = pd.DataFrame(
            [
                {"race_id": race_id, "horse": "A", "jockey": "J1", "trainer": "T1", "weather": "晴", "venue": "東京"},
                {"race_id": race_id, "horse": "B", "jockey": "J2", "trainer": "T2", "weather": "晴", "venue": "東京"},
            ]
        )

        def fake_fetch(lat: float, lon: float, d: date) -> wf.ForecastResult | None:
            return wf.ForecastResult(weather="雨", precip_prob=76.0, temp_max=19.5, temp_min=11.0, source="test")

        with tempfile.TemporaryDirectory() as td:
            out, notes = wf.enrich_entries_weather_with_forecast(
                entries,
                cache_path=Path(td) / "cache.json",
                cache_hours=6,
                fetcher=fake_fetch,
                now=datetime.now(),
            )
        self.assertTrue(bool((out["weather"] == "雨").all()))
        self.assertIn("forecast_precip_prob", out.columns)
        self.assertIn("weather_forecast_applied_races=1", notes)

    def test_cache_hit(self) -> None:
        target_day = date.today() + timedelta(days=1)
        race_id = target_day.strftime("%Y%m%d") + "0201"
        entries = pd.DataFrame(
            [{"race_id": race_id, "horse": "A", "jockey": "J1", "trainer": "T1", "weather": "晴", "venue": "中山"}]
        )
        cache_path: Path
        with tempfile.TemporaryDirectory() as td:
            cache_path = Path(td) / "cache.json"
            count = {"v": 0}

            def fake_fetch_first(lat: float, lon: float, d: date) -> wf.ForecastResult | None:
                count["v"] += 1
                return wf.ForecastResult(weather="曇", precip_prob=20.0, temp_max=15.0, temp_min=8.0, source="test")

            out1, _ = wf.enrich_entries_weather_with_forecast(
                entries,
                cache_path=cache_path,
                cache_hours=6,
                fetcher=fake_fetch_first,
                now=datetime.now(),
            )
            self.assertEqual(count["v"], 1)
            self.assertEqual(str(out1.loc[0, "weather"]), "曇")

            def fake_fetch_never(lat: float, lon: float, d: date) -> wf.ForecastResult | None:
                raise RuntimeError("must not call")

            out2, notes2 = wf.enrich_entries_weather_with_forecast(
                entries,
                cache_path=cache_path,
                cache_hours=6,
                fetcher=fake_fetch_never,
                now=datetime.now(),
            )
            self.assertEqual(str(out2.loc[0, "weather"]), "曇")
            self.assertTrue(any("weather_forecast_cache_hits=1" == n for n in notes2))


if __name__ == "__main__":
    unittest.main()

