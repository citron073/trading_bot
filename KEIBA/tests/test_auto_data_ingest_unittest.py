from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import auto_data_ingest as adi
import pandas as pd


class _FakeScraper:
    @staticmethod
    def race_list(year: int, month: int):
        if year == 2026 and month == 3:
            return ["202603010101", "202603080101", "202603220101"]
        return []


class AutoDataIngestTest(unittest.TestCase):
    def test_emit_progress_clamps_value(self) -> None:
        rows: list[tuple[float, str]] = []
        adi._emit_progress(lambda value, message: rows.append((value, message)), 1.8, "done")
        self.assertEqual(rows, [(1.0, "done")])

    def test_call_with_retry_retries_then_succeeds(self) -> None:
        state = {"count": 0}

        def flaky() -> str:
            state["count"] += 1
            if state["count"] < 3:
                raise RuntimeError("temporary")
            return "ok"

        result = adi._call_with_retry(flaky, attempts=3, retry_sleep_sec=0.0)
        self.assertEqual(result, "ok")
        self.assertEqual(state["count"], 3)

    def test_extract_distance(self) -> None:
        self.assertEqual(adi._extract_distance("芝1600m"), 1600.0)
        self.assertEqual(adi._extract_distance("ダ1400"), 1400.0)
        self.assertEqual(adi._extract_distance(None, fallback=1800.0), 1800.0)

    def test_list_race_ids_filters_by_date(self) -> None:
        ids = adi._list_race_ids(
            _FakeScraper,
            from_day=date(2026, 3, 5),
            to_day=date(2026, 3, 10),
            cap=50,
        )
        self.assertEqual(ids, ["202603080101"])

    def test_list_race_ids_netkeiba_daily_extracts_only_race_links(self) -> None:
        html = """
        <html><body>
          <a href="/race/shutuba.html?race_id=202603070101">entry</a>
          <a href="/race/result.html?race_id=202603070102">result</a>
          <a href="/horse/123/?race_id=202606020301">ignore-non-race</a>
          <a href="/race/shutuba.html?race_id=202603070101">dup</a>
        </body></html>
        """

        class _Resp:
            def __init__(self, text: str) -> None:
                self.text = text

            def raise_for_status(self) -> None:
                return None

        with patch("auto_data_ingest.requests.get", return_value=_Resp(html)):
            ids = adi._list_race_ids_netkeiba_daily(
                from_day=date(2026, 3, 7),
                to_day=date(2026, 3, 7),
                cap=50,
            )
            meta = adi._list_race_meta_netkeiba_daily(
                from_day=date(2026, 3, 7),
                to_day=date(2026, 3, 7),
                cap=50,
            )
        self.assertEqual(ids, ["202603070101", "202603070102"])
        self.assertEqual(meta[0]["race_date"], "2026-03-07")
        self.assertEqual(meta[0]["race_name"], "entry")

    def test_history_rows_from_payload(self) -> None:
        payload = {
            "race": [
                {
                    "weather": "晴れ",
                    "track_condition": "良",
                    "distance": "芝1600m",
                    "race_name": "テスト記念",
                    "race_date": "2026-03-08",
                }
            ],
            "entry": [
                {
                    "horse_name": "A",
                    "jockey": "J1",
                    "trainer": "T1",
                    "rank": 1,
                    "frame_number": 1,
                    "odds": 2.4,
                },
                {
                    "horse_name": "B",
                    "jockey": "J2",
                    "trainer": "T2",
                    "rank": 2,
                    "frame_number": 2,
                    "odds": 4.8,
                },
            ],
        }
        rows = adi._history_rows_from_payload("202603080101", payload)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["horse"], "A")
        self.assertEqual(rows[0]["finish"], 1)
        self.assertEqual(rows[0]["weather"], "晴")
        self.assertEqual(rows[0]["track_condition"], "良")
        self.assertEqual(rows[0]["race_name"], "テスト記念")
        self.assertEqual(rows[0]["race_date"], "2026-03-08")

    def test_history_rows_from_tuple_payload(self) -> None:
        race = [{"weather": "晴れ", "track_condition": "良", "distance": "芝1600m"}]
        entry = [
            {"horse_name": "A", "jockey": "J1", "trainer": "T1", "rank": 1, "frame_number": 1, "odds": 2.4},
            {"horse_name": "B", "jockey": "J2", "trainer": "T2", "rank": 2, "frame_number": 2, "odds": 4.8},
        ]
        rows = adi._history_rows_from_payload("202603080101", (race, entry))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["horse"], "A")
        self.assertEqual(rows[0]["finish"], 1)

    def test_synthetic_entry_detection(self) -> None:
        rows = [
            {"horse": "Horse_01", "jockey": "Jockey_01"},
            {"horse": "Horse_02", "jockey": "Jockey_02"},
        ]
        self.assertTrue(adi._looks_synthetic_entries(rows))

        rows_real = [
            {"horse": "ドウデュース", "jockey": "武 豊"},
            {"horse": "スターズオンアース", "jockey": "C.ルメール"},
        ]
        self.assertFalse(adi._looks_synthetic_entries(rows_real))

    def test_entry_rows_from_netkeiba_html(self) -> None:
        html = """
        <html><head><title>東京11R</title></head>
        <body>
          <div class="RaceData01">芝1600m / 天候 : 曇 / 馬場 : 良</div>
          <table class="Shutuba_Table">
            <tbody>
              <tr>
                <td class="Umaban">3</td>
                <td class="HorseInfo"><span class="HorseName"><a href="/horse/1/">テストホースA</a></span></td>
                <td class="Jockey"><a href="/jockey/1/">騎手A</a></td>
                <td class="Trainer"><a href="/trainer/1/">調教師A</a></td>
                <td class="Odds">5.4</td>
              </tr>
              <tr>
                <td class="Umaban">8</td>
                <td class="HorseInfo"><span class="HorseName"><a href="/horse/2/">テストホースB</a></span></td>
                <td class="Jockey"><a href="/jockey/2/">騎手B</a></td>
                <td class="Trainer"><a href="/trainer/2/">調教師B</a></td>
                <td class="Odds">12.1</td>
              </tr>
            </tbody>
          </table>
        </body></html>
        """
        rows = adi._entry_rows_from_netkeiba_html("202603080101", html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["horse"], "テストホースA")
        self.assertEqual(rows[0]["jockey"], "騎手A")
        self.assertEqual(rows[0]["weather"], "曇")
        self.assertEqual(rows[0]["track_condition"], "良")
        self.assertEqual(rows[0]["distance"], 1600.0)
        self.assertEqual(rows[0]["race_name"], "東京11R")

    def test_overlay_entry_meta_prefers_html_like_values(self) -> None:
        rows = [
            {
                "race_id": "202603080101",
                "horse": "A",
                "jockey": "J",
                "weather": "晴",
                "track_condition": "良",
                "distance": 1400.0,
                "venue": "中京",
                "race_name": "ファルコンS",
            }
        ]
        meta_rows = [
            {
                "weather": "曇",
                "track_condition": "稍重",
                "distance": "1600m",
                "venue": "東京",
            }
        ]
        out = adi._overlay_entry_meta(rows, race_date="2026-03-21", race_name="補助名", meta_rows=meta_rows)
        self.assertEqual(out[0]["race_date"], "2026-03-21")
        self.assertEqual(out[0]["weather"], "晴")
        self.assertEqual(out[0]["track_condition"], "良")
        self.assertEqual(out[0]["distance"], 1400.0)
        self.assertEqual(out[0]["venue"], "中京")
        self.assertEqual(out[0]["race_name"], "ファルコンS")

    def test_payout_rows_from_netkeiba_result_html(self) -> None:
        html = """
        <html><body>
          <table class="PayBack_Table">
            <tr><th>単勝</th><td>1</td><td>250円</td><td>2</td></tr>
            <tr><th>複勝</th><td>2</td><td>140円</td><td>1</td></tr>
            <tr><th>馬連</th><td>1 2</td><td>430円</td><td>3</td></tr>
            <tr><th>三連複</th><td>1 2 3</td><td>910円</td><td>5</td></tr>
          </table>
        </body></html>
        """
        rows = adi._payout_rows_from_netkeiba_result_html("202603210101", html)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["bet_type"], "単勝")
        self.assertEqual(rows[0]["ticket"], "1")
        self.assertEqual(rows[2]["bet_type"], "馬連")
        self.assertEqual(rows[2]["ticket"], "1-2")
        self.assertEqual(rows[3]["bet_type"], "三連複")
        self.assertEqual(rows[3]["ticket"], "1-2-3")

    def test_history_rows_from_netkeiba_result_html(self) -> None:
        html = """
        <html><body>
          <h1 class="RaceName">日本ダービー</h1>
          <div class="RaceData01">芝2400m / 天候 : 晴 / 馬場 : 良</div>
          <div class="RaceData02">東京 11R</div>
          <table class="RaceTable01">
            <tbody>
              <tr>
                <td class="Rank">1</td>
                <td class="Umaban">5</td>
                <td><span class="HorseName"><a href="/horse/1">ロブチェン</a></span></td>
                <td class="Jockey"><a>横山武史</a></td>
                <td class="Odds">3.2</td>
                <td class="Popular">1</td>
              </tr>
              <tr>
                <td class="Rank">2</td>
                <td class="Umaban">8</td>
                <td><span class="HorseName"><a href="/horse/2">ダノンシーマ</a></span></td>
                <td class="Jockey"><a>川田将雅</a></td>
                <td class="Odds">6.1</td>
                <td class="Popular">3</td>
              </tr>
            </tbody>
          </table>
        </body></html>
        """
        rows = adi._history_rows_from_netkeiba_result_html("202605021211", html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["finish"], 1)
        self.assertEqual(rows[0]["horse"], "ロブチェン")
        self.assertEqual(rows[0]["gate"], 5.0)
        self.assertEqual(rows[0]["jockey"], "横山武史")
        self.assertEqual(rows[0]["race_name"], "日本ダービー")
        self.assertEqual(rows[0]["venue"], "東京")
        self.assertEqual(rows[0]["distance"], 2400.0)
        self.assertEqual(rows[0]["weather"], "晴")
        self.assertEqual(rows[0]["track_condition"], "良")

    def test_is_netkeiba_block_page(self) -> None:
        self.assertTrue(adi._is_netkeiba_block_page("本サービスのポリシーに反するサイト", "http://block.wifi-cloud2.jp/block.html"))
        self.assertFalse(adi._is_netkeiba_block_page("<html>RaceTable01</html>", "https://race.netkeiba.com/race/result.html"))

    def test_prune_weekly_entries(self) -> None:
        today = date.today()
        old_race_id = (today - timedelta(days=40)).strftime("%Y%m%d") + "0101"
        near_race_id = (today + timedelta(days=2)).strftime("%Y%m%d") + "0101"
        df = pd.DataFrame(
            [
                {
                    "race_id": old_race_id,
                    "horse": "古い馬",
                    "jockey": "古い騎手",
                    "fetched_date": (today - timedelta(days=35)).isoformat(),
                },
                {
                    "race_id": near_race_id,
                    "horse": "近い馬",
                    "jockey": "近い騎手",
                    "fetched_date": today.isoformat(),
                },
                {"race_id": "AUTO20260307", "horse": "Horse_01", "jockey": "Jockey_01"},
            ]
        )
        out = adi._prune_weekly_entries(df, today=today, days_back=1, days_ahead=21)
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out.iloc[0]["horse"]), "近い馬")

    def test_max_race_date_from_history(self) -> None:
        df = pd.DataFrame(
            {
                "race_id": ["202603010101", "202603080101", "bad_id"],
                "horse": ["A", "B", "C"],
            }
        )
        got = adi._max_race_date_from_history(df)
        self.assertEqual(got, date(2026, 3, 8))

    def test_fetch_auto_data_without_keibascraper(self) -> None:
        if adi.has_keibascraper():
            self.skipTest("keibascraper is installed in this environment")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                adi.fetch_auto_data(Path(td), months_back=3, weekly_days_ahead=5)

    def test_fetch_auto_data_skip_network_updates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            history_path = data_dir / "history_auto.csv"
            pd.DataFrame(
                [
                    {
                        "race_id": "202603080101",
                        "horse": "A",
                        "jockey": "J1",
                        "trainer": "T1",
                        "weather": "晴",
                        "track_condition": "良",
                        "distance": 1600,
                        "finish": 1,
                    }
                ]
            ).to_csv(history_path, index=False)

            report = adi.fetch_auto_data(
                data_dir=data_dir,
                update_history=False,
                update_entries=False,
                run_tuning=False,
            )
            self.assertEqual(report.history_rows, 1)
            self.assertEqual(report.entries_rows, 0)


if __name__ == "__main__":
    unittest.main()
