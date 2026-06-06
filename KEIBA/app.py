from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape as html_escape
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Dict, List
import urllib.error
import urllib.request

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from auto_data_ingest import AutoUpdateReport, fetch_auto_data, has_keibascraper, read_weights_json
from auto_agent import FREE_HARNESS_STATUS_FILENAME, run_free_prediction_harness
from llm_memory import append_jsonl_with_compaction, read_jsonl_tail as _read_jsonl_if_exists
from state_store import (
    DEFAULT_CSV_TEXT_DTYPES,
    ensure_data_layout,
    file_signature as _file_signature,
    frames_equal_for_storage as _frames_equal_for_storage,
    parquet_cache_status,
    read_csv_if_exists as _read_csv_if_exists,
    read_json_if_exists as _read_json_if_exists,
    write_csv as _write_csv,
    write_csv_if_changed,
    write_json as _write_json,
)
from evaluation import (
    aggregate_prediction_feedback,
    build_budget_basis_performance_table,
    build_bet_type_feedback_rows,
    build_bet_type_performance_table,
    build_condition_adjustment_performance_table,
    build_condition_segment_performance_table,
    build_llm_disagreement_performance_table,
    build_prediction_feedback,
    upsert_prediction_archive,
)
from feedback_learning import upsert_prediction_feature_archive
from prediction_pipeline import (
    build_prediction_feedback_from_paths,
    collect_auto_update_status_lines,
    feedback_new_result_count,
    feedback_summary_delta_snapshot,
    feedback_summary_delta_text,
    ensure_weekly_prediction_columns as pipeline_ensure_weekly_prediction_columns,
    filter_current_week as pipeline_filter_current_week,
    merge_selected_weekly_prediction,
    normalize_race_ids,
    prepare_weekly_display_columns,
    prepare_weekly_predictions_preview,
    remaining_targeted_result_ids,
    result_fetch_attempt_status,
    result_refresh_chip,
    result_refresh_notice_text,
    result_refresh_outcome_summary,
    result_refresh_summary_detail,
    resolve_update_profile,
    save_weekly_predictions,
    weekly_notice_message,
    weekly_notice_row,
)
from ui_archive import (
    build_archive_detail_frames,
    render_archive_detail_toggle,
    render_bet_type_feedback_rows,
    render_bet_type_performance_table,
    render_budget_basis_performance_table,
    render_condition_performance_tables,
    render_feedback_summary_metrics,
    render_llm_disagreement_performance_table,
    render_prediction_feedback_table,
    render_weight_change_table,
)
from ui_sidebar import (
    render_auto_agent_panel,
    render_auto_cycle_panel,
    render_auto_improve_panel,
    render_auto_update_detail_settings,
    render_easy_action_buttons,
    render_latest_update_caption,
    render_latest_update_metrics,
    render_llm_alignment_shortcuts,
    render_llm_hands_free_history_panel,
    render_local_confirmation_footer,
    render_local_confirmation_header,
    render_local_llm_panel,
    render_post_race_action_buttons,
    render_public_access_panel,
    render_sidebar_budget_basis_cards,
    render_sidebar_budget_basis_selector,
    render_standard_update_buttons,
    render_update_operation_header,
    render_update_profile_settings,
)
from ui_prediction import (
    render_bet_candidate_tables,
    render_prediction_ticket_table,
)
from ui_weekly import (
    render_graded_focus_section,
    render_weekly_prediction_tables,
    render_weekly_filter_controls,
    render_program_order_panel,
    render_venue_reader_panel,
    render_weekly_detail_selector_panel,
    render_weekly_race_overview_table,
    render_weekly_scope_selector,
)

from predictor import (
    PredictionResult,
    TRACK_OPTIONS,
    WEATHER_OPTIONS,
    export_template_csv,
    generate_sample_entries,
    generate_sample_history,
    predict_race,
)

DATA_DIR = APP_DIR / "data"
DATA_LAYOUT_PATHS = ensure_data_layout(DATA_DIR)
AUTO_HISTORY_PATH = DATA_DIR / "history_auto.csv"
AUTO_ENTRIES_PATH = DATA_DIR / "weekly_entries_auto.csv"
AUTO_WEIGHTS_PATH = DATA_DIR / "keiba_best_weights.json"
WEEKLY_PREDICTIONS_PATH = DATA_DIR / "weekly_predictions_auto.csv"
PUBLIC_TUNNEL_STATUS_PATH = DATA_DIR / "public_tunnel_status.json"
PUBLIC_HEALTH_STATUS_PATH = DATA_DIR / "public_health_status.json"
PUBLIC_WATCH_STATE_PATH = DATA_DIR / "public_watch_state.json"
LOCAL_RUNTIME_STATUS_PATH = DATA_DIR / "local_runtime_status.json"
LOCAL_OPERATION_STATUS_PATH = DATA_DIR / "local_operation_status.json"
RESULT_FETCH_STATE_PATH = DATA_DIR / "result_fetch_state.json"
RESULT_SAMPLE_PATH = DATA_DIR / "race_result_samples.csv"
LOCAL_LLM_MEMORY_PATH = DATA_DIR / "local_llm_keiba_memory.jsonl"
PREDICTION_ARCHIVE_PATH = DATA_DIR / "prediction_archive.csv"
PREDICTION_FEEDBACK_PATH = DATA_DIR / "prediction_feedback.csv"
PREDICTION_FEATURE_ARCHIVE_PATH = DATA_DIR / "prediction_feature_archive.csv"
WEIGHT_CHANGE_PATH = DATA_DIR / "weight_change_latest.csv"
AUTO_PAYOUTS_PATH = DATA_DIR / "payouts_auto.csv"
AUTO_IMPROVE_STATE_PATH = DATA_DIR / "auto_improve_state.json"
AUTO_CYCLE_STATUS_PATH = DATA_DIR / "auto_cycle_status.json"
AUTO_CYCLE_CONFIG_PATH = DATA_DIR / "auto_cycle_config.json"
AUTO_AGENT_STATUS_PATH = DATA_DIR / "auto_agent_status.json"
AUTO_AGENT_REPORT_PATH = DATA_DIR / "auto_agent_report.json"
PREDICTION_HARNESS_STATUS_PATH = DATA_DIR / FREE_HARNESS_STATUS_FILENAME
LLM_HANDS_FREE_HISTORY_PATH = DATA_DIR / "llm_hands_free_history.jsonl"
LOCAL_LLM_MEMORY_MAX_ACTIVE_ROWS = int(os.getenv("KEIBA_LLM_MEMORY_MAX_ACTIVE_ROWS", "12000"))
LOCAL_LLM_MEMORY_MAX_ACTIVE_BYTES = int(os.getenv("KEIBA_LLM_MEMORY_MAX_ACTIVE_BYTES", str(16 * 1024 * 1024)))
AUTO_IMPROVE_CHECKPOINT_INTERVAL_SECONDS = int(os.getenv("KEIBA_AUTO_IMPROVE_CHECKPOINT_SECONDS", "300"))

LOCAL_LLM_BASE_URL_DEFAULT = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
LOCAL_LLM_MODEL_DEFAULT = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
LOCAL_LLM_STYLE_DEFAULT = "バランス"

_RACE_GRADE_ALIASES: Dict[str, str] = {
    "弥生賞ディープインパクト記念": "G2",
    "スプリングS": "G2",
    "金鯱賞": "G2",
    "阪神大賞典": "G2",
    "フラワーC": "G3",
    "ファルコンS": "G3",
    "愛知杯": "G3",
    "阪神スプリングJ": "G2",
    "ペガサスジャンプS": "G3",
    "フェブラリーS": "G1",
    "高松宮記念": "G1",
    "大阪杯": "G1",
    "桜花賞": "G1",
    "皐月賞": "G1",
    "天皇賞": "G1",
    "NHKマイルC": "G1",
    "ヴィクトリアマイル": "G1",
    "オークス": "G1",
    "日本ダービー": "G1",
    "安田記念": "G1",
    "宝塚記念": "G1",
    "スプリンターズS": "G1",
    "秋華賞": "G1",
    "菊花賞": "G1",
    "天皇賞(秋)": "G1",
    "天皇賞・秋": "G1",
    "エリザベス女王杯": "G1",
    "マイルチャンピオンS": "G1",
    "ジャパンC": "G1",
    "チャンピオンズC": "G1",
    "阪神JF": "G1",
    "朝日杯FS": "G1",
    "有馬記念": "G1",
    "ホープフルS": "G1",
}

_GRADE_ORDER = {"G1": 0, "G2": 1, "G3": 2, "重賞": 3, "未判定": 9}

st.set_page_config(
    page_title="競馬予想アプリ (独立版)",
    page_icon="🏇",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _inject_style() -> None:
    st.markdown(
        """
<style>
:root {
  --k-card-bg: rgba(255, 255, 255, 0.84);
  --k-card-border: rgba(46, 87, 58, 0.25);
  --k-text-main: #1f2d1f;
  --k-text-sub: #35513b;
  --k-accent: #27813f;
  --k-accent-soft: #dff4e5;
  --k-danger-bg: rgba(255, 241, 239, 0.94);
  --k-danger-border: rgba(174, 49, 36, 0.28);
  --k-danger-text: #8b2318;
  --k-danger-soft: rgba(255, 225, 221, 0.92);
  --k-gold-bg: rgba(255, 249, 231, 0.95);
  --k-gold-border: rgba(179, 138, 18, 0.24);
}
.stApp {
  background-color: #f2f8ef;
  background-image:
    linear-gradient(180deg, rgba(252, 255, 251, 0.76) 0%, rgba(245, 252, 247, 0.86) 100%),
    radial-gradient(880px 280px at 20% -10%, rgba(201, 240, 211, 0.45), transparent 66%),
    radial-gradient(820px 260px at 85% -10%, rgba(255, 251, 215, 0.45), transparent 66%),
    url("https://upload.wikimedia.org/wikipedia/commons/thumb/1/15/Horse-racing-1.jpg/1920px-Horse-racing-1.jpg");
  background-repeat: no-repeat, no-repeat, no-repeat, no-repeat;
  background-size: cover, cover, cover, cover;
  background-position: center top, 20% top, 85% top, center center;
  background-attachment: fixed, fixed, fixed, fixed;
  color: var(--k-text-main);
  font-family: "Hiragino Sans", "Yu Gothic", "Meiryo", sans-serif;
}
section.main > div.block-container {
  padding-top: 1.1rem;
  padding-bottom: 1.4rem;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(59, 97, 69, 0.2);
  border-radius: 1rem;
  box-shadow: 0 10px 28px rgba(33, 63, 41, 0.13);
  backdrop-filter: blur(2px);
}
h1, h2, h3 {
  color: var(--k-text-main);
  letter-spacing: 0.01em;
}
p, label, span {
  color: var(--k-text-sub);
}
div[data-testid="stMetric"] {
  border: 1px solid var(--k-card-border);
  border-radius: 0.95rem;
  background: var(--k-card-bg);
  box-shadow: 0 8px 20px rgba(33, 63, 41, 0.12);
}
div.stButton > button {
  background: linear-gradient(180deg, #2f9950 0%, #237740 100%);
  color: #f5fff7;
  border: 1px solid #1f6a37;
  border-radius: 0.8rem;
  font-weight: 700;
}
div[data-testid="stSidebar"] > div:first-child {
  background: linear-gradient(180deg, rgba(252, 255, 248, 0.94) 0%, rgba(234, 246, 236, 0.94) 100%);
  border-right: 1px solid var(--k-card-border);
}
div[data-baseweb="tab-list"] {
  gap: 0.4rem;
}
button[data-baseweb="tab"] {
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(44, 95, 61, 0.22);
  border-radius: 0.65rem;
}
.danger-grid, .memo-grid, .bet-pick-grid {
  display: grid;
  gap: 0.8rem;
  margin: 0.35rem 0 0.9rem;
}
.weekly-race-grid {
  display: grid;
  gap: 0.8rem;
  margin: 0.25rem 0 1rem;
}
.weekly-grade-title {
  margin: 0.8rem 0 0.35rem;
  font-size: 0.92rem;
  font-weight: 900;
  letter-spacing: 0.03em;
  color: #17321c;
}
.weekly-grade-sub {
  margin: 0 0 0.45rem;
  font-size: 0.8rem;
  line-height: 1.5;
  color: #54705d;
}
.danger-grid {
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}
.memo-grid {
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
}
.bet-pick-grid {
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
}
.danger-card, .memo-card, .bet-pick-card {
  border-radius: 1rem;
  padding: 0.9rem 1rem;
  box-shadow: 0 12px 24px rgba(33, 63, 41, 0.11);
}
.danger-card {
  background: linear-gradient(180deg, var(--k-danger-bg) 0%, rgba(255, 248, 246, 0.98) 100%);
  border: 1px solid var(--k-danger-border);
}
.memo-card {
  background: linear-gradient(180deg, var(--k-gold-bg) 0%, rgba(255, 255, 249, 0.98) 100%);
  border: 1px solid var(--k-gold-border);
}
.bet-pick-card {
  background: linear-gradient(180deg, rgba(244, 252, 246, 0.94) 0%, rgba(255, 255, 255, 0.98) 100%);
  border: 1px solid rgba(54, 109, 69, 0.18);
}
.bet-pick-card.highlight {
  background: linear-gradient(180deg, rgba(225, 246, 231, 0.98) 0%, rgba(248, 255, 249, 0.99) 100%);
  border: 1px solid rgba(41, 120, 69, 0.26);
  box-shadow: 0 14px 28px rgba(34, 102, 58, 0.16);
}
.bet-pick-card.history-highlight {
  background: linear-gradient(180deg, rgba(255, 236, 212, 0.99) 0%, rgba(255, 248, 240, 0.99) 100%);
  border: 1px solid rgba(179, 96, 24, 0.28);
  box-shadow: 0 16px 30px rgba(170, 88, 22, 0.16);
}
.danger-title, .memo-title, .bet-pick-title {
  font-weight: 800;
  letter-spacing: 0.02em;
  margin-bottom: 0.3rem;
}
.danger-title {
  color: var(--k-danger-text);
  font-size: 1rem;
}
.memo-title {
  color: #8a6408;
  font-size: 1rem;
}
.bet-pick-title {
  color: var(--k-text-main);
  font-size: 0.98rem;
}
.danger-chip, .memo-chip, .bet-pick-chip {
  display: inline-block;
  font-size: 0.76rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 0.18rem 0.55rem;
  margin-bottom: 0.45rem;
}
.danger-chip {
  background: var(--k-danger-soft);
  color: var(--k-danger-text);
}
.memo-chip {
  background: rgba(255, 240, 191, 0.86);
  color: #7d5d10;
}
.bet-pick-chip {
  background: rgba(225, 246, 231, 0.96);
  color: #1f5d37;
}
.danger-line, .memo-line, .bet-pick-line {
  color: var(--k-text-main);
  font-size: 0.9rem;
  line-height: 1.55;
}
.bet-focus-card {
  margin: 0.2rem 0 0.9rem;
  border-radius: 1rem;
  padding: 0.88rem 0.96rem;
  border: 1px solid rgba(42, 118, 67, 0.2);
  background: linear-gradient(180deg, rgba(233, 249, 238, 0.98) 0%, rgba(250, 255, 251, 0.99) 100%);
  box-shadow: 0 12px 26px rgba(35, 93, 57, 0.10);
}
.bet-focus-card.history-highlight {
  border: 1px solid rgba(179, 96, 24, 0.24);
  background: linear-gradient(180deg, rgba(255, 238, 216, 0.99) 0%, rgba(255, 250, 244, 0.99) 100%);
  box-shadow: 0 15px 28px rgba(170, 88, 22, 0.15);
}
.bet-focus-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.16rem 0.56rem;
  border-radius: 999px;
  font-size: 0.73rem;
  font-weight: 900;
  color: #1f5d37;
  background: rgba(218, 243, 225, 0.96);
}
.bet-focus-card.history-highlight .bet-focus-chip {
  color: #8b5311;
  background: rgba(255, 234, 211, 0.98);
}
.bet-focus-card.history-highlight .bet-focus-title {
  color: #7c4216;
}
.bet-focus-card.history-highlight .bet-focus-sub {
  color: #7a5737;
}
.bet-focus-card.history-highlight .bet-focus-badge {
  color: #7b4b1f;
  background: rgba(255, 240, 223, 0.98);
}
.bet-focus-title {
  margin-top: 0.42rem;
  font-size: 1rem;
  font-weight: 900;
  color: #18341f;
}
.bet-focus-sub {
  margin-top: 0.18rem;
  font-size: 0.84rem;
  line-height: 1.6;
  color: #44604d;
}
.bet-focus-row {
  margin-top: 0.48rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.36rem;
}
.bet-focus-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.16rem 0.54rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 900;
  color: #30503d;
  background: rgba(229, 244, 233, 0.95);
}
.result-sync-card {
  margin: 0.35rem 0 1rem;
  border-radius: 1.1rem;
  padding: 1rem 1.05rem;
  border: 1px solid rgba(46, 128, 69, 0.22);
  background: linear-gradient(180deg, rgba(233, 250, 237, 0.96) 0%, rgba(252, 255, 252, 0.98) 100%);
  box-shadow: 0 14px 28px rgba(33, 63, 41, 0.11);
}
.operation-guide-card {
  margin: 0.2rem 0 0.85rem;
  border-radius: 1.15rem;
  padding: 1rem 1.05rem 0.95rem;
  border: 1px solid rgba(48, 97, 58, 0.20);
  background: linear-gradient(180deg, rgba(247, 252, 247, 0.97) 0%, rgba(255, 255, 255, 0.98) 100%);
  box-shadow: 0 14px 28px rgba(33, 63, 41, 0.10);
}
.operation-guide-card.acquire {
  background: linear-gradient(180deg, rgba(231, 246, 236, 0.98) 0%, rgba(255, 255, 255, 0.99) 100%);
  border-color: rgba(40, 124, 69, 0.24);
}
.operation-guide-card.predict {
  background: linear-gradient(180deg, rgba(255, 249, 231, 0.98) 0%, rgba(255, 255, 255, 0.99) 100%);
  border-color: rgba(179, 138, 18, 0.22);
}
.operation-guide-card.results {
  background: linear-gradient(180deg, rgba(255, 241, 239, 0.98) 0%, rgba(255, 255, 255, 0.99) 100%);
  border-color: rgba(174, 49, 36, 0.22);
}
.operation-guide-card.learn {
  background: linear-gradient(180deg, rgba(239, 243, 255, 0.98) 0%, rgba(255, 255, 255, 0.99) 100%);
  border-color: rgba(64, 93, 172, 0.22);
}
.operation-guide-card.check {
  background: linear-gradient(180deg, rgba(247, 248, 250, 0.98) 0%, rgba(255, 255, 255, 0.99) 100%);
  border-color: rgba(98, 107, 120, 0.18);
}
.operation-guide-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.18rem 0.62rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 900;
  color: #1f5d37;
  background: rgba(218, 243, 225, 0.96);
}
.operation-guide-chip.predict {
  color: #7d5d10;
  background: rgba(255, 240, 191, 0.88);
}
.operation-guide-chip.results {
  color: #8b2318;
  background: rgba(255, 225, 221, 0.94);
}
.operation-guide-chip.learn {
  color: #294a9a;
  background: rgba(228, 236, 255, 0.96);
}
.operation-guide-chip.check {
  color: #50606b;
  background: rgba(233, 237, 242, 0.96);
}
.operation-guide-title {
  margin-top: 0.45rem;
  font-size: 1.18rem;
  font-weight: 900;
  color: var(--k-text-main);
}
.operation-guide-reason {
  margin-top: 0.26rem;
  font-size: 0.92rem;
  line-height: 1.65;
  color: #3d5645;
}
.operation-guide-status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.55rem;
  margin-top: 0.72rem;
}
.operation-guide-status {
  border-radius: 0.88rem;
  padding: 0.62rem 0.72rem;
  border: 1px solid rgba(52, 92, 61, 0.16);
  background: rgba(255, 255, 255, 0.86);
}
.operation-guide-status-label {
  font-size: 0.73rem;
  font-weight: 800;
  color: #56705c;
}
.operation-guide-status-state {
  margin-top: 0.18rem;
  font-size: 0.95rem;
  font-weight: 900;
  color: #18341f;
}
.operation-guide-status-detail {
  margin-top: 0.16rem;
  font-size: 0.76rem;
  line-height: 1.5;
  color: #5b7260;
}
.operation-guide-step {
  margin-top: 0.22rem;
  font-size: 0.85rem;
  line-height: 1.6;
  color: #476051;
}
.easy-action-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.6rem;
  margin: 0.35rem 0 0.85rem;
}
.easy-action-card {
  border-radius: 0.95rem;
  padding: 0.82rem 0.88rem;
  border: 1px solid rgba(46, 87, 58, 0.18);
  background: linear-gradient(180deg, rgba(250, 255, 250, 0.98) 0%, rgba(255, 255, 255, 0.99) 100%);
  box-shadow: 0 8px 18px rgba(33, 63, 41, 0.08);
}
.easy-action-title {
  font-size: 0.95rem;
  font-weight: 900;
  color: #18341f;
}
.easy-action-sub {
  margin-top: 0.22rem;
  font-size: 0.78rem;
  line-height: 1.5;
  color: #5a7060;
}
.result-sync-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.18rem 0.58rem;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0.03em;
  color: #1d6e39;
  background: rgba(220, 245, 226, 0.96);
}
.result-sync-title {
  margin-top: 0.45rem;
  font-size: 1.05rem;
  font-weight: 900;
  color: #17321c;
}
.result-sync-sub {
  margin-top: 0.22rem;
  font-size: 0.9rem;
  line-height: 1.6;
  color: #3f5f49;
}
.result-sync-delta {
  margin-top: 0.55rem;
  padding-top: 0.55rem;
  border-top: 1px dashed rgba(59, 97, 69, 0.18);
  font-size: 0.88rem;
  line-height: 1.65;
  color: #254230;
}
.result-sync-basis {
  margin-top: 0.55rem;
  padding-top: 0.55rem;
  border-top: 1px dashed rgba(59, 97, 69, 0.18);
}
.result-sync-basis-title {
  font-size: 0.84rem;
  font-weight: 900;
  color: #1e3a27;
}
.result-sync-basis-text {
  margin-top: 0.18rem;
  font-size: 0.85rem;
  line-height: 1.62;
  color: #355240;
}
.result-sync-list {
  margin-top: 0.55rem;
  padding-top: 0.55rem;
  border-top: 1px dashed rgba(59, 97, 69, 0.18);
}
.result-sync-list-title {
  font-size: 0.84rem;
  font-weight: 900;
  color: #1e3a27;
  margin-bottom: 0.28rem;
}
.result-sync-list-line {
  font-size: 0.86rem;
  line-height: 1.58;
  color: #2f4b38;
  padding: 0.48rem 0.62rem;
  border-radius: 0.7rem;
  margin-top: 0.34rem;
  border: 1px solid rgba(59, 97, 69, 0.12);
  background: rgba(255, 255, 255, 0.7);
}
.result-sync-list-line.hit {
  color: #1f5b32;
  background: rgba(226, 247, 232, 0.94);
  border-color: rgba(46, 128, 69, 0.20);
}
.result-sync-list-line.miss {
  color: #7d2d23;
  background: rgba(255, 239, 236, 0.96);
  border-color: rgba(174, 49, 36, 0.18);
}
.result-sync-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.34rem;
  margin-top: 0.36rem;
}
.result-sync-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.14rem 0.5rem;
  border-radius: 999px;
  font-size: 0.74rem;
  font-weight: 800;
  letter-spacing: 0.02em;
}
.result-sync-badge.single {
  color: #1b5f33;
  background: rgba(221, 246, 227, 0.96);
}
.result-sync-badge.place {
  color: #256542;
  background: rgba(226, 250, 236, 0.96);
}
.result-sync-badge.combo {
  color: #23517b;
  background: rgba(226, 239, 255, 0.96);
}
.result-sync-badge.exacta {
  color: #96560d;
  background: rgba(255, 239, 214, 0.98);
}
.result-sync-badge.trio {
  color: #6b2c93;
  background: rgba(243, 230, 255, 0.96);
}
.result-sync-badge.trifecta {
  color: #8b1f1f;
  background: rgba(255, 229, 229, 0.98);
}
.result-sync-reason {
  margin-top: 0.34rem;
  font-size: 0.78rem;
  line-height: 1.6;
  color: #6a3a2f;
}
.result-sync-tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.32rem;
  margin-top: 0.34rem;
}
.result-sync-tag {
  display: inline-flex;
  align-items: center;
  padding: 0.12rem 0.5rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 900;
  letter-spacing: 0.02em;
}
.result-sync-tag.pop {
  color: #7a4d12;
  background: rgba(255, 239, 214, 0.98);
}
.result-sync-tag.track {
  color: #1f5b32;
  background: rgba(226, 247, 232, 0.96);
}
.result-sync-tag.distance {
  color: #23517b;
  background: rgba(226, 239, 255, 0.96);
}
.result-sync-tag.adjust {
  color: #6b2c93;
  background: rgba(243, 230, 255, 0.96);
}
.result-sync-avoid {
  margin-top: 0.34rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.32rem;
}
.result-sync-avoid-label {
  font-size: 0.74rem;
  font-weight: 900;
  color: #6d3027;
}
.result-sync-avoid-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.12rem 0.46rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 800;
  color: #7d2d23;
  background: rgba(255, 230, 225, 0.96);
  border: 1px solid rgba(174, 49, 36, 0.14);
}
.result-sync-prefer {
  margin-top: 0.28rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.32rem;
}
.result-sync-prefer-label {
  font-size: 0.74rem;
  font-weight: 900;
  color: #225136;
}
.result-sync-prefer-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.12rem 0.46rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 800;
  color: #1f5b32;
  background: rgba(226, 247, 232, 0.96);
  border: 1px solid rgba(46, 128, 69, 0.14);
}
.llm-reason-tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.32rem;
  margin-top: 0.34rem;
}
.llm-reason-tag {
  display: inline-flex;
  align-items: center;
  padding: 0.12rem 0.5rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 900;
  letter-spacing: 0.02em;
}
.llm-reason-tag.longshot {
  color: #8b5311;
  background: rgba(255, 242, 220, 0.98);
}
.llm-reason-tag.danger {
  color: #7d2d23;
  background: rgba(255, 230, 225, 0.96);
}
.llm-reason-tag.market {
  color: #23517b;
  background: rgba(226, 239, 255, 0.96);
}
.llm-reason-tag.adjust {
  color: #6b2c93;
  background: rgba(243, 230, 255, 0.96);
}
.llm-reason-tag.generic {
  color: #35513b;
  background: rgba(232, 243, 236, 0.96);
}
.feedback-trend-card {
  margin: 0.2rem 0 0.9rem;
  border-radius: 1.1rem;
  padding: 0.95rem 1rem;
  border: 1px solid rgba(187, 148, 30, 0.20);
  background: linear-gradient(180deg, rgba(255, 248, 227, 0.96) 0%, rgba(255, 253, 246, 0.98) 100%);
  box-shadow: 0 12px 26px rgba(116, 83, 0, 0.08);
}
.feedback-trend-title {
  font-size: 0.98rem;
  font-weight: 900;
  color: #5e430c;
}
.feedback-trend-sub {
  margin-top: 0.2rem;
  font-size: 0.84rem;
  line-height: 1.58;
  color: #71551d;
}
.feedback-trend-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.36rem;
  margin-top: 0.5rem;
}
.feedback-trend-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.16rem 0.56rem;
  border-radius: 999px;
  font-size: 0.74rem;
  font-weight: 900;
  color: #6d5218;
  background: rgba(255, 242, 205, 0.96);
}
.llm-hit-card {
  margin: 0.25rem 0 1rem;
  border-radius: 1.05rem;
  padding: 0.9rem 0.98rem;
  border: 1px solid rgba(52, 111, 173, 0.18);
  background: linear-gradient(180deg, rgba(235, 245, 255, 0.98) 0%, rgba(249, 252, 255, 0.99) 100%);
  box-shadow: 0 12px 24px rgba(52, 111, 173, 0.08);
}
.llm-hit-card.strong {
  border-color: rgba(174, 79, 28, 0.22);
  background: linear-gradient(180deg, rgba(255, 240, 228, 0.98) 0%, rgba(255, 249, 244, 0.99) 100%);
  box-shadow: 0 14px 26px rgba(167, 77, 27, 0.10);
}
.llm-hit-card .memo-chip {
  background: rgba(224, 238, 255, 0.96);
  color: #2a588a;
}
.llm-hit-card.strong .memo-chip {
  background: rgba(255, 229, 210, 0.96);
  color: #9a4d17;
}
.llm-hit-card .memo-title {
  color: #234b74;
}
.llm-hit-card.strong .memo-title {
  color: #8a4216;
}
.llm-hit-card .memo-line {
  color: #43607f;
}
.llm-hit-card.strong .memo-line {
  color: #7f4f2d;
}
.llm-hit-highlight {
  margin-top: 0.44rem;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.16rem 0.62rem;
  border-radius: 999px;
  font-size: 0.74rem;
  font-weight: 900;
  color: #25527e;
  background: rgba(226, 239, 255, 0.98);
}
.llm-hit-card.strong .llm-hit-highlight {
  color: #924716;
  background: rgba(255, 234, 219, 0.98);
}
.local-llm-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.55rem;
  margin: 0.35rem 0 0.7rem;
}
.local-llm-summary-card {
  border-radius: 1rem;
  padding: 0.8rem 0.9rem 0.86rem;
  border: 1px solid rgba(74, 99, 120, 0.16);
  background: linear-gradient(180deg, rgba(249, 251, 255, 0.99) 0%, rgba(255, 255, 255, 0.99) 100%);
  box-shadow: 0 10px 22px rgba(54, 84, 113, 0.08);
}
.local-llm-summary-card.favorite {
  border-color: rgba(184, 141, 23, 0.20);
  background: linear-gradient(180deg, rgba(255, 249, 228, 0.99) 0%, rgba(255, 255, 251, 0.99) 100%);
}
.local-llm-summary-card.longshot {
  border-color: rgba(196, 122, 25, 0.18);
  background: linear-gradient(180deg, rgba(255, 244, 230, 0.99) 0%, rgba(255, 255, 251, 0.99) 100%);
}
.local-llm-summary-card.danger {
  border-color: rgba(174, 49, 36, 0.18);
  background: linear-gradient(180deg, rgba(255, 239, 236, 0.99) 0%, rgba(255, 255, 255, 0.99) 100%);
}
.local-llm-summary-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.26rem;
  padding: 0.16rem 0.56rem;
  border-radius: 999px;
  font-size: 0.73rem;
  font-weight: 900;
  letter-spacing: 0.02em;
}
.local-llm-summary-card.favorite .local-llm-summary-chip {
  color: #8a6408;
  background: rgba(255, 239, 191, 0.92);
}
.local-llm-summary-card.longshot .local-llm-summary-chip {
  color: #8b5311;
  background: rgba(255, 235, 212, 0.96);
}
.local-llm-summary-card.danger .local-llm-summary-chip {
  color: #8b2318;
  background: rgba(255, 227, 222, 0.96);
}
.local-llm-summary-text {
  margin-top: 0.42rem;
  font-size: 0.88rem;
  line-height: 1.62;
  color: var(--k-text-main);
}
.basis-change-card {
  margin: 0.25rem 0 0.75rem;
  border-radius: 1.08rem;
  padding: 0.95rem 1rem;
  border: 1px solid rgba(64, 103, 150, 0.16);
  background: linear-gradient(180deg, rgba(241, 247, 255, 0.98) 0%, rgba(253, 255, 255, 0.99) 100%);
  box-shadow: 0 12px 24px rgba(56, 92, 132, 0.08);
}
.basis-change-card.changed {
  border-color: rgba(42, 125, 73, 0.20);
  background: linear-gradient(180deg, rgba(233, 248, 237, 0.98) 0%, rgba(251, 255, 252, 0.99) 100%);
  box-shadow: 0 14px 28px rgba(33, 103, 56, 0.10);
}
.basis-change-card.stable {
  border-color: rgba(90, 106, 130, 0.16);
  background: linear-gradient(180deg, rgba(245, 247, 250, 0.98) 0%, rgba(255, 255, 255, 0.99) 100%);
  box-shadow: 0 12px 24px rgba(72, 86, 104, 0.08);
}
.basis-change-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
}
.basis-change-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.16rem 0.56rem;
  border-radius: 999px;
  font-size: 0.73rem;
  font-weight: 900;
  letter-spacing: 0.02em;
  color: #2b537c;
  background: rgba(225, 239, 255, 0.96);
}
.basis-change-card.changed .basis-change-chip {
  color: #1f5b32;
  background: rgba(220, 244, 227, 0.98);
}
.basis-change-card.stable .basis-change-chip {
  color: #4a5866;
  background: rgba(235, 239, 244, 0.98);
}
.basis-change-title {
  margin-top: 0.44rem;
  font-size: 1.02rem;
  font-weight: 900;
  color: #24496f;
}
.basis-change-card.changed .basis-change-title {
  color: #1f5b32;
}
.basis-change-card.stable .basis-change-title {
  color: #4a5866;
}
.basis-change-flow {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 0.5rem;
  align-items: center;
  margin-top: 0.62rem;
}
.basis-change-node {
  border-radius: 0.92rem;
  padding: 0.68rem 0.75rem;
  border: 1px solid rgba(77, 101, 128, 0.12);
  background: rgba(255, 255, 255, 0.88);
}
.basis-change-node-label {
  font-size: 0.71rem;
  font-weight: 900;
  letter-spacing: 0.02em;
  color: #607080;
}
.basis-change-node-value {
  margin-top: 0.18rem;
  font-size: 0.92rem;
  font-weight: 900;
  color: var(--k-text-main);
}
.basis-change-node-mode {
  margin-top: 0.3rem;
  display: inline-flex;
  align-items: center;
  padding: 0.12rem 0.46rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 900;
  color: #30503d;
  background: rgba(229, 244, 233, 0.95);
}
.basis-change-node-mode.manual {
  color: #6c4b11;
  background: rgba(255, 241, 205, 0.96);
}
.basis-change-arrow {
  font-size: 1.15rem;
  font-weight: 900;
  color: #6b8094;
}
.basis-change-reason {
  margin-top: 0.45rem;
  font-size: 0.84rem;
  line-height: 1.6;
  color: #456078;
}
.basis-change-card.changed .basis-change-reason {
  color: #3f654e;
}
.basis-change-card.stable .basis-change-reason {
  color: #5d6773;
}
.ui-notice-card {
  margin: 0.2rem 0 0.9rem;
  border-radius: 1.05rem;
  padding: 0.9rem 0.98rem;
  border: 1px solid rgba(57, 126, 72, 0.18);
  background: linear-gradient(180deg, rgba(233, 248, 237, 0.98) 0%, rgba(248, 254, 250, 0.99) 100%);
  box-shadow: 0 12px 24px rgba(53, 110, 66, 0.08);
}
.ui-notice-card.info {
  border-color: rgba(52, 111, 173, 0.18);
  background: linear-gradient(180deg, rgba(232, 243, 255, 0.98) 0%, rgba(248, 252, 255, 0.99) 100%);
}
.ui-notice-card.warning {
  border-color: rgba(178, 120, 20, 0.2);
  background: linear-gradient(180deg, rgba(255, 247, 222, 0.98) 0%, rgba(255, 252, 244, 0.99) 100%);
}
.ui-notice-card.error {
  border-color: rgba(178, 60, 40, 0.2);
  background: linear-gradient(180deg, rgba(255, 235, 232, 0.98) 0%, rgba(255, 248, 247, 0.99) 100%);
}
.ui-notice-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.14rem 0.52rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 900;
  color: #225137;
  background: rgba(218, 243, 225, 0.96);
}
.ui-notice-card.info .ui-notice-chip {
  color: #24517d;
  background: rgba(224, 239, 255, 0.96);
}
.ui-notice-card.warning .ui-notice-chip {
  color: #7d5d10;
  background: rgba(255, 240, 191, 0.95);
}
.ui-notice-card.error .ui-notice-chip {
  color: #8f2c1f;
  background: rgba(255, 225, 220, 0.96);
}
.ui-notice-title {
  margin-top: 0.36rem;
  font-size: 1rem;
  font-weight: 900;
  color: #17321c;
}
.ui-notice-card.info .ui-notice-title { color: #1e4670; }
.ui-notice-card.warning .ui-notice-title { color: #6b5113; }
.ui-notice-card.error .ui-notice-title { color: #7b2f24; }
.ui-notice-sub {
  margin-top: 0.22rem;
  font-size: 0.86rem;
  line-height: 1.62;
  color: #3f5f49;
}
.ui-notice-card.info .ui-notice-sub { color: #40627f; }
.ui-notice-card.warning .ui-notice-sub { color: #7a6127; }
.ui-notice-card.error .ui-notice-sub { color: #7d4439; }
.ui-notice-cases {
  margin-top: 0.55rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.48rem;
}
.ui-notice-case {
  border-radius: 0.88rem;
  padding: 0.68rem 0.74rem;
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(57, 126, 72, 0.14);
}
.ui-notice-case.fit {
  border-color: rgba(46, 128, 69, 0.16);
  background: rgba(241, 251, 244, 0.94);
}
.ui-notice-case.unfit {
  border-color: rgba(174, 49, 36, 0.14);
  background: rgba(255, 242, 240, 0.94);
}
.ui-notice-case-label {
  display: block;
  font-size: 0.72rem;
  font-weight: 900;
  letter-spacing: 0.03em;
}
.ui-notice-case.fit .ui-notice-case-label {
  color: #25613a;
}
.ui-notice-case.unfit .ui-notice-case-label {
  color: #8b382b;
}
.ui-notice-case-text {
  margin-top: 0.16rem;
  font-size: 0.81rem;
  line-height: 1.6;
  color: #435f4d;
}
.sidebar-basis-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.36rem;
  margin: 0.38rem 0 0.5rem;
}
.sidebar-basis-chip {
  border-radius: 0.8rem;
  padding: 0.45rem 0.42rem;
  border: 1px solid rgba(57, 112, 71, 0.12);
  background: rgba(247, 251, 248, 0.94);
  text-align: center;
}
.sidebar-basis-chip .label {
  display: block;
  font-size: 0.7rem;
  font-weight: 900;
  color: #52705d;
}
.sidebar-basis-chip .value {
  margin-top: 0.14rem;
  display: block;
  font-size: 0.78rem;
  font-weight: 900;
  color: #244331;
}
.sidebar-basis-chip .active-mark {
  margin-top: 0.18rem;
  display: inline-flex;
  align-items: center;
  padding: 0.12rem 0.42rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 900;
  letter-spacing: 0.02em;
  color: #ffffff;
  background: rgba(35, 92, 56, 0.88);
}
.sidebar-basis-chip.active {
  box-shadow: 0 10px 22px rgba(35, 93, 57, 0.10);
}
.sidebar-basis-chip.active.trend {
  background: linear-gradient(180deg, rgba(222, 245, 229, 0.98) 0%, rgba(247, 252, 249, 0.99) 100%);
  border-color: rgba(43, 122, 72, 0.18);
}
.sidebar-basis-chip.active.analog {
  background: linear-gradient(180deg, rgba(231, 240, 255, 0.98) 0%, rgba(248, 251, 255, 0.99) 100%);
  border-color: rgba(55, 106, 171, 0.18);
}
.sidebar-basis-chip.active.base {
  background: linear-gradient(180deg, rgba(255, 243, 218, 0.98) 0%, rgba(255, 250, 243, 0.99) 100%);
  border-color: rgba(180, 122, 29, 0.18);
}
.sidebar-basis-chip.active.analog .active-mark {
  background: rgba(44, 93, 160, 0.92);
}
.sidebar-basis-chip.active.base .active-mark {
  background: rgba(163, 107, 16, 0.92);
}
.basis-decision-grid {
  margin-top: 0.42rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.48rem;
}
.basis-decision-card {
  border-radius: 0.92rem;
  padding: 0.72rem 0.76rem;
  background: rgba(255,255,255,0.78);
  border: 1px solid rgba(56, 108, 72, 0.12);
}
.basis-decision-card.trend {
  border-color: rgba(43, 122, 72, 0.16);
  background: rgba(242, 251, 245, 0.98);
}
.basis-decision-card.history {
  border-color: rgba(49, 92, 162, 0.16);
  background: rgba(244, 248, 255, 0.98);
}
.basis-decision-card.final {
  border-color: rgba(176, 124, 27, 0.18);
  background: rgba(255, 248, 237, 0.98);
}
.basis-decision-title {
  font-size: 0.72rem;
  font-weight: 900;
  letter-spacing: 0.03em;
  color: #4f6a58;
}
.basis-decision-card.history .basis-decision-title {
  color: #426184;
}
.basis-decision-card.final .basis-decision-title {
  color: #79551a;
}
.basis-decision-value {
  margin-top: 0.22rem;
  font-size: 0.92rem;
  font-weight: 900;
  color: #233f30;
  line-height: 1.5;
}
.basis-decision-card.history .basis-decision-value {
  color: #25456d;
}
.basis-decision-card.final .basis-decision-value {
  color: #5b4217;
}
.basis-decision-sub {
  margin-top: 0.18rem;
  font-size: 0.79rem;
  line-height: 1.58;
  color: #44604d;
}
.basis-decision-metrics {
  margin-top: 0.3rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.28rem;
}
.basis-decision-metric {
  display: inline-flex;
  align-items: center;
  gap: 0.22rem;
  padding: 0.12rem 0.44rem;
  border-radius: 999px;
  font-size: 0.69rem;
  font-weight: 800;
  color: #30503d;
  background: rgba(227, 243, 232, 0.92);
}
.basis-decision-card.history .basis-decision-metric {
  color: #31557e;
  background: rgba(229, 239, 255, 0.96);
}
.basis-decision-card.final .basis-decision-metric {
  color: #6d4f1c;
  background: rgba(255, 238, 208, 0.98);
}
.basis-decision-bet-row {
  margin-top: 0.26rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.28rem;
}
.basis-decision-bet-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.12rem 0.44rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 900;
  letter-spacing: 0.02em;
}
.basis-decision-bet-badge.prefer {
  color: #1f5d37;
  background: rgba(225, 246, 231, 0.96);
}
.basis-decision-bet-badge.avoid {
  color: #8a3d2d;
  background: rgba(255, 235, 231, 0.97);
}
.basis-decision-chip {
  margin-top: 0.26rem;
  display: inline-flex;
  align-items: center;
  padding: 0.12rem 0.44rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 900;
  letter-spacing: 0.02em;
  color: #ffffff;
  background: rgba(33, 99, 60, 0.88);
}
.basis-decision-card.history .basis-decision-chip {
  background: rgba(45, 93, 160, 0.9);
}
.basis-decision-card.final .basis-decision-chip {
  background: rgba(171, 112, 17, 0.92);
}
.basis-decision-chip.override {
  background: rgba(182, 65, 37, 0.92) !important;
}
.feedback-trend-stance {
  margin-top: 0.48rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.55rem;
}
.feedback-trend-stance-card {
  border-radius: 0.9rem;
  padding: 0.72rem 0.78rem;
  background: rgba(255,255,255,0.72);
  border: 1px solid rgba(187, 148, 30, 0.16);
}
.feedback-trend-stance-card.longshot {
  border-color: rgba(195, 129, 35, 0.20);
  background: rgba(255, 247, 233, 0.96);
}
.feedback-trend-stance-card.danger {
  border-color: rgba(173, 55, 40, 0.18);
  background: rgba(255, 241, 238, 0.96);
}
.feedback-trend-stance-card.market {
  border-color: rgba(52, 111, 173, 0.18);
  background: rgba(238, 246, 255, 0.96);
}
.feedback-trend-stance-card.adjust {
  border-color: rgba(120, 63, 171, 0.18);
  background: rgba(247, 239, 255, 0.96);
}
.feedback-trend-stance-card.neutral {
  border-color: rgba(80, 104, 84, 0.16);
  background: rgba(242, 247, 243, 0.96);
}
.feedback-trend-stance-title {
  font-size: 0.74rem;
  font-weight: 900;
  color: #6d5218;
}
.feedback-trend-stance-card.market .feedback-trend-stance-title {
  color: #2f5e8a;
}
.feedback-trend-stance-card.adjust .feedback-trend-stance-title {
  color: #6d3ea2;
}
.feedback-trend-stance-card.danger .feedback-trend-stance-title {
  color: #8b382b;
}
.feedback-trend-stance-card.longshot .feedback-trend-stance-title {
  color: #8c5c16;
}
.feedback-trend-stance-card.neutral .feedback-trend-stance-title {
  color: #4b6352;
}
.feedback-trend-stance-value {
  margin-top: 0.22rem;
  font-size: 0.9rem;
  font-weight: 800;
  color: #4f3b10;
  line-height: 1.55;
}
.feedback-trend-stance-card.market .feedback-trend-stance-value {
  color: #315882;
}
.feedback-trend-stance-card.adjust .feedback-trend-stance-value {
  color: #5e3b83;
}
.feedback-trend-stance-card.danger .feedback-trend-stance-value {
  color: #7b4337;
}
.feedback-trend-stance-card.longshot .feedback-trend-stance-value {
  color: #754c15;
}
.feedback-trend-stance-card.neutral .feedback-trend-stance-value {
  color: #425849;
}
.llm-hit-badge-row {
  margin-top: 0.34rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.34rem;
}
.llm-hit-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.14rem 0.52rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 900;
  letter-spacing: 0.02em;
}
.llm-hit-badge.recommend {
  color: #1f5b32;
  background: rgba(226, 247, 232, 0.96);
}
.llm-hit-badge.avoid {
  color: #7d2d23;
  background: rgba(255, 230, 225, 0.96);
}
.llm-hit-badge.longshot {
  background: rgba(255, 242, 220, 0.98);
  color: #8b5311;
}
.llm-hit-badge.danger {
  background: rgba(255, 230, 225, 0.96);
  color: #7d2d23;
}
.llm-hit-badge.market {
  background: rgba(226, 239, 255, 0.96);
  color: #23517b;
}
.llm-hit-badge.adjust {
  background: rgba(243, 230, 255, 0.96);
  color: #6b2c93;
}
.llm-hit-badge.neutral {
  background: rgba(232, 243, 236, 0.96);
  color: #35513b;
}
.llm-priority-card.longshot {
  border-color: rgba(195, 129, 35, 0.20);
  background: linear-gradient(180deg, rgba(255, 247, 233, 0.98) 0%, rgba(255, 252, 247, 0.99) 100%);
}
.llm-priority-card.danger {
  border-color: rgba(173, 55, 40, 0.18);
  background: linear-gradient(180deg, rgba(255, 241, 238, 0.98) 0%, rgba(255, 249, 248, 0.99) 100%);
}
.llm-priority-card.market {
  border-color: rgba(52, 111, 173, 0.18);
  background: linear-gradient(180deg, rgba(238, 246, 255, 0.98) 0%, rgba(249, 252, 255, 0.99) 100%);
}
.llm-priority-card.adjust {
  border-color: rgba(120, 63, 171, 0.18);
  background: linear-gradient(180deg, rgba(247, 239, 255, 0.98) 0%, rgba(252, 249, 255, 0.99) 100%);
}
.llm-priority-card.neutral {
  border-color: rgba(80, 104, 84, 0.16);
  background: linear-gradient(180deg, rgba(242, 247, 243, 0.98) 0%, rgba(251, 253, 251, 0.99) 100%);
}
.llm-priority-card .memo-chip.longshot {
  background: rgba(255, 242, 220, 0.98);
  color: #8b5311;
}
.llm-priority-card .memo-chip.danger {
  background: rgba(255, 230, 225, 0.96);
  color: #7d2d23;
}
.llm-priority-card .memo-chip.market {
  background: rgba(226, 239, 255, 0.96);
  color: #23517b;
}
.llm-priority-card .memo-chip.adjust {
  background: rgba(243, 230, 255, 0.96);
  color: #6b2c93;
}
.llm-priority-card .memo-chip.neutral {
  background: rgba(232, 243, 236, 0.96);
  color: #35513b;
}
.feedback-trend-allocation {
  margin-top: 0.3rem;
  display: flex;
  overflow: hidden;
  border-radius: 999px;
  height: 0.64rem;
  background: rgba(226, 214, 181, 0.32);
}
.feedback-trend-allocation-segment {
  height: 100%;
}
.feedback-trend-allocation-segment.main {
  background: linear-gradient(90deg, rgba(56, 132, 78, 0.92) 0%, rgba(71, 156, 92, 0.92) 100%);
}
.feedback-trend-allocation-segment.cover {
  background: linear-gradient(90deg, rgba(74, 118, 184, 0.92) 0%, rgba(96, 140, 205, 0.92) 100%);
}
.feedback-trend-allocation-segment.hole {
  background: linear-gradient(90deg, rgba(210, 136, 48, 0.92) 0%, rgba(225, 154, 69, 0.92) 100%);
}
.feedback-trend-badge-row {
  margin-top: 0.24rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.34rem;
}
.feedback-trend-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.14rem 0.48rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 900;
  letter-spacing: 0.02em;
}
.feedback-trend-badge.high {
  color: #1f5b32;
  background: rgba(226, 247, 232, 0.96);
}
.feedback-trend-badge.mid {
  color: #23517b;
  background: rgba(226, 239, 255, 0.96);
}
.feedback-trend-badge.low {
  color: #8a5d1d;
  background: rgba(255, 241, 213, 0.98);
}
.feedback-trend-focus-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.55rem;
  margin-top: 0.58rem;
}
.feedback-trend-focus-card {
  border-radius: 1rem;
  padding: 0.9rem 0.92rem;
  background: rgba(255,255,255,0.82);
  border: 1px solid rgba(187, 148, 30, 0.18);
}
.feedback-trend-focus-card.primary {
  background: linear-gradient(180deg, rgba(226, 247, 232, 0.96) 0%, rgba(252, 255, 252, 0.98) 100%);
  border-color: rgba(46, 128, 69, 0.18);
}
.feedback-trend-focus-card.secondary {
  background: linear-gradient(180deg, rgba(238, 246, 255, 0.96) 0%, rgba(252, 254, 255, 0.98) 100%);
  border-color: rgba(52, 102, 166, 0.18);
}
.feedback-trend-focus-card.tertiary {
  background: linear-gradient(180deg, rgba(255, 244, 229, 0.96) 0%, rgba(255, 251, 246, 0.98) 100%);
  border-color: rgba(196, 116, 34, 0.18);
}
.feedback-trend-focus-kicker {
  font-size: 0.72rem;
  font-weight: 900;
  letter-spacing: 0.06em;
  color: #6d5218;
}
.feedback-trend-focus-value {
  margin-top: 0.28rem;
  font-size: 1.18rem;
  font-weight: 900;
  color: #17321c;
}
.feedback-trend-focus-sub {
  margin-top: 0.2rem;
  font-size: 0.8rem;
  line-height: 1.55;
  color: #4b5f52;
}
.result-sync-weight-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.7rem;
  margin-top: 0.55rem;
}
.result-sync-weight-card {
  border-radius: 0.95rem;
  padding: 0.85rem 0.9rem;
  border: 1px solid rgba(59, 97, 69, 0.14);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 10px 22px rgba(33, 63, 41, 0.06);
}
.result-sync-weight-card.strong {
  background: rgba(232, 248, 235, 0.94);
  border-color: rgba(46, 128, 69, 0.18);
}
.result-sync-weight-card.weak {
  background: rgba(255, 241, 239, 0.96);
  border-color: rgba(174, 49, 36, 0.16);
}
.result-sync-weight-title {
  font-size: 0.8rem;
  font-weight: 900;
  letter-spacing: 0.03em;
  color: #1e3a27;
}
.result-sync-weight-card.weak .result-sync-weight-title {
  color: #7d2d23;
}
.result-sync-weight-line {
  margin-top: 0.42rem;
  font-size: 0.8rem;
  line-height: 1.56;
  color: #294131;
}
.result-sync-weight-card.weak .result-sync-weight-line {
  color: #6e3027;
}
.danger-line strong, .memo-line strong, .bet-pick-line strong {
  color: inherit;
}
.prediction-hero {
  margin: 0.25rem 0 1rem;
  border-radius: 1.2rem;
  padding: 1.1rem 1.15rem 1rem;
  border: 1px solid rgba(38, 94, 53, 0.18);
  background:
    linear-gradient(135deg, rgba(255, 252, 237, 0.96) 0%, rgba(242, 251, 244, 0.97) 58%, rgba(231, 246, 236, 0.96) 100%);
  box-shadow: 0 16px 30px rgba(33, 63, 41, 0.12);
}
.prediction-kicker {
  display: inline-block;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #1f6a37;
  background: rgba(220, 245, 226, 0.95);
}
.prediction-title {
  margin-top: 0.55rem;
  font-size: 1.45rem;
  font-weight: 900;
  color: #17321c;
  line-height: 1.25;
}
.prediction-subtitle {
  margin-top: 0.3rem;
  font-size: 0.96rem;
  color: #45614d;
  line-height: 1.55;
}
.prediction-ribbon {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.7rem;
  margin-top: 0.95rem;
}
.prediction-ribbon-card {
  border-radius: 0.95rem;
  padding: 0.75rem 0.85rem;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(56, 107, 70, 0.16);
}
.prediction-ribbon-label {
  font-size: 0.74rem;
  font-weight: 800;
  color: #51705a;
  letter-spacing: 0.06em;
}
.prediction-ribbon-value {
  margin-top: 0.24rem;
  font-size: 1rem;
  font-weight: 800;
  color: #17321c;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.prediction-mark-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 0.8rem;
  margin: 0.25rem 0 1rem;
}
.prediction-mark-card {
  border-radius: 1rem;
  padding: 0.95rem 1rem 0.9rem;
  background: rgba(255, 255, 255, 0.87);
  border: 1px solid rgba(52, 99, 66, 0.16);
  box-shadow: 0 12px 24px rgba(33, 63, 41, 0.11);
}
.prediction-mark-card.danger {
  background: linear-gradient(180deg, rgba(255, 241, 239, 0.95) 0%, rgba(255, 249, 248, 0.98) 100%);
  border-color: rgba(174, 49, 36, 0.24);
}
.prediction-mark-card.primary {
  background: linear-gradient(180deg, rgba(255, 250, 229, 0.98) 0%, rgba(255, 255, 250, 0.98) 100%);
  border-color: rgba(180, 138, 17, 0.24);
}
.prediction-mark-card.rival {
  background: linear-gradient(180deg, rgba(235, 247, 255, 0.96) 0%, rgba(250, 253, 255, 0.98) 100%);
  border-color: rgba(52, 102, 166, 0.22);
}
.prediction-mark-card.longshot {
  background: linear-gradient(180deg, rgba(255, 245, 230, 0.96) 0%, rgba(255, 252, 247, 0.98) 100%);
  border-color: rgba(196, 116, 34, 0.22);
}
.prediction-mark-card.support {
  background: linear-gradient(180deg, rgba(245, 244, 255, 0.97) 0%, rgba(253, 252, 255, 0.99) 100%);
  border-color: rgba(109, 96, 187, 0.20);
}
.prediction-mark-card.dream {
  background: linear-gradient(180deg, rgba(239, 246, 250, 0.96) 0%, rgba(253, 255, 255, 0.98) 100%);
  border-color: rgba(57, 98, 120, 0.22);
}
.prediction-mark-card.spiritual {
  background: linear-gradient(180deg, rgba(239, 246, 250, 0.96) 0%, rgba(253, 255, 255, 0.98) 100%);
  border-color: rgba(57, 98, 120, 0.22);
}
.prediction-mark-top {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  margin-bottom: 0.38rem;
}
.prediction-mark {
  min-width: 2.1rem;
  height: 2.1rem;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  font-weight: 900;
  color: #fff;
  background: linear-gradient(180deg, #2d8d48 0%, #1d6d36 100%);
}
.prediction-mark-card.danger .prediction-mark {
  background: linear-gradient(180deg, #d35a46 0%, #a33122 100%);
}
.prediction-mark-card.primary .prediction-mark {
  background: linear-gradient(180deg, #d3a532 0%, #9f7312 100%);
}
.prediction-mark-card.rival .prediction-mark {
  background: linear-gradient(180deg, #4d8bd6 0%, #2d63aa 100%);
}
.prediction-mark-card.longshot .prediction-mark {
  background: linear-gradient(180deg, #de8b34 0%, #ac5b11 100%);
}
.prediction-mark-card.support .prediction-mark {
  background: linear-gradient(180deg, #7f72d8 0%, #5948b4 100%);
}
.prediction-mark-card.dream .prediction-mark {
  background: linear-gradient(180deg, #5c93a9 0%, #356678 100%);
}
.prediction-mark-card.spiritual .prediction-mark {
  background: linear-gradient(180deg, #5c93a9 0%, #356678 100%);
}
.prediction-mark-label {
  font-size: 0.82rem;
  font-weight: 800;
  color: #4d6d56;
  letter-spacing: 0.04em;
}
.prediction-mark-name {
  font-size: 1.08rem;
  font-weight: 900;
  color: #16311b;
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.prediction-mark-meta {
  margin-top: 0.24rem;
  font-size: 0.88rem;
  line-height: 1.55;
  color: #476050;
  overflow-wrap: anywhere;
}
.prediction-sheet {
  border-radius: 1rem;
  overflow: hidden;
  margin: 0.15rem 0 1.2rem;
  border: 1px solid rgba(49, 96, 63, 0.18);
  box-shadow: 0 12px 24px rgba(33, 63, 41, 0.09);
}
.prediction-sheet-head, .prediction-sheet-row {
  display: grid;
  grid-template-columns: 70px minmax(140px, 1.1fr) minmax(120px, 1fr) minmax(180px, 1.2fr);
  gap: 0.7rem;
  align-items: center;
}
.prediction-sheet-head {
  background: linear-gradient(180deg, rgba(33, 63, 41, 0.95) 0%, rgba(23, 50, 28, 0.95) 100%);
  color: #f7fff9;
  padding: 0.72rem 0.95rem;
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0.08em;
}
.prediction-sheet-row {
  padding: 0.8rem 0.95rem;
  background: rgba(255, 255, 255, 0.9);
  border-top: 1px solid rgba(72, 114, 84, 0.12);
}
.prediction-sheet-row:nth-child(even) {
  background: rgba(248, 252, 249, 0.96);
}
.prediction-sheet-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 999px;
  color: #fff;
  font-size: 0.96rem;
  font-weight: 900;
}
.prediction-sheet-mark.primary { background: linear-gradient(180deg, #d3a532 0%, #9f7312 100%); }
.prediction-sheet-mark.rival { background: linear-gradient(180deg, #4d8bd6 0%, #2d63aa 100%); }
.prediction-sheet-mark.longshot { background: linear-gradient(180deg, #de8b34 0%, #ac5b11 100%); }
.prediction-sheet-mark.danger { background: linear-gradient(180deg, #d35a46 0%, #a33122 100%); }
.prediction-sheet-mark.dream { background: linear-gradient(180deg, #5c93a9 0%, #356678 100%); }
.prediction-sheet-main {
  font-size: 1rem;
  font-weight: 900;
  color: #17321c;
  overflow-wrap: anywhere;
}
.prediction-sheet-sub {
  margin-top: 0.18rem;
  font-size: 0.8rem;
  color: #53705c;
  overflow-wrap: anywhere;
}
.prediction-sheet-bet, .prediction-sheet-note {
  font-size: 0.88rem;
  line-height: 1.55;
  color: #395342;
  overflow-wrap: anywhere;
}
.prediction-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
  gap: 0.65rem;
  margin: 0.2rem 0 1rem;
}
.prediction-strip-item {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.75rem 0.85rem;
  border-radius: 0.95rem;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(56, 104, 69, 0.15);
  box-shadow: 0 10px 20px rgba(33, 63, 41, 0.08);
}
.prediction-strip-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 999px;
  color: #fff;
  font-weight: 900;
  font-size: 0.95rem;
}
.prediction-strip-mark.primary { background: linear-gradient(180deg, #d3a532 0%, #9f7312 100%); }
.prediction-strip-mark.rival { background: linear-gradient(180deg, #4d8bd6 0%, #2d63aa 100%); }
.prediction-strip-mark.longshot { background: linear-gradient(180deg, #de8b34 0%, #ac5b11 100%); }
.prediction-strip-mark.support { background: linear-gradient(180deg, #7f72d8 0%, #5948b4 100%); }
.prediction-strip-mark.spiritual { background: linear-gradient(180deg, #5c93a9 0%, #356678 100%); }
.prediction-strip-mark.danger { background: linear-gradient(180deg, #d35a46 0%, #a33122 100%); }
.prediction-strip-main {
  font-size: 0.96rem;
  font-weight: 900;
  color: #17321c;
  line-height: 1.3;
}
.prediction-strip-sub {
  margin-top: 0.14rem;
  font-size: 0.77rem;
  color: #54705d;
}
.bet-slip-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 0.85rem;
  margin: 0.25rem 0 1rem;
}
.bet-slip-card {
  border-radius: 1rem;
  padding: 0.95rem 1rem 0.9rem;
  box-shadow: 0 12px 24px rgba(33, 63, 41, 0.10);
  border: 1px solid rgba(49, 96, 63, 0.15);
  background: rgba(255, 255, 255, 0.9);
}
.bet-slip-card.main {
  background: linear-gradient(180deg, rgba(236, 250, 240, 0.98) 0%, rgba(255, 255, 255, 0.98) 100%);
}
.bet-slip-card.cover {
  background: linear-gradient(180deg, rgba(239, 245, 255, 0.98) 0%, rgba(255, 255, 255, 0.98) 100%);
}
.bet-slip-card.hole {
  background: linear-gradient(180deg, rgba(255, 246, 231, 0.98) 0%, rgba(255, 255, 255, 0.98) 100%);
}
.bet-slip-chip {
  display: inline-block;
  border-radius: 999px;
  padding: 0.18rem 0.58rem;
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  margin-bottom: 0.45rem;
}
.bet-slip-card.main .bet-slip-chip {
  background: rgba(217, 243, 224, 0.95);
  color: #1d6d36;
}
.bet-slip-card.cover .bet-slip-chip {
  background: rgba(223, 235, 255, 0.95);
  color: #2d63aa;
}
.bet-slip-card.hole .bet-slip-chip {
  background: rgba(255, 232, 198, 0.95);
  color: #a35a14;
}
.bet-slip-title {
  font-size: 1rem;
  font-weight: 900;
  color: #17321c;
  margin-bottom: 0.35rem;
}
.bet-slip-row {
  font-size: 0.9rem;
  line-height: 1.6;
  color: #35513b;
  margin-top: 0.16rem;
}
.budget-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 0.85rem;
  margin: 0.2rem 0 1rem;
}
.budget-card {
  border-radius: 1rem;
  padding: 0.95rem 1rem;
  border: 1px solid rgba(49, 96, 63, 0.15);
  box-shadow: 0 12px 24px rgba(33, 63, 41, 0.10);
  background: rgba(255, 255, 255, 0.92);
}
.budget-card.main {
  background: linear-gradient(180deg, rgba(236, 250, 240, 0.98) 0%, rgba(255, 255, 255, 0.98) 100%);
}
.budget-card.cover {
  background: linear-gradient(180deg, rgba(239, 245, 255, 0.98) 0%, rgba(255, 255, 255, 0.98) 100%);
}
.budget-card.hole {
  background: linear-gradient(180deg, rgba(255, 246, 231, 0.98) 0%, rgba(255, 255, 255, 0.98) 100%);
}
.budget-chip {
  display: inline-block;
  border-radius: 999px;
  padding: 0.18rem 0.58rem;
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  margin-bottom: 0.45rem;
}
.budget-card.main .budget-chip {
  background: rgba(217, 243, 224, 0.95);
  color: #1d6d36;
}
.budget-card.cover .budget-chip {
  background: rgba(223, 235, 255, 0.95);
  color: #2d63aa;
}
.budget-card.hole .budget-chip {
  background: rgba(255, 232, 198, 0.95);
  color: #a35a14;
}
.budget-total {
  font-size: 1.3rem;
  font-weight: 900;
  color: #17321c;
  margin-bottom: 0.25rem;
}
.budget-line {
  font-size: 0.88rem;
  line-height: 1.6;
  color: #395342;
}
.mark-bet-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 0.7rem;
  margin: 0.4rem 0 1rem;
}
.mark-bet-card {
  border-radius: 1rem;
  padding: 0.85rem 0.95rem;
  border: 1px solid rgba(35, 83, 50, 0.14);
  background: rgba(255, 255, 255, 0.84);
  box-shadow: 0 12px 22px rgba(24, 53, 36, 0.08);
}
.mark-bet-card.primary {
  background: linear-gradient(135deg, rgba(255, 247, 210, 0.98), rgba(255, 255, 245, 0.98));
}
.mark-bet-card.rival {
  background: linear-gradient(135deg, rgba(228, 244, 255, 0.98), rgba(246, 251, 255, 0.98));
}
.mark-bet-card.longshot {
  background: linear-gradient(135deg, rgba(255, 236, 219, 0.98), rgba(255, 249, 242, 0.98));
}
.mark-bet-mark {
  font-size: 1.18rem;
  font-weight: 900;
  color: #17321c;
}
.mark-bet-horse {
  margin-top: 0.18rem;
  font-size: 1rem;
  font-weight: 900;
  color: #17321c;
}
.mark-bet-note {
  margin-top: 0.22rem;
  font-size: 0.84rem;
  line-height: 1.55;
  color: #4e6556;
}
.mark-bet-picks {
  margin-top: 0.48rem;
  font-size: 0.88rem;
  line-height: 1.6;
  color: #284837;
}
.weekly-race-card {
  border-radius: 1rem;
  padding: 0.95rem 1rem 0.9rem;
  background: linear-gradient(180deg, rgba(255, 252, 237, 0.98) 0%, rgba(248, 253, 249, 0.99) 100%);
  border: 1px solid rgba(179, 138, 18, 0.18);
  box-shadow: 0 12px 24px rgba(33, 63, 41, 0.10);
  height: 100%;
  overflow: visible;
}
.weekly-feature-card {
  border-radius: 1.15rem;
  padding: 1.05rem 1.1rem 1rem;
  margin: 0.2rem 0 0.95rem;
  background: linear-gradient(135deg, rgba(255, 249, 231, 0.98) 0%, rgba(244, 251, 245, 0.98) 62%, rgba(232, 244, 236, 0.98) 100%);
  border: 1px solid rgba(179, 138, 18, 0.24);
  box-shadow: 0 16px 30px rgba(33, 63, 41, 0.13);
  overflow: visible;
}
.weekly-feature-title {
  margin-top: 0.28rem;
  font-size: 1.18rem;
  font-weight: 900;
  line-height: 1.35;
  color: #17321c;
  overflow-wrap: anywhere;
}
.weekly-feature-sub {
  margin-top: 0.24rem;
  font-size: 0.9rem;
  line-height: 1.55;
  color: #46614f;
  overflow-wrap: anywhere;
}
.weekly-feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 0.55rem;
  margin-top: 0.75rem;
}
.weekly-feature-item {
  border-radius: 0.9rem;
  padding: 0.68rem 0.78rem;
  background: rgba(255, 255, 255, 0.80);
  border: 1px solid rgba(56, 107, 70, 0.14);
  min-width: 0;
  overflow-wrap: anywhere;
}
.weekly-feature-item strong {
  display: block;
  margin-bottom: 0.16rem;
  color: #17321c;
}
.weekly-race-chiprow {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-bottom: 0.45rem;
}
.weekly-race-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.14rem 0.5rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 800;
  background: rgba(233, 245, 237, 0.95);
  color: #2d6541;
}
.weekly-race-chip.grade {
  background: rgba(255, 240, 191, 0.92);
  color: #7d5d10;
}
.weekly-llm-banner {
  margin: 0.18rem 0 0.45rem;
  display: inline-flex;
  align-items: center;
  gap: 0.36rem;
  padding: 0.28rem 0.72rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 900;
  letter-spacing: 0.02em;
}
.weekly-llm-banner.agree {
  color: #1f5b32;
  background: rgba(226, 247, 232, 0.96);
  border: 1px solid rgba(46, 128, 69, 0.16);
}
.weekly-llm-banner.diff {
  color: #8b5311;
  background: rgba(255, 242, 220, 0.98);
  border: 1px solid rgba(196, 136, 37, 0.18);
}
.weekly-llm-banner.pending {
  color: #46614f;
  background: rgba(240, 245, 241, 0.98);
  border: 1px solid rgba(93, 113, 99, 0.16);
}
.weekly-llm-banner.large {
  margin-top: 0.42rem;
  padding: 0.36rem 0.86rem;
  font-size: 0.86rem;
}
.weekly-race-title {
  font-size: 1rem;
  font-weight: 900;
  line-height: 1.4;
  color: #17321c;
  overflow-wrap: anywhere;
}
.weekly-race-meta {
  margin-top: 0.3rem;
  font-size: 0.86rem;
  line-height: 1.55;
  color: #486151;
  overflow-wrap: anywhere;
}
.weekly-race-meta-grid {
  margin-top: 0.52rem;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.42rem;
}
.weekly-race-meta-card {
  border-radius: 0.8rem;
  padding: 0.55rem 0.62rem;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(56, 107, 70, 0.12);
  min-width: 0;
}
.weekly-race-meta-label {
  display: block;
  font-size: 0.7rem;
  font-weight: 800;
  letter-spacing: 0.05em;
  color: #567160;
}
.weekly-race-meta-value {
  margin-top: 0.12rem;
  font-size: 0.86rem;
  line-height: 1.45;
  color: #17321c;
  font-weight: 800;
  overflow-wrap: anywhere;
}
.weekly-race-picks {
  margin-top: 0.52rem;
  display: grid;
  gap: 0.24rem;
}
.weekly-race-pick {
  font-size: 0.86rem;
  line-height: 1.45;
  color: #274132;
  overflow-wrap: anywhere;
}
.weekly-race-pick strong {
  color: #17321c;
}
.weekly-race-ticket {
  margin-top: 0.5rem;
  font-size: 0.82rem;
  line-height: 1.52;
  color: #34503f;
  overflow-wrap: anywhere;
}
.weekly-race-expectation {
  margin-top: 0.55rem;
  padding: 0.72rem 0.78rem 0.7rem;
  border-radius: 0.9rem;
  background: linear-gradient(180deg, rgba(255, 251, 236, 0.98) 0%, rgba(248, 252, 255, 0.96) 100%);
  border: 1px solid rgba(177, 137, 33, 0.18);
}
.weekly-race-expectation-title {
  font-size: 0.74rem;
  font-weight: 900;
  letter-spacing: 0.05em;
  color: #6b531d;
}
.weekly-race-expectation .feedback-trend-badge-row {
  margin-top: 0.36rem;
  gap: 0.42rem;
}
.weekly-race-expectation .feedback-trend-badge {
  font-size: 0.82rem;
  padding: 0.22rem 0.62rem;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.32);
}
.print-sheet-wrap {
  margin: 0.3rem 0 1rem;
  border: 1px solid rgba(50, 95, 63, 0.18);
  border-radius: 1rem;
  overflow: hidden;
  box-shadow: 0 12px 24px rgba(33, 63, 41, 0.10);
}
.print-sheet-header {
  padding: 1rem 1.05rem 0.9rem;
  background: linear-gradient(180deg, rgba(255, 254, 246, 0.98) 0%, rgba(242, 249, 244, 0.98) 100%);
  border-bottom: 1px solid rgba(66, 107, 77, 0.14);
}
.print-sheet-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.7rem;
  flex-wrap: wrap;
}
.print-sheet-logo {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.28rem 0.65rem;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 900;
  letter-spacing: 0.08em;
  color: #1f6a37;
  background: rgba(220, 245, 226, 0.95);
}
.print-sheet-kicker {
  font-size: 0.74rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #1d6d36;
}
.print-sheet-title {
  margin-top: 0.4rem;
  font-size: 1.35rem;
  font-weight: 900;
  color: #17321c;
}
.print-sheet-sub {
  margin-top: 0.22rem;
  font-size: 0.9rem;
  color: #496151;
}
.print-sheet-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 0.55rem;
  margin-top: 0.75rem;
}
.print-sheet-meta-card {
  border-radius: 0.85rem;
  padding: 0.68rem 0.75rem;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(56, 107, 70, 0.16);
}
.print-sheet-meta-card.emphasis {
  background: linear-gradient(180deg, rgba(255, 249, 231, 0.96) 0%, rgba(255, 255, 248, 0.98) 100%);
  border-color: rgba(179, 138, 18, 0.20);
}
.print-sheet-meta-label {
  font-size: 0.7rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  color: #54705d;
}
.print-sheet-meta-value {
  margin-top: 0.22rem;
  font-size: 0.95rem;
  font-weight: 800;
  line-height: 1.35;
  color: #17321c;
}
.print-ticket-band-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.55rem;
  padding: 0.9rem 1rem 0.2rem;
  background: rgba(249, 252, 250, 0.92);
}
.print-ticket-band {
  border-radius: 0.92rem;
  padding: 0.75rem 0.8rem;
  border: 1px solid rgba(56, 107, 70, 0.16);
  background: rgba(255, 255, 255, 0.82);
}
.print-ticket-band.main {
  background: linear-gradient(180deg, rgba(255, 249, 231, 0.96) 0%, rgba(255, 255, 248, 0.98) 100%);
  border-color: rgba(179, 138, 18, 0.22);
}
.print-ticket-band.cover {
  background: linear-gradient(180deg, rgba(238, 246, 255, 0.96) 0%, rgba(252, 254, 255, 0.98) 100%);
  border-color: rgba(52, 102, 166, 0.20);
}
.print-ticket-band.hole {
  background: linear-gradient(180deg, rgba(255, 244, 229, 0.96) 0%, rgba(255, 251, 246, 0.98) 100%);
  border-color: rgba(196, 116, 34, 0.22);
}
.print-ticket-band-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.16rem 0.52rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 800;
  color: #17321c;
  background: rgba(255, 255, 255, 0.72);
}
.print-ticket-band-title {
  margin-top: 0.32rem;
  font-size: 0.96rem;
  font-weight: 900;
  color: #17321c;
}
.print-ticket-band-line {
  margin-top: 0.24rem;
  font-size: 0.84rem;
  line-height: 1.5;
  color: #2f4a36;
}
.ticket-amount-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.7rem;
  margin: 0.35rem 0 1rem;
}
.ticket-amount-card {
  border-radius: 1rem;
  padding: 0.9rem 1rem 0.85rem;
  border: 1px solid rgba(56, 107, 70, 0.16);
  background: rgba(255, 255, 255, 0.86);
  box-shadow: 0 12px 24px rgba(33, 63, 41, 0.10);
}
.ticket-amount-card.main {
  background: linear-gradient(180deg, rgba(255, 249, 231, 0.96) 0%, rgba(255, 255, 248, 0.98) 100%);
  border-color: rgba(179, 138, 18, 0.22);
}
.ticket-amount-card.cover {
  background: linear-gradient(180deg, rgba(238, 246, 255, 0.96) 0%, rgba(252, 254, 255, 0.98) 100%);
  border-color: rgba(52, 102, 166, 0.20);
}
.ticket-amount-card.hole {
  background: linear-gradient(180deg, rgba(255, 244, 229, 0.96) 0%, rgba(255, 251, 246, 0.98) 100%);
  border-color: rgba(196, 116, 34, 0.22);
}
.ticket-amount-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.16rem 0.52rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 800;
  color: #17321c;
  background: rgba(255, 255, 255, 0.72);
}
.ticket-amount-total {
  margin-top: 0.34rem;
  font-size: 1.45rem;
  font-weight: 900;
  color: #17321c;
}
.ticket-amount-metric {
  margin-top: 0.25rem;
  font-size: 0.82rem;
  font-weight: 800;
  line-height: 1.5;
  color: #3b5a42;
}
.ticket-amount-line {
  margin-top: 0.26rem;
  font-size: 0.84rem;
  line-height: 1.55;
  color: #35513b;
}
.print-sheet-table {
  width: 100%;
  border-collapse: collapse;
  background: rgba(255, 255, 255, 0.96);
}
.print-sheet-table th,
.print-sheet-table td {
  padding: 0.7rem 0.8rem;
  border-top: 1px solid rgba(70, 112, 82, 0.12);
  text-align: left;
  vertical-align: top;
  font-size: 0.87rem;
  color: #274132;
}
.print-sheet-table th {
  font-size: 0.75rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  background: rgba(244, 249, 245, 0.94);
}
.print-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 2rem;
  height: 2rem;
  border-radius: 999px;
  color: #fff;
  font-size: 0.95rem;
  font-weight: 900;
}
.print-badge.primary { background: linear-gradient(180deg, #d3a532 0%, #9f7312 100%); }
.print-badge.rival { background: linear-gradient(180deg, #4d8bd6 0%, #2d63aa 100%); }
.print-badge.longshot { background: linear-gradient(180deg, #de8b34 0%, #ac5b11 100%); }
.print-badge.support { background: linear-gradient(180deg, #7f72d8 0%, #5948b4 100%); }
.print-badge.spiritual { background: linear-gradient(180deg, #5c93a9 0%, #356678 100%); }
.print-badge.danger { background: linear-gradient(180deg, #d35a46 0%, #a33122 100%); }
</style>
""",
        unsafe_allow_html=True,
    )


def _to_csv_download(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def _with_one_based_index(frame: pd.DataFrame, label: str = "No.") -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    out.index = pd.RangeIndex(start=1, stop=len(out) + 1, step=1, name=label)
    return out



def _annotate_prediction_archive_budget_basis(
    frame: pd.DataFrame | None,
    *,
    basis_key: Any,
    basis_label: Any,
    auto_mode: bool,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    out = frame.copy()
    out["budget_basis_key"] = _to_text(basis_key) or "base"
    out["budget_basis_label"] = _to_text(basis_label) or "ベース配分"
    out["budget_basis_mode"] = "半自動" if bool(auto_mode) else "手動"
    return out


def _sync_prediction_archive(frame: pd.DataFrame | None) -> pd.DataFrame:
    existing = _read_csv_if_exists(PREDICTION_ARCHIVE_PATH)
    merged = upsert_prediction_archive(existing, frame)
    if not merged.empty:
        existing_for_compare = None
        if existing is not None:
            existing_for_compare = upsert_prediction_archive(existing, pd.DataFrame())
        if not _frames_equal_for_storage(existing_for_compare, merged):
            _write_csv(PREDICTION_ARCHIVE_PATH, merged)
    elif PREDICTION_ARCHIVE_PATH.exists():
        PREDICTION_ARCHIVE_PATH.unlink(missing_ok=True)
    return merged


def _build_prediction_feature_rows(
    result: PredictionResult,
    *,
    race_id: Any,
    race_date: Any,
    race_name: Any,
    race_grade: Any,
    venue: Any,
    weather: Any,
    track_condition: Any,
    distance: Any,
    field_size: Any,
    predicted_at: str | None = None,
) -> pd.DataFrame:
    if result.horse_predictions.empty:
        return pd.DataFrame()
    work = result.horse_predictions.copy().reset_index(drop=True)
    work.insert(0, "predicted_rank", work.index + 1)
    rename_map = {
        "馬": "horse",
        "騎手": "jockey",
        "勝率": "predicted_win_prob",
        "複勝率": "predicted_place_prob",
    }
    work = work.rename(columns=rename_map)
    keep_cols = [
        "horse",
        "jockey",
        "predicted_rank",
        "predicted_win_prob",
        "predicted_place_prob",
        "horse_win_rate",
        "horse_place_rate",
        "jockey_win_rate",
        "jockey_place_rate",
        "trainer_win_rate",
        "trainer_place_rate",
        "gate_place_rate",
        "weather_fit",
        "track_fit",
        "distance_fit",
        "form_factor",
        "condition_factor",
        "paddock_factor",
        "weight_diff_factor",
        "odds_shift_factor",
        "market_factor",
    ]
    keep_cols = [col for col in keep_cols if col in work.columns]
    out = work[keep_cols].copy()
    out.insert(0, "race_id", _to_text(race_id))
    out.insert(1, "race_date", _to_text(race_date))
    out.insert(2, "race_name", _to_text(race_name))
    out.insert(3, "race_grade", _to_text(race_grade))
    out.insert(4, "venue", _to_text(venue))
    out.insert(5, "weather", _to_text(weather))
    out.insert(6, "track_condition", _to_text(track_condition))
    distance_value = pd.to_numeric(pd.Series([distance]), errors="coerce").iloc[0]
    field_size_value = pd.to_numeric(pd.Series([field_size]), errors="coerce").iloc[0]
    out.insert(7, "distance", "" if pd.isna(distance_value) else float(distance_value))
    out.insert(8, "field_size", "" if pd.isna(field_size_value) else int(float(field_size_value)))
    out.insert(9, "predicted_at", predicted_at or datetime.now().isoformat(timespec="seconds"))
    return out


def _sync_prediction_feature_archive(frame: pd.DataFrame | None) -> pd.DataFrame:
    existing = _read_csv_if_exists(PREDICTION_FEATURE_ARCHIVE_PATH)
    merged = upsert_prediction_feature_archive(existing, frame)
    if not merged.empty:
        existing_for_compare = None
        if existing is not None:
            existing_for_compare = upsert_prediction_feature_archive(existing, pd.DataFrame())
        if not _frames_equal_for_storage(existing_for_compare, merged):
            _write_csv(PREDICTION_FEATURE_ARCHIVE_PATH, merged)
    elif PREDICTION_FEATURE_ARCHIVE_PATH.exists():
        PREDICTION_FEATURE_ARCHIVE_PATH.unlink(missing_ok=True)
    return merged


@st.cache_data(ttl=120, show_spinner=False)
def _build_prediction_feedback_from_files_cached(
    archive_path_text: str,
    archive_mtime_ns: int,
    archive_size: int,
    history_path_text: str,
    history_mtime_ns: int,
    history_size: int,
    payouts_path_text: str,
    payouts_mtime_ns: int,
    payouts_size: int,
) -> pd.DataFrame:
    del archive_mtime_ns, archive_size, history_mtime_ns, history_size, payouts_mtime_ns, payouts_size
    return build_prediction_feedback_from_paths(
        Path(archive_path_text),
        Path(history_path_text),
        Path(payouts_path_text),
        dtype=DEFAULT_CSV_TEXT_DTYPES,
    )


def _sync_prediction_feedback_from_files(history_path: Path) -> pd.DataFrame:
    archive_sig = _file_signature(PREDICTION_ARCHIVE_PATH)
    history_sig = _file_signature(history_path)
    payouts_sig = _file_signature(AUTO_PAYOUTS_PATH)
    feedback = _build_prediction_feedback_from_files_cached(
        str(PREDICTION_ARCHIVE_PATH),
        archive_sig[0],
        archive_sig[1],
        str(history_path),
        history_sig[0],
        history_sig[1],
        str(AUTO_PAYOUTS_PATH),
        payouts_sig[0],
        payouts_sig[1],
    ).copy()
    if not feedback.empty:
        existing = _read_csv_if_exists(PREDICTION_FEEDBACK_PATH)
        if not _frames_equal_for_storage(existing, feedback):
            _write_csv(PREDICTION_FEEDBACK_PATH, feedback)
    elif PREDICTION_FEEDBACK_PATH.exists():
        PREDICTION_FEEDBACK_PATH.unlink(missing_ok=True)
    return feedback


def _load_prediction_feedback_snapshot() -> pd.DataFrame:
    weekly_df = _read_csv_if_exists(WEEKLY_PREDICTIONS_PATH)
    history_path = Path(st.session_state.get("auto_history_path", str(AUTO_HISTORY_PATH)))
    archive_input = pipeline_ensure_weekly_prediction_columns(weekly_df if weekly_df is not None else pd.DataFrame())
    archive_input = _annotate_prediction_archive_budget_basis(
        archive_input,
        basis_key=st.session_state.get("budget_basis_choice", "trend"),
        basis_label=_format_budget_basis_label(st.session_state.get("budget_basis_choice", "trend")),
        auto_mode=bool(st.session_state.get("budget_basis_auto_enabled", True)),
    )
    _sync_prediction_archive(archive_input)
    return _sync_prediction_feedback_from_files(history_path)


def _load_prediction_feedback_summary_snapshot() -> Dict[str, Any]:
    return aggregate_prediction_feedback(_load_prediction_feedback_snapshot())


def _build_budget_basis_performance_delta_text(
    before_feedback_df: pd.DataFrame | None,
    after_feedback_df: pd.DataFrame | None,
    *,
    basis_label: Any,
    basis_mode: Any,
) -> str:
    label_text = _to_text(basis_label) or "-"
    mode_text = _to_text(basis_mode) or "-"
    before_perf = build_budget_basis_performance_table(before_feedback_df)
    after_perf = build_budget_basis_performance_table(after_feedback_df)
    if after_perf.empty:
        return f"{label_text} / {mode_text}: まだ評価レースなし"

    def _pick_row(frame: pd.DataFrame) -> pd.Series:
        if frame.empty:
            return pd.Series(dtype=object)
        hit = frame[
            (frame["配分基準"].map(_to_text) == label_text)
            & (frame["採用モード"].map(_to_text) == mode_text)
        ]
        if not hit.empty:
            return hit.iloc[0]
        fallback = frame[frame["配分基準"].map(_to_text) == label_text]
        if not fallback.empty:
            return fallback.iloc[0]
        return pd.Series(dtype=object)

    before_row = _pick_row(before_perf)
    after_row = _pick_row(after_perf)
    if after_row.empty:
        return f"{label_text} / {mode_text}: まだ評価レースなし"

    def _to_int_delta(column_name: str) -> int:
        before_value = pd.to_numeric(pd.Series([before_row.get(column_name)]), errors="coerce").iloc[0]
        after_value = pd.to_numeric(pd.Series([after_row.get(column_name)]), errors="coerce").iloc[0]
        before_num = 0 if pd.isna(before_value) else int(float(before_value))
        after_num = 0 if pd.isna(after_value) else int(float(after_value))
        return after_num - before_num

    def _to_rate_delta(column_name: str) -> str:
        before_value = pd.to_numeric(pd.Series([before_row.get(column_name)]), errors="coerce").iloc[0]
        after_value = pd.to_numeric(pd.Series([after_row.get(column_name)]), errors="coerce").iloc[0]
        if pd.isna(after_value):
            return "-"
        before_num = 0.0 if pd.isna(before_value) else float(before_value)
        diff = float(after_value) - before_num
        return f"{diff:+.1%}"

    parts = [
        f"{label_text} / {mode_text}",
        f"評価 { _to_int_delta('評価済みレース'):+d}",
        f"本命勝率 {_to_rate_delta('本命的中率')}",
        f"単勝回収率 {_to_rate_delta('単勝回収率')}",
    ]
    return " / ".join(parts)


def _split_condition_adjustment_summary(value: Any) -> List[str]:
    text = _to_text(value)
    if not text or text == "-":
        return []
    parts = [part.strip() for part in re.split(r"\s*/\s*|\s*\|\s*", text) if part.strip()]
    labels: List[str] = []
    for part in parts:
        label = _format_condition_segment_label(part)
        if not label or label == "-" or label in labels:
            continue
        labels.append(label)
    return labels


def _load_prediction_archive_context_map() -> Dict[str, Dict[str, Any]]:
    archive_df = _read_csv_if_exists(PREDICTION_ARCHIVE_PATH)
    if not isinstance(archive_df, pd.DataFrame) or archive_df.empty or "race_id" not in archive_df.columns:
        return {}
    archive_work = archive_df.copy()
    archive_work["race_id_text"] = archive_work["race_id"].map(_to_text)
    if "predicted_at" in archive_work.columns:
        archive_work = archive_work.sort_values("predicted_at", ascending=True)
    archive_work = archive_work.drop_duplicates(subset=["race_id_text"], keep="last")
    return {
        _to_text(row.get("race_id_text", "")): row.to_dict()
        for _, row in archive_work.iterrows()
        if _to_text(row.get("race_id_text", ""))
    }


def _format_result_sync_distance_reason(value: Any) -> str:
    distance_num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(distance_num):
        distance_text = _to_text(value)
        return f"距離: {distance_text}" if distance_text and distance_text != "-" else "距離: データ不足"
    distance_int = int(float(distance_num))
    if distance_int <= 1400:
        bucket = "短距離"
    elif distance_int <= 1800:
        bucket = "マイル寄り"
    elif distance_int <= 2200:
        bucket = "中距離"
    else:
        bucket = "長距離"
    return f"距離: {distance_int}m ({bucket})"


def _build_result_sync_miss_tags(row: pd.Series | Dict[str, Any], archive_row: pd.Series | Dict[str, Any] | None) -> List[str]:
    archive = archive_row if isinstance(archive_row, (pd.Series, dict)) else {}
    tags: List[str] = []
    top_pop_num = pd.to_numeric(pd.Series([archive.get("top_pop_rank", "")]), errors="coerce").iloc[0]
    winner_odds_num = pd.to_numeric(pd.Series([row.get("winner_odds", "")]), errors="coerce").iloc[0]
    distance_num = pd.to_numeric(pd.Series([archive.get("distance", "")]), errors="coerce").iloc[0]
    track_text = _to_text(archive.get("track_condition", ""))
    adjustment_labels = _split_condition_adjustment_summary(
        archive.get("condition_adjustments", row.get("condition_adjustments", ""))
    )

    if pd.notna(top_pop_num) and pd.notna(winner_odds_num) and (
        (float(top_pop_num) <= 3 and float(winner_odds_num) >= 10)
        or (float(top_pop_num) >= 6 and float(winner_odds_num) <= 4.5)
    ):
        tags.append("人気ズレ")
    elif pd.notna(top_pop_num) or pd.notna(winner_odds_num):
        tags.append("人気確認")
    else:
        tags.append("人気不足")

    if track_text in {"稍重", "重", "不良"}:
        tags.append("馬場注意")
    elif track_text:
        tags.append("馬場確認")
    else:
        tags.append("馬場不足")

    if pd.notna(distance_num) and (float(distance_num) <= 1400 or float(distance_num) >= 2200):
        tags.append("距離注意")
    elif pd.notna(distance_num):
        tags.append("距離確認")
    else:
        tags.append("距離不足")

    tags.append("補正活用" if adjustment_labels else "補正不足")
    return tags[:4]


def _build_result_sync_avoid_bets(tags_text: Any) -> List[str]:
    tags = [part.strip() for part in _to_text(tags_text).split("/") if part.strip()]
    avoid_map = {
        "人気ズレ": ["単勝", "馬単"],
        "人気確認": ["単勝"],
        "人気不足": ["馬単"],
        "馬場注意": ["馬単", "三連単"],
        "馬場確認": ["三連単"],
        "馬場不足": ["三連単"],
        "距離注意": ["三連複", "三連単"],
        "距離確認": ["三連単"],
        "距離不足": ["三連単"],
        "補正不足": ["馬単", "三連単"],
        "補正活用": ["見送りなし"],
    }
    bets: List[str] = []
    for tag in tags:
        for bet in avoid_map.get(tag, []):
            if bet not in bets:
                bets.append(bet)
    if not bets:
        return ["見送りなし"]
    if "見送りなし" in bets and len(bets) > 1:
        bets = [bet for bet in bets if bet != "見送りなし"]
    return bets[:4]


def _build_result_sync_preferred_bets(tags_text: Any) -> List[str]:
    tags = [part.strip() for part in _to_text(tags_text).split("/") if part.strip()]
    prefer_map = {
        "人気ズレ": ["複勝", "ワイド"],
        "人気確認": ["複勝", "ワイド"],
        "人気不足": ["ワイド", "三連複"],
        "馬場注意": ["複勝", "ワイド"],
        "馬場確認": ["ワイド", "三連複"],
        "馬場不足": ["複勝"],
        "距離注意": ["複勝", "ワイド"],
        "距離確認": ["ワイド", "三連複"],
        "距離不足": ["複勝"],
        "補正不足": ["複勝", "ワイド"],
        "補正活用": ["単勝", "三連複"],
    }
    bets: List[str] = []
    for tag in tags:
        for bet in prefer_map.get(tag, []):
            if bet not in bets:
                bets.append(bet)
    return bets[:4] if bets else ["複勝", "ワイド"]


def _build_result_sync_miss_reason(row: pd.Series | Dict[str, Any], archive_row: pd.Series | Dict[str, Any] | None) -> str:
    archive = archive_row if isinstance(archive_row, (pd.Series, dict)) else {}
    top_pop_num = pd.to_numeric(pd.Series([archive.get("top_pop_rank", "")]), errors="coerce").iloc[0]
    winner_odds_num = pd.to_numeric(pd.Series([row.get("winner_odds", "")]), errors="coerce").iloc[0]
    if pd.notna(top_pop_num) and pd.notna(winner_odds_num):
        popularity_reason = (
            f"人気: 本命{int(float(top_pop_num))}番人気想定に対して人気薄決着 ({float(winner_odds_num):.1f}倍)"
            if float(winner_odds_num) >= 10
            else f"人気: 本命{int(float(top_pop_num))}番人気想定 / 勝ち馬{float(winner_odds_num):.1f}倍"
        )
    elif pd.notna(top_pop_num):
        popularity_reason = f"人気: 本命{int(float(top_pop_num))}番人気想定"
    elif pd.notna(winner_odds_num):
        popularity_reason = (
            f"人気: 人気薄決着 ({float(winner_odds_num):.1f}倍)"
            if float(winner_odds_num) >= 10
            else f"人気: 勝ち馬{float(winner_odds_num):.1f}倍"
        )
    else:
        popularity_reason = "人気: 市場データ不足"

    track_text = _to_text(archive.get("track_condition", ""))
    if track_text in {"稍重", "重", "不良"}:
        track_reason = f"馬場: {track_text}でパワー寄り"
    elif track_text:
        track_reason = f"馬場: {track_text}"
    else:
        track_reason = "馬場: データ不足"

    distance_reason = _format_result_sync_distance_reason(archive.get("distance", ""))

    adjustment_labels = _split_condition_adjustment_summary(
        archive.get("condition_adjustments", row.get("condition_adjustments", ""))
    )
    if adjustment_labels:
        adjustments_text = " / ".join(adjustment_labels[:2])
        if len(adjustment_labels) > 2:
            adjustments_text += " など"
        adjustment_reason = f"条件補正: {adjustments_text}"
    else:
        adjustment_reason = "条件補正: なし"
    return " / ".join([popularity_reason, track_reason, distance_reason, adjustment_reason])


def _build_feedback_trend_summary(feedback_df: pd.DataFrame | None, *, lookback_days: int = 7) -> Dict[str, Any]:
    feedback = feedback_df.copy() if isinstance(feedback_df, pd.DataFrame) else pd.DataFrame()
    if feedback.empty or "race_id" not in feedback.columns:
        return {"title": "", "summary": "", "chips": []}
    if "result_available" in feedback.columns:
        mask = _truthy_series(feedback["result_available"])
        feedback = feedback[mask].copy()
    if feedback.empty:
        return {"title": "", "summary": "", "chips": []}
    race_days = feedback.apply(lambda row: _parse_date_text(row.get("race_date", "")), axis=1)
    today = datetime.now().date()
    if lookback_days > 0:
        recent_mask = race_days.map(lambda value: bool(value is not None and (today - value).days <= max(0, int(lookback_days))))
        recent = feedback[recent_mask].copy()
        if recent.empty:
            recent = feedback.copy()
    else:
        recent = feedback.copy()
    if recent.empty:
        return {"title": "", "summary": "", "chips": []}
    if "top_horse_hit" in recent.columns:
        miss_mask = ~_truthy_series(recent["top_horse_hit"])
        recent = recent[miss_mask].copy()
    if recent.empty:
        return {
            "title": "今週の反省傾向",
            "summary": "直近は本命外れが少なく、極端な偏りは見えていません。",
            "chips": ["安定推移"],
            "stance": "標準",
            "recommended_bets": ["単勝", "複勝", "ワイド"],
            "avoid_bets": ["見送りなし"],
            "lead_tag": "",
            "lead_count": 0,
        }
    archive_by_race_id = _load_prediction_archive_context_map()
    tag_counts: Dict[str, int] = {}
    for _, row in recent.iterrows():
        archive_row = archive_by_race_id.get(_to_text(row.get("race_id", "")), {})
        for tag in _build_result_sync_miss_tags(row, archive_row):
            tag_counts[tag] = int(tag_counts.get(tag, 0)) + 1
    if not tag_counts:
        return {
            "title": "今週の反省傾向",
            "summary": "外れの型はまだ散っていて、偏りは小さめです。",
            "chips": ["偏り小"],
            "stance": "標準",
            "recommended_bets": ["単勝", "複勝", "ワイド"],
            "avoid_bets": ["見送りなし"],
            "lead_tag": "",
            "lead_count": 0,
        }
    sorted_tags = sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))
    top_tags = sorted_tags[:3]
    lead_tag, lead_count = top_tags[0]
    recommended_bets: List[str] = []
    avoid_bets: List[str] = []
    for tag, _ in top_tags:
        for bet in _build_result_sync_preferred_bets(tag):
            if bet not in recommended_bets:
                recommended_bets.append(bet)
        for bet in _build_result_sync_avoid_bets(tag):
            if bet not in avoid_bets:
                avoid_bets.append(bet)
    if lead_tag == "人気ズレ":
        summary = f"人気ズレが {lead_count} 件で最多です。人気サイドの単勝・馬単を少し抑えて、ワイドや複勝寄りで整える週です。"
        stance = "ワイド寄り"
    elif lead_tag == "馬場注意":
        summary = f"馬場注意が {lead_count} 件で目立っています。重めの馬場を前提に、三連単より複勝・ワイドを厚めにした方が安全です。"
        stance = "複勝・ワイド寄り"
    elif lead_tag == "距離注意":
        summary = f"距離注意が {lead_count} 件で多めです。距離替わりの見極めが鍵なので、三連系は絞って入りたい流れです。"
        stance = "保守寄り"
    elif lead_tag == "補正不足":
        summary = f"条件補正の拾い漏れが {lead_count} 件あります。開催・馬場・距離帯が合うレースほど補正本数を確認したい週です。"
        stance = "補正確認寄り"
    else:
        summary = f"{lead_tag} が {lead_count} 件で多めです。外れ方の型が見えているので、券種を少し保守寄りに寄せるのがよさそうです。"
        stance = "標準"
    chips = [f"{tag} {count}件" for tag, count in top_tags]
    if "見送りなし" in avoid_bets and len(avoid_bets) > 1:
        avoid_bets = [bet for bet in avoid_bets if bet != "見送りなし"]
    return {
        "title": "今週の反省傾向",
        "summary": summary,
        "chips": chips,
        "stance": stance,
        "recommended_bets": recommended_bets[:4] if recommended_bets else ["複勝", "ワイド"],
        "avoid_bets": avoid_bets[:4] if avoid_bets else ["見送りなし"],
        "lead_tag": lead_tag,
        "lead_count": int(lead_count),
    }


def _render_feedback_trend_card(summary: Dict[str, Any] | None) -> None:
    if not isinstance(summary, dict):
        return
    title = _to_text(summary.get("title", ""))
    if not title:
        return
    sub = _to_text(summary.get("summary", ""))
    chips = summary.get("chips", [])
    stance = _to_text(summary.get("stance", "")) or "標準"
    recommended_bets = summary.get("recommended_bets", [])
    avoid_bets = summary.get("avoid_bets", [])
    chip_html = ""
    if isinstance(chips, list) and chips:
        chip_html = "<div class='feedback-trend-row'>" + "".join(
            f"<span class='feedback-trend-chip'>{html_escape(_to_text(chip))}</span>"
            for chip in chips
            if _to_text(chip)
        ) + "</div>"
    stance_html = """
<div class="feedback-trend-stance">
  <div class="feedback-trend-stance-card">
    <div class="feedback-trend-stance-title">今週の買い方方針</div>
    <div class="feedback-trend-stance-value">{stance}</div>
  </div>
  <div class="feedback-trend-stance-card">
    <div class="feedback-trend-stance-title">おすすめ券種</div>
    <div class="feedback-trend-stance-value">{recommended}</div>
  </div>
  <div class="feedback-trend-stance-card">
    <div class="feedback-trend-stance-title">抑えたい券種</div>
    <div class="feedback-trend-stance-value">{avoid}</div>
  </div>
</div>
""".format(
        stance=html_escape(stance),
        recommended=html_escape(" / ".join(_to_text(item) for item in recommended_bets if _to_text(item)) or "-"),
        avoid=html_escape(" / ".join(_to_text(item) for item in avoid_bets if _to_text(item)) or "-"),
    )
    focus_bets = [item for item in recommended_bets if _to_text(item)][:3]
    focus_cards_html = ""
    if focus_bets:
        card_classes = ["primary", "secondary", "tertiary"]
        focus_cards_html = "<div class='feedback-trend-focus-grid'>" + "".join(
            """
<div class="feedback-trend-focus-card {class_name}">
  <div class="feedback-trend-focus-kicker">{rank}</div>
  <div class="feedback-trend-focus-value">{bet}</div>
  <div class="feedback-trend-focus-sub">{sub}</div>
</div>
""".format(
                class_name=html_escape(card_classes[idx] if idx < len(card_classes) else "secondary"),
                rank=html_escape(f"おすすめ {idx + 1}"),
                bet=html_escape(_to_text(bet)),
                sub=html_escape(f"{stance} の週は {_to_text(bet)} を主軸にしやすいです。"),
            )
            for idx, bet in enumerate(focus_bets)
        ) + "</div>"
    st.markdown(
        """
<div class="feedback-trend-card">
  <div class="feedback-trend-title">{title}</div>
  <div class="feedback-trend-sub">{sub}</div>
  {chips}
  {stance_html}
  {focus_cards_html}
</div>
""".format(
            title=html_escape(title),
            sub=html_escape(sub),
            chips=chip_html,
            stance_html=stance_html,
            focus_cards_html=focus_cards_html,
        ),
        unsafe_allow_html=True,
    )


def _build_feedback_trend_strategy_snapshot(summary: Dict[str, Any] | None) -> Dict[str, str]:
    if not isinstance(summary, dict):
        return {
            "style": "-",
            "main_bets": "-",
            "sub_bets": "-",
            "caution": "-",
        }
    stance = _to_text(summary.get("stance", "")) or "標準"
    recommended = [_to_text(item) for item in summary.get("recommended_bets", []) if _to_text(item)]
    avoid = [_to_text(item) for item in summary.get("avoid_bets", []) if _to_text(item)]
    main_bets = " / ".join(recommended[:2]) if recommended else "-"
    sub_bets = " / ".join(recommended[2:4]) if len(recommended) > 2 else (" / ".join(recommended[:1]) if recommended else "-")
    caution = " / ".join([bet for bet in avoid if bet != "見送りなし"][:3]) if avoid else "特になし"
    return {
        "style": stance,
        "main_bets": main_bets or "-",
        "sub_bets": sub_bets or "-",
        "caution": caution or "特になし",
    }


def _render_single_race_feedback_trend_focus(summary: Dict[str, Any] | None) -> None:
    if not isinstance(summary, dict):
        return
    stance = _to_text(summary.get("stance", ""))
    recommended = [_to_text(item) for item in summary.get("recommended_bets", []) if _to_text(item)]
    avoid = [_to_text(item) for item in summary.get("avoid_bets", []) if _to_text(item)]
    sub = _to_text(summary.get("summary", ""))
    if not stance and not recommended and not avoid:
        return
    cards = [
        ("primary", "今日の券種スタイル", stance or "標準", sub or "今週の反省傾向から見た基本姿勢です。"),
        ("secondary", "おすすめ券種", " / ".join(recommended[:3]) if recommended else "-", "今日の買い目はここを主軸にします。"),
        ("tertiary", "抑えたい券種", " / ".join([bet for bet in avoid if bet != "見送りなし"][:3]) if avoid else "特になし", "強く買いすぎない方が良い券種です。"),
    ]
    html = "<div class='feedback-trend-focus-grid'>" + "".join(
        """
<div class="feedback-trend-focus-card {class_name}">
  <div class="feedback-trend-focus-kicker">{title}</div>
  <div class="feedback-trend-focus-value">{value}</div>
  <div class="feedback-trend-focus-sub">{sub}</div>
</div>
""".format(
            class_name=html_escape(class_name),
            title=html_escape(title),
            value=html_escape(value),
            sub=html_escape(sub_text),
        )
        for class_name, title, value, sub_text in cards
    ) + "</div>"
    st.caption("今日の買い方方針")
    st.markdown(html, unsafe_allow_html=True)


def _build_feedback_trend_weekly_label(summary: Dict[str, Any] | None) -> str:
    if not isinstance(summary, dict):
        return "-"
    stance = _to_text(summary.get("stance", "")) or "-"
    recommended = [_to_text(item) for item in summary.get("recommended_bets", []) if _to_text(item)]
    if not recommended:
        return stance
    return f"{stance} / 主軸 {' / '.join(recommended[:2])}"


def _build_newly_evaluated_race_items(
    before_feedback_df: pd.DataFrame | None,
    after_feedback_df: pd.DataFrame | None,
    *,
    limit: int = 6,
) -> List[Dict[str, str]]:
    before_df = before_feedback_df.copy() if isinstance(before_feedback_df, pd.DataFrame) else pd.DataFrame()
    after_df = after_feedback_df.copy() if isinstance(after_feedback_df, pd.DataFrame) else pd.DataFrame()
    if after_df.empty or "race_id" not in after_df.columns:
        return []

    def _evaluated_race_ids(frame: pd.DataFrame) -> set[str]:
        if frame.empty or "race_id" not in frame.columns or "result_available" not in frame.columns:
            return set()
        work = frame.copy()
        flags = work["result_available"].astype(str).str.lower().isin(["true", "1"])
        if work["result_available"].dtype == bool:
            flags = work["result_available"].astype(bool)
        return {
            _to_text(rid)
            for rid in work.loc[flags, "race_id"].tolist()
            if _to_text(rid)
        }

    before_ids = _evaluated_race_ids(before_df)
    after_work = after_df.copy()
    if "result_available" not in after_work.columns:
        return []
    after_flags = after_work["result_available"].astype(str).str.lower().isin(["true", "1"])
    if after_work["result_available"].dtype == bool:
        after_flags = after_work["result_available"].astype(bool)
    target = after_work.loc[after_flags].copy()
    if target.empty:
        return []
    target["race_id_text"] = target["race_id"].map(_to_text)
    target = target[~target["race_id_text"].isin(before_ids)].copy()
    if target.empty:
        return []
    target["race_label"] = target.apply(
        lambda row: _format_race_label(
            row.get("race_id", ""),
            row.get("venue", ""),
            row.get("race_date", ""),
            row.get("race_name", ""),
        ),
        axis=1,
    )
    target = target.drop_duplicates(subset=["race_id_text"]).copy()
    target = _sort_by_race_id_safe(target, "race_id_text", ascending=True)
    archive_by_race_id = _load_prediction_archive_context_map()

    def _collect_hit_bets(row: pd.Series) -> str:
        bet_map = [
            ("single_hit", "単勝"),
            ("place_hit", "複勝"),
            ("quinella_hit", "馬連"),
            ("wide_hit", "ワイド"),
            ("exacta_hit", "馬単"),
            ("trio_hit", "三連複"),
            ("trifecta_hit", "三連単"),
        ]
        hits: List[str] = []
        for key, label in bet_map:
            value = row.get(key, "")
            is_hit = bool(str(value).lower() in {"true", "1"}) or value is True
            if is_hit:
                hits.append(label)
        return " / ".join(hits) if hits else "的中なし"

    rows: List[Dict[str, str]] = []
    for _, row in target.head(max(1, int(limit))).iterrows():
        hit_value = row.get("top_horse_hit", "")
        is_hit = bool(str(hit_value).lower() in {"true", "1"}) or hit_value is True
        archive_row = archive_by_race_id.get(_to_text(row.get("race_id_text", "")), {})
        rows.append(
            {
                "race_id": _to_text(row.get("race_id_text", "")),
                "label": _to_text(row.get("race_label", "")),
                "status": "本命ヒット" if is_hit else "本命外れ",
                "winner": _to_text(row.get("actual_winner", "")),
                "top_horse": _to_text(row.get("top_horse", "")),
                "hit_bets": _collect_hit_bets(row),
                "miss_reason": "" if is_hit else _build_result_sync_miss_reason(row, archive_row),
                "miss_tags": "" if is_hit else " / ".join(_build_result_sync_miss_tags(row, archive_row)),
                "avoid_bets": "" if is_hit else " / ".join(_build_result_sync_avoid_bets(" / ".join(_build_result_sync_miss_tags(row, archive_row)))),
                "preferred_bets": "" if is_hit else " / ".join(_build_result_sync_preferred_bets(" / ".join(_build_result_sync_miss_tags(row, archive_row)))),
            }
        )
    return rows


def _join_names(values: pd.Series, limit: int = 5) -> str:
    seen: list[str] = []
    for value in values.tolist():
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.append(text)
    if not seen:
        return "-"
    if len(seen) <= limit:
        return " / ".join(seen)
    return " / ".join(seen[:limit]) + f" ... +{len(seen) - limit}"


_SYNTHETIC_NAME_RE = re.compile(r"^(Horse|Jockey|Trainer)_(\d+)$", re.IGNORECASE)
_AUTO_RACE_ID_RE = re.compile(r"^AUTO(\d{8})$", re.IGNORECASE)


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in ("nan", "none", "<na>"):
        return ""
    return text


def _is_synthetic_name(value: Any) -> bool:
    return bool(_SYNTHETIC_NAME_RE.match(_to_text(value)))


def _render_single_name(value: Any) -> str:
    text = _to_text(value)
    if not text:
        return "-"
    m = _SYNTHETIC_NAME_RE.match(text)
    if not m:
        return text
    role = m.group(1).lower()
    num = m.group(2).zfill(2)
    jp = {"horse": "馬", "jockey": "騎手", "trainer": "調教師"}.get(role, "候補")
    return f"{jp}{num}（仮）"


def _render_name_text(value: Any) -> str:
    text = _to_text(value)
    if not text:
        return "-"
    if " / " in text:
        parts: list[str] = []
        for part in text.split(" / "):
            token = part.strip()
            if token.startswith("... +"):
                parts.append(token)
            else:
                parts.append(_render_single_name(token))
        return " / ".join(parts)
    if "-" in text:
        return "-".join(_render_single_name(token) for token in text.split("-"))
    return _render_single_name(text)


def _has_synthetic_marker(value: Any) -> bool:
    text = _to_text(value)
    if not text:
        return False
    if _is_synthetic_name(text):
        return True
    tokens = [token.strip() for token in re.split(r"[-/]", text)]
    return any(_is_synthetic_name(token) for token in tokens if token)


def _format_date_text(value: Any) -> str:
    text = _to_text(value)
    if not text:
        return "-"
    m = re.search(r"(\d{4})[/-]?(\d{2})[/-]?(\d{2})", text)
    if not m:
        return text
    return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"


def _result_status_text(result_available: Any, race_date: Any, race_id: Any) -> str:
    if str(result_available).lower() in {"true", "1"} or result_available is True:
        return "確定"
    race_day = _parse_date_text(race_date)
    if race_day is None:
        digits = re.sub(r"\D", "", _to_text(race_id))
        if len(digits) >= 8:
            try:
                race_day = datetime.strptime(digits[:8], "%Y%m%d").date()
            except Exception:
                race_day = None
    if race_day is None:
        return "日付不明"
    return "未来予想" if race_day > datetime.now().date() else "結果待ち"


def _truthy_series(values: pd.Series) -> pd.Series:
    if values.dtype == bool:
        return values.astype(bool)
    return values.map(lambda value: str(value).strip().lower() in {"true", "1", "yes", "on"})


def _feedback_row_key(row: pd.Series | Dict[str, Any]) -> str:
    if isinstance(row, dict):
        race_id = _to_text(row.get("race_id", ""))
        predicted_at = _to_text(row.get("predicted_at", ""))
    else:
        race_id = _to_text(row.get("race_id", ""))
        predicted_at = _to_text(row.get("predicted_at", ""))
    return f"{race_id}::{predicted_at}"


def _trim_text_list(values: List[str], *, max_items: int = 1600) -> List[str]:
    cleaned = [value for value in values if _to_text(value)]
    if len(cleaned) <= max(1, int(max_items)):
        return cleaned
    return cleaned[-max(1, int(max_items)) :]


def _load_auto_improve_state() -> Dict[str, Any]:
    payload = _read_json_if_exists(AUTO_IMPROVE_STATE_PATH)
    if not isinstance(payload, dict):
        return {
            "memory_synced_keys": [],
            "reflection_trained_keys": [],
            "budget_basis_auto_enabled": True,
        }
    payload["memory_synced_keys"] = _trim_text_list(list(payload.get("memory_synced_keys", [])))
    payload["reflection_trained_keys"] = _trim_text_list(list(payload.get("reflection_trained_keys", [])))
    payload["budget_basis_auto_enabled"] = bool(payload.get("budget_basis_auto_enabled", True))
    return payload


def _save_auto_improve_state(payload: Dict[str, Any]) -> None:
    out = dict(payload) if isinstance(payload, dict) else {}
    out["memory_synced_keys"] = _trim_text_list(list(out.get("memory_synced_keys", [])))
    out["reflection_trained_keys"] = _trim_text_list(list(out.get("reflection_trained_keys", [])))
    out["budget_basis_auto_enabled"] = bool(out.get("budget_basis_auto_enabled", True))
    out["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(AUTO_IMPROVE_STATE_PATH, out)


def _save_auto_improve_state_checkpoint(payload: Dict[str, Any], *, force: bool = False) -> None:
    if not isinstance(payload, dict):
        return
    age_seconds = _timestamp_age_seconds(payload.get("last_checked_at", ""))
    if not force and age_seconds is not None and age_seconds < max(30, int(AUTO_IMPROVE_CHECKPOINT_INTERVAL_SECONDS)):
        return
    payload["last_checked_at"] = datetime.now().isoformat(timespec="seconds")
    _save_auto_improve_state(payload)


def _persist_budget_basis_preference(
    *,
    auto_enabled: bool | None = None,
    manual_choice: Any | None = None,
    auto_choice: Any | None = None,
) -> None:
    state = _load_auto_improve_state()
    if auto_enabled is not None:
        state["budget_basis_auto_enabled"] = bool(auto_enabled)
    if manual_choice is not None:
        state["last_manual_budget_basis"] = _to_text(manual_choice)
    if auto_choice is not None:
        state["last_auto_budget_basis"] = _to_text(auto_choice)
    _save_auto_improve_state(state)


def _build_feedback_memory_summary(row: pd.Series | Dict[str, Any]) -> str:
    top_horse = _to_text(row.get("top_horse", ""))
    actual_winner = _to_text(row.get("actual_winner", ""))
    actual_top3 = _to_text(row.get("actual_top3", ""))
    status = "本命ヒット" if bool(str(row.get("top_horse_hit", "")).lower() in {"true", "1"}) or row.get("top_horse_hit") is True else "本命外れ"
    llm_top_horse = _to_text(row.get("llm_top_horse", ""))
    llm_top_hit = bool(str(row.get("llm_top_hit", "")).lower() in {"true", "1"}) or row.get("llm_top_hit") is True
    llm_disagreement = bool(str(row.get("llm_disagreement", "")).lower() in {"true", "1"}) or row.get("llm_disagreement") is True
    llm_reason = _to_text(row.get("llm_disagreement_reason", ""))
    archive_row = _load_prediction_archive_context_map().get(_to_text(row.get("race_id", "")), {})
    segments: List[str] = [status]
    if top_horse:
        segments.append(f"本命={top_horse}")
    if llm_top_horse:
        segments.append(f"LLM本命={llm_top_horse}")
    if actual_winner:
        segments.append(f"勝ち馬={actual_winner}")
    if actual_top3:
        segments.append(f"実上位={actual_top3}")
    if llm_disagreement and llm_top_hit:
        segments.append("LLM別軸ヒット")
    elif llm_disagreement:
        segments.append("LLM別軸")
    if llm_reason and llm_reason != "-":
        segments.append(f"LLM要因={llm_reason}")
    condition_text = _to_text(row.get("condition_adjustments", ""))
    if condition_text and condition_text != "-":
        segments.append(f"補正={condition_text}")
    if status != "本命ヒット":
        miss_reason = _build_result_sync_miss_reason(row, archive_row)
        if miss_reason:
            segments.append(f"要因={miss_reason}")
    return " / ".join(segments) if segments else "-"


def _build_feedback_memory_payload(row: pd.Series | Dict[str, Any]) -> Dict[str, Any]:
    race_date_text = _format_date_text(row.get("race_date", ""))
    venue_text = _to_text(row.get("venue", ""))
    race_name_text = _to_text(row.get("race_name", ""))
    race_label = " ".join(part for part in [race_date_text if race_date_text != "-" else "", venue_text, race_name_text] if part).strip()
    if not race_label:
        race_label = _to_text(row.get("race_id", "-")) or "-"
    archive_row = _load_prediction_archive_context_map().get(_to_text(row.get("race_id", "")), {})
    llm_disagreement = bool(str(row.get("llm_disagreement", "")).lower() in {"true", "1"}) or row.get("llm_disagreement") is True
    llm_top_hit = bool(str(row.get("llm_top_hit", "")).lower() in {"true", "1"}) or row.get("llm_top_hit") is True
    return {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "source": "auto_feedback",
        "feedback_key": _feedback_row_key(row),
        "race_id": _to_text(row.get("race_id", "")),
        "race_label": race_label,
        "race_grade": _to_text(row.get("race_grade", "")) or "未判定",
        "llm_style": "反省",
        "reasoning_mode": "反省",
        "weather": _to_text(row.get("weather", "")) or _to_text(archive_row.get("weather", "")),
        "track_condition": _to_text(row.get("track_condition", "")) or _to_text(archive_row.get("track_condition", "")),
        "distance": _to_text(row.get("distance", "")) or _to_text(archive_row.get("distance", "")),
        "summary": _build_feedback_memory_summary(row),
        "miss_reason": _build_result_sync_miss_reason(row, archive_row),
        "miss_tags": " / ".join(_build_result_sync_miss_tags(row, archive_row)),
        "llm_disagreement": llm_disagreement,
        "llm_top_hit": llm_top_hit,
        "llm_top_horse": _to_text(row.get("llm_top_horse", "")),
        "llm_disagreement_reason": _to_text(row.get("llm_disagreement_reason", "")),
        "preferred_bets": " / ".join(
            _build_result_sync_preferred_bets(" / ".join(_build_result_sync_miss_tags(row, archive_row)))
        ),
        "avoid_bets": " / ".join(
            _build_result_sync_avoid_bets(" / ".join(_build_result_sync_miss_tags(row, archive_row)))
        ),
    }


def _format_gate_text(value: Any) -> str:
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(num):
        return "-"
    return f"{int(float(num))}番"


def _build_gate_lookup(entries_df: pd.DataFrame) -> Dict[str, str]:
    if entries_df.empty or "horse" not in entries_df.columns or "gate" not in entries_df.columns:
        return {}
    work = entries_df.copy()
    work["horse"] = work["horse"].map(_to_text)
    work["gate_num"] = pd.to_numeric(work["gate"], errors="coerce")
    work = work[work["horse"] != ""]
    out: Dict[str, str] = {}
    for _, row in work.drop_duplicates("horse").iterrows():
        gate_text = _format_gate_text(row.get("gate_num"))
        if gate_text != "-":
            out[_to_text(row.get("horse", ""))] = gate_text
    return out


def _build_race_gate_lookup(entries_df: pd.DataFrame) -> Dict[str, Dict[str, str]]:
    if entries_df.empty or "race_id" not in entries_df.columns:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    work = entries_df.copy()
    work["race_id"] = work["race_id"].map(_to_text)
    for race_id, group in work.groupby("race_id", sort=False):
        if race_id:
            out[race_id] = _build_gate_lookup(group)
    return out


def _render_name_text_with_gate(value: Any, gate_lookup: Dict[str, str] | None = None) -> str:
    text = _to_text(value)
    if not text:
        return "-"
    lookup = gate_lookup or {}

    def _decorate_token(token: str) -> str:
        raw = token.strip()
        if not raw:
            return "-"
        if raw.startswith("... +"):
            return raw
        rendered = _render_single_name(raw)
        gate_text = lookup.get(raw, "")
        return f"{gate_text} {rendered}".strip() if gate_text else rendered

    if " / " in text:
        return " / ".join(_decorate_token(token) for token in text.split(" / "))
    if "-" in text:
        return "-".join(_decorate_token(token) for token in text.split("-"))
    return _decorate_token(text)


def _decorate_columns_with_gate(
    frame: pd.DataFrame,
    *,
    race_id_col: str,
    gate_lookup_by_race: Dict[str, Dict[str, str]],
    target_columns: List[str],
) -> pd.DataFrame:
    if frame.empty or race_id_col not in frame.columns or not gate_lookup_by_race:
        return frame
    out = frame.copy()
    for idx, row in out.iterrows():
        race_id = _to_text(row.get(race_id_col, ""))
        if not race_id:
            continue
        gate_lookup = gate_lookup_by_race.get(race_id, {})
        if not gate_lookup:
            continue
        for col in target_columns:
            if col in out.columns:
                out.at[idx, col] = _render_name_text_with_gate(row.get(col, ""), gate_lookup)
    return out


def _decorate_frame_gate_columns(
    frame: pd.DataFrame,
    gate_lookup: Dict[str, str],
    target_columns: List[str],
) -> pd.DataFrame:
    if frame.empty or not gate_lookup:
        return frame
    out = frame.copy()
    for col in target_columns:
        if col in out.columns:
            out[col] = out[col].map(lambda value: _render_name_text_with_gate(value, gate_lookup))
    return out


def _build_result_learning_samples(history_df: pd.DataFrame) -> pd.DataFrame:
    if history_df.empty or "race_id" not in history_df.columns or "finish" not in history_df.columns:
        return pd.DataFrame()
    work = history_df.copy()
    work["race_id"] = work["race_id"].map(_to_text)
    work["horse"] = work["horse"].map(_to_text) if "horse" in work.columns else ""
    work["jockey"] = work["jockey"].map(_to_text) if "jockey" in work.columns else ""
    work["finish_num"] = pd.to_numeric(work["finish"], errors="coerce")
    work["gate_num"] = pd.to_numeric(work.get("gate", pd.Series(index=work.index, dtype=float)), errors="coerce")
    work = work[work["race_id"] != ""]
    if work.empty:
        return pd.DataFrame()

    race_rows: List[Dict[str, Any]] = []
    for race_id, group in work.groupby("race_id", sort=False):
        ranked = group.sort_values(["finish_num", "horse"], ascending=[True, True]).copy()
        ranked = ranked[ranked["finish_num"].notna()]
        if ranked.empty:
            continue

        def _top_finisher(rank_no: int) -> tuple[str, str]:
            hit = ranked[ranked["finish_num"] == rank_no].head(1)
            if hit.empty:
                return "-", "-"
            row = hit.iloc[0]
            horse_text = _to_text(row.get("horse", ""))
            gate_text = _format_gate_text(row.get("gate_num"))
            name_text = _render_name_text(horse_text)
            return (f"{gate_text} {name_text}".strip() if gate_text != "-" else name_text, _to_text(row.get("jockey", "-")) or "-")

        winner, winner_jockey = _top_finisher(1)
        second, second_jockey = _top_finisher(2)
        third, third_jockey = _top_finisher(3)
        first_row = ranked.iloc[0]
        race_rows.append(
            {
                "race_id": race_id,
                "race_date": _format_date_text(race_id),
                "venue": _to_text(first_row.get("venue", "")) or "-",
                "weather": _to_text(first_row.get("weather", "")) or "-",
                "track_condition": _to_text(first_row.get("track_condition", "")) or "-",
                "distance": pd.to_numeric(pd.Series([first_row.get("distance")]), errors="coerce").iloc[0],
                "field_size": int(ranked["horse"].replace("", pd.NA).dropna().shape[0]) if "horse" in ranked.columns else int(len(ranked)),
                "winner": winner or "-",
                "winner_jockey": winner_jockey or "-",
                "second": second or "-",
                "second_jockey": second_jockey or "-",
                "third": third or "-",
                "third_jockey": third_jockey or "-",
            }
        )
    out = pd.DataFrame(race_rows)
    if out.empty:
        return out
    out = out.sort_values("race_id", ascending=False).reset_index(drop=True)
    if "distance" in out.columns:
        out["distance"] = pd.to_numeric(out["distance"], errors="coerce")
    return out


def _sync_result_learning_samples(history_df: pd.DataFrame) -> pd.DataFrame:
    samples = _build_result_learning_samples(history_df)
    if samples.empty:
        return samples
    save_df = samples.copy()
    if "distance" in save_df.columns:
        save_df["distance"] = save_df["distance"].map(lambda x: "" if pd.isna(x) else int(float(x)))
    write_csv_if_changed(RESULT_SAMPLE_PATH, save_df)
    return samples


def _build_result_sample_prompt_text(
    samples_df: pd.DataFrame,
    *,
    venue: Any,
    track_condition: Any,
    distance: Any,
    limit: int = 4,
) -> str:
    if samples_df.empty:
        return "- サンプルなし"
    work = samples_df.copy()
    score = pd.Series(0.0, index=work.index, dtype=float)
    venue_text = _to_text(venue)
    track_text = _to_text(track_condition)
    distance_num = pd.to_numeric(pd.Series([distance]), errors="coerce").iloc[0]
    if venue_text and "venue" in work.columns:
        score += work["venue"].map(lambda x: 2.4 if _to_text(x) == venue_text else 0.0)
    if track_text and "track_condition" in work.columns:
        score += work["track_condition"].map(lambda x: 1.0 if _to_text(x) == track_text else 0.0)
    if pd.notna(distance_num) and "distance" in work.columns:
        dist_num = pd.to_numeric(work["distance"], errors="coerce")
        score += (1.2 - (dist_num.sub(float(distance_num)).abs() / 1200.0)).clip(lower=0.0).fillna(0.0)
    work["_score"] = score
    work = work.sort_values(["_score", "race_id"], ascending=[False, False]).head(max(1, int(limit)))
    lines: List[str] = []
    for _, row in work.iterrows():
        distance_text = "-" if pd.isna(pd.to_numeric(pd.Series([row.get("distance")]), errors="coerce").iloc[0]) else f"{int(float(row.get('distance')))}m"
        lines.append(
            " / ".join(
                [
                    f"日付={_to_text(row.get('race_date', '-'))}",
                    f"開催={_to_text(row.get('venue', '-'))}",
                    f"馬場={_to_text(row.get('track_condition', '-'))}",
                    f"距離={distance_text}",
                    f"1着={_to_text(row.get('winner', '-'))}",
                    f"2着={_to_text(row.get('second', '-'))}",
                    f"3着={_to_text(row.get('third', '-'))}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- サンプルなし"


def _append_local_llm_memory_sample(payload: Dict[str, Any]) -> None:
    append_jsonl_with_compaction(
        LOCAL_LLM_MEMORY_PATH,
        payload,
        max_rows=LOCAL_LLM_MEMORY_MAX_ACTIVE_ROWS,
        max_bytes=LOCAL_LLM_MEMORY_MAX_ACTIVE_BYTES,
    )


def _append_llm_hands_free_history(
    *,
    action_label: Any,
    action_key: Any,
    category: Any,
    reason: Any,
    status: Any,
    data_mode: Any,
    signature: Any,
) -> None:
    payload = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "action_label": _to_text(action_label),
        "action_key": _to_text(action_key),
        "category": _to_text(category),
        "reason": _to_text(reason),
        "status": _to_text(status),
        "data_mode": _to_text(data_mode),
        "signature": _to_text(signature),
    }
    if not payload["action_label"]:
        return
    LLM_HANDS_FREE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False)
    with LLM_HANDS_FREE_HISTORY_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _build_llm_hands_free_history_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    label_map = {
        "queued": "自動実行",
        "switched_mode": "自動切替",
        "completed": "完了",
        "failed": "失敗",
    }
    frame = pd.DataFrame(
        [
            {
                "時刻": _format_timestamp_text(row.get("at", "")),
                "自動操作": _to_text(row.get("action_label", "-")),
                "状態": label_map.get(_to_text(row.get("status", "")), _to_text(row.get("status", "-")) or "-"),
                "カテゴリ": _to_text(row.get("category", "-")) or "-",
                "理由": _to_text(row.get("reason", "-")) or "-",
                "結果": _to_text(row.get("outcome_summary", "-")) or "-",
                "読み込み": _to_text(row.get("data_mode", "-")) or "-",
            }
            for row in rows
            if isinstance(row, dict)
        ]
    )
    return frame if not frame.empty else pd.DataFrame()


def _render_llm_hands_free_latest_cards(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        st.caption("まだ自動実行履歴はありません。")
        return
    latest = rows[-1] if isinstance(rows[-1], dict) else {}
    if not latest:
        st.caption("まだ自動実行履歴はありません。")
        return
    st.caption("直近の自動実行結果")
    top_cols = st.columns(3)
    top_cols[0].metric("操作", _to_text(latest.get("action_label", "-")) or "-")
    top_cols[1].metric("状態", _to_text(latest.get("status_label", latest.get("status", "-"))) or "-")
    top_cols[2].metric("時刻", _format_timestamp_text(latest.get("at", "")))
    summary_text = _to_text(latest.get("outcome_summary", ""))
    if summary_text:
        st.info(summary_text)
    budget_basis_change = latest.get("budget_basis_change")
    if isinstance(budget_basis_change, dict) and budget_basis_change:
        st.caption("この自動実行での標準配分変化")
        st.markdown(_render_budget_basis_change_html(budget_basis_change), unsafe_allow_html=True)
        changed_recommended = [_to_text(item) for item in budget_basis_change.get("after_recommended", []) if _to_text(item)]
        amount_preview = budget_basis_change.get("after_budget_amounts", [])
        primary_bet = changed_recommended[0] if changed_recommended else ""
        primary_button_label = (
            f"買い目提案を開く（{primary_bet}）"
            if primary_bet
            else "買い目提案を開く"
        )
        if st.button(
            primary_button_label,
            key=f"llm_history_basis_primary_jump_{_to_text(latest.get('at', ''))}",
            width="stretch",
        ):
            _request_open_bets_tab(primary_bet, amount_preview=amount_preview, highlight_source="history")
            st.rerun()
        if changed_recommended:
            st.caption("おすすめ券種を見る")
            jump_cols = st.columns(min(3, len(changed_recommended)), gap="small")
            for idx, bet in enumerate(changed_recommended[:3]):
                if jump_cols[idx].button(
                    f"{bet} を見る",
                    key=f"llm_history_basis_jump_{_to_text(latest.get('at', ''))}_{idx}_{bet}",
                    width="stretch",
                ):
                    _request_open_bets_tab(bet, amount_preview=amount_preview, highlight_source="history")
                    st.rerun()
    bet_guidance_change = latest.get("bet_guidance_change")
    if isinstance(bet_guidance_change, dict) and bet_guidance_change:
        st.caption("この自動実行でのおすすめ券種変化")
        st.markdown(_render_bet_guidance_change_html(bet_guidance_change), unsafe_allow_html=True)
    delta_snapshot = latest.get("delta_snapshot")
    if isinstance(delta_snapshot, dict) and delta_snapshot:
        metric_order = [
            "evaluated_races",
            "pending_races",
            "top_horse_hit_rate",
            "single_hit_rate",
            "place_hit_rate",
        ]
        metric_items = [delta_snapshot.get(key) for key in metric_order if isinstance(delta_snapshot.get(key), dict)]
        if metric_items:
            metric_cols = st.columns(min(5, len(metric_items)))
            for idx, item in enumerate(metric_items[:5]):
                metric_cols[idx].metric(
                    _to_text(item.get("label", "-")) or "-",
                    _to_text(item.get("after_text", item.get("text", "-"))) or "-",
                    _to_text(item.get("delta_text", "")) or None,
                )


def _build_bet_guidance_change_payload(
    *,
    basis_key: Any,
    before_summary: Dict[str, Any] | None,
    after_summary: Dict[str, Any] | None,
) -> Dict[str, Any]:
    key_text = _normalize_budget_basis_key(basis_key)
    before_recommended, before_avoid = _build_budget_basis_bet_guidance(key_text or "base", before_summary)
    after_recommended, after_avoid = _build_budget_basis_bet_guidance(key_text or "base", after_summary)
    changed = before_recommended != after_recommended or before_avoid != after_avoid
    if changed:
        summary = (
            f"寄せ {' / '.join(after_recommended[:3]) if after_recommended else '-'} / "
            f"抑え {' / '.join(after_avoid[:3]) if after_avoid else '特になし'}"
        )
    else:
        summary = "おすすめ券種は大きく変わっていません。"
    return {
        "basis_label": _format_budget_basis_label(key_text or "base"),
        "before_recommended": before_recommended[:3],
        "before_avoid": before_avoid[:3],
        "after_recommended": after_recommended[:3],
        "after_avoid": after_avoid[:3],
        "changed": bool(changed),
        "summary": summary,
    }


def _render_bet_guidance_change_html(payload: Dict[str, Any] | None) -> str:
    if not isinstance(payload, dict) or not payload:
        return ""

    def _badge_row(items: List[str], *, kind: str) -> str:
        filtered = [_to_text(item) for item in items if _to_text(item)]
        if not filtered:
            filtered = ["-"]
        badge_kind = "recommend" if kind == "recommend" else "avoid"
        prefix = "寄せ" if kind == "recommend" else "抑え"
        return "<div class='llm-hit-badge-row'>" + "".join(
            f"<span class='llm-hit-badge {badge_kind} neutral'>{prefix} {html_escape(item)}</span>"
            for item in filtered
        ) + "</div>"

    return """
<div class="memo-card" style="margin:0.25rem 0 0.65rem;">
  <div class="memo-chip">おすすめ券種の変化</div>
  <div class="memo-title">{basis}</div>
  <div class="memo-line"><strong>変化:</strong> {summary}</div>
  <div class="memo-line"><strong>前:</strong></div>
  {before_recommend}
  {before_avoid}
  <div class="memo-line" style="margin-top:0.35rem;"><strong>後:</strong></div>
  {after_recommend}
  {after_avoid}
</div>
""".format(
        basis=html_escape(_to_text(payload.get("basis_label", "-")) or "-"),
        summary=html_escape(_to_text(payload.get("summary", "-")) or "-"),
        before_recommend=_badge_row(payload.get("before_recommended", []), kind="recommend"),
        before_avoid=_badge_row(payload.get("before_avoid", []), kind="avoid"),
        after_recommend=_badge_row(payload.get("after_recommended", []), kind="recommend"),
        after_avoid=_badge_row(payload.get("after_avoid", []), kind="avoid"),
    )


def _capture_budget_basis_state_snapshot() -> Dict[str, Any]:
    basis_key = _to_text(st.session_state.get("budget_basis_choice", "trend")) or "trend"
    auto_enabled = bool(st.session_state.get("budget_basis_auto_enabled", True))
    decision_payload = st.session_state.get("budget_basis_auto_decision_payload")
    if not isinstance(decision_payload, dict):
        decision_payload = {}
    budget_total = pd.to_numeric(pd.Series([st.session_state.get("predict_budget_total", 10000)]), errors="coerce").iloc[0]
    bet_unit = pd.to_numeric(pd.Series([st.session_state.get("predict_bet_unit", 100)]), errors="coerce").iloc[0]
    recommended_bets = [_to_text(item) for item in decision_payload.get("final_recommended_bets", []) if _to_text(item)]
    avoid_bets = [_to_text(item) for item in decision_payload.get("final_avoid_bets", []) if _to_text(item)]
    return {
        "basis_key": basis_key,
        "basis_label": _format_budget_basis_label(basis_key),
        "mode_label": "半自動" if auto_enabled else "手動",
        "auto_enabled": auto_enabled,
        "reason": _to_text(decision_payload.get("final_reason", "")),
        "recommended_bets": recommended_bets[:3],
        "avoid_bets": avoid_bets[:3],
        "budget_total": int(float(budget_total)) if pd.notna(budget_total) and float(budget_total) > 0 else 10000,
        "bet_unit": int(float(bet_unit)) if pd.notna(bet_unit) and float(bet_unit) > 0 else 100,
    }


def _build_budget_basis_amount_preview(snapshot: Dict[str, Any] | None) -> List[Dict[str, str]]:
    if not isinstance(snapshot, dict):
        return []
    bets = [_to_text(item) for item in snapshot.get("recommended_bets", []) if _to_text(item)]
    if not bets:
        return []
    total_budget = pd.to_numeric(pd.Series([snapshot.get("budget_total")]), errors="coerce").iloc[0]
    bet_unit = pd.to_numeric(pd.Series([snapshot.get("bet_unit")]), errors="coerce").iloc[0]
    total_budget_int = int(float(total_budget)) if pd.notna(total_budget) and float(total_budget) > 0 else 10000
    bet_unit_int = int(float(bet_unit)) if pd.notna(bet_unit) and float(bet_unit) > 0 else 100

    count = min(3, len(bets))
    if count <= 1:
        ratios = [1.0]
    elif count == 2:
        ratios = [0.65, 0.35]
    else:
        ratios = [0.50, 0.30, 0.20]

    def _round_amount(value: float) -> int:
        return int(max(bet_unit_int, round(float(value) / bet_unit_int) * bet_unit_int))

    amounts: List[int] = []
    remaining = total_budget_int
    for idx, ratio in enumerate(ratios[:count]):
        if idx == count - 1:
            amount = max(bet_unit_int, remaining)
        else:
            amount = _round_amount(total_budget_int * ratio)
            amount = min(amount, remaining)
        amounts.append(amount)
        remaining -= amount
    if amounts:
        diff = total_budget_int - sum(amounts)
        amounts[-1] += diff

    preview_rows: List[Dict[str, str]] = []
    for bet, amount in zip(bets[:count], amounts):
        preview_rows.append(
            {
                "bet": bet,
                "amount": f"{int(amount):,}円",
            }
        )
    return preview_rows


def _build_budget_basis_change_payload(
    before_snapshot: Dict[str, Any] | None,
    after_snapshot: Dict[str, Any] | None,
) -> Dict[str, Any]:
    before = before_snapshot if isinstance(before_snapshot, dict) else {}
    after = after_snapshot if isinstance(after_snapshot, dict) else {}
    before_label = _to_text(before.get("basis_label", "")) or _format_budget_basis_label(before.get("basis_key", "trend"))
    after_label = _to_text(after.get("basis_label", "")) or _format_budget_basis_label(after.get("basis_key", "trend"))
    before_mode = _to_text(before.get("mode_label", "")) or "半自動"
    after_mode = _to_text(after.get("mode_label", "")) or "半自動"
    before_recommended = [_to_text(item) for item in before.get("recommended_bets", []) if _to_text(item)]
    after_recommended = [_to_text(item) for item in after.get("recommended_bets", []) if _to_text(item)]
    before_avoid = [_to_text(item) for item in before.get("avoid_bets", []) if _to_text(item)]
    after_avoid = [_to_text(item) for item in after.get("avoid_bets", []) if _to_text(item)]
    changed = any(
        [
            _to_text(before.get("basis_key", "")) != _to_text(after.get("basis_key", "")),
            bool(before.get("auto_enabled", True)) != bool(after.get("auto_enabled", True)),
            before_recommended != after_recommended,
            before_avoid != after_avoid,
        ]
    )
    if changed:
        summary = f"{before_label} ({before_mode}) -> {after_label} ({after_mode})"
    else:
        summary = f"{after_label} ({after_mode}) を維持"
    return {
        "changed": bool(changed),
        "summary": summary,
        "before_label": before_label,
        "after_label": after_label,
        "before_mode": before_mode,
        "after_mode": after_mode,
        "before_reason": _to_text(before.get("reason", "")),
        "after_reason": _to_text(after.get("reason", "")),
        "before_recommended": before_recommended[:3],
        "after_recommended": after_recommended[:3],
        "before_avoid": before_avoid[:3],
        "after_avoid": after_avoid[:3],
        "after_budget_amounts": _build_budget_basis_amount_preview(after),
    }


def _render_budget_basis_change_html(payload: Dict[str, Any] | None) -> str:
    if not isinstance(payload, dict) or not payload:
        return ""

    def _badge_row(items: List[str], *, kind: str) -> str:
        filtered = [_to_text(item) for item in items if _to_text(item)]
        if not filtered:
            filtered = ["-"]
        badge_kind = "recommend" if kind == "recommend" else "avoid"
        prefix = "寄せ" if kind == "recommend" else "抑え"
        return "<div class='llm-hit-badge-row'>" + "".join(
            f"<span class='llm-hit-badge {badge_kind} neutral'>{prefix} {html_escape(item)}</span>"
            for item in filtered
        ) + "</div>"

    summary = _to_text(payload.get("summary", "-")) or "-"
    change_text = "更新あり" if bool(payload.get("changed", False)) else "変更なし"
    card_class = "changed" if bool(payload.get("changed", False)) else "stable"
    before_reason = _to_text(payload.get("before_reason", "")) or "前回理由なし"
    after_reason = _to_text(payload.get("after_reason", "")) or "今回理由なし"
    before_label = _to_text(payload.get("before_label", "-")) or "-"
    after_label = _to_text(payload.get("after_label", "-")) or "-"
    before_mode = _to_text(payload.get("before_mode", "-")) or "-"
    after_mode = _to_text(payload.get("after_mode", "-")) or "-"
    amount_preview_rows = payload.get("after_budget_amounts", [])
    amount_preview_html = ""
    if isinstance(amount_preview_rows, list) and amount_preview_rows:
        amount_preview_html = (
            "<div class='basis-change-reason' style='margin-top:0.42rem;'><strong>今のおすすめ券種で寄せる目安:</strong> "
            + " / ".join(
                f"{html_escape(_to_text(row.get('bet', '-')))} {html_escape(_to_text(row.get('amount', '-')))}"
                for row in amount_preview_rows[:3]
                if isinstance(row, dict)
            )
            + "</div>"
        )
    return """
<div class="basis-change-card {card_class}">
  <div class="basis-change-top">
    <span class="basis-change-chip">標準配分の変化</span>
    <span class="basis-change-chip">{change_text}</span>
  </div>
  <div class="basis-change-title">{summary}</div>
  <div class="basis-change-flow">
    <div class="basis-change-node">
      <div class="basis-change-node-label">前回</div>
      <div class="basis-change-node-value">{before_label}</div>
      <span class="basis-change-node-mode {before_mode_class}">{before_mode}</span>
    </div>
    <div class="basis-change-arrow">→</div>
    <div class="basis-change-node">
      <div class="basis-change-node-label">今回</div>
      <div class="basis-change-node-value">{after_label}</div>
      <span class="basis-change-node-mode {after_mode_class}">{after_mode}</span>
    </div>
  </div>
  <div class="basis-change-reason"><strong>前の理由:</strong> {before_reason}</div>
  {before_recommend}
  {before_avoid}
  <div class="basis-change-reason" style="margin-top:0.38rem;"><strong>今回の理由:</strong> {after_reason}</div>
  {after_recommend}
  {after_avoid}
  {amount_preview_html}
</div>
""".format(
        card_class=card_class,
        summary=html_escape(summary),
        change_text=html_escape(change_text),
        before_label=html_escape(before_label),
        after_label=html_escape(after_label),
        before_mode=html_escape(before_mode),
        after_mode=html_escape(after_mode),
        before_mode_class=("manual" if before_mode == "手動" else "auto"),
        after_mode_class=("manual" if after_mode == "手動" else "auto"),
        before_reason=html_escape(before_reason),
        after_reason=html_escape(after_reason),
        before_recommend=_badge_row(payload.get("before_recommended", []), kind="recommend"),
        before_avoid=_badge_row(payload.get("before_avoid", []), kind="avoid"),
        after_recommend=_badge_row(payload.get("after_recommended", []), kind="recommend"),
        after_avoid=_badge_row(payload.get("after_avoid", []), kind="avoid"),
        amount_preview_html=amount_preview_html,
    )


def _build_local_llm_focus_cards(llm_text: str) -> List[Dict[str, str]]:
    text = _to_text(llm_text)
    if not text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    def _extract(prefixes: List[str]) -> str:
        for raw_line in lines:
            line = re.sub(r"^[\-\*\•\d\.\)\s]+", "", raw_line).strip()
            for prefix in prefixes:
                match = re.match(rf"^{re.escape(prefix)}\s*[：:]\s*(.+)$", line)
                if match:
                    return match.group(1).strip()
        return ""

    cards = [
        {
            "label": "本命",
            "icon": "◎",
            "kind": "favorite",
            "text": _extract(["本命視点", "本命", "軸"]),
        },
        {
            "label": "穴",
            "icon": "▲",
            "kind": "longshot",
            "text": _extract(["一発候補", "穴候補", "穴", "大穴"]),
        },
        {
            "label": "危険人気",
            "icon": "危",
            "kind": "danger",
            "text": _extract(["危険人気馬", "危険人気", "危険"]),
        },
    ]
    summary_line = _extract(["総評", "結論", "買い目案", "注意"]) or (lines[0] if lines else "")
    for card in cards:
        if not _to_text(card.get("text", "")):
            card["text"] = summary_line or "まだ要約がありません。"
    return cards


def _render_local_llm_focus_cards(cards: List[Dict[str, str]]) -> str:
    if not cards:
        return ""
    rendered: List[str] = []
    for card in cards:
        rendered.append(
            """
<div class="local-llm-summary-card {kind}">
  <div class="local-llm-summary-chip">{icon} {label}</div>
  <div class="local-llm-summary-text">{text}</div>
</div>
""".format(
                kind=html_escape(_to_text(card.get("kind", "favorite")) or "favorite"),
                icon=html_escape(_to_text(card.get("icon", "")) or ""),
                label=html_escape(_to_text(card.get("label", "-")) or "-"),
                text=html_escape(_to_text(card.get("text", "-")) or "-"),
            )
        )
    return "<div class='local-llm-summary-grid'>" + "".join(rendered) + "</div>"


def _set_llm_hands_free_active_action(
    *,
    action_label: Any,
    action_key: Any,
    category: Any,
    reason: Any,
    data_mode: Any,
    signature: Any,
) -> None:
    st.session_state["llm_hands_free_active_action"] = {
        "action_label": _to_text(action_label),
        "action_key": _to_text(action_key),
        "category": _to_text(category),
        "reason": _to_text(reason),
        "data_mode": _to_text(data_mode),
        "signature": _to_text(signature),
        "queued_at": datetime.now().isoformat(timespec="seconds"),
        "budget_basis_snapshot": _capture_budget_basis_state_snapshot(),
    }


def _consume_llm_hands_free_active_action(expected_action_key: Any) -> Dict[str, Any] | None:
    payload = st.session_state.get("llm_hands_free_active_action")
    if not isinstance(payload, dict):
        return None
    if _to_text(payload.get("action_key", "")) != _to_text(expected_action_key):
        return None
    return payload


def _finalize_llm_hands_free_active_action(
    expected_action_key: Any,
    *,
    outcome_summary: Any,
    status: str = "completed",
    extra: Dict[str, Any] | None = None,
) -> None:
    payload = _consume_llm_hands_free_active_action(expected_action_key)
    if not payload:
        return
    _append_llm_hands_free_history(
        action_label=payload.get("action_label"),
        action_key=payload.get("action_key"),
        category=payload.get("category"),
        reason=payload.get("reason"),
        status=status,
        data_mode=payload.get("data_mode"),
        signature=payload.get("signature"),
    )
    history_rows = _read_jsonl_if_exists(LLM_HANDS_FREE_HISTORY_PATH, limit=200)
    if history_rows:
        history_rows[-1]["outcome_summary"] = _to_text(outcome_summary)
        history_rows[-1]["status_label"] = {
            "completed": "完了",
            "failed": "失敗",
            "queued": "自動実行",
            "switched_mode": "自動切替",
        }.get(status, _to_text(status) or "-")
        budget_basis_change = _build_budget_basis_change_payload(
            payload.get("budget_basis_snapshot"),
            _capture_budget_basis_state_snapshot(),
        )
        history_rows[-1]["budget_basis_change"] = budget_basis_change
        if isinstance(extra, dict):
            for key, value in extra.items():
                history_rows[-1][str(key)] = value
        LLM_HANDS_FREE_HISTORY_PATH.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in history_rows) + "\n",
            encoding="utf-8",
        )
        if status == "completed" and isinstance(budget_basis_change, dict) and bool(budget_basis_change.get("changed", False)):
            next_basis = _to_text(budget_basis_change.get("after_label", "")) or "-"
            next_mode = _to_text(budget_basis_change.get("after_mode", "")) or "-"
            recommended = " / ".join(
                [_to_text(item) for item in budget_basis_change.get("after_recommended", []) if _to_text(item)]
            ) or "おすすめ券種なし"
            _set_ui_notice(
                f"標準配分を更新しました: {_to_text(budget_basis_change.get('summary', '')) or next_basis}",
                title="自動判断で標準配分を切替",
                chip="自動判断 更新",
                detail=f"現在は `{next_basis}` ({next_mode})。おすすめ券種は {recommended} です。",
                level="info",
            )
    st.session_state.pop("llm_hands_free_active_action", None)


def _build_llm_memory_prompt_text(
    memory_rows: List[Dict[str, Any]],
    *,
    llm_style: str,
    limit: int = 3,
) -> str:
    if not memory_rows:
        return "- メモなし"
    selected: List[Dict[str, Any]] = []
    style_text = _to_text(llm_style)
    for row in reversed(memory_rows):
        if style_text and _to_text(row.get("llm_style", "")) == style_text:
            selected.append(row)
        if len(selected) >= max(1, int(limit)):
            break
    if not selected:
        selected = list(reversed(memory_rows[-max(1, int(limit)) :]))
    lines: List[str] = []
    for row in selected[: max(1, int(limit))]:
        lines.append(
            " / ".join(
                [
                    f"レース={_to_text(row.get('race_label', '-'))}",
                    f"方針={_to_text(row.get('llm_style', '-'))}",
                    f"要点={_to_text(row.get('summary', '-'))}",
                    f"タグ={_to_text(row.get('miss_tags', '-'))}",
                    f"推奨={_to_text(row.get('preferred_bets', '-'))}",
                    f"回避={_to_text(row.get('avoid_bets', '-'))}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- メモなし"


def _build_prediction_ticket_prompt_text(ticket_df: pd.DataFrame, limit: int = 6) -> str:
    if ticket_df.empty:
        return "- 予想票なし"
    lines: List[str] = []
    for _, row in ticket_df.head(max(1, int(limit))).iterrows():
        lines.append(
            " / ".join(
                [
                    f"券種={_to_text(row.get('券種', '-'))}",
                    f"本線={_to_text(row.get('本線', '-'))}",
                    f"押さえ={_to_text(row.get('押さえ', '-'))}",
                    f"期待度={_to_text(row.get('期待度', '-'))}",
                    f"メモ={_to_text(row.get('買い方メモ', '-'))}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- 予想票なし"


def _build_feedback_sample_prompt_text(
    feedback_df: pd.DataFrame,
    *,
    venue: Any,
    track_condition: Any,
    distance: Any,
    race_grade: Any,
    misses_only: bool = False,
    limit: int = 4,
) -> str:
    if feedback_df.empty:
        return "- フィードバックなし"
    work = feedback_df.copy()
    archive_by_race_id = _load_prediction_archive_context_map()
    if "result_available" in work.columns:
        result_mask = work["result_available"].map(lambda value: bool(str(value).lower() in {"true", "1"})) if work["result_available"].dtype != bool else work["result_available"].astype(bool)
        work = work[result_mask].copy()
    if work.empty:
        return "- フィードバックなし"
    if misses_only:
        miss_rows = pd.DataFrame()
        if "top_horse_hit" in work.columns:
            miss_rows = work[~work["top_horse_hit"].fillna(False).astype(bool)].copy()
        elif "single_hit" in work.columns:
            miss_rows = work[~work["single_hit"].fillna(False).astype(bool)].copy()
        if miss_rows.empty:
            return "- 外れレースの実結果フィードバックなし"
        work = miss_rows

    score = pd.Series(0.0, index=work.index, dtype=float)
    venue_text = _to_text(venue)
    track_text = _to_text(track_condition)
    grade_text = _to_text(race_grade)
    distance_num = pd.to_numeric(pd.Series([distance]), errors="coerce").iloc[0]
    if venue_text and "venue" in work.columns:
        score += work["venue"].map(lambda value: 2.2 if _to_text(value) == venue_text else 0.0)
    if track_text:
        score += work["race_id"].map(
            lambda value: 1.0 if _to_text(archive_by_race_id.get(_to_text(value), {}).get("track_condition", "")) == track_text else 0.0
        )
    if grade_text and "race_grade" in work.columns:
        score += work["race_grade"].map(lambda value: 0.8 if _to_text(value) == grade_text else 0.0)
    if pd.notna(distance_num):
        dist_num = work["race_id"].map(
            lambda value: archive_by_race_id.get(_to_text(value), {}).get("distance", "")
        )
        dist_num = pd.to_numeric(dist_num, errors="coerce")
        score += (1.2 - (dist_num.sub(float(distance_num)).abs() / 1200.0)).clip(lower=0.0).fillna(0.0)
    work["_score"] = score
    work = work.sort_values(["_score", "race_date", "race_id"], ascending=[False, False, False]).head(max(1, int(limit)))
    lines: List[str] = []
    for _, row in work.iterrows():
        archive_row = archive_by_race_id.get(_to_text(row.get("race_id", "")), {})
        miss_hit = bool(str(row.get("top_horse_hit", "")).lower() in {"true", "1"}) or row.get("top_horse_hit") is True
        miss_reason = "-" if miss_hit and not misses_only else _build_result_sync_miss_reason(row, archive_row)
        lines.append(
            " / ".join(
                [
                    f"レース={_to_text(row.get('race_name', row.get('race_id', '-')))}",
                    f"格付={_to_text(row.get('race_grade', '-'))}",
                    f"馬場={_to_text(archive_row.get('track_condition', '-')) or '-'}",
                    f"距離={_to_text(archive_row.get('distance', '-')) or '-'}",
                    f"補正={_to_text(row.get('condition_adjustments', '-'))}",
                    f"本命={_to_text(row.get('top_horse', '-'))}",
                    f"1着={_to_text(row.get('actual_winner', '-'))}",
                    f"本命的中={_format_hit_mark(row.get('top_horse_hit'))}",
                    f"単勝的中={_format_hit_mark(row.get('single_hit'))}",
                    f"要因={miss_reason}" if misses_only else f"反省={miss_reason}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- フィードバックなし"


def _build_odds_shift_alert_prompt_text(table: pd.DataFrame, limit: int = 3) -> str:
    if table.empty:
        return "- 人気急変なし"
    lines: List[str] = []
    for _, row in table.head(max(1, int(limit))).iterrows():
        lines.append(
            " / ".join(
                [
                    f"馬番={_to_text(row.get('馬番', '-'))}",
                    f"馬={_to_text(row.get('馬', '-'))}",
                    f"状態={_to_text(row.get('アラート', '-'))}",
                    f"人気={_to_text(row.get('人気', '-'))}",
                    f"直前オッズ差={_to_text(row.get('直前オッズ差', '-'))}",
                    f"理由={_to_text(row.get('理由', '-'))}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- 人気急変なし"


def _build_horse_feature_diff_prompt_text(result: PredictionResult, limit: int = 6) -> str:
    if result.horse_predictions.empty:
        return "- 差分なし"
    work = result.horse_predictions.copy()
    numeric_labels = [
        ("horse_win_rate", "馬実績"),
        ("horse_place_rate", "馬複勝"),
        ("jockey_win_rate", "騎手勝率"),
        ("jockey_place_rate", "騎手複勝"),
        ("trainer_win_rate", "厩舎勝率"),
        ("trainer_place_rate", "厩舎複勝"),
        ("weather_fit", "天気適性"),
        ("track_fit", "馬場適性"),
        ("distance_fit", "距離適性"),
        ("form_factor", "調子"),
        ("condition_factor", "状態"),
        ("paddock_factor", "気配"),
        ("weight_diff_factor", "体重変動"),
        ("odds_shift_factor", "直前気配"),
        ("market_factor", "市場評価"),
    ]
    for column_name, _ in numeric_labels:
        if column_name in work.columns:
            work[column_name] = pd.to_numeric(work[column_name], errors="coerce")
    means = {
        column_name: float(work[column_name].mean())
        for column_name, _ in numeric_labels
        if column_name in work.columns and work[column_name].notna().any()
    }
    lines: List[str] = []
    for _, row in work.head(max(1, int(limit))).iterrows():
        diffs: List[tuple[float, str]] = []
        for column_name, label in numeric_labels:
            if column_name not in means:
                continue
            value = pd.to_numeric(pd.Series([row.get(column_name)]), errors="coerce").iloc[0]
            if pd.isna(value):
                continue
            delta = float(value) - float(means[column_name])
            diffs.append((abs(delta), f"{label}{delta:+.2f}"))
        diffs = sorted(diffs, key=lambda item: item[0], reverse=True)
        diff_text = ", ".join(item[1] for item in diffs[:5]) if diffs else "-"
        lines.append(
            " / ".join(
                [
                    f"馬番={_to_text(row.get('馬番', '-'))}",
                    f"馬={_to_text(row.get('馬', '-'))}",
                    f"人気={_to_text(row.get('人気', '-'))}",
                    f"勝率={float(pd.to_numeric(pd.Series([row.get('勝率')]), errors='coerce').iloc[0]):.2%}" if pd.notna(pd.to_numeric(pd.Series([row.get("勝率")]), errors="coerce").iloc[0]) else "勝率=-",
                    f"差分={diff_text}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- 差分なし"


def _build_target_horse_analog_table(
    history_df: pd.DataFrame,
    entries_df: pd.DataFrame,
    *,
    target_horses: List[str],
    venue: Any,
    track_condition: Any,
    distance: Any,
    analogs_per_horse: int = 2,
) -> pd.DataFrame:
    if history_df.empty or entries_df.empty or not target_horses:
        return pd.DataFrame()
    if "horse" not in history_df.columns or "finish" not in history_df.columns or "horse" not in entries_df.columns:
        return pd.DataFrame()

    history = history_df.copy()
    history["horse"] = history["horse"].map(_to_text)
    history["finish_num"] = pd.to_numeric(history.get("finish"), errors="coerce")
    history["distance_num"] = pd.to_numeric(history.get("distance"), errors="coerce")
    history["form_score_num"] = pd.to_numeric(history.get("form_score"), errors="coerce")
    history["condition_score_num"] = pd.to_numeric(history.get("condition_score"), errors="coerce")
    history["paddock_score_num"] = pd.to_numeric(history.get("paddock_score"), errors="coerce")
    history["weight_diff_num"] = pd.to_numeric(history.get("weight_diff"), errors="coerce")
    history["gate_num"] = pd.to_numeric(history.get("gate"), errors="coerce")
    history["venue_text"] = history.get("venue", pd.Series(index=history.index, dtype=object)).map(_to_text)
    history["track_text"] = history.get("track_condition", pd.Series(index=history.index, dtype=object)).map(_to_text)
    history = history[(history["horse"] != "") & history["finish_num"].notna()].copy()
    if history.empty:
        return pd.DataFrame()

    entries = entries_df.copy()
    entries["horse"] = entries["horse"].map(_to_text)
    entries["distance_num"] = pd.to_numeric(entries.get("distance"), errors="coerce")
    entries["form_score_num"] = pd.to_numeric(entries.get("form_score"), errors="coerce")
    entries["condition_score_num"] = pd.to_numeric(entries.get("condition_score"), errors="coerce")
    entries["paddock_score_num"] = pd.to_numeric(entries.get("paddock_score"), errors="coerce")
    entries["weight_diff_num"] = pd.to_numeric(entries.get("weight_diff"), errors="coerce")
    entries["gate_num"] = pd.to_numeric(entries.get("gate"), errors="coerce")
    entries["venue_text"] = entries.get("venue", pd.Series(index=entries.index, dtype=object)).map(_to_text)
    entries["track_text"] = entries.get("track_condition", pd.Series(index=entries.index, dtype=object)).map(_to_text)

    target_distance = pd.to_numeric(pd.Series([distance]), errors="coerce").iloc[0]
    target_venue = _to_text(venue)
    target_track = _to_text(track_condition)

    rows: List[Dict[str, Any]] = []
    clean_targets = [_to_text(name) for name in target_horses if _to_text(name)]
    for horse_name in clean_targets:
        entry_hit = entries[entries["horse"] == horse_name].head(1)
        if entry_hit.empty:
            continue
        entry_row = entry_hit.iloc[0]
        score = pd.Series(0.0, index=history.index, dtype=float)
        if target_venue:
            score += history["venue_text"].map(lambda value: 1.8 if value == target_venue else 0.0)
        elif _to_text(entry_row.get("venue_text", "")):
            score += history["venue_text"].map(lambda value: 1.8 if value == _to_text(entry_row.get("venue_text", "")) else 0.0)
        if target_track:
            score += history["track_text"].map(lambda value: 1.0 if value == target_track else 0.0)
        elif _to_text(entry_row.get("track_text", "")):
            score += history["track_text"].map(lambda value: 1.0 if value == _to_text(entry_row.get("track_text", "")) else 0.0)

        entry_distance = pd.to_numeric(pd.Series([entry_row.get("distance_num")]), errors="coerce").iloc[0]
        effective_distance = target_distance if pd.notna(target_distance) else entry_distance
        if pd.notna(effective_distance):
            score += (1.6 - (history["distance_num"].sub(float(effective_distance)).abs() / 1200.0)).clip(lower=0.0).fillna(0.0)

        for hist_col, entry_col, weight, scale in [
            ("form_score_num", "form_score_num", 1.0, 40.0),
            ("condition_score_num", "condition_score_num", 1.0, 40.0),
            ("paddock_score_num", "paddock_score_num", 0.8, 40.0),
            ("weight_diff_num", "weight_diff_num", 0.8, 10.0),
            ("gate_num", "gate_num", 0.4, 8.0),
        ]:
            entry_value = pd.to_numeric(pd.Series([entry_row.get(entry_col)]), errors="coerce").iloc[0]
            if pd.isna(entry_value):
                continue
            score += (float(weight) * (1.0 - (history[hist_col].sub(float(entry_value)).abs() / float(scale))).clip(lower=0.0)).fillna(0.0)

        score += history["finish_num"].map(lambda value: 1.4 if float(value) == 1.0 else (0.8 if float(value) <= 3.0 else 0.0))
        analogs = history.copy()
        analogs["類似度"] = score
        analogs = analogs.sort_values(["類似度", "finish_num"], ascending=[False, True]).head(max(1, int(analogs_per_horse)))
        for _, analog_row in analogs.iterrows():
            finish_num = float(pd.to_numeric(pd.Series([analog_row.get("finish_num")]), errors="coerce").iloc[0])
            analog_type = "凡走型"
            if finish_num == 1.0:
                analog_type = "勝ち切り型"
            elif finish_num <= 3.0:
                analog_type = "連下型"
            rows.append(
                {
                    "対象馬": horse_name,
                    "類似馬": _to_text(analog_row.get("horse", "-")),
                    "類似度": float(pd.to_numeric(pd.Series([analog_row.get("類似度")]), errors="coerce").iloc[0]),
                    "参照型": analog_type,
                    "開催": _to_text(analog_row.get("venue_text", "-")) or "-",
                    "馬場": _to_text(analog_row.get("track_text", "-")) or "-",
                    "距離": "-" if pd.isna(analog_row.get("distance_num")) else f"{int(float(analog_row.get('distance_num')))}m",
                    "着順": int(float(analog_row.get("finish_num"))),
                    "体重増減": "-" if pd.isna(analog_row.get("weight_diff_num")) else f"{float(analog_row.get('weight_diff_num')):+.0f}",
                    "調子": "-" if pd.isna(analog_row.get("form_score_num")) else f"{float(analog_row.get('form_score_num')):.0f}",
                    "状態": "-" if pd.isna(analog_row.get("condition_score_num")) else f"{float(analog_row.get('condition_score_num')):.0f}",
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["類似度"] = pd.to_numeric(out["類似度"], errors="coerce")
    return out.sort_values(["対象馬", "類似度", "着順"], ascending=[True, False, True]).reset_index(drop=True)


def _build_analog_horse_history_table(
    history_df: pd.DataFrame,
    entries_df: pd.DataFrame,
    result: PredictionResult,
    *,
    venue: Any,
    track_condition: Any,
    distance: Any,
    limit_horses: int = 5,
    analogs_per_horse: int = 2,
) -> pd.DataFrame:
    if history_df.empty or entries_df.empty or result.horse_predictions.empty:
        return pd.DataFrame()
    top_horses = result.horse_predictions.head(max(1, int(limit_horses)))["馬"].map(_to_text).tolist()
    return _build_target_horse_analog_table(
        history_df,
        entries_df,
        target_horses=top_horses,
        venue=venue,
        track_condition=track_condition,
        distance=distance,
        analogs_per_horse=analogs_per_horse,
    )


def _analog_horse_history_to_prompt_text(table: pd.DataFrame, limit: int = 8) -> str:
    if table.empty:
        return "- 類似個体なし"
    lines: List[str] = []
    for _, row in table.head(max(1, int(limit))).iterrows():
        lines.append(
            " / ".join(
                [
                    f"対象馬={_to_text(row.get('対象馬', '-'))}",
                    f"類似馬={_to_text(row.get('類似馬', '-'))}",
                    f"型={_to_text(row.get('参照型', '-'))}",
                    f"類似度={_to_text(row.get('類似度', '-'))}",
                    f"開催={_to_text(row.get('開催', '-'))}",
                    f"馬場={_to_text(row.get('馬場', '-'))}",
                    f"距離={_to_text(row.get('距離', '-'))}",
                    f"着順={_to_text(row.get('着順', '-'))}",
                    f"体重増減={_to_text(row.get('体重増減', '-'))}",
                    f"調子={_to_text(row.get('調子', '-'))}",
                    f"状態={_to_text(row.get('状態', '-'))}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- 類似個体なし"


def _build_analog_type_summary(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty or "参照型" not in table.columns:
        return pd.DataFrame(columns=["参照型", "件数"])
    order = {"勝ち切り型": 0, "連下型": 1, "凡走型": 2}
    summary = (
        table["参照型"]
        .fillna("")
        .astype(str)
        .str.strip()
        .loc[lambda s: s != ""]
        .value_counts()
        .rename_axis("参照型")
        .reset_index(name="件数")
    )
    if summary.empty:
        return pd.DataFrame(columns=["参照型", "件数"])
    summary["_order"] = summary["参照型"].map(lambda value: order.get(str(value), 99))
    summary = summary.sort_values(["_order", "件数"], ascending=[True, False]).drop(columns=["_order"])
    return summary.reset_index(drop=True)


def _build_analog_betting_tendency_table(table: pd.DataFrame) -> pd.DataFrame:
    summary = _build_analog_type_summary(table)
    if summary.empty:
        return pd.DataFrame(columns=["参照型", "件数", "想定傾向", "向く買い方", "見方"])
    tendency_map = {
        "勝ち切り型": {
            "想定傾向": "1着まで押し切るイメージがある",
            "向く買い方": "単勝 / 馬単1着 / 三連単1着軸",
            "見方": "本命寄りで頭固定を検討",
        },
        "連下型": {
            "想定傾向": "2-3着で残りやすい",
            "向く買い方": "複勝 / ワイド / 三連複軸",
            "見方": "相手本線や軸候補で安定寄り",
        },
        "凡走型": {
            "想定傾向": "飛ぶリスクが残る",
            "向く買い方": "見送り / 抑え / 相手薄め",
            "見方": "人気なら危険人気として注意",
        },
    }
    out = summary.copy()
    out["想定傾向"] = out["参照型"].map(lambda value: tendency_map.get(_to_text(value), {}).get("想定傾向", "-"))
    out["向く買い方"] = out["参照型"].map(lambda value: tendency_map.get(_to_text(value), {}).get("向く買い方", "-"))
    out["見方"] = out["参照型"].map(lambda value: tendency_map.get(_to_text(value), {}).get("見方", "-"))
    return out.reset_index(drop=True)


def _build_analog_budget_bias_table(table: pd.DataFrame) -> pd.DataFrame:
    summary = _build_analog_type_summary(table)
    if summary.empty:
        return pd.DataFrame(columns=["券種", "型補正倍率", "配分方針", "根拠"])
    counts = {str(row["参照型"]): int(row["件数"]) for _, row in summary.iterrows()}
    total = max(1, int(sum(counts.values())))
    win_share = counts.get("勝ち切り型", 0) / total
    place_share = counts.get("連下型", 0) / total
    poor_share = counts.get("凡走型", 0) / total
    dominant_type = max(
        [("勝ち切り型", win_share), ("連下型", place_share), ("凡走型", poor_share)],
        key=lambda item: item[1],
    )[0]
    root_text = {
        "勝ち切り型": f"勝ち切り型 {win_share:.0%} が優勢",
        "連下型": f"連下型 {place_share:.0%} が優勢",
        "凡走型": f"凡走型 {poor_share:.0%} が優勢",
    }.get(dominant_type, "型は拮抗")
    multiplier_map = {
        "単勝": 1.0 + (1.00 * win_share) + (0.10 * place_share) - (0.35 * poor_share),
        "複勝": 1.0 + (0.20 * win_share) + (0.75 * place_share) - (0.10 * poor_share),
        "馬連": 1.0 + (0.35 * win_share) + (0.30 * place_share) - (0.10 * poor_share),
        "ワイド": 1.0 + (0.10 * win_share) + (0.65 * place_share) - (0.05 * poor_share),
        "馬単": 1.0 + (0.75 * win_share) + (0.10 * place_share) - (0.25 * poor_share),
        "三連複": 1.0 + (0.20 * win_share) + (0.50 * place_share) - (0.15 * poor_share),
        "三連単": 1.0 + (0.95 * win_share) + (0.05 * place_share) - (0.35 * poor_share),
    }
    rows: List[Dict[str, Any]] = []
    for bet_type in ["単勝", "複勝", "馬連", "ワイド", "馬単", "三連複", "三連単"]:
        multiplier = float(max(0.55, min(1.75, multiplier_map.get(bet_type, 1.0))))
        policy = "標準"
        if multiplier >= 1.18:
            policy = "強め"
        elif multiplier <= 0.92:
            policy = "抑え"
        if bet_type in {"単勝", "馬単", "三連単"}:
            reason = f"{root_text} / 頭固定寄りの券種"
        elif bet_type in {"複勝", "ワイド", "三連複"}:
            reason = f"{root_text} / 連下寄りの券種"
        else:
            reason = root_text
        rows.append(
            {
                "券種": bet_type,
                "型補正倍率": multiplier,
                "配分方針": policy,
                "根拠": reason,
            }
        )
    return pd.DataFrame(rows)


def _build_analog_adjusted_budget_plan(
    plan_df: pd.DataFrame,
    bias_df: pd.DataFrame,
    *,
    bet_units: int,
) -> pd.DataFrame:
    if (
        plan_df.empty
        or bias_df.empty
        or "券種" not in plan_df.columns
        or "推奨金額" not in plan_df.columns
        or "券種" not in bias_df.columns
        or "型補正倍率" not in bias_df.columns
    ):
        return pd.DataFrame()
    work = plan_df.copy()
    work["ベース配分"] = pd.to_numeric(work["推奨金額"], errors="coerce").fillna(0.0)
    work = work[work["ベース配分"] > 0].copy()
    if work.empty:
        return pd.DataFrame()
    bias_map = {
        _to_text(row.get("券種", "")): float(pd.to_numeric(pd.Series([row.get("型補正倍率")]), errors="coerce").iloc[0])
        for _, row in bias_df.iterrows()
        if _to_text(row.get("券種", ""))
    }
    policy_map = {_to_text(row.get("券種", "")): _to_text(row.get("配分方針", "")) for _, row in bias_df.iterrows()}
    reason_map = {_to_text(row.get("券種", "")): _to_text(row.get("根拠", "")) for _, row in bias_df.iterrows()}
    work["型補正倍率"] = work["券種"].map(lambda value: float(bias_map.get(_to_text(value), 1.0)))
    work["配分方針"] = work["券種"].map(lambda value: policy_map.get(_to_text(value), "標準"))
    work["型根拠"] = work["券種"].map(lambda value: reason_map.get(_to_text(value), "-"))
    work["補正スコア"] = work["ベース配分"] * work["型補正倍率"]
    score_sum = float(work["補正スコア"].sum())
    if score_sum <= 0:
        return pd.DataFrame()
    total_budget = float(work["ベース配分"].sum())
    unit = max(float(bet_units), 100.0)
    work["型補正後金額"] = np.round((total_budget * work["補正スコア"] / score_sum) / unit) * unit
    diff = int(round(total_budget - float(work["型補正後金額"].sum())))
    if diff != 0 and len(work) > 0:
        adjust_order = work.sort_values(["補正スコア", "ベース配分"], ascending=[False, False]).index.tolist()
        step = int(unit) if unit > 0 else 100
        remaining = diff
        while remaining != 0 and adjust_order:
            moved = False
            for idx in adjust_order:
                current_amount = float(work.at[idx, "型補正後金額"])
                if remaining > 0:
                    work.at[idx, "型補正後金額"] = current_amount + step
                    remaining -= step
                    moved = True
                elif remaining < 0 and current_amount - step >= 0:
                    work.at[idx, "型補正後金額"] = current_amount - step
                    remaining += step
                    moved = True
                if remaining == 0:
                    break
            if not moved:
                break
    work["ベース配分"] = work["ベース配分"].map(lambda value: f"{int(round(float(value))):,}円")
    work["型補正後金額"] = pd.to_numeric(work["型補正後金額"], errors="coerce").fillna(0.0).map(
        lambda value: f"{int(round(float(value))):,}円"
    )
    work["型補正倍率"] = pd.to_numeric(work["型補正倍率"], errors="coerce").map(
        lambda value: "-" if pd.isna(value) else f"{float(value):.2f}x"
    )
    keep_cols = ["券種", "買い目", "ベース配分", "型補正後金額", "型補正倍率", "配分方針", "型根拠"]
    keep_cols = [col for col in keep_cols if col in work.columns]
    return work[keep_cols].reset_index(drop=True)


def _build_feedback_trend_bias_table(summary: Dict[str, Any] | None) -> pd.DataFrame:
    if not isinstance(summary, dict):
        return pd.DataFrame(columns=["券種", "傾向倍率", "今週方針", "今週根拠"])
    recommended = [_to_text(item) for item in summary.get("recommended_bets", []) if _to_text(item)]
    avoid = [_to_text(item) for item in summary.get("avoid_bets", []) if _to_text(item) and _to_text(item) != "見送りなし"]
    stance = _to_text(summary.get("stance", "")) or "標準"
    if not recommended and not avoid:
        return pd.DataFrame(columns=["券種", "傾向倍率", "今週方針", "今週根拠"])

    all_bets = ["単勝", "複勝", "馬連", "ワイド", "馬単", "三連複", "三連単"]
    multiplier_map = {bet: 1.0 for bet in all_bets}
    for idx, bet in enumerate(recommended[:4]):
        multiplier_map[bet] = max(multiplier_map.get(bet, 1.0), [1.24, 1.16, 1.10, 1.06][idx])
    for bet in avoid[:4]:
        multiplier_map[bet] = min(multiplier_map.get(bet, 1.0), 0.84)

    rows: List[Dict[str, Any]] = []
    for bet in all_bets:
        multiplier = float(multiplier_map.get(bet, 1.0))
        if multiplier >= 1.15:
            policy = f"{stance}で厚め"
        elif multiplier > 1.0:
            policy = f"{stance}で少し厚め"
        elif multiplier < 0.95:
            policy = "抑え気味"
        else:
            policy = "標準"
        if bet in recommended:
            reason = "今週おすすめ券種"
        elif bet in avoid:
            reason = "今週は抑えたい券種"
        else:
            reason = "今週傾向では中立"
        rows.append(
            {
                "券種": bet,
                "傾向倍率": multiplier,
                "今週方針": policy,
                "今週根拠": reason,
            }
        )
    return pd.DataFrame(rows)


def _build_feedback_trend_adjusted_budget_plan(
    plan_df: pd.DataFrame,
    trend_summary: Dict[str, Any] | None,
    *,
    bet_units: int,
) -> pd.DataFrame:
    trend_bias_df = _build_feedback_trend_bias_table(trend_summary)
    if plan_df.empty or trend_bias_df.empty or "券種" not in plan_df.columns:
        return pd.DataFrame()
    amount_col = ""
    for candidate in ["推奨金額", "型補正後金額"]:
        if candidate in plan_df.columns:
            amount_col = candidate
            break
    if not amount_col:
        return pd.DataFrame()
    work = plan_df.copy()
    work["ベース配分"] = pd.to_numeric(work[amount_col].astype(str).str.replace("円", "", regex=False).str.replace(",", "", regex=False), errors="coerce").fillna(0.0)
    work = work[work["ベース配分"] > 0].copy()
    if work.empty:
        return pd.DataFrame()
    bias_map = {
        _to_text(row.get("券種", "")): float(pd.to_numeric(pd.Series([row.get("傾向倍率")]), errors="coerce").iloc[0])
        for _, row in trend_bias_df.iterrows()
        if _to_text(row.get("券種", ""))
    }
    policy_map = {_to_text(row.get("券種", "")): _to_text(row.get("今週方針", "")) for _, row in trend_bias_df.iterrows()}
    reason_map = {_to_text(row.get("券種", "")): _to_text(row.get("今週根拠", "")) for _, row in trend_bias_df.iterrows()}
    work["傾向倍率"] = work["券種"].map(lambda value: float(bias_map.get(_to_text(value), 1.0)))
    work["今週方針"] = work["券種"].map(lambda value: policy_map.get(_to_text(value), "標準"))
    work["今週根拠"] = work["券種"].map(lambda value: reason_map.get(_to_text(value), "-"))
    work["補正スコア"] = work["ベース配分"] * work["傾向倍率"]
    score_sum = float(work["補正スコア"].sum())
    if score_sum <= 0:
        return pd.DataFrame()
    total_budget = float(work["ベース配分"].sum())
    unit = max(float(bet_units), 100.0)
    work["今週傾向後金額"] = np.round((total_budget * work["補正スコア"] / score_sum) / unit) * unit
    diff = int(round(total_budget - float(work["今週傾向後金額"].sum())))
    if diff != 0 and len(work) > 0:
        adjust_order = work.sort_values(["補正スコア", "ベース配分"], ascending=[False, False]).index.tolist()
        step = int(unit) if unit > 0 else 100
        remaining = diff
        while remaining != 0 and adjust_order:
            moved = False
            for idx in adjust_order:
                current_amount = float(work.at[idx, "今週傾向後金額"])
                if remaining > 0:
                    work.at[idx, "今週傾向後金額"] = current_amount + step
                    remaining -= step
                    moved = True
                elif remaining < 0 and current_amount - step >= 0:
                    work.at[idx, "今週傾向後金額"] = current_amount - step
                    remaining += step
                    moved = True
                if remaining == 0:
                    break
            if not moved:
                break
    work["ベース配分"] = work["ベース配分"].map(lambda value: f"{int(round(float(value))):,}円")
    work["今週傾向後金額"] = pd.to_numeric(work["今週傾向後金額"], errors="coerce").fillna(0.0).map(
        lambda value: f"{int(round(float(value))):,}円"
    )
    work["傾向倍率"] = pd.to_numeric(work["傾向倍率"], errors="coerce").map(
        lambda value: "-" if pd.isna(value) else f"{float(value):.2f}x"
    )
    keep_cols = ["券種", "買い目", "ベース配分", "今週傾向後金額", "傾向倍率", "今週方針", "今週根拠"]
    keep_cols = [col for col in keep_cols if col in work.columns]
    return work[keep_cols].reset_index(drop=True)


def _build_analog_strategy_snapshot(bias_df: pd.DataFrame) -> Dict[str, str]:
    if bias_df.empty or "券種" not in bias_df.columns or "型補正倍率" not in bias_df.columns:
        return {
            "style": "-",
            "main_bets": "-",
            "sub_bets": "-",
            "caution": "-",
        }
    work = bias_df.copy()
    work["型補正倍率_num"] = pd.to_numeric(work["型補正倍率"], errors="coerce")
    work = work[work["型補正倍率_num"].notna()].copy()
    if work.empty:
        return {
            "style": "-",
            "main_bets": "-",
            "sub_bets": "-",
            "caution": "-",
        }
    ranked = work.sort_values(["型補正倍率_num", "券種"], ascending=[False, True]).reset_index(drop=True)
    top_bets = ranked.loc[ranked["型補正倍率_num"] >= 1.08, "券種"].astype(str).tolist()
    if not top_bets:
        top_bets = ranked.head(2)["券種"].astype(str).tolist()
    low_bets = ranked.loc[ranked["型補正倍率_num"] <= 0.92, "券種"].astype(str).tolist()
    style = "バランス"
    top_set = set(top_bets)
    if top_set & {"単勝", "馬単", "三連単"}:
        style = "頭狙い"
    if top_set & {"複勝", "ワイド", "三連複"} and not (top_set & {"単勝", "馬単", "三連単"}):
        style = "連下寄り"
    if len(top_set & {"単勝", "馬単", "三連単"}) > 0 and len(top_set & {"複勝", "ワイド", "三連複"}) > 0:
        style = "二刀流"
    return {
        "style": style,
        "main_bets": " / ".join(top_bets[:3]) if top_bets else "-",
        "sub_bets": " / ".join(ranked.head(5)["券種"].astype(str).tolist()[3:5]) or "-",
        "caution": " / ".join(low_bets[:3]) if low_bets else "特になし",
    }


def _build_mark_analog_profile_table(
    analog_table: pd.DataFrame,
    mark_items: List[Dict[str, str]],
    budget_plan_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    empty_cols = ["印", "馬", "勝ち切り型", "連下型", "凡走型", "向く買い方", "使い方メモ", "推奨金額目安", "資金寄せ"]
    if analog_table.empty or not mark_items:
        return pd.DataFrame(columns=empty_cols)
    target_marks = [item for item in mark_items if _to_text(item.get("mark", "")) in {"◎", "○", "▲"}]
    if not target_marks:
        return pd.DataFrame(columns=empty_cols)

    rows: List[Dict[str, Any]] = []
    for item in target_marks:
        horse_name = _to_text(item.get("horse", ""))
        plain_horse_name = _strip_gate_prefix(horse_name)
        budget_summary = _build_mark_budget_summary(budget_plan_df, plain_horse_name)
        candidates = analog_table[analog_table["対象馬"].map(_to_text) == plain_horse_name].copy()
        if candidates.empty:
            rows.append(
                {
                    "印": _to_text(item.get("mark", "-")),
                    "馬": horse_name or "-",
                    "勝ち切り型": "0%",
                    "連下型": "0%",
                    "凡走型": "0%",
                    "向く買い方": "-",
                    "使い方メモ": "類似個体データ不足",
                    "推奨金額目安": budget_summary.get("amount_text", "-"),
                    "資金寄せ": budget_summary.get("focus_text", "配分データなし"),
                }
            )
            continue
        counts = candidates["参照型"].fillna("").astype(str).value_counts()
        total = max(1, int(counts.sum()))
        win_share = int(round((counts.get("勝ち切り型", 0) / total) * 100))
        place_share = int(round((counts.get("連下型", 0) / total) * 100))
        poor_share = int(round((counts.get("凡走型", 0) / total) * 100))
        if win_share >= max(place_share, poor_share):
            bet_text = "単勝 / 馬単 / 三連単1着軸"
            note = "頭固定寄りで攻めやすい"
        elif place_share >= max(win_share, poor_share):
            bet_text = "複勝 / ワイド / 三連複軸"
            note = "相手本線や連下で安定寄り"
        else:
            bet_text = "押さえ / 相手薄め / 見送り"
            note = "人気なら評価を下げて使う"
        rows.append(
            {
                "印": _to_text(item.get("mark", "-")),
                "馬": horse_name or plain_horse_name or "-",
                "勝ち切り型": f"{win_share}%",
                "連下型": f"{place_share}%",
                "凡走型": f"{poor_share}%",
                "向く買い方": bet_text,
                "使い方メモ": note,
                "推奨金額目安": budget_summary.get("amount_text", "-"),
                "資金寄せ": budget_summary.get("focus_text", "配分データなし"),
            }
        )
    return pd.DataFrame(rows)


def _render_mark_bet_cards_html(mark_profile_df: pd.DataFrame) -> str:
    if mark_profile_df.empty:
        return ""
    class_map = {"◎": "primary", "○": "rival", "▲": "longshot"}
    cards: List[str] = []
    for _, row in mark_profile_df.iterrows():
        mark = _to_text(row.get("印", "-"))
        horse = _to_text(row.get("馬", "-"))
        bet_text = _to_text(row.get("向く買い方", "-"))
        note = _to_text(row.get("使い方メモ", "-"))
        profile_text = " / ".join(
            [
                f"勝ち切り {_to_text(row.get('勝ち切り型', '-'))}",
                f"連下 {_to_text(row.get('連下型', '-'))}",
                f"凡走 {_to_text(row.get('凡走型', '-'))}",
            ]
        )
        cards.append(
            """
<div class="mark-bet-card {class_name}">
  <div class="mark-bet-mark">{mark}</div>
  <div class="mark-bet-horse">{horse}</div>
  <div class="mark-bet-note">{profile}</div>
  <div class="mark-bet-picks"><strong>推奨金額目安</strong> {amount}</div>
  <div class="mark-bet-note">資金の寄せ方: {focus}</div>
  <div class="mark-bet-picks"><strong>推奨券種</strong> {bets}</div>
  <div class="mark-bet-note">{note}</div>
</div>
""".format(
                class_name=html_escape(class_map.get(mark, "rival")),
                mark=html_escape(mark),
                horse=html_escape(horse),
                profile=html_escape(profile_text),
                amount=html_escape(_to_text(row.get("推奨金額目安", "-"))),
                focus=html_escape(_to_text(row.get("資金寄せ", "-"))),
                bets=html_escape(bet_text),
                note=html_escape(note),
            )
        )
    return "<div class='mark-bet-grid'>" + "".join(cards) + "</div>"


def _classify_target_profile_type(
    history_df: pd.DataFrame,
    entries_df: pd.DataFrame,
    *,
    horse_name: str,
    venue: Any,
    track_condition: Any,
    distance: Any,
) -> str:
    horse_text = _to_text(horse_name)
    if history_df.empty or not horse_text or "horse" not in history_df.columns or "finish" not in history_df.columns:
        return "-"
    history = history_df.copy()
    history["horse"] = history["horse"].map(_to_text)
    direct = history[history["horse"] == horse_text].copy()
    target_venue = _to_text(venue)
    target_track = _to_text(track_condition)
    target_distance = pd.to_numeric(pd.Series([distance]), errors="coerce").iloc[0]

    def _classify_from_rows(rows: pd.DataFrame) -> str:
        if rows.empty:
            return "-"
        rows = rows.copy()
        rows["finish_num"] = pd.to_numeric(rows.get("finish", rows.get("finish_num")), errors="coerce")
        rows["distance_num"] = pd.to_numeric(rows.get("distance", rows.get("distance_num")), errors="coerce")
        rows["score"] = 1.0
        if target_venue and "venue" in rows.columns:
            rows["score"] += rows["venue"].map(lambda value: 1.2 if _to_text(value) == target_venue else 0.0)
        if target_track and "track_condition" in rows.columns:
            rows["score"] += rows["track_condition"].map(lambda value: 0.8 if _to_text(value) == target_track else 0.0)
        if pd.notna(target_distance) and "distance_num" in rows.columns:
            rows["score"] += (1.0 - (rows["distance_num"].sub(float(target_distance)).abs() / 1200.0)).clip(lower=0.0).fillna(0.0)
        rows = rows.sort_values(["score"], ascending=False).head(6)
        win_score = float(rows.loc[rows["finish_num"] == 1.0, "score"].sum())
        place_score = float(rows.loc[(rows["finish_num"] > 1.0) & (rows["finish_num"] <= 3.0), "score"].sum())
        poor_score = float(rows.loc[rows["finish_num"] > 3.0, "score"].sum())
        if win_score >= max(place_score, poor_score) and win_score > 0:
            return "勝ち切り"
        if place_score >= max(win_score, poor_score) and place_score > 0:
            return "連下"
        if poor_score > 0:
            return "凡走注意"
        return "-"

    direct_type = _classify_from_rows(direct)
    if direct_type != "-":
        return direct_type

    analog_table = _build_target_horse_analog_table(
        history_df,
        entries_df,
        target_horses=[horse_text],
        venue=venue,
        track_condition=track_condition,
        distance=distance,
        analogs_per_horse=3,
    )
    if analog_table.empty:
        return "-"
    counts = analog_table["参照型"].fillna("").astype(str).value_counts()
    if counts.empty:
        return "-"
    best_type = counts.index.tolist()[0]
    return {"勝ち切り型": "勝ち切り", "連下型": "連下", "凡走型": "凡走注意"}.get(_to_text(best_type), "-")


def _build_weekly_mark_type_summary(
    row: pd.Series,
    *,
    history_df: pd.DataFrame,
    entries_df: pd.DataFrame,
) -> str:
    race_id = _to_text(row.get("race_id", row.get("レースID", "")))
    if not race_id or entries_df.empty or "race_id" not in entries_df.columns:
        return "-"
    race_entries = entries_df[entries_df["race_id"].map(_to_text) == race_id].copy()
    if race_entries.empty:
        return "-"
    mark_values = _infer_weekly_mark_columns(row)
    distance_value = row.get("distance", row.get("距離", ""))
    venue_value = row.get("venue", row.get("開催", ""))
    track_value = row.get("track_condition", row.get("馬場", ""))
    labels = [("◎", _to_text(mark_values.get("◎", ""))), ("○", _to_text(mark_values.get("○", ""))), ("▲", _to_text(mark_values.get("▲", "")))]
    parts: List[str] = []
    for mark, horse_name in labels:
        if not horse_name or horse_name == "-":
            continue
        profile_type = _classify_target_profile_type(
            history_df,
            race_entries,
            horse_name=horse_name,
            venue=venue_value,
            track_condition=track_value,
            distance=distance_value,
        )
        if profile_type != "-":
            parts.append(f"{mark}{profile_type}")
    return " / ".join(parts) if parts else "-"


def _format_weekly_mark_type_badges(value: Any) -> str:
    text = _to_text(value)
    if not text or text == "-":
        return "-"
    parts = [chunk.strip() for chunk in text.split("/") if chunk.strip()]
    badge_parts: List[str] = []
    for part in parts:
        normalized = _to_text(part)
        if normalized.startswith("◎"):
            badge_parts.append(f"🟡{normalized}")
        elif normalized.startswith("○"):
            badge_parts.append(f"🔵{normalized}")
        elif normalized.startswith("▲"):
            badge_parts.append(f"🟠{normalized}")
        else:
            badge_parts.append(f"⚪{normalized}")
    return "  ".join(badge_parts) if badge_parts else "-"


def _format_weekly_buying_style_badges(value: Any) -> str:
    text = _to_text(value)
    if not text or text == "-":
        return "-"
    parts = [chunk.strip() for chunk in text.split("/") if chunk.strip()]
    if not parts:
        return "-"
    stance = parts[0]
    if "ワイド" in stance:
        stance_badge = f"🔵{stance}"
    elif "単勝" in stance or "頭" in stance:
        stance_badge = f"🟡{stance}"
    elif "三連複" in stance:
        stance_badge = f"🟠{stance}"
    elif "複勝" in stance or "保守" in stance:
        stance_badge = f"🟢{stance}"
    else:
        stance_badge = f"⚪{stance}"
    if len(parts) == 1:
        return stance_badge
    return f"{stance_badge}  ⚪{' / '.join(parts[1:3])}"


def _build_strategy_expectation_rows(strategy: Any) -> List[tuple[str, str]]:
    strategy_text = _to_text(strategy)
    if "ワイド" in strategy_text:
        return [("ワイド", "高"), ("複勝", "中"), ("三連複", "中")]
    if "単勝" in strategy_text or "頭" in strategy_text:
        return [("単勝", "高"), ("馬単", "中"), ("三連単", "中")]
    if "三連複" in strategy_text:
        return [("三連複", "高"), ("ワイド", "中"), ("三連単", "中")]
    if "複勝" in strategy_text or "保守" in strategy_text:
        return [("複勝", "高"), ("ワイド", "中"), ("単勝", "低")]
    return [("単勝", "中"), ("ワイド", "中"), ("三連複", "中")]


def _format_strategy_expectation_badges_text(strategy: Any) -> str:
    rows = _build_strategy_expectation_rows(strategy)
    if not rows:
        return "-"
    icon_map = {"高": "🟠", "中": "🟡", "低": "⚪"}
    return " / ".join(
        f"{icon_map.get(level, '⚪')}{bet} {level}"
        for bet, level in rows[:3]
    )


def _render_strategy_expectation_badges_html(strategy: Any) -> str:
    rows = _build_strategy_expectation_rows(strategy)
    if not rows:
        return "<span class='feedback-trend-badge low'>期待度 未算出</span>"
    return "<div class='feedback-trend-badge-row'>" + "".join(
        f"<span class='feedback-trend-badge {'high' if level == '高' else 'mid' if level == '中' else 'low'}'>{html_escape(bet)} {html_escape(level)}</span>"
        for bet, level in rows[:3]
    ) + "</div>"


def _prepare_budget_focus_cards_df(budget_df: pd.DataFrame | None, *, amount_col: str) -> pd.DataFrame:
    if budget_df is None or budget_df.empty:
        return pd.DataFrame()
    out = budget_df.copy()
    if amount_col in out.columns and amount_col != "推奨金額":
        out = out.rename(columns={amount_col: "推奨金額"})
    return out


def _format_budget_basis_label(value: Any) -> str:
    key = _to_text(value)
    return {
        "trend": "今週傾向反映",
        "analog": "類似個体補正",
        "base": "ベース配分",
    }.get(key, "未選択")


def _build_budget_basis_notice_payload(key: Any, summary: Dict[str, Any] | None = None) -> Dict[str, str]:
    normalized = _to_text(key)
    lead_tag = _to_text(summary.get("lead_tag", "")) if isinstance(summary, dict) else ""
    lead_count = int(summary.get("lead_count", 0) or 0) if isinstance(summary, dict) else 0
    payloads = {
        "trend": {
            "title": "今週傾向反映を標準採用中",
            "chip": "配分の見方",
            "detail": "直近の反省傾向をベースに、今週はどの券種へ寄せるかを反映した標準配分です。迷ったらこの配分を起点に見れば大丈夫です。",
            "fit_case": "直近で人気ズレや馬場ズレが続いていて、今週は券種の寄せ方を少し変えたい時。",
            "unfit_case": "まだ結果データが少ない週や、まず素の配分を見て基準線を確認したい時。",
            "level": "success",
        },
        "analog": {
            "title": "類似個体補正を標準採用中",
            "chip": "配分の見方",
            "detail": "近い個体タイプの勝ち切り型・連下型・凡走型を見て、券種ごとの比重を寄せた標準配分です。似た傾向を重視したい時に向きます。",
            "fit_case": "似たコース適性や体重帯の個体が多く、過去の近い勝ち方・負け方を参考にしたい時。",
            "unfit_case": "類似個体のサンプルが薄いレースや、実績差がはっきりしていて補正をかけすぎたくない時。",
            "level": "info",
        },
        "base": {
            "title": "ベース配分を標準採用中",
            "chip": "配分の見方",
            "detail": "補正を入れない素の推奨配分です。まず基準線を見たい時や、補正をかけすぎたくない時の土台として使えます。",
            "fit_case": "まず素の予想を確認したい時、補正前後の差を見比べたい時。",
            "unfit_case": "今週の反省傾向や類似個体の偏りが強く出ていて、券種の寄せ方を変えた方が良い時。",
            "level": "warning",
        },
    }
    payload = dict(payloads.get(normalized, payloads["base"]))
    if normalized == "trend" and lead_tag:
        if lead_tag == "人気ズレ":
            payload["fit_case"] = f"人気ズレが {lead_count} 件で目立つ週。人気サイドの単勝・馬単を抑えて、ワイドや複勝へ寄せたい時。"
            payload["unfit_case"] = "人気の歪みがほとんど見えず、素の序列をそのまま使いたい週。"
        elif lead_tag == "馬場注意":
            payload["fit_case"] = f"馬場注意が {lead_count} 件で多い週。馬場悪化を前提に、安全側の券種へ重心を移したい時。"
            payload["unfit_case"] = "良馬場中心で荒れ方の偏りが弱く、馬場要因で券種を寄せる必要が薄い週。"
        elif lead_tag == "距離注意":
            payload["fit_case"] = f"距離注意が {lead_count} 件で多い週。距離替わりの不確実性を織り込んで三連系を絞りたい時。"
            payload["unfit_case"] = "同距離条件が多く、距離適性の読み違いが少ない週。"
        elif lead_tag == "補正不足":
            payload["fit_case"] = f"補正不足が {lead_count} 件で多い週。開催・馬場・距離の補正を強めて寄せたい時。"
            payload["unfit_case"] = "条件補正が十分効いていて、今週の傾向でさらに寄せる必要が薄い週。"
    elif normalized == "analog" and lead_tag:
        if lead_tag in {"馬場注意", "距離注意", "補正不足"}:
            payload["fit_case"] = f"{lead_tag} が {lead_count} 件で多い週。近い個体の走り方から券種の寄せ方を決めたい時。"
            payload["unfit_case"] = "類似個体サンプルが薄い新条件レースや、極端に実力差が大きいレース。"
    elif normalized == "base" and lead_tag:
        payload["fit_case"] = "まず補正前の基準線を見て、傾向反映との差を比較したい時。"
        payload["unfit_case"] = f"{lead_tag} が {lead_count} 件で目立つ週で、補正なしだと券種の重心がズレやすい時。"
    return payload


def _build_budget_basis_winning_comment(
    row: pd.Series | Dict[str, Any],
    summary: Dict[str, Any] | None = None,
) -> str:
    basis_label = _to_text(row.get("配分基準", ""))
    basis_mode = _to_text(row.get("採用モード", ""))
    top_hit = pd.to_numeric(pd.Series([row.get("本命的中率")]), errors="coerce").iloc[0]
    single_roi = pd.to_numeric(pd.Series([row.get("単勝回収率")]), errors="coerce").iloc[0]
    place_roi = pd.to_numeric(pd.Series([row.get("複勝回収率")]), errors="coerce").iloc[0]
    place_hit = pd.to_numeric(pd.Series([row.get("複勝的中率")]), errors="coerce").iloc[0]

    if pd.notna(single_roi) and float(single_roi) >= 1.0 and pd.notna(top_hit) and float(top_hit) >= 0.33:
        core = "頭で押し切る形が機能していて、単勝まで届いています。"
    elif pd.notna(place_roi) and float(place_roi) >= 1.0:
        core = "連下で拾う形が安定していて、複勝寄りの回収が効いています。"
    elif pd.notna(place_hit) and float(place_hit) >= 0.7:
        core = "大崩れは少なく、複勝やワイドで丁寧に拾いやすい流れです。"
    elif pd.notna(top_hit) and float(top_hit) >= 0.3:
        core = "本命筋はある程度合っていて、券種の寄せ方次第で伸ばせます。"
    else:
        core = "まだ手探り気味で、券種の寄せ方を見直す余地があります。"

    if "今週傾向" in basis_label:
        tail = "反省傾向に合わせた寄せ方がハマりやすい基準です。"
    elif "類似個体" in basis_label:
        tail = "近い個体タイプを参照した寄せ方が効きやすい基準です。"
    elif "ベース" in basis_label:
        tail = "補正を掛けすぎず、素直な基準線で見たい時に向きます。"
    else:
        tail = ""

    if basis_mode == "半自動":
        tail = (tail + " 半自動で追従させる相性も悪くありません。").strip()

    dynamic = ""
    lead_tag = _to_text(summary.get("lead_tag", "")) if isinstance(summary, dict) else ""
    lead_count = int(summary.get("lead_count", 0) or 0) if isinstance(summary, dict) else 0
    if lead_tag == "人気ズレ" and "今週傾向" in basis_label:
        dynamic = f"今週は人気ズレが {lead_count} 件で多く、傾向反映を素直に使いやすい週です。"
    elif lead_tag in {"馬場注意", "距離注意", "補正不足"} and "類似個体" in basis_label:
        dynamic = f"今週は {lead_tag} が {lead_count} 件で多く、類似個体寄りの補正がハマりやすい週です。"
    elif lead_tag and "ベース" in basis_label:
        dynamic = f"今週は {lead_tag} が目立つので、基準線だけで見る時は押さえ気味が向きます。"

    return " ".join(part for part in [core, tail, dynamic] if part).strip()


def _build_budget_basis_bet_guidance(choice_key: Any, summary: Dict[str, Any] | None) -> tuple[List[str], List[str]]:
    key_text = _to_text(choice_key)
    summary_recommended = [_to_text(item) for item in (summary or {}).get("recommended_bets", []) if _to_text(item)]
    summary_avoid = [
        _to_text(item)
        for item in (summary or {}).get("avoid_bets", [])
        if _to_text(item) and _to_text(item) != "見送りなし"
    ]
    lead_tag = _to_text((summary or {}).get("lead_tag", ""))

    if key_text == "trend":
        recommended = summary_recommended[:3] or ["複勝", "ワイド", "馬連"]
        avoid = summary_avoid[:3] or ["単勝", "馬単"]
    elif key_text == "analog":
        if lead_tag in {"馬場注意", "距離注意", "補正不足"}:
            recommended = ["ワイド", "複勝", "三連複"]
            avoid = ["単勝", "三連単"]
        else:
            recommended = ["複勝", "ワイド", "馬連"]
            avoid = ["三連単", "馬単"]
    else:
        recommended = ["単勝", "複勝", "ワイド"]
        avoid = summary_avoid[:2] or ["三連単"]
    return recommended[:3], avoid[:3]


def _apply_budget_basis_from_ui(
    choice_key: Any,
    *,
    summary: Dict[str, Any] | None,
    auto_mode: bool,
    source_label: str,
) -> None:
    key_text = _to_text(choice_key)
    if key_text not in {"trend", "analog", "base"}:
        return
    st.session_state["budget_basis_auto_enabled"] = bool(auto_mode)
    st.session_state["budget_basis_choice"] = key_text
    if auto_mode:
        _persist_budget_basis_preference(auto_enabled=True, auto_choice=key_text)
        notice_payload = _build_budget_basis_notice_payload(key_text, summary)
        _set_ui_notice(
            f"{source_label}: 半自動で `{_format_budget_basis_label(key_text)}` を採用しました",
            title=notice_payload["title"],
            chip="半自動ON",
            detail=notice_payload["detail"],
            fit_case=notice_payload.get("fit_case", ""),
            unfit_case=notice_payload.get("unfit_case", ""),
            level=notice_payload["level"],
        )
    else:
        _persist_budget_basis_preference(auto_enabled=False, manual_choice=key_text)
        notice_payload = _build_budget_basis_notice_payload(key_text, summary)
        _set_ui_notice(
            f"{source_label}: 標準配分を `{_format_budget_basis_label(key_text)}` に切り替えました",
            title=notice_payload["title"],
            chip="標準配分 更新",
            detail=notice_payload["detail"],
            fit_case=notice_payload.get("fit_case", ""),
            unfit_case=notice_payload.get("unfit_case", ""),
            level=notice_payload["level"],
        )
    _request_open_budget_tab()


def _normalize_budget_basis_key(value: Any) -> str:
    text = _to_text(value)
    if text in {"trend", "analog", "base"}:
        return text
    if "今週傾向" in text:
        return "trend"
    if "類似個体" in text:
        return "analog"
    if "ベース" in text:
        return "base"
    return ""


def _extract_auto_agent_basis_hint(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    basis_payload = payload.get("basis_recommendation", {})
    if not isinstance(basis_payload, dict):
        return {}
    basis_key = _normalize_budget_basis_key(basis_payload.get("budget_basis_key", ""))
    if not basis_key:
        return {}
    return {
        "budget_basis_key": basis_key,
        "budget_basis_label": _format_budget_basis_label(basis_key),
        "recommended_bets": [_to_text(item) for item in basis_payload.get("recommended_bets", []) if _to_text(item)],
        "avoid_bets": [_to_text(item) for item in basis_payload.get("avoid_bets", []) if _to_text(item)],
        "reason": _to_text(basis_payload.get("reason", "")),
    }


def _score_budget_basis_performance_row(row: pd.Series | Dict[str, Any]) -> float:
    single_roi = pd.to_numeric(pd.Series([row.get("単勝回収率")]), errors="coerce").iloc[0]
    place_roi = pd.to_numeric(pd.Series([row.get("複勝回収率")]), errors="coerce").iloc[0]
    top_hit = pd.to_numeric(pd.Series([row.get("本命的中率")]), errors="coerce").iloc[0]
    place_hit = pd.to_numeric(pd.Series([row.get("複勝的中率")]), errors="coerce").iloc[0]
    sample_size = pd.to_numeric(pd.Series([row.get("評価済みレース")]), errors="coerce").iloc[0]
    return float(
        (0.48 * (0.0 if pd.isna(single_roi) else float(single_roi)))
        + (0.22 * (0.0 if pd.isna(place_roi) else float(place_roi)))
        + (0.18 * (0.0 if pd.isna(top_hit) else float(top_hit)))
        + (0.08 * (0.0 if pd.isna(place_hit) else float(place_hit)))
        + (0.01 * min(20.0, 0.0 if pd.isna(sample_size) else float(sample_size)))
    )


def _find_best_budget_basis_row(performance_df: pd.DataFrame | None, basis_key: Any) -> Dict[str, Any] | None:
    key_text = _normalize_budget_basis_key(basis_key)
    if performance_df is None or performance_df.empty or not key_text:
        return None
    matching = performance_df[performance_df["配分基準"].map(_normalize_budget_basis_key) == key_text].copy()
    if matching.empty:
        return None
    matching = matching.assign(_score=matching.apply(_score_budget_basis_performance_row, axis=1))
    best = matching.sort_values(["_score", "評価済みレース"], ascending=[False, False]).iloc[0].to_dict()
    best.pop("_score", None)
    return best


def _select_historical_budget_basis(
    performance_df: pd.DataFrame | None,
    available_keys: Iterable[str],
) -> tuple[str, str, Dict[str, Any] | None]:
    keys = {_to_text(item) for item in available_keys if _to_text(item)}
    if performance_df is None or performance_df.empty or not keys:
        return "", "", None
    rows: List[Dict[str, Any]] = []
    for _, row in performance_df.iterrows():
        key = _normalize_budget_basis_key(row.get("配分基準", ""))
        if key not in keys:
            continue
        score = _score_budget_basis_performance_row(row)
        rows.append(
            {
                "key": key,
                "label": _to_text(row.get("配分基準", "")) or _format_budget_basis_label(key),
                "mode": _to_text(row.get("採用モード", "")) or "-",
                "evaluated_races": int(pd.to_numeric(pd.Series([row.get("評価済みレース")]), errors="coerce").fillna(0).iloc[0]),
                "single_roi": pd.to_numeric(pd.Series([row.get("単勝回収率")]), errors="coerce").iloc[0],
                "place_roi": pd.to_numeric(pd.Series([row.get("複勝回収率")]), errors="coerce").iloc[0],
                "top_hit": pd.to_numeric(pd.Series([row.get("本命的中率")]), errors="coerce").iloc[0],
                "score": score,
            }
        )
    if not rows:
        return "", "", None
    rows = sorted(rows, key=lambda item: (item["score"], item["evaluated_races"]), reverse=True)
    best = rows[0]
    reason = (
        f"直近の保存結果では `{best['label']}` / `{best['mode']}` が "
        f"{best['evaluated_races']} レースで "
        f"単勝回収率 {_format_roi_metric(best['single_roi'])} / "
        f"本命勝率 {_format_rate_metric(best['top_hit'])} と相対的に良好です。"
    )
    return _to_text(best["key"]), reason, best


def _build_budget_basis_decision_snapshot(
    summary: Dict[str, Any] | None,
    available_keys: Iterable[str],
    performance_df: pd.DataFrame | None = None,
    agent_hint: Dict[str, Any] | None = None,
    llm_hit_summary: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    keys = {_to_text(item) for item in available_keys if _to_text(item)}
    lead_tag = _to_text(summary.get("lead_tag", "")) if isinstance(summary, dict) else ""
    lead_count = int(summary.get("lead_count", 0) or 0) if isinstance(summary, dict) else 0
    historical_key, historical_reason, historical_best = _select_historical_budget_basis(performance_df, keys)
    agent_key = _normalize_budget_basis_key((agent_hint or {}).get("budget_basis_key", ""))
    agent_reason = _to_text((agent_hint or {}).get("reason", "")) or (
        f"自律レビューでは `{_format_budget_basis_label(agent_key)}` が向くと判断しています。" if agent_key else ""
    )
    llm_hit_key = _normalize_budget_basis_key((llm_hit_summary or {}).get("basis_key", ""))
    llm_hit_segment = _to_text((llm_hit_summary or {}).get("best_segment", ""))
    llm_hit_edge = pd.to_numeric(pd.Series([(llm_hit_summary or {}).get("best_edge")]), errors="coerce").iloc[0]
    llm_hit_reason = (
        f"LLM別軸ヒットでは `{llm_hit_segment}` 型が {_format_signed_rate_metric(llm_hit_edge)} で優勢のため、"
        f" `{_format_budget_basis_label(llm_hit_key)}` を少し重視します。"
        if llm_hit_key and llm_hit_segment and pd.notna(llm_hit_edge)
        else ""
    )

    def _pack_payload(final_key: str, final_reason: str, *, trend_key: str, trend_reason: str, override_used: bool) -> Dict[str, Any]:
        trend_best = _find_best_budget_basis_row(performance_df, trend_key)
        final_best = _find_best_budget_basis_row(performance_df, final_key)
        trend_recommended, trend_avoid = _build_budget_basis_bet_guidance(trend_key, summary)
        historical_recommended, historical_avoid = _build_budget_basis_bet_guidance(historical_key or "base", summary)
        final_recommended, final_avoid = _build_budget_basis_bet_guidance(final_key, summary)
        llm_hit_recommended, llm_hit_avoid = _build_budget_basis_bet_guidance(llm_hit_key or final_key, summary)
        return {
            "trend_key": trend_key,
            "trend_reason": trend_reason,
            "historical_key": historical_key,
            "historical_reason": historical_reason,
            "agent_key": agent_key,
            "agent_reason": agent_reason,
            "llm_hit_key": llm_hit_key,
            "llm_hit_segment": llm_hit_segment,
            "llm_hit_edge": llm_hit_edge,
            "llm_hit_reason": llm_hit_reason,
            "final_key": final_key,
            "final_reason": final_reason,
            "lead_tag": lead_tag,
            "lead_count": lead_count,
            "override_used": override_used,
            "historical_best": historical_best,
            "trend_best": trend_best,
            "final_best": final_best,
            "trend_recommended_bets": trend_recommended,
            "trend_avoid_bets": trend_avoid,
            "historical_recommended_bets": historical_recommended,
            "historical_avoid_bets": historical_avoid,
            "agent_recommended_bets": list((agent_hint or {}).get("recommended_bets", [])) if agent_key else [],
            "agent_avoid_bets": list((agent_hint or {}).get("avoid_bets", [])) if agent_key else [],
            "llm_hit_recommended_bets": llm_hit_recommended,
            "llm_hit_avoid_bets": llm_hit_avoid,
            "final_recommended_bets": final_recommended,
            "final_avoid_bets": final_avoid,
        }

    if not lead_tag or lead_count <= 0:
        if llm_hit_key in keys and pd.notna(llm_hit_edge) and float(llm_hit_edge) >= 0.10 and (
            not historical_key or historical_key == llm_hit_key or historical_best is None
        ):
            return _pack_payload(
                llm_hit_key,
                f"反省傾向の偏りがまだ小さく、{llm_hit_reason}",
                trend_key=llm_hit_key,
                trend_reason="反省傾向の偏りはまだ小さめです。",
                override_used=True,
            )
        if agent_key in keys and (not historical_key or historical_key == agent_key):
            return _pack_payload(
                agent_key,
                f"反省傾向の偏りがまだ小さいため、自律レビューの推奨 `{_format_budget_basis_label(agent_key)}` を優先します。 {agent_reason}",
                trend_key=agent_key,
                trend_reason="反省傾向の偏りはまだ小さめです。",
                override_used=False,
            )
        if historical_key in keys:
            return _pack_payload(
                historical_key,
                f"反省傾向の偏りがまだ小さいので、直近実績が良い `{_format_budget_basis_label(historical_key)}` を優先します。 {historical_reason}",
                trend_key=("base" if "base" in keys else historical_key),
                trend_reason="反省傾向の偏りはまだ小さめです。",
                override_used=False,
            )
        for candidate in ("base", "trend", "analog"):
            if candidate in keys:
                return _pack_payload(
                    candidate,
                    "反省傾向の偏りがまだ小さいので、まずは基準線の配分を使います。",
                    trend_key=candidate,
                    trend_reason="反省傾向の偏りがまだ小さいので、まずは基準線の配分を使います。",
                    override_used=False,
                )
        return _pack_payload(
            "base",
            "基準線の配分を使います。",
            trend_key="base",
            trend_reason="基準線の配分を使います。",
            override_used=False,
        )

    preferred_order: List[str]
    preferred_reason: str
    if lead_tag == "人気ズレ":
        preferred_order = ["trend", "analog", "base"]
        preferred_reason = f"人気ズレが {lead_count} 件で多いので、今週傾向反映を優先します。"
    elif lead_tag in {"馬場注意", "距離注意", "補正不足"}:
        preferred_order = ["analog", "trend", "base"]
        preferred_reason = f"{lead_tag} が {lead_count} 件で多いので、類似個体や条件補正寄りで見ます。"
    else:
        preferred_order = ["trend", "analog", "base"]
        preferred_reason = f"{lead_tag} が {lead_count} 件で目立つため、傾向寄りの配分を使います。"

    fallback_choice = next((candidate for candidate in ("trend", "analog", "base") if candidate in keys), "base")
    trend_choice = next((candidate for candidate in preferred_order if candidate in keys), fallback_choice)
    if not historical_key or historical_key not in keys or historical_best is None:
        if llm_hit_key in keys and llm_hit_key != trend_choice and pd.notna(llm_hit_edge) and float(llm_hit_edge) >= 0.12:
            return _pack_payload(
                llm_hit_key,
                f"{preferred_reason} あわせて {llm_hit_reason}",
                trend_key=trend_choice,
                trend_reason=preferred_reason,
                override_used=True,
            )
        if agent_key in keys and agent_key != trend_choice and lead_count <= 1:
            return _pack_payload(
                agent_key,
                f"{preferred_reason} ただ、自律レビューでは `{_format_budget_basis_label(agent_key)}` を推しているため、今回はそちらも優先します。 {agent_reason}",
                trend_key=trend_choice,
                trend_reason=preferred_reason,
                override_used=True,
            )
        return _pack_payload(
            trend_choice,
            preferred_reason,
            trend_key=trend_choice,
            trend_reason=preferred_reason,
            override_used=False,
        )

    if agent_key in keys and agent_key == historical_key and historical_key != trend_choice:
        return _pack_payload(
            historical_key,
            f"{preferred_reason} さらに自律レビューも `{_format_budget_basis_label(historical_key)}` を支持しているため、今回は実績側へ寄せます。 {historical_reason}",
            trend_key=trend_choice,
            trend_reason=preferred_reason,
            override_used=True,
        )

    if historical_key == trend_choice:
        return _pack_payload(
            trend_choice,
            f"{preferred_reason} {historical_reason}" + (f" {agent_reason}" if agent_key == trend_choice and agent_reason else ""),
            trend_key=trend_choice,
            trend_reason=preferred_reason,
            override_used=False,
        )

    historical_score = float(historical_best.get("score", 0.0) or 0.0)
    sample_size = int(historical_best.get("evaluated_races", 0) or 0)
    comparison_row = None
    if performance_df is not None and not performance_df.empty:
        matching = performance_df[
            performance_df["配分基準"].map(_normalize_budget_basis_key) == trend_choice
        ].copy()
        if not matching.empty:
            matching = matching.assign(_score=matching.apply(_score_budget_basis_performance_row, axis=1))
            comparison_row = matching.sort_values(["_score", "評価済みレース"], ascending=[False, False]).iloc[0]
    comparison_score = _score_budget_basis_performance_row(comparison_row) if comparison_row is not None else 0.0

    if agent_key in keys and agent_key not in {trend_choice, historical_key} and sample_size < 8 and lead_count <= 1:
        return _pack_payload(
            agent_key,
            f"{preferred_reason} 実績サンプルがまだ薄いため、自律レビューの推奨 `{_format_budget_basis_label(agent_key)}` も採用します。 {agent_reason}",
            trend_key=trend_choice,
            trend_reason=preferred_reason,
            override_used=True,
        )

    if (
        llm_hit_key in keys
        and llm_hit_key not in {trend_choice, historical_key}
        and pd.notna(llm_hit_edge)
        and float(llm_hit_edge) >= 0.14
        and sample_size < 12
        and abs(float(historical_score) - float(comparison_score)) < 0.16
    ):
        return _pack_payload(
            llm_hit_key,
            f"{preferred_reason} 直近実績は拮抗しているため、今回は {llm_hit_reason}",
            trend_key=trend_choice,
            trend_reason=preferred_reason,
            override_used=True,
        )

    if sample_size >= 8 and (historical_score - comparison_score) >= 0.18:
        return _pack_payload(
            historical_key,
            f"{preferred_reason} ただ、直近実績では `{_format_budget_basis_label(historical_key)}` の方が明確に良いため、今回はそちらを優先します。 {historical_reason}",
            trend_key=trend_choice,
            trend_reason=preferred_reason,
            override_used=True,
        )
    return _pack_payload(
        trend_choice,
        f"{preferred_reason} 直近実績では `{_format_budget_basis_label(historical_key)}` も好調ですが、今回は今週傾向を優先します。"
        + (f" {llm_hit_reason}" if llm_hit_key == trend_choice and llm_hit_reason else ""),
        trend_key=trend_choice,
        trend_reason=preferred_reason,
        override_used=False,
    )


def _recommend_budget_basis_key(
    summary: Dict[str, Any] | None,
    available_keys: Iterable[str],
    performance_df: pd.DataFrame | None = None,
    agent_hint: Dict[str, Any] | None = None,
    llm_hit_summary: Dict[str, Any] | None = None,
) -> tuple[str, str]:
    payload = _build_budget_basis_decision_snapshot(
        summary,
        available_keys,
        performance_df,
        agent_hint=agent_hint,
        llm_hit_summary=llm_hit_summary,
    )
    return _to_text(payload.get("final_key", "base")) or "base", _to_text(payload.get("final_reason", "")) or "現在の標準配分を使います。"


def _render_budget_basis_decision_cards(
    payload: Dict[str, Any] | None,
    *,
    allow_jump: bool = False,
    button_prefix: str = "basis_decision",
) -> None:
    if not isinstance(payload, dict):
        return
    trend_key = _to_text(payload.get("trend_key", "")) or "-"
    trend_reason = _to_text(payload.get("trend_reason", "")) or "今週傾向データなし"
    historical_key = _to_text(payload.get("historical_key", "")) or "-"
    historical_reason = _to_text(payload.get("historical_reason", "")) or "直近実績データなし"
    final_key = _to_text(payload.get("final_key", "")) or trend_key
    final_reason = _to_text(payload.get("final_reason", "")) or trend_reason
    override_used = bool(payload.get("override_used", False))
    lead_tag = _to_text(payload.get("lead_tag", ""))
    lead_count = int(payload.get("lead_count", 0) or 0)
    trend_value = _format_budget_basis_label(trend_key) if trend_key != "-" else "-"
    trend_chip = f"{lead_tag} {lead_count}件" if lead_tag and lead_count > 0 else "傾向弱め"
    history_value = _format_budget_basis_label(historical_key) if historical_key != "-" else "実績不足"
    final_value = _format_budget_basis_label(final_key) if final_key != "-" else "-"
    final_chip = "実績優先" if override_used else "傾向優先"

    def _metrics_html(row: Dict[str, Any] | None) -> str:
        if not isinstance(row, dict) or not row:
            return ""
        parts: List[str] = []
        eval_count = pd.to_numeric(pd.Series([row.get("評価済みレース", row.get("evaluated_races"))]), errors="coerce").iloc[0]
        if pd.notna(eval_count) and int(float(eval_count)) > 0:
            parts.append(f"<span class='basis-decision-metric'>評価 {int(float(eval_count))}件</span>")
        single_roi = row.get("単勝回収率", row.get("single_roi"))
        place_roi = row.get("複勝回収率", row.get("place_roi"))
        top_hit = row.get("本命的中率", row.get("top_hit"))
        if _format_roi_metric(single_roi) != "-":
            parts.append(f"<span class='basis-decision-metric'>単勝 {_format_roi_metric(single_roi)}</span>")
        if _format_roi_metric(place_roi) != "-":
            parts.append(f"<span class='basis-decision-metric'>複勝 {_format_roi_metric(place_roi)}</span>")
        if _format_rate_metric(top_hit) != "-":
            parts.append(f"<span class='basis-decision-metric'>本命 {_format_rate_metric(top_hit)}</span>")
        if not parts:
            return ""
        return "<div class='basis-decision-metrics'>" + "".join(parts) + "</div>"

    def _bet_badges_html(recommended: Any, avoid: Any) -> str:
        rec_items = [_to_text(item) for item in (recommended or []) if _to_text(item)]
        avoid_items = [_to_text(item) for item in (avoid or []) if _to_text(item)]
        if not rec_items and not avoid_items:
            return ""
        html_parts: List[str] = ["<div class='basis-decision-bet-row'>"]
        html_parts.extend(
            f"<span class='basis-decision-bet-badge prefer'>寄せ {html_escape(item)}</span>"
            for item in rec_items[:2]
        )
        html_parts.extend(
            f"<span class='basis-decision-bet-badge avoid'>抑え {html_escape(item)}</span>"
            for item in avoid_items[:2]
        )
        html_parts.append("</div>")
        return "".join(html_parts)

    trend_metrics_html = _metrics_html(payload.get("trend_best"))
    history_metrics_html = _metrics_html(payload.get("historical_best"))
    final_metrics_html = _metrics_html(payload.get("final_best"))
    trend_bets_html = _bet_badges_html(payload.get("trend_recommended_bets"), payload.get("trend_avoid_bets"))
    history_bets_html = _bet_badges_html(payload.get("historical_recommended_bets"), payload.get("historical_avoid_bets"))
    final_bets_html = _bet_badges_html(payload.get("final_recommended_bets"), payload.get("final_avoid_bets"))
    decision_html = """
<div class="basis-decision-grid">
<div class="basis-decision-card trend">
<div class="basis-decision-title">今週傾向の判断</div>
<div class="basis-decision-value">{trend_value}</div>
<div class="basis-decision-sub">{trend_reason}</div>
{trend_metrics_html}
{trend_bets_html}
<span class="basis-decision-chip">{trend_chip}</span>
</div>
<div class="basis-decision-card history">
<div class="basis-decision-title">直近実績の判断</div>
<div class="basis-decision-value">{history_value}</div>
<div class="basis-decision-sub">{history_reason}</div>
{history_metrics_html}
{history_bets_html}
<span class="basis-decision-chip">保存結果ベース</span>
</div>
<div class="basis-decision-card final">
<div class="basis-decision-title">最終採用</div>
<div class="basis-decision-value">{final_value}</div>
<div class="basis-decision-sub">{final_reason}</div>
{final_metrics_html}
{final_bets_html}
<span class="basis-decision-chip {final_chip_class}">{final_chip}</span>
</div>
</div>
""".format(
            trend_value=html_escape(trend_value),
            trend_reason=html_escape(trend_reason),
            trend_metrics_html=trend_metrics_html,
            trend_bets_html=trend_bets_html,
            trend_chip=html_escape(trend_chip),
            history_value=html_escape(history_value),
            history_reason=html_escape(historical_reason),
            history_metrics_html=history_metrics_html,
            history_bets_html=history_bets_html,
            final_value=html_escape(final_value),
            final_reason=html_escape(final_reason),
            final_metrics_html=final_metrics_html,
            final_bets_html=final_bets_html,
            final_chip=html_escape(final_chip),
            final_chip_class=("override" if override_used else ""),
        )
    st.markdown(decision_html, unsafe_allow_html=True)
    if allow_jump:
        st.caption("おすすめ券種を押すと `買い目提案` タブへ移動します。")
        jump_specs = [
            ("今週傾向", payload.get("trend_recommended_bets", [])),
            ("直近実績", payload.get("historical_recommended_bets", [])),
            ("最終採用", payload.get("final_recommended_bets", [])),
        ]
        jump_cols = st.columns(3, gap="small")
        for idx, (label, bets) in enumerate(jump_specs):
            rec_items = [_to_text(item) for item in (bets or []) if _to_text(item)]
            if not rec_items:
                jump_cols[idx].caption(f"{label}: おすすめなし")
                continue
            jump_cols[idx].caption(label)
            for bet in rec_items[:2]:
                if jump_cols[idx].button(
                    bet,
                    key=f"{button_prefix}_{idx}_{bet}",
                    width="stretch",
                ):
                    _request_open_bets_tab(bet)
                    st.rerun()


def _maybe_notify_budget_basis_decision_change(payload: Dict[str, Any] | None, *, auto_enabled: bool) -> None:
    if not isinstance(payload, dict):
        return
    previous_payload = st.session_state.get("budget_basis_auto_decision_payload")
    final_key = _to_text(payload.get("final_key", "")) or "base"
    override_used = bool(payload.get("override_used", False))
    lead_tag = _to_text(payload.get("lead_tag", ""))
    lead_count = int(payload.get("lead_count", 0) or 0)
    token = "|".join([final_key, "override" if override_used else "trend", lead_tag, str(lead_count)])
    previous = _to_text(st.session_state.get("budget_basis_auto_decision_token", ""))
    st.session_state["budget_basis_auto_decision_token"] = token
    st.session_state["budget_basis_auto_decision_payload"] = dict(payload)
    if not auto_enabled or not previous or previous == token:
        return
    previous_key = previous.split("|", 1)[0] if previous else ""
    final_label = _format_budget_basis_label(final_key)
    previous_label = _format_budget_basis_label(previous_key) if previous_key else "-"
    title = "今回は実績優先に切替" if override_used else "今回は傾向優先で更新"
    chip = "自動判断 更新"
    message = f"半自動判断: `{previous_label}` -> `{final_label}` に更新しました"
    detail = _to_text(payload.get("final_reason", "")) or "半自動判断を更新しました。"
    if isinstance(previous_payload, dict):
        prev_recommended = "/".join([_to_text(item) for item in previous_payload.get("final_recommended_bets", []) if _to_text(item)]) or "-"
        next_recommended = "/".join([_to_text(item) for item in payload.get("final_recommended_bets", []) if _to_text(item)]) or "-"
        prev_avoid = "/".join([_to_text(item) for item in previous_payload.get("final_avoid_bets", []) if _to_text(item)]) or "-"
        next_avoid = "/".join([_to_text(item) for item in payload.get("final_avoid_bets", []) if _to_text(item)]) or "-"
        if prev_recommended != next_recommended or prev_avoid != next_avoid:
            detail = (
                f"{detail} おすすめ券種 {prev_recommended} -> {next_recommended} / "
                f"抑えたい券種 {prev_avoid} -> {next_avoid}"
            )
    _set_ui_notice(
        message,
        title=title,
        chip=chip,
        detail=detail,
        level=("info" if override_used else "success"),
    )


def _strip_gate_prefix(value: Any) -> str:
    text = _to_text(value)
    if not text:
        return ""
    return re.sub(r"^\d+番\s*", "", text).strip()


def _build_mark_budget_summary(budget_plan_df: pd.DataFrame | None, horse_name: Any) -> Dict[str, str]:
    horse_text = _strip_gate_prefix(horse_name)
    if budget_plan_df is None or budget_plan_df.empty or not horse_text:
        return {"amount_text": "-", "focus_text": "配分データなし"}
    if not {"券種", "買い目", "推奨金額"}.issubset(budget_plan_df.columns):
        return {"amount_text": "-", "focus_text": "配分データなし"}

    bucket_totals = {"main": 0.0, "cover": 0.0, "hole": 0.0}
    total_amount = 0.0
    work = budget_plan_df.copy()
    for _, row in work.iterrows():
        bet_type = _to_text(row.get("券種", ""))
        pick_text = _to_text(row.get("買い目", ""))
        amount = pd.to_numeric(pd.Series([row.get("推奨金額")]), errors="coerce").iloc[0]
        if not bet_type or not pick_text or pd.isna(amount) or float(amount) <= 0:
            continue
        tokens = [_strip_gate_prefix(token) for token in pick_text.split("-")]
        tokens = [token for token in tokens if token]
        if horse_text not in tokens and horse_text != _strip_gate_prefix(pick_text):
            continue
        total_amount += float(amount)
        if bet_type in {"単勝", "複勝", "馬連"}:
            bucket_totals["main"] += float(amount)
        elif bet_type in {"ワイド", "馬単"}:
            bucket_totals["cover"] += float(amount)
        else:
            bucket_totals["hole"] += float(amount)
    if total_amount <= 0:
        return {"amount_text": "-", "focus_text": "配分データなし"}
    focus_bucket = max(bucket_totals.items(), key=lambda item: item[1])[0]
    focus_label = {
        "main": "本線寄り",
        "cover": "押さえ寄り",
        "hole": "穴寄り",
    }.get(focus_bucket, "標準")
    return {
        "amount_text": f"{int(round(total_amount)):,}円",
        "focus_text": focus_label,
    }


def _build_race_result_snapshot(history_df: pd.DataFrame, race_id: Any) -> pd.DataFrame:
    race_text = _to_text(race_id)
    if history_df.empty or not race_text or "race_id" not in history_df.columns:
        return pd.DataFrame()
    work = history_df.copy()
    work["race_id"] = work["race_id"].map(_to_text)
    work = work[work["race_id"] == race_text].copy()
    if work.empty or "finish" not in work.columns:
        return pd.DataFrame()
    work["finish_num"] = pd.to_numeric(work["finish"], errors="coerce")
    work["gate_num"] = pd.to_numeric(work.get("gate", pd.Series(index=work.index, dtype=float)), errors="coerce")
    work = work[work["finish_num"].notna()].sort_values(["finish_num", "horse"], ascending=[True, True]).copy()
    if work.empty:
        return pd.DataFrame()
    if "horse" in work.columns:
        work["馬"] = work.apply(
            lambda row: (
                f"{_format_gate_text(row.get('gate_num'))} {_render_name_text(row.get('horse', '-'))}".strip()
                if _format_gate_text(row.get("gate_num")) != "-"
                else _render_name_text(row.get("horse", "-"))
            ),
            axis=1,
        )
    if "jockey" in work.columns:
        work["騎手"] = work["jockey"].map(_to_text).replace("", "-")
    work["着順"] = work["finish_num"].map(lambda x: "-" if pd.isna(x) else int(float(x)))
    cols = [c for c in ["着順", "馬", "騎手"] if c in work.columns]
    return work[cols].head(5).reset_index(drop=True)



def _format_timestamp_text(value: Any) -> str:
    text = _to_text(value)
    if not text:
        return "-"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y/%m/%d %H:%M")
    except Exception:
        return text


def _parse_timestamp_value(value: Any) -> datetime | None:
    text = _to_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _format_age_text(value: Any) -> str:
    dt_value = value if isinstance(value, datetime) else _parse_timestamp_value(value)
    if dt_value is None:
        return "-"
    now_value = datetime.now(dt_value.tzinfo) if dt_value.tzinfo else datetime.now()
    seconds = max(0, int((now_value - dt_value).total_seconds()))
    if seconds < 60:
        return f"{seconds}秒前"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}時間前"
    days = hours // 24
    return f"{days}日前"


def _format_next_run_text(status_payload: Any, config_payload: Any) -> str:
    if not isinstance(config_payload, dict):
        return "-"
    interval_sec = int(config_payload.get("interval_sec", 0) or 0)
    if interval_sec <= 0:
        return "-"
    base_dt = None
    if isinstance(status_payload, dict):
        base_dt = _parse_timestamp_value(status_payload.get("last_completed_at", "")) or _parse_timestamp_value(
            status_payload.get("last_started_at", "")
        )
    if base_dt is None:
        return "-"
    next_dt = base_dt + timedelta(seconds=interval_sec)
    return next_dt.strftime("%Y/%m/%d %H:%M")


def _format_next_run_remaining_text(status_payload: Any, config_payload: Any) -> str:
    if not isinstance(config_payload, dict):
        return "-"
    interval_sec = int(config_payload.get("interval_sec", 0) or 0)
    if interval_sec <= 0:
        return "-"
    base_dt = None
    if isinstance(status_payload, dict):
        base_dt = _parse_timestamp_value(status_payload.get("last_completed_at", "")) or _parse_timestamp_value(
            status_payload.get("last_started_at", "")
        )
    if base_dt is None:
        return "-"
    next_dt = base_dt + timedelta(seconds=interval_sec)
    now_dt = datetime.now(next_dt.tzinfo) if next_dt.tzinfo else datetime.now()
    remaining_sec = int((next_dt - now_dt).total_seconds())
    if remaining_sec <= 0:
        return "まもなく"
    remaining_min = max(1, remaining_sec // 60)
    return f"あと{remaining_min}分"


def _format_file_timestamp(path: Path) -> str:
    if not path.exists():
        return "-"
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y/%m/%d %H:%M")
    except Exception:
        return "-"


def _format_file_age(path: Path) -> str:
    if not path.exists():
        return "-"
    try:
        return _format_age_text(datetime.fromtimestamp(path.stat().st_mtime))
    except Exception:
        return "-"


def _get_file_mtime(path: Path) -> datetime | None:
    if not path.exists():
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except Exception:
        return None


def _get_file_age_hours(path: Path) -> float | None:
    mtime = _get_file_mtime(path)
    if mtime is None:
        return None
    now_value = datetime.now(mtime.tzinfo) if mtime.tzinfo else datetime.now()
    return max(0.0, float((now_value - mtime).total_seconds()) / 3600.0)


def _load_or_refresh_prediction_harness_status(*, force: bool = False) -> Dict[str, Any]:
    status = _read_json_if_exists(PREDICTION_HARNESS_STATUS_PATH) or {}
    generated_at = _parse_timestamp_value(status.get("generated_at", "")) if isinstance(status, dict) else None
    source_paths = [
        WEEKLY_PREDICTIONS_PATH,
        AUTO_ENTRIES_PATH,
        PREDICTION_FEEDBACK_PATH,
        PREDICTION_ARCHIVE_PATH,
    ]
    source_newer = any(
        bool(mtime is not None and (generated_at is None or mtime > generated_at))
        for mtime in (_get_file_mtime(path) for path in source_paths)
    )
    now_for_status = datetime.now(generated_at.tzinfo) if generated_at is not None and generated_at.tzinfo else datetime.now()
    status_stale = bool(generated_at is None or (now_for_status - generated_at).total_seconds() > 15 * 60)
    if force or not status or source_newer or status_stale:
        try:
            return run_free_prediction_harness(DATA_DIR)
        except Exception as exc:
            return {
                "ok": False,
                "free_local": True,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "message": f"無料ハーネス診断失敗: {exc}",
                "planner": {"next_action": "確認", "reason": str(exc), "severity": "error", "skip_actions": []},
            }
    return status


def _build_operation_guide_snapshot(
    *,
    data_mode: str,
    entries_path: Path,
    weekly_predictions_path: Path,
    weights_path: Path,
    feedback_path: Path,
    feedback_summary: Dict[str, Any] | None,
    entries_rows: int = 0,
    weekly_rows: int = 0,
) -> Dict[str, Any]:
    summary = feedback_summary if isinstance(feedback_summary, dict) else {}
    pending_races = int(summary.get("pending_races", 0) or 0)
    upcoming_races = int(summary.get("upcoming_races", 0) or 0)
    evaluated_races = int(summary.get("evaluated_races", 0) or 0)
    entries_age_hours = _get_file_age_hours(entries_path)
    weekly_age_hours = _get_file_age_hours(weekly_predictions_path)
    weights_age_hours = _get_file_age_hours(weights_path)
    entries_mtime = _get_file_mtime(entries_path)
    weekly_mtime = _get_file_mtime(weekly_predictions_path)
    weights_mtime = _get_file_mtime(weights_path)
    feedback_mtime = _get_file_mtime(feedback_path)

    entries_missing = entries_rows <= 0 or not entries_path.exists()
    entries_stale = entries_age_hours is not None and entries_age_hours >= 18
    weekly_missing = weekly_rows <= 0 or not weekly_predictions_path.exists()
    weekly_older_than_entries = bool(entries_mtime and weekly_mtime and weekly_mtime < entries_mtime)
    weekly_stale = bool(weekly_missing or weekly_older_than_entries or (weekly_age_hours is not None and weekly_age_hours >= 18))
    weights_missing = not weights_path.exists()
    learning_stale = bool(
        evaluated_races > 0
        and (
            weights_missing
            or (feedback_mtime is not None and weights_mtime is not None and weights_mtime < feedback_mtime)
        )
    )

    statuses = [
        {
            "label": "情報取得",
            "state": "未取得" if entries_missing else ("更新推奨" if entries_stale else "準備OK"),
            "detail": (
                "まず `最新だけ更新`"
                if entries_missing
                else f"{entries_rows:,}行 / {_format_file_age(entries_path)}"
            ),
        },
        {
            "label": "予想",
            "state": "未作成" if weekly_missing else ("更新推奨" if weekly_stale else "準備OK"),
            "detail": (
                "まず `今週AI予想だけ更新`"
                if weekly_missing
                else f"{weekly_rows:,}レース / {_format_file_age(weekly_predictions_path)}"
            ),
        },
        {
            "label": "結果反映",
            "state": f"{pending_races:,}件待ち" if pending_races > 0 else "反映OK",
            "detail": (
                "`結果取得だけ` で自動確認・採点"
                if pending_races > 0
                else (f"評価済み {evaluated_races:,}件" if evaluated_races > 0 else "レース後に使います")
            ),
        },
        {
            "label": "学習",
            "state": "未学習" if weights_missing else ("再学習推奨" if learning_stale else "準備OK"),
            "detail": (
                "`学習だけ実行`"
                if weights_missing
                else (f"{_format_file_age(weights_path)} / 反映待ちあり" if learning_stale else _format_file_age(weights_path))
            ),
        },
    ]
    all_actions = [
        "最新だけ更新",
        "今週AI予想だけ更新",
        "結果取得だけ",
        "反省再学習だけ",
        "学習だけ実行",
        "結果取得→履歴更新→再学習",
    ]

    if data_mode != "自動取得データ":
        return {
            "category": "入力確認",
            "action_label": "自動取得データを使う",
            "reason": "いまは手動CSVモードです。自動取得の更新ボタンや結果反映を使うなら、自動取得データモードで見るのが分かりやすいです。",
            "steps": [
                "まずデータモードを `自動取得データ` にします。",
                "今週の出走表がなければ `最新だけ更新` を押します。",
                "そのあと `今週AI予想だけ更新` で予想を作ります。",
            ],
            "statuses": statuses,
            "skip_actions": ["学習だけ実行", "反省再学習だけ", "結果取得→履歴更新→再学習"],
        }

    if entries_missing or (entries_stale and weekly_missing):
        return {
            "category": "情報取得",
            "action_label": "最新だけ更新",
            "reason": "今週の出走データがまだ足りません。まず最新情報を取り込むと、そのあと学習や予想の判断がしやすくなります。",
            "steps": [
                "`最新だけ更新` を押して出走表と履歴を取り込みます。",
                "取り込み後に `今週AI予想だけ更新` を押します。",
                "レース後は `結果取得だけ` で成績を反映します。",
            ],
            "statuses": statuses,
            "skip_actions": ["反省再学習だけ", "学習だけ実行", "結果取得→履歴更新→再学習"],
        }

    if pending_races > 0:
        return {
            "category": "結果反映",
            "action_label": "結果取得だけ",
            "reason": f"結果待ちが {pending_races:,} 件あります。今は新しい予想を作る前に、まず実結果を取り込むのが一番効きます。",
            "steps": [
                "`結果取得だけ` で結果待ちレースをまとめて確認し、自動採点します。",
                "外れが増えていたら `反省再学習だけ` を押します。",
                "必要なら最後に `今週AI予想だけ更新` で予想を作り直します。",
            ],
            "statuses": statuses,
            "skip_actions": ["学習だけ実行", "最新だけ更新"],
        }

    if weekly_stale:
        reason_tail = "出走表より予想が古いです。" if weekly_older_than_entries else "今週予想がまだ新しくありません。"
        return {
            "category": "予想更新",
            "action_label": "今週AI予想だけ更新",
            "reason": f"{reason_tail} 今は学習より先に、まず今週の予想を作り直すのが分かりやすい段階です。",
            "steps": [
                "`今週AI予想だけ更新` を押します。",
                "気になる開催は `開催別レース順` で確認します。",
                "レース後に `結果取得だけ`、必要なら `反省再学習だけ` に進みます。",
            ],
            "statuses": statuses,
            "skip_actions": ["学習だけ実行", "結果取得→履歴更新→再学習"],
        }

    if learning_stale and evaluated_races >= 8:
        return {
            "category": "学習",
            "action_label": "反省再学習だけ",
            "reason": f"評価済みレースが {evaluated_races:,} 件あり、結果の反省がまだ重みに反映しきれていません。今は学習を一度かける価値があります。",
            "steps": [
                "`反省再学習だけ` を押します。",
                "終わったら `今週AI予想だけ更新` で予想を更新します。",
                "そのあと `今週AI自動予想` や `先に確認したいレース` を見ます。",
            ],
            "statuses": statuses,
            "skip_actions": ["最新だけ更新", "結果取得→履歴更新→再学習"],
        }

    return {
        "category": "確認",
        "action_label": "予想を見る",
        "reason": "今は大きな更新を急がなくて大丈夫です。情報取得・結果反映・予想はひと通り揃っているので、まずレースを見て判断する段階です。",
        "steps": [
            "`今週AI自動予想` か `開催別レース順` を見ます。",
            "LLMが別軸で見ているレースを先に確認します。",
            f"次の結果待ちは {pending_races:,} 件、今週の未評価レースは {upcoming_races:,} 件です。",
        ],
        "statuses": statuses,
        "skip_actions": all_actions,
    }


def _operation_action_key_from_label(action_label: Any) -> str:
    label = _to_text(action_label)
    return {
        "自動取得データを使う": "switch_auto_mode",
        "最新だけ更新": "latest_only",
        "結果取得だけ": "results_only",
        "今週AI予想だけ更新": "weekly_only",
        "反省再学習だけ": "reflection_only",
        "学習だけ実行": "train_only",
        "結果取得→履歴更新→再学習": "results_train",
        "予想を見る": "open_predictions",
    }.get(label, "")


def _operation_category_style_class(category: Any) -> str:
    text = _to_text(category)
    if text in {"入力確認", "情報取得"}:
        return "acquire"
    if text == "予想更新":
        return "predict"
    if text == "結果反映":
        return "results"
    if text == "学習":
        return "learn"
    return "check"


def _render_operation_status_grid_html(statuses: Any) -> str:
    if not isinstance(statuses, list):
        return ""
    cards: List[str] = []
    for status in statuses[:4]:
        if not isinstance(status, dict):
            continue
        cards.append(
            """
<div class="operation-guide-status">
  <div class="operation-guide-status-label">{label}</div>
  <div class="operation-guide-status-state">{state}</div>
  <div class="operation-guide-status-detail">{detail}</div>
</div>
""".format(
                label=html_escape(_to_text(status.get("label", "-"))),
                state=html_escape(_to_text(status.get("state", "-"))),
                detail=html_escape(_to_text(status.get("detail", "-"))),
            )
        )
    if not cards:
        return ""
    return "<div class='operation-guide-status-grid'>" + "".join(cards) + "</div>"


def _render_operation_skip_actions_html(skip_actions: Any) -> str:
    if not isinstance(skip_actions, list):
        return ""
    items = [_to_text(item) for item in skip_actions if _to_text(item)]
    if not items:
        return ""
    return "<div class='llm-hit-badge-row'>" + "".join(
        f"<span class='llm-hit-badge avoid neutral'>今は不要 {html_escape(item)}</span>"
        for item in items[:4]
    ) + "</div>"


def _build_operation_snapshot_signature(snapshot: Dict[str, Any] | None) -> str:
    if not isinstance(snapshot, dict):
        return ""
    action_label = _to_text(snapshot.get("action_label", ""))
    status_parts = []
    for status in snapshot.get("statuses", [])[:4]:
        if not isinstance(status, dict):
            continue
        status_parts.append(f"{_to_text(status.get('label', ''))}:{_to_text(status.get('state', ''))}")
    return "|".join([action_label, *status_parts])


def _maybe_queue_llm_hands_free_action(
    snapshot: Dict[str, Any] | None,
    *,
    enabled: bool,
    data_mode: str,
    auto_ready: bool,
) -> None:
    if not enabled or not isinstance(snapshot, dict) or not snapshot:
        st.session_state.pop("llm_hands_free_last_signature", None)
        return
    action_label = _to_text(snapshot.get("action_label", ""))
    action_key = _operation_action_key_from_label(action_label)
    category = _to_text(snapshot.get("category", "")) or "確認"
    reason = _to_text(snapshot.get("reason", ""))
    if not action_key:
        return
    signature = _build_operation_snapshot_signature(snapshot)
    if signature and signature == _to_text(st.session_state.get("llm_hands_free_last_signature", "")):
        return
    if action_key == "open_predictions":
        return
    if action_key == "switch_auto_mode":
        if data_mode != "自動取得データ":
            st.session_state["llm_hands_free_last_signature"] = signature
            st.session_state["data_mode_selector"] = "自動取得データ"
            _append_llm_hands_free_history(
                action_label=action_label,
                action_key=action_key,
                category=category,
                reason=reason,
                status="switched_mode",
                data_mode=data_mode,
                signature=signature,
            )
            _set_ui_notice("LLMおまかせで `自動取得データ` に切り替えました。", level="info")
            st.rerun()
        return
    if not auto_ready and action_key in {"latest_only", "results_only", "weekly_only", "reflection_only", "train_only", "results_train"}:
        return
    st.session_state["llm_hands_free_last_signature"] = signature
    _set_llm_hands_free_active_action(
        action_label=action_label,
        action_key=action_key,
        category=category,
        reason=reason,
        data_mode=data_mode,
        signature=signature,
    )
    st.session_state["queued_operation_action"] = action_key
    _append_llm_hands_free_history(
        action_label=action_label,
        action_key=action_key,
        category=category,
        reason=reason,
        status="queued",
        data_mode=data_mode,
        signature=signature,
    )
    _set_ui_notice(f"LLMおまかせで `{action_label}` を自動実行します。", level="info")
    st.rerun()


def _queue_operation_action(action_label: Any) -> None:
    action_key = _operation_action_key_from_label(action_label)
    if not action_key:
        return
    if action_key == "switch_auto_mode":
        st.session_state["data_mode_selector"] = "自動取得データ"
        _set_ui_notice("読み込み方法を `自動取得データ` に切り替えました。")
        st.rerun()
    if action_key == "open_predictions":
        _request_open_home_predictions()
        _set_ui_notice("予想ホームの予想一覧へ移動します。")
        st.rerun()
    st.session_state["queued_operation_action"] = action_key
    st.rerun()


def _render_operation_guide(snapshot: Dict[str, Any] | None) -> None:
    if not isinstance(snapshot, dict) or not snapshot:
        return
    st.subheader("次にやること")
    category = _to_text(snapshot.get("category", "")) or "確認"
    action_label = _to_text(snapshot.get("action_label", "")) or "-"
    category_class = _operation_category_style_class(category)
    status_grid_html = _render_operation_status_grid_html(snapshot.get("statuses", []))
    st.markdown(
        """
<div class="operation-guide-card {category_class}">
  <div class="operation-guide-chip {category_class}">いま優先 / {category}</div>
  <div class="operation-guide-title">{action_label}</div>
  <div class="operation-guide-reason">{reason}</div>
  {status_grid_html}
</div>
""".format(
            category_class=html_escape(category_class),
            category=html_escape(category),
            action_label=html_escape(action_label),
            reason=html_escape(_to_text(snapshot.get("reason", "")) or "次の操作はここに出ます。"),
            status_grid_html=status_grid_html,
        ),
        unsafe_allow_html=True,
    )
    steps = [step for step in snapshot.get("steps", []) if _to_text(step)]
    if steps:
        st.caption("迷ったらこの順番")
        for index, step in enumerate(steps, start=1):
            st.markdown(f"<div class='operation-guide-step'>{index}. {html_escape(step)}</div>", unsafe_allow_html=True)
    skip_actions_html = _render_operation_skip_actions_html(snapshot.get("skip_actions", []))
    if skip_actions_html:
        st.caption("今は押さなくていいボタン")
        st.markdown(skip_actions_html, unsafe_allow_html=True)
    primary_action_label = action_label
    if primary_action_label and primary_action_label != "-":
        button_label = "いまやる: " + (
            "予想ホームを見る" if primary_action_label == "予想を見る" else primary_action_label
        )
        if st.button(button_label, key=f"operation_guide_{_operation_action_key_from_label(primary_action_label) or 'primary'}", width="stretch"):
            _queue_operation_action(primary_action_label)


def _format_toggle_label(value: Any) -> str:
    text = _to_text(value).lower()
    if text in {"true", "1", "on", "yes"}:
        return "ON"
    if text in {"false", "0", "off", "no"}:
        return "OFF"
    return "-"


def _set_ui_notice(
    message: str,
    *,
    level: str = "success",
    title: str = "",
    chip: str = "",
    detail: str = "",
    fit_case: str = "",
    unfit_case: str = "",
) -> None:
    st.session_state["ui_notice"] = {
        "message": str(message).strip(),
        "level": str(level).strip().lower() or "success",
        "title": _to_text(title),
        "chip": _to_text(chip),
        "detail": _to_text(detail),
        "fit_case": _to_text(fit_case),
        "unfit_case": _to_text(unfit_case),
        "at": datetime.now().isoformat(timespec="seconds"),
    }


def _set_result_sync_summary(
    title: str,
    summary: str,
    delta_text: str = "",
    chip: str = "結果取得だけ 完了",
    basis_key: str = "",
    basis_label: str = "",
    basis_mode: str = "",
    basis_delta_text: str = "",
    race_items: List[Dict[str, str]] | None = None,
) -> None:
    st.session_state.pop("result_sync_weight_focus", None)
    st.session_state["result_sync_summary"] = {
        "title": _to_text(title),
        "summary": _to_text(summary),
        "delta_text": _to_text(delta_text),
        "chip": _to_text(chip) or "結果取得だけ 完了",
        "basis_key": _to_text(basis_key),
        "basis_label": _to_text(basis_label),
        "basis_mode": _to_text(basis_mode),
        "basis_delta_text": _to_text(basis_delta_text),
        "race_items": [
            {
                "race_id": _to_text(item.get("race_id", "")),
                "label": _to_text(item.get("label", "")),
                "status": _to_text(item.get("status", "")),
                "winner": _to_text(item.get("winner", "")),
                "top_horse": _to_text(item.get("top_horse", "")),
                "hit_bets": _to_text(item.get("hit_bets", "")),
                "miss_reason": _to_text(item.get("miss_reason", "")),
                "miss_tags": _to_text(item.get("miss_tags", "")),
                "avoid_bets": _to_text(item.get("avoid_bets", "")),
                "preferred_bets": _to_text(item.get("preferred_bets", "")),
            }
            for item in (race_items or [])
            if isinstance(item, dict) and (_to_text(item.get("race_id", "")) or _to_text(item.get("label", "")))
        ],
        "at": datetime.now().isoformat(timespec="seconds"),
    }


def _set_result_sync_weight_focus(table: pd.DataFrame | None, *, mode_label: str) -> None:
    if table is None or table.empty:
        st.session_state.pop("result_sync_weight_focus", None)
        return
    strong_table, weak_table = _build_weight_change_focus_tables(table, limit=4)
    st.session_state["result_sync_weight_focus"] = {
        "mode_label": _to_text(mode_label) or "反省再学習だけ",
        "strong": strong_table.to_dict(orient="records") if not strong_table.empty else [],
        "weak": weak_table.to_dict(orient="records") if not weak_table.empty else [],
        "at": datetime.now().isoformat(timespec="seconds"),
    }


def _render_result_sync_weight_focus() -> None:
    payload = st.session_state.get("result_sync_weight_focus")
    if not isinstance(payload, dict):
        return
    strong_rows = payload.get("strong", [])
    weak_rows = payload.get("weak", [])
    if not isinstance(strong_rows, list):
        strong_rows = []
    if not isinstance(weak_rows, list):
        weak_rows = []
    if not strong_rows and not weak_rows:
        return

    def _lines_html(rows: List[Dict[str, Any]], empty_text: str) -> str:
        if not rows:
            return f"<div class='result-sync-weight-line'>{html_escape(empty_text)}</div>"
        lines: List[str] = []
        for row in rows:
            feature = _to_text(row.get("特徴量", "")) or "-"
            diff_num = pd.to_numeric(pd.Series([row.get("差分")]), errors="coerce").iloc[0]
            ratio_num = pd.to_numeric(pd.Series([row.get("倍率")]), errors="coerce").iloc[0]
            diff_text = "-" if pd.isna(diff_num) else f"{float(diff_num):+.3f}"
            ratio_text = "" if pd.isna(ratio_num) else f" / {float(ratio_num):.2f}x"
            lines.append(
                f"<div class='result-sync-weight-line'><strong>{html_escape(feature)}</strong><br>{html_escape(diff_text + ratio_text)}</div>"
            )
        return "".join(lines)

    mode_label = _to_text(payload.get("mode_label", "")) or "反省再学習だけ"
    age_text = _format_age_text(payload.get("at", ""))
    st.caption(f"{mode_label} 後の重み変化" + (f" ({age_text})" if age_text != "-" else ""))
    st.markdown(
        """
<div class="result-sync-weight-grid">
  <div class="result-sync-weight-card strong">
    <div class="result-sync-weight-title">強化された要素</div>
    {strong}
  </div>
  <div class="result-sync-weight-card weak">
    <div class="result-sync-weight-title">抑えた要素</div>
    {weak}
  </div>
</div>
""".format(
            strong=_lines_html(strong_rows, "強化なし"),
            weak=_lines_html(weak_rows, "抑制なし"),
        ),
        unsafe_allow_html=True,
    )


def _render_ui_notice() -> None:
    payload = st.session_state.get("ui_notice")
    if not isinstance(payload, dict):
        return
    message = _to_text(payload.get("message", ""))
    if not message:
        return
    age_text = _format_age_text(payload.get("at", ""))
    body = message if age_text == "-" else f"{message} ({age_text})"
    level = _to_text(payload.get("level", "success"))
    title = _to_text(payload.get("title", ""))
    chip = _to_text(payload.get("chip", ""))
    detail = _to_text(payload.get("detail", ""))
    fit_case = _to_text(payload.get("fit_case", ""))
    unfit_case = _to_text(payload.get("unfit_case", ""))
    if title or chip or detail or fit_case or unfit_case:
        age_line = f"反映: {age_text}" if age_text != "-" else "反映直後"
        summary_line = detail or message
        case_html = ""
        if fit_case or unfit_case:
            case_html = """
<div class="ui-notice-cases">
  {fit_html}
  {unfit_html}
</div>
""".format(
                fit_html=(
                    """
<div class="ui-notice-case fit">
  <span class="ui-notice-case-label">向くケース</span>
  <div class="ui-notice-case-text">{text}</div>
</div>
""".format(text=html_escape(fit_case))
                    if fit_case
                    else ""
                ),
                unfit_html=(
                    """
<div class="ui-notice-case unfit">
  <span class="ui-notice-case-label">向かないケース</span>
  <div class="ui-notice-case-text">{text}</div>
</div>
""".format(text=html_escape(unfit_case))
                    if unfit_case
                    else ""
                ),
            )
        st.markdown(
            """
<div class="ui-notice-card {level}">
  {chip_html}
  <div class="ui-notice-title">{title}</div>
  <div class="ui-notice-sub">{summary}<br>{age}</div>
  {case_html}
</div>
""".format(
                level=html_escape(level if level in {"success", "info", "warning", "error"} else "success"),
                chip_html=(
                    f"<span class='ui-notice-chip'>{html_escape(chip)}</span>" if chip else ""
                ),
                title=html_escape(title or message),
                summary=html_escape(summary_line),
                age=html_escape(age_line),
                case_html=case_html,
            ),
            unsafe_allow_html=True,
        )
        return
    if level == "error":
        st.error(body)
    elif level == "warning":
        st.warning(body)
    elif level == "info":
        st.info(body)
    else:
        st.success(body)


def _render_result_sync_summary() -> None:
    payload = st.session_state.get("result_sync_summary")
    if not isinstance(payload, dict):
        return
    title = _to_text(payload.get("title", ""))
    summary = _to_text(payload.get("summary", ""))
    delta_text = _to_text(payload.get("delta_text", ""))
    chip = _to_text(payload.get("chip", "結果取得だけ 完了")) or "結果取得だけ 完了"
    basis_key = _to_text(payload.get("basis_key", ""))
    basis_label = _to_text(payload.get("basis_label", ""))
    basis_mode = _to_text(payload.get("basis_mode", ""))
    basis_delta_text = _to_text(payload.get("basis_delta_text", ""))
    race_items = payload.get("race_items", [])
    if not title and not summary:
        return
    age_text = _format_age_text(payload.get("at", ""))
    age_line = f"反映時刻: {age_text}" if age_text != "-" else "反映直後"
    delta_html = (
        f"<div class='result-sync-delta'><strong>更新差分</strong><br>{html_escape(delta_text)}</div>"
        if delta_text
        else ""
    )
    result_sync_feedback_df = _read_csv_if_exists(PREDICTION_FEEDBACK_PATH)
    result_sync_summary = _build_feedback_trend_summary(result_sync_feedback_df, lookback_days=7)
    result_sync_basis_perf_df = build_budget_basis_performance_table(result_sync_feedback_df)
    result_sync_llm_perf_df = build_llm_disagreement_performance_table(result_sync_feedback_df)
    result_sync_llm_hit_summary = _build_llm_hit_weekly_summary(result_sync_llm_perf_df)
    result_sync_agent_hint = _extract_auto_agent_basis_hint(_read_json_if_exists(AUTO_AGENT_STATUS_PATH))
    result_sync_basis_decision = _build_budget_basis_decision_snapshot(
        result_sync_summary,
        ["trend", "analog", "base"],
        performance_df=result_sync_basis_perf_df,
        agent_hint=result_sync_agent_hint,
        llm_hit_summary=result_sync_llm_hit_summary,
    )
    if not basis_key:
        label_key = _to_text(basis_label)
        if "類似個体" in label_key:
            basis_key = "analog"
        elif "ベース" in label_key:
            basis_key = "base"
        else:
            basis_key = "trend"
    basis_recommended, basis_avoid = _build_budget_basis_bet_guidance(basis_key, result_sync_summary)
    basis_guidance_html = ""
    if basis_recommended or basis_avoid:
        basis_guidance_html = """
<div class='result-sync-basis-guidance'>
  {prefer}
  {avoid}
</div>
""".format(
            prefer=(
                "<div class='result-sync-prefer'>"
                "<span class='result-sync-prefer-label'>この基準ならおすすめ券種</span>"
                + "".join(
                    f"<span class='result-sync-prefer-badge'>{html_escape(bet)}</span>"
                    for bet in basis_recommended
                )
                + "</div>"
            )
            if basis_recommended
            else "",
            avoid=(
                "<div class='result-sync-avoid'>"
                "<span class='result-sync-avoid-label'>この基準で抑えたい券種</span>"
                + "".join(
                    f"<span class='result-sync-avoid-badge'>{html_escape(bet)}</span>"
                    for bet in basis_avoid
                )
                + "</div>"
            )
            if basis_avoid
            else "",
        )
    basis_html = (
        """
<div class='result-sync-basis'>
  <div class='result-sync-basis-title'>今回の配分基準</div>
  <div class='result-sync-basis-text'>{basis}</div>
  <div class='result-sync-basis-text'>{delta}</div>
  {guidance}
</div>
""".format(
            basis=html_escape(" / ".join(part for part in [basis_label, basis_mode] if part) or "-"),
            delta=html_escape(basis_delta_text),
            guidance=basis_guidance_html,
        )
        if basis_label or basis_mode or basis_delta_text
        else ""
    )
    list_html = ""
    rendered_items: List[Dict[str, str]] = []
    if isinstance(race_items, list):
        rendered_items = [
            {
                "race_id": _to_text(item.get("race_id", "")),
                "label": _to_text(item.get("label", "")),
                "status": _to_text(item.get("status", "")),
                "winner": _to_text(item.get("winner", "")),
                "top_horse": _to_text(item.get("top_horse", "")),
                "hit_bets": _to_text(item.get("hit_bets", "")),
                "miss_reason": _to_text(item.get("miss_reason", "")),
                "miss_tags": _to_text(item.get("miss_tags", "")),
                "avoid_bets": _to_text(item.get("avoid_bets", "")),
                "preferred_bets": _to_text(item.get("preferred_bets", "")),
            }
            for item in race_items
            if isinstance(item, dict) and (_to_text(item.get("label", "")) or _to_text(item.get("race_id", "")))
        ]
        if rendered_items:
            def _bet_badges_html(hit_bets_text: str) -> str:
                label_map = {
                    "単勝": "single",
                    "複勝": "place",
                    "馬連": "combo",
                    "ワイド": "combo",
                    "馬単": "exacta",
                    "三連複": "trio",
                    "三連単": "trifecta",
                }
                parts = [part.strip() for part in hit_bets_text.split("/") if part.strip()]
                if not parts or hit_bets_text == "的中なし":
                    return "<span class='result-sync-badge trifecta'>的中なし</span>"
                return "".join(
                    f"<span class='result-sync-badge {label_map.get(part, 'combo')}'>{html_escape(part)}</span>"
                    for part in parts
                )

            def _items_html(items: List[Dict[str, str]]) -> str:
                def _miss_tags_html(tags_text: str) -> str:
                    tag_parts = [part.strip() for part in tags_text.split("/") if part.strip()]
                    if not tag_parts:
                        return ""
                    def _tag_class(tag: str) -> str:
                        if "人気" in tag:
                            return "pop"
                        if "馬場" in tag:
                            return "track"
                        if "距離" in tag:
                            return "distance"
                        return "adjust"
                    return "<div class='result-sync-tag-row'>" + "".join(
                        f"<span class='result-sync-tag {_tag_class(tag)}'>{html_escape(tag)}</span>"
                        for tag in tag_parts
                    ) + "</div>"

                def _avoid_bets_html(bets_text: str) -> str:
                    bet_parts = [part.strip() for part in bets_text.split("/") if part.strip()]
                    if not bet_parts:
                        return ""
                    return (
                        "<div class='result-sync-avoid'>"
                        "<span class='result-sync-avoid-label'>避けたい券種</span>"
                        + "".join(
                            f"<span class='result-sync-avoid-badge'>{html_escape(bet)}</span>"
                            for bet in bet_parts
                        )
                        + "</div>"
                    )

                def _preferred_bets_html(bets_text: str) -> str:
                    bet_parts = [part.strip() for part in bets_text.split("/") if part.strip()]
                    if not bet_parts:
                        return ""
                    return (
                        "<div class='result-sync-prefer'>"
                        "<span class='result-sync-prefer-label'>寄せたい券種</span>"
                        + "".join(
                            f"<span class='result-sync-prefer-badge'>{html_escape(bet)}</span>"
                            for bet in bet_parts
                        )
                        + "</div>"
                    )

                return "".join(
                    (
                        f"<div class='result-sync-list-line {'hit' if _to_text(item.get('status', '')) == '本命ヒット' else 'miss'}'>"
                        f"<strong>{html_escape(_to_text(item.get('status', '-')))}</strong>"
                        f" / {html_escape(_to_text(item.get('label', '-')))}"
                        + (
                            f"<br>勝ち馬: {html_escape(_to_text(item.get('winner', '-')))}"
                            if _to_text(item.get('winner', '')) else ""
                        )
                        + (
                            f" / 本命馬: {html_escape(_to_text(item.get('top_horse', '-')))}"
                            if _to_text(item.get('top_horse', '')) else ""
                        )
                        + (
                            _miss_tags_html(_to_text(item.get("miss_tags", "")))
                            if _to_text(item.get("status", "")) != "本命ヒット" and _to_text(item.get("miss_tags", ""))
                            else ""
                        )
                        + (
                            f"<div class='result-sync-reason'>{html_escape(_to_text(item.get('miss_reason', '')))}</div>"
                            if _to_text(item.get("status", "")) != "本命ヒット" and _to_text(item.get("miss_reason", ""))
                            else ""
                        )
                        + (
                            _preferred_bets_html(_to_text(item.get("preferred_bets", "")))
                            if _to_text(item.get("status", "")) != "本命ヒット" and _to_text(item.get("preferred_bets", ""))
                            else ""
                        )
                        + (
                            _avoid_bets_html(_to_text(item.get("avoid_bets", "")))
                            if _to_text(item.get("status", "")) != "本命ヒット" and _to_text(item.get("avoid_bets", ""))
                            else ""
                        )
                        + f"<div class='result-sync-badges'>{_bet_badges_html(_to_text(item.get('hit_bets', '')))}</div>"
                        + "</div>"
                    )
                    for item in items
                )

            visible_items = rendered_items[:6]
            hit_items = [item for item in visible_items if _to_text(item.get("status", "")) == "本命ヒット"]
            miss_items = [item for item in visible_items if _to_text(item.get("status", "")) != "本命ヒット"]
            extra = len(rendered_items) - len(visible_items)
            blocks: List[str] = []
            if hit_items:
                blocks.append(
                    "<div class='result-sync-list'>"
                    "<div class='result-sync-list-title'>本命ヒット</div>"
                    f"{_items_html(hit_items)}"
                    "</div>"
                )
            if miss_items:
                blocks.append(
                    "<div class='result-sync-list'>"
                    "<div class='result-sync-list-title'>本命外れ</div>"
                    f"{_items_html(miss_items)}"
                    "</div>"
                )
            if extra > 0:
                blocks.append(
                    "<div class='result-sync-list'>"
                    f"<div class='result-sync-list-line'>- ほか {extra} レース</div>"
                    "</div>"
                )
            list_html = "".join(blocks)
    st.markdown(
        (
            "<div class='result-sync-card'>"
            f"<span class='result-sync-chip'>{html_escape(chip)}</span>"
            f"<div class='result-sync-title'>{html_escape(title)}</div>"
            f"<div class='result-sync-sub'>{html_escape(summary)}<br>{html_escape(age_line)}</div>"
            f"{delta_html}"
            f"{basis_html}"
            f"{list_html}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    st.caption("結果反映後の半自動判断")
    _render_llm_hit_weekly_card(
        result_sync_llm_hit_summary,
        trend_summary=result_sync_summary,
        allow_apply=True,
        button_prefix="result_sync_llm_hit",
    )
    _render_budget_basis_decision_cards(result_sync_basis_decision, allow_jump=True, button_prefix="result_sync_basis")
    result_sync_basis_cols = st.columns(4, gap="small")
    current_basis_key = _to_text(st.session_state.get("budget_basis_choice", "trend")) or "trend"
    current_auto_mode = bool(st.session_state.get("budget_basis_auto_enabled", True))
    auto_basis_key = _to_text(result_sync_basis_decision.get("final_key", "base")) or "base"
    if result_sync_basis_cols[0].button(
        "今週傾向へ切替",
        key="result_sync_apply_trend",
        width="stretch",
        disabled=(not current_auto_mode and current_basis_key == "trend"),
    ):
        _apply_budget_basis_from_ui("trend", summary=result_sync_summary, auto_mode=False, source_label="結果取得カード")
        st.rerun()
    if result_sync_basis_cols[1].button(
        "類似個体へ切替",
        key="result_sync_apply_analog",
        width="stretch",
        disabled=(not current_auto_mode and current_basis_key == "analog"),
    ):
        _apply_budget_basis_from_ui("analog", summary=result_sync_summary, auto_mode=False, source_label="結果取得カード")
        st.rerun()
    if result_sync_basis_cols[2].button(
        "ベースへ切替",
        key="result_sync_apply_base",
        width="stretch",
        disabled=(not current_auto_mode and current_basis_key == "base"),
    ):
        _apply_budget_basis_from_ui("base", summary=result_sync_summary, auto_mode=False, source_label="結果取得カード")
        st.rerun()
    if result_sync_basis_cols[3].button(
        "半自動に戻す",
        key="result_sync_apply_auto",
        width="stretch",
        disabled=(current_auto_mode and current_basis_key == auto_basis_key),
    ):
        _apply_budget_basis_from_ui(auto_basis_key, summary=result_sync_summary, auto_mode=True, source_label="結果取得カード")
        st.rerun()
    st.caption(
        "結果取得カードからそのまま標準配分を切り替えられます。"
        + (f" 現在は `{_format_budget_basis_label(current_basis_key)}` を {'半自動' if current_auto_mode else '手動'} 採用中です。" if current_basis_key else "")
    )
    if rendered_items:
        entries_path = Path(st.session_state.get("auto_entries_path", str(AUTO_ENTRIES_PATH)))
        entries_df = _read_csv_if_exists(entries_path)
        available_race_ids: set[str] = set()
        if isinstance(entries_df, pd.DataFrame) and (not entries_df.empty) and "race_id" in entries_df.columns:
            available_race_ids = {
                _to_text(value)
                for value in entries_df["race_id"].tolist()
                if _to_text(value)
            }
        st.caption("今回取得できたレースから詳細予想へ")
        for item in rendered_items[:6]:
            race_id = _to_text(item.get("race_id", ""))
            label = _to_text(item.get("label", race_id)) or race_id or "-"
            status = _to_text(item.get("status", ""))
            winner = _to_text(item.get("winner", ""))
            button_text = " ".join(
                part for part in [status, label] if part
            ).strip()
            button_help = f"勝ち馬: {winner}" if winner else "詳細予想へ移動"
            is_available = bool(race_id and race_id in available_race_ids and isinstance(entries_df, pd.DataFrame))
            row_cols = st.columns([3.6, 1.0], gap="small")
            if row_cols[0].button(
                button_text,
                key=f"result_sync_jump_{race_id}",
                width="stretch",
                disabled=not is_available,
                help=button_help,
            ):
                _request_scroll_to_detail()
                _queue_selected_race_for_prediction(
                    race_id=race_id,
                    source_entries_df=entries_df,
                    label=label,
                )
            row_cols[1].caption("詳細表示" if is_available else "詳細不可")
        miss_items = [item for item in rendered_items if _to_text(item.get("status", "")) != "本命ヒット"]
        if miss_items:
            if st.button("本命外れレースで反省再学習を実行", key="result_sync_reflection_train"):
                try:
                    before_payload = _load_auto_model_payload()
                    with st.status("本命外れレースを使って反省再学習中...", expanded=True) as tune_status:
                        tune_status.write(f"対象 {len(miss_items):,} レースを確認しています")
                        tuning_result = _run_reflection_light_tuning(
                            trials=16,
                            val_races=10,
                            simulations=1000,
                        )
                        tune_status.write(
                            f"対象 {int(tuning_result.get('race_count', 0)):,} レース / "
                            f"{int(tuning_result.get('feature_rows', 0)):,} 行 / "
                            f"反省対象 {int(tuning_result.get('reflection_rows', 0)):,} 行"
                        )
                        tune_status.update(label="反省再学習だけ 完了", state="complete")
                    after_payload = _load_auto_model_payload()
                    weight_change_table = _store_weight_change_table(before_payload, after_payload, mode_label="反省再学習だけ")
                    _set_result_sync_weight_focus(weight_change_table, mode_label="反省再学習だけ")
                    _set_ui_notice(
                        f"反省再学習完了: 対象 {int(tuning_result.get('race_count', 0)):,} レース / "
                        f"反省 {int(tuning_result.get('reflection_rows', 0)):,} 行"
                    )
                    st.success(
                        f"反省再学習完了: 対象 {int(tuning_result.get('race_count', 0)):,} レース / "
                        f"反省 {int(tuning_result.get('reflection_rows', 0)):,} 行"
                    )
                    if not weight_change_table.empty:
                        st.caption("重み変化を保存しました。`アーカイブ > 成績評価` で確認できます。")
                except Exception as exc:
                    st.error(f"反省再学習に失敗しました: {exc}")
            _render_result_sync_weight_focus()


def _request_scroll_to_detail() -> None:
    st.session_state["scroll_to_detail_after_rerun"] = True


def _render_scroll_to_detail_anchor() -> None:
    components.html(
        """
<script>
const anchor = window.parent.document.getElementById("detail-predict-anchor");
if (anchor) {
  anchor.scrollIntoView({behavior: "smooth", block: "start"});
}
</script>
""",
        height=0,
        width=0,
    )


def _render_reload_after_delay(delay_ms: int = 1500) -> None:
    components.html(
        f"""
<script>
setTimeout(() => {{
  window.parent.location.reload();
}}, {int(delay_ms)});
</script>
""",
        height=0,
        width=0,
    )


def _request_open_archive_eval_tab() -> None:
    st.session_state["open_archive_eval_after_rerun"] = True
    st.session_state["archive_detail_loaded"] = True


def _render_open_archive_eval_script() -> None:
    components.html(
        """
<script>
function clickTab(label) {
  const tabs = Array.from(window.parent.document.querySelectorAll('button[role="tab"]'));
  const target = tabs.find((tab) => (tab.innerText || '').trim() === label);
  if (target) {
    target.click();
    return true;
  }
  return false;
}

setTimeout(() => {
  clickTab("アーカイブ");
  setTimeout(() => {
    clickTab("成績評価");
    const anchor = window.parent.document.getElementById("archive-eval-anchor");
    if (anchor) {
      anchor.scrollIntoView({behavior: "smooth", block: "start"});
    }
  }, 250);
}, 150);
</script>
""",
        height=0,
        width=0,
    )


def _request_open_budget_tab() -> None:
    st.session_state["open_budget_tab_after_rerun"] = True


def _request_open_home_predictions() -> None:
    st.session_state["open_home_predictions_after_rerun"] = True
    st.session_state["archive_detail_loaded"] = False


def _request_open_bets_tab(
    target_bet_type: str = "",
    amount_preview: List[Dict[str, Any]] | None = None,
    highlight_source: str = "",
) -> None:
    st.session_state["open_bets_tab_after_rerun"] = True
    st.session_state["open_bets_target_bet_type"] = _to_text(target_bet_type)
    st.session_state["highlight_bet_type_name"] = _to_text(target_bet_type)
    st.session_state["highlight_bet_source_name"] = _to_text(highlight_source)
    if isinstance(amount_preview, list) and amount_preview:
        st.session_state["highlight_bet_amount_preview"] = [
            row for row in amount_preview[:3] if isinstance(row, dict)
        ]
    else:
        st.session_state.pop("highlight_bet_amount_preview", None)


def _render_open_budget_tab_script() -> None:
    components.html(
        """
<script>
function clickTab(label) {
  const tabs = Array.from(window.parent.document.querySelectorAll('button[role="tab"]'));
  const target = tabs.find((tab) => (tab.innerText || '').trim() === label);
  if (target) {
    target.click();
    return true;
  }
  return false;
}

setTimeout(() => {
  clickTab("予算配分");
  setTimeout(() => {
    const anchor = window.parent.document.getElementById("budget-plan-anchor");
    if (anchor) {
      anchor.scrollIntoView({behavior: "smooth", block: "start"});
    }
  }, 220);
}, 150);
</script>
""",
        height=0,
        width=0,
    )


def _render_open_home_predictions_script() -> None:
    components.html(
        """
<script>
function clickTab(label) {
  const tabs = Array.from(window.parent.document.querySelectorAll('button[role="tab"]'));
  const target = tabs.find((tab) => (tab.innerText || '').trim() === label);
  if (target) {
    target.click();
    return true;
  }
  return false;
}

setTimeout(() => {
  clickTab("予想ホーム");
  setTimeout(() => {
    const anchor = window.parent.document.getElementById("home-predictions-anchor");
    if (anchor) {
      anchor.scrollIntoView({behavior: "smooth", block: "start"});
    }
  }, 220);
}, 150);
</script>
""",
        height=0,
        width=0,
    )


def _bet_type_anchor_id(bet_type: Any) -> str:
    return {
        "単勝": "bet-anchor-single",
        "複勝": "bet-anchor-place",
        "馬連": "bet-anchor-quinella",
        "ワイド": "bet-anchor-wide",
        "馬単": "bet-anchor-exacta",
        "三連複": "bet-anchor-trio",
        "三連単": "bet-anchor-trifecta",
    }.get(_to_text(bet_type), "bet-plan-anchor")


def _render_open_bets_tab_script(target_bet_type: str = "") -> None:
    anchor_id = _bet_type_anchor_id(target_bet_type)
    components.html(
        """
<script>
function clickTab(label) {
  const tabs = Array.from(window.parent.document.querySelectorAll('button[role="tab"]'));
  const target = tabs.find((tab) => (tab.innerText || '').trim() === label);
  if (target) {
    target.click();
    return true;
  }
  return false;
}

setTimeout(() => {
  clickTab("買い目提案");
  setTimeout(() => {
    const anchor = window.parent.document.getElementById("%s");
    if (anchor) {
      anchor.scrollIntoView({behavior: "smooth", block: "start"});
    }
  }, 220);
}, 150);
</script>
"""
        % anchor_id,
        height=0,
        width=0,
    )


def _format_health_label(ok: Any) -> str:
    if ok is True:
        return "正常"
    if ok is False:
        return "異常"
    return "未確認"


def _format_health_message_label(message: Any) -> str:
    text = _to_text(message)
    if not text or text == "-":
        return "-"
    if text == "ok":
        return "正常稼働中"
    if text.startswith("public http error:"):
        return "外部公開エラー"
    if text.startswith("local health failed:"):
        return "ローカル応答なし"
    if text.startswith("public health failed:"):
        return "外部応答なし"
    return text


def _format_watch_status_label(status: Any) -> str:
    text = _to_text(status).lower()
    return {
        "healthy": "正常監視中",
        "unhealthy": "要確認",
    }.get(text, _to_text(status) or "-")


def _format_watch_event_label(event: Any) -> str:
    text = _to_text(event).lower()
    return {
        "url_changed": "URL更新",
        "recovered": "復旧",
        "unhealthy": "異常検知",
        "still_unhealthy": "異常継続",
    }.get(text, _to_text(event) or "-")


def _format_restart_result_label(result: Any) -> str:
    text = _to_text(result)
    if not text or text == "-":
        return "-"
    if text.startswith("terminated_pid="):
        return "トンネル再起動済み"
    if text.startswith("kickstart:"):
        return "常駐再起動済み"
    if text == "restart_cooldown":
        return "再起動待機中"
    if text == "auto_restart_disabled":
        return "自動復旧OFF"
    if text == "pid_missing":
        return "対象なし"
    if text.startswith("pid_not_found="):
        return "対象なし"
    if text.startswith("kill_failed:"):
        return "再起動失敗"
    if text.startswith("kickstart_failed:"):
        return "常駐再起動失敗"
    return text


def _format_notify_result_label(result: Any) -> str:
    text = _to_text(result)
    if not text or text == "-":
        return "-"
    parts = [part.strip() for part in text.split(",") if part.strip()]
    labels: List[str] = []
    for part in parts:
        if part == "macos":
            labels.append("Mac通知")
        elif part == "no_remote_target":
            labels.append("外部通知設定なし")
        elif part.startswith("ntfy:"):
            labels.append("ntfy通知")
        elif part.startswith("webhook:"):
            labels.append("Webhook通知")
        else:
            labels.append(part)
    return " / ".join(labels) if labels else "-"


def _format_auto_cycle_mode_label(config: Any) -> str:
    if not isinstance(config, dict):
        return "-"
    skip_entries = bool(config.get("skip_entries"))
    run_tuning = bool(config.get("run_tuning"))
    if skip_entries and (not run_tuning):
        return "軽量"
    if skip_entries and run_tuning:
        return "結果+反省"
    if (not skip_entries) and (not run_tuning):
        return "結果+出走表"
    return "フル"


def _format_auto_cycle_mode_detail(config: Any) -> str:
    if not isinstance(config, dict):
        return "-"
    parts: List[str] = []
    parts.append("結果取得のみ" if bool(config.get("skip_entries")) else "結果取得+今週出走表")
    parts.append("学習OFF" if not bool(config.get("run_tuning")) else "反省再学習ON")
    return " / ".join(parts)


def _timestamp_age_seconds(value: Any) -> int | None:
    dt_value = value if isinstance(value, datetime) else _parse_timestamp_value(value)
    if dt_value is None:
        return None
    now_value = datetime.now(dt_value.tzinfo) if dt_value.tzinfo else datetime.now()
    return max(0, int((now_value - dt_value).total_seconds()))


def _format_auto_cycle_feedback_sync(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    evaluated = int(payload.get("evaluated_races", 0) or 0)
    pending = int(payload.get("pending_races", 0) or 0)
    message = _to_text(payload.get("message", ""))
    if evaluated or pending:
        return f"採点: 評価済み {evaluated:,}件 / 結果待ち {pending:,}件"
    return message


def _format_storage_size(size_bytes: Any) -> str:
    try:
        size = float(size_bytes)
    except Exception:
        return "-"
    if size <= 0:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return "-"


def _render_autonomous_overview_card(
    status_payload: Any,
    config_payload: Any,
    feedback_summary: Dict[str, Any] | None,
    *,
    entries_rows: int,
    weekly_rows: int,
    history_path: Path,
) -> None:
    feedback_summary = feedback_summary if isinstance(feedback_summary, dict) else {}
    pending_count = int(feedback_summary.get("pending_races", 0) or 0)
    evaluated_count = int(feedback_summary.get("evaluated_races", 0) or 0)
    running = bool(status_payload.get("running")) if isinstance(status_payload, dict) else False
    phase = _to_text(status_payload.get("last_phase", "")) if isinstance(status_payload, dict) else ""
    next_run_text = _format_next_run_text(status_payload, config_payload)
    next_run_remaining = _format_next_run_remaining_text(status_payload, config_payload)
    cache_status = parquet_cache_status(history_path)
    cache_label = (
        "Parquet準備済み"
        if bool(cache_status.get("fresh"))
        else ("Parquet準備中" if bool(cache_status.get("enabled")) else "CSV")
    )
    if running:
        tone = "#2563eb"
        bg = "linear-gradient(135deg, rgba(37,99,235,.18), rgba(255,255,255,.94))"
        headline = "自動運用中"
        detail = phase or "最新情報と結果を確認しています。"
    elif pending_count > 0:
        tone = "#ea580c"
        bg = "linear-gradient(135deg, rgba(251,146,60,.22), rgba(255,255,255,.95))"
        headline = "結果取得だけ待ち"
        detail = f"結果待ちが {pending_count:,} 件あります。次の自動運用で確認、採点、学習材料化します。"
    elif int(entries_rows) <= 0:
        tone = "#dc2626"
        bg = "linear-gradient(135deg, rgba(248,113,113,.20), rgba(255,255,255,.95))"
        headline = "出走表の取得待ち"
        detail = "まず最新情報を取得すると、今週の予想を作れます。"
    elif int(weekly_rows) <= 0:
        tone = "#ca8a04"
        bg = "linear-gradient(135deg, rgba(250,204,21,.22), rgba(255,255,255,.95))"
        headline = "今週AI予想の更新待ち"
        detail = "出走表はあります。今週AI予想だけ作れば見られます。"
    else:
        tone = "#15803d"
        bg = "linear-gradient(135deg, rgba(34,197,94,.18), rgba(255,255,255,.95))"
        headline = "今日やることはありません"
        detail = "見るだけで大丈夫です。結果待ちが出たら自動運用かボタンで採点へ回します。"
    next_text = "-"
    if next_run_text != "-":
        next_text = next_run_text if next_run_remaining == "-" else f"{next_run_text} ({next_run_remaining})"
    st.markdown(
        f"""
<div style="border:1px solid rgba(15,23,42,.10);border-left:7px solid {tone};border-radius:22px;padding:18px 20px;margin:12px 0 18px;background:{bg};box-shadow:0 12px 30px rgba(15,23,42,.08);">
  <div style="font-size:13px;font-weight:800;letter-spacing:.08em;color:{tone};">おまかせ運用ステータス</div>
  <div style="font-size:28px;font-weight:900;color:#102018;margin-top:4px;">{html_escape(headline)}</div>
  <div style="font-size:14px;color:#334155;margin-top:4px;">{html_escape(detail)}</div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;">
    <span style="background:white;border:1px solid rgba(15,23,42,.10);border-radius:999px;padding:7px 10px;font-weight:700;">結果待ち {pending_count:,}件</span>
    <span style="background:white;border:1px solid rgba(15,23,42,.10);border-radius:999px;padding:7px 10px;font-weight:700;">評価済み {evaluated_count:,}件</span>
    <span style="background:white;border:1px solid rgba(15,23,42,.10);border-radius:999px;padding:7px 10px;font-weight:700;">今週予想 {int(weekly_rows):,}件</span>
    <span style="background:white;border:1px solid rgba(15,23,42,.10);border-radius:999px;padding:7px 10px;font-weight:700;">次回 {html_escape(next_text)}</span>
    <span style="background:white;border:1px solid rgba(15,23,42,.10);border-radius:999px;padding:7px 10px;font-weight:700;">履歴読込 {html_escape(cache_label)}</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    if pending_count > 0 and not running:
        if st.button("結果取得・採点をバックグラウンドに回す", key="autonomous_overview_queue_results", type="primary", width="stretch"):
            _queue_operation_action("結果取得だけ")


def _render_auto_cycle_visible_progress(status_payload: Any, config_payload: Any) -> None:
    if not isinstance(status_payload, dict) or not status_payload:
        return
    running = bool(status_payload.get("running"))
    updated_age = _timestamp_age_seconds(status_payload.get("updated_at", ""))
    completed_age = _timestamp_age_seconds(status_payload.get("last_completed_at", ""))
    visible_age_limit_seconds = 6 * 60 * 60
    recently_touched = bool(
        (updated_age is not None and updated_age <= visible_age_limit_seconds)
        or (completed_age is not None and completed_age <= visible_age_limit_seconds)
    )
    if not running and not recently_touched:
        return

    pct = max(0, min(100, int(status_payload.get("progress_pct", 0) or 0)))
    phase = _to_text(status_payload.get("last_phase", "")) or ("実行中" if running else "完了")
    mode_label = _format_auto_cycle_mode_label(config_payload)
    target_count = int(status_payload.get("targeted_races", 0) or 0)
    last_success = bool(status_payload.get("last_success", True))
    stale_running = bool(running and updated_age is not None and updated_age > 15 * 60)
    label = (
        "自動運用 応答待ち"
        if stale_running
        else ("自動運用 実行中" if running else ("直近の自動運用 完了" if last_success else "直近の自動運用 失敗"))
    )
    st.caption(label)
    st.progress(pct, text=f"{label}: {phase} ({pct}%)")
    detail_parts: List[str] = []
    if mode_label != "-":
        detail_parts.append(f"モード {mode_label}")
    if target_count > 0:
        detail_parts.append(f"対象 {target_count:,}件")
    started_text = _format_timestamp_text(status_payload.get("last_started_at", ""))
    if started_text != "-":
        detail_parts.append(f"開始 {started_text}")
    completed_text = _format_timestamp_text(status_payload.get("last_completed_at", ""))
    if completed_text != "-":
        detail_parts.append(f"完了 {completed_text}")
    age_text = _format_age_text(status_payload.get("updated_at", ""))
    if age_text != "-":
        detail_parts.append(f"更新 {age_text}")
    feedback_text = _format_auto_cycle_feedback_sync(status_payload.get("feedback_sync"))
    if feedback_text:
        detail_parts.append(feedback_text)
    if detail_parts:
        st.caption(" / ".join(detail_parts))
    summary = _to_text(status_payload.get("last_summary", ""))
    if summary:
        st.caption("直近サマリ: " + (summary[:180] + "..." if len(summary) > 180 else summary))
    error_text = _to_text(status_payload.get("error", ""))
    if error_text:
        st.warning(f"自動運用エラー: {error_text}")
    if stale_running:
        st.warning("自動運用の進捗が15分以上更新されていません。処理が止まって見える場合は、ターミナルで `ps aux | grep keiba_auto_cycle` を確認してください。")
        if st.button("古い自動運用表示をクリア", key="clear_stale_auto_cycle_status", width="stretch"):
            cleared_payload = dict(status_payload)
            cleared_payload.update(
                {
                    "running": False,
                    "last_success": False,
                    "error": "stale_running_cleared_by_user",
                    "progress_pct": 100,
                    "last_phase": "停止扱い",
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "last_completed_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            _write_json(AUTO_CYCLE_STATUS_PATH, cleared_payload)
            st.rerun()
    if running and not stale_running:
        components.html(
            """
<script>
setTimeout(() => {
  window.parent.location.reload();
}, 10000);
</script>
""",
            height=0,
            width=0,
        )


def _set_in_page_operation_status(
    *,
    label: str,
    progress_pct: int,
    phase: str,
    state: str = "running",
) -> None:
    payload = {
        "label": _to_text(label) or "画面内処理",
        "progress_pct": max(0, min(100, int(progress_pct))),
        "phase": _to_text(phase) or "-",
        "state": _to_text(state) or "running",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if payload["state"] in {"completed", "failed"}:
        payload["completed_at"] = payload["updated_at"]
    st.session_state["in_page_operation_status"] = payload
    try:
        LOCAL_OPERATION_STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _render_in_page_operation_status() -> None:
    payload = st.session_state.get("in_page_operation_status")
    if not isinstance(payload, dict):
        payload = _read_json_if_exists(LOCAL_OPERATION_STATUS_PATH)
    if not isinstance(payload, dict):
        return
    age_seconds = _timestamp_age_seconds(payload.get("updated_at", ""))
    running = _to_text(payload.get("state", "")) == "running"
    stale_running = bool(running and age_seconds is not None and age_seconds > 15 * 60)
    if not running and (age_seconds is None or age_seconds > 900):
        return
    pct = max(0, min(100, int(payload.get("progress_pct", 0) or 0)))
    label = _to_text(payload.get("label", "")) or "画面内処理"
    phase = _to_text(payload.get("phase", "")) or "-"
    status_label = (
        "応答待ち/古い表示"
        if stale_running
        else ("実行中" if running else ("失敗" if _to_text(payload.get("state", "")) == "failed" else "完了"))
    )
    st.caption("画面内の処理")
    st.progress(pct, text=f"{label}: {phase} ({pct}%)")
    age_text = _format_age_text(payload.get("updated_at", ""))
    st.caption(f"状態: {status_label}" + (f" / 更新 {age_text}" if age_text != "-" else ""))
    if stale_running:
        st.warning("15分以上進捗が更新されていません。裏で処理が残っていない場合は、ページを更新してから `無料ハーネス診断を再チェック` してください。")


def _render_free_prediction_harness_status(payload: Any) -> None:
    if not isinstance(payload, dict) or not payload:
        return
    planner = payload.get("planner", {})
    generator = payload.get("generator", {})
    evaluator = payload.get("evaluator", {})
    contract = payload.get("contract", {})
    if not isinstance(planner, dict):
        planner = {}
    if not isinstance(generator, dict):
        generator = {}
    if not isinstance(evaluator, dict):
        evaluator = {}
    if not isinstance(contract, dict):
        contract = {}

    severity = _to_text(planner.get("severity", "info")) or "info"
    next_action = _to_text(planner.get("next_action", "")) or "確認"
    reason = _to_text(planner.get("reason", "")) or _to_text(payload.get("message", ""))
    generated_text = _format_age_text(payload.get("generated_at", ""))
    header = "次にやること診断"
    body = f"おすすめ: {next_action}" + (f" / {reason}" if reason else "")
    failed_count = int(contract.get("failed_count", 0) or 0)
    warned_count = int(contract.get("warned_count", 0) or 0)
    quality_score = max(0, min(100, 100 - failed_count * 18 - warned_count * 6))
    if severity == "error":
        st.error(f"{header}: {body}")
    elif severity == "warn":
        st.warning(f"{header}: {body}")
    elif severity == "ok":
        st.success(f"{header}: {body}")
    else:
        st.info(f"{header}: {body}")

    metric_cols = st.columns(2)
    metric_cols[0].metric("予想", f"{int(generator.get('weekly_races', 0) or 0):,}R")
    metric_cols[1].metric("出走表", f"{int(generator.get('entries_races', 0) or 0):,}R")
    metric_cols = st.columns(2)
    metric_cols[0].metric("採点", f"{int(evaluator.get('evaluated_races', 0) or 0):,}")
    metric_cols[1].metric("結果待ち", f"{int(evaluator.get('pending_due_races', evaluator.get('pending_races', 0)) or 0):,}")
    st.progress(quality_score, text=f"予想票チェック: {quality_score}%")
    st.caption(
        "確認結果: "
        f"要修正 {failed_count:,} / "
        f"注意 {warned_count:,}"
        + (f" / 診断 {generated_text}" if generated_text != "-" else "")
    )
    if _operation_action_key_from_label(next_action):
        st.caption("迷ったらこのボタンだけでOKです。押すと診断に沿った処理を1つだけ実行します。")
        if st.button(f"診断どおり実行: {next_action}", key="free_harness_run_next_action", width="stretch"):
            _queue_operation_action(next_action)

    issues = contract.get("issues", [])
    skip_actions = planner.get("skip_actions", [])
    with st.expander("診断の内訳", expanded=False):
        st.caption("予想票、出走表、採点状況を分けて確認しています。注意は「壊れている」ではなく、精度を上げるための確認ポイントです。")
        rate_cols = st.columns(3)
        rate_cols[0].metric("本命勝率", _format_rate_metric(evaluator.get("top_horse_hit_rate")))
        rate_cols[1].metric("複勝的中率", _format_rate_metric(evaluator.get("place_hit_rate")))
        rate_cols[2].metric("三連複的中率", _format_rate_metric(evaluator.get("trio_hit_rate")))
        date_scope = generator.get("date_scope", {})
        if isinstance(date_scope, dict) and int(date_scope.get("date_span_days", 0) or 0) > 0:
            st.caption(
                "予想CSV期間: "
                f"{_to_text(date_scope.get('first_date', '-'))} 〜 {_to_text(date_scope.get('last_date', '-'))} / "
                f"今日 {int(date_scope.get('today_races', 0) or 0):,}R / "
                f"過去 {int(date_scope.get('past_races', 0) or 0):,}R / "
                f"未来 {int(date_scope.get('future_races', 0) or 0):,}R"
            )
        if isinstance(skip_actions, list) and skip_actions:
            st.caption("今は押さなくていい: " + " / ".join(_to_text(item) for item in skip_actions if _to_text(item)))
        if isinstance(issues, list) and issues:
            issue_rows = [
                {
                    "重要度": _to_text(issue.get("level", "")),
                    "確認": _to_text(issue.get("check", "")),
                    "件数": int(issue.get("count", 0) or 0),
                    "内容": _to_text(issue.get("message", "")),
                    "次": _to_text(issue.get("action", "")),
                }
                for issue in issues
                if isinstance(issue, dict)
            ]
            if issue_rows:
                st.dataframe(_with_one_based_index(pd.DataFrame(issue_rows)), width="stretch", height=220)
        else:
            st.caption("厳格チェックで大きな未完成は見つかっていません。")
        if st.button("無料ハーネス診断を再チェック", key="refresh_free_prediction_harness", width="stretch"):
            _load_or_refresh_prediction_harness_status(force=True)
            _set_ui_notice("無料ハーネス診断を更新しました。", level="info")
            st.rerun()


def _render_auto_update_status_block(notes: Any, *, title: str = "更新メモ") -> None:
    lines = collect_auto_update_status_lines(notes)
    if not lines:
        return
    st.caption(title)
    for line in lines:
        st.caption(f"- {line}")


def _format_rate_metric(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "-" if pd.isna(numeric) else f"{float(numeric):.1%}"


def _format_signed_rate_metric(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "-" if pd.isna(numeric) else f"{float(numeric):+.1%}"


def _format_roi_metric(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "-" if pd.isna(numeric) else f"{float(numeric):.0%}"


def _format_hit_mark(value: Any) -> str:
    if isinstance(value, bool):
        return "○" if value else "×"
    text = _to_text(value).lower()
    return "○" if text in {"true", "1"} else "×"


def _top_pick_text(table: pd.DataFrame) -> str:
    if table.empty:
        return "-"
    row = table.iloc[0]
    for key in ("馬", "組み合わせ", "買い目"):
        text = _to_text(row.get(key, ""))
        if text:
            return text
    return "-"


def _format_race_label(race_id: Any, venue: Any = "", race_date: Any = "", race_name: Any = "") -> str:
    rid = _to_text(race_id)
    if not rid:
        return "-"
    venue_text = _to_text(venue)
    race_name_text = _to_text(race_name)
    race_date_text = _format_date_text(race_date)
    if race_date_text == "-":
        race_date_text = ""
    auto_m = _AUTO_RACE_ID_RE.match(rid)
    if auto_m and not race_date_text:
        try:
            race_date_text = datetime.strptime(auto_m.group(1), "%Y%m%d").strftime("%Y/%m/%d")
        except ValueError:
            race_date_text = auto_m.group(1)

    parts: List[str] = []
    if race_date_text:
        parts.append(race_date_text)
    if venue_text and venue_text not in ("-", "nan", "None"):
        parts.append(venue_text)
    if race_name_text and race_name_text not in ("-", "nan", "None"):
        parts.append(race_name_text)
    parts.append(f"[{rid}]")
    return " ".join(parts).strip()


def _extract_race_context(entries_df: pd.DataFrame, race_id: Any = "") -> Dict[str, Any]:
    if entries_df.empty:
        return {}
    work = entries_df.copy()
    if "race_id" in work.columns:
        work["race_id"] = work["race_id"].fillna("").astype(str).str.strip()
    requested_race_id = _to_text(race_id)
    subset = pd.DataFrame()
    if requested_race_id and "race_id" in work.columns:
        subset = work[work["race_id"] == requested_race_id].copy()
    if subset.empty:
        if "race_id" in work.columns:
            race_ids = [rid for rid in work["race_id"].dropna().astype(str).str.strip().tolist() if rid]
            seen: List[str] = []
            for rid in race_ids:
                if rid not in seen:
                    seen.append(rid)
            if seen:
                requested_race_id = seen[0]
                subset = work[work["race_id"] == requested_race_id].copy()
        else:
            subset = work.copy()
            requested_race_id = "AUTO_SELECTED"
    if subset.empty:
        return {}

    def _first_text(col_name: str) -> str:
        if col_name not in subset.columns:
            return ""
        series = subset[col_name].dropna()
        for value in series.tolist():
            text = _to_text(value)
            if text:
                return text
        return ""

    distance_value: Any = ""
    if "distance" in subset.columns:
        distance_series = pd.to_numeric(subset["distance"], errors="coerce").dropna()
        if not distance_series.empty:
            distance_value = int(float(distance_series.iloc[0]))

    race_date = _first_text("race_date") or _first_text("fetched_date")
    race_name = _first_text("race_name")
    venue = _first_text("venue")
    weather = _first_text("weather")
    track_condition = _first_text("track_condition")
    return {
        "race_id": requested_race_id,
        "race_date": race_date,
        "race_name": race_name,
        "venue": venue,
        "weather": weather,
        "track_condition": track_condition,
        "distance": distance_value,
        "field_size": int(len(subset)),
        "label": _format_race_label(requested_race_id, venue, race_date, race_name),
    }


def _apply_selected_race_context_to_inputs(context: Dict[str, Any], *, force: bool = False) -> None:
    race_id = _to_text(context.get("race_id", ""))
    if not race_id:
        return
    if not force and _to_text(st.session_state.get("predict_context_race_id", "")) == race_id:
        return
    weather = _to_text(context.get("weather", ""))
    if weather in WEATHER_OPTIONS:
        st.session_state["predict_weather"] = weather
    track_condition = _to_text(context.get("track_condition", ""))
    if track_condition in TRACK_OPTIONS:
        st.session_state["predict_track_condition"] = track_condition
    distance_num = pd.to_numeric(pd.Series([context.get("distance")]), errors="coerce").iloc[0]
    if pd.notna(distance_num):
        st.session_state["predict_distance"] = int(float(distance_num))
    st.session_state["predict_context_race_id"] = race_id
    st.session_state["selected_detail_race_id"] = race_id
    st.session_state["selected_detail_race_label"] = _to_text(context.get("label", "")) or race_id


def _build_detail_race_selector_frame(*frames: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for frame in frames:
        if frame.empty or "レースID" not in frame.columns:
            continue
        for _, row in frame.iterrows():
            race_id = _to_text(row.get("レースID", ""))
            if not race_id or race_id in seen:
                continue
            seen.add(race_id)
            label = _to_text(row.get("レース", ""))
            if not label:
                label = _format_race_label(
                    race_id,
                    row.get("開催", ""),
                    row.get("日付", ""),
                    row.get("レース名", ""),
                )
            rows.append(
                {
                    "race_id": race_id,
                    "label": label,
                    "venue": _to_text(row.get("開催", "")) or "-",
                    "grade": _to_text(row.get("格付", "")) or "-",
                    "field_size": _to_text(row.get("頭数", "")) or "-",
                }
            )
    return pd.DataFrame(rows)


def _race_number_from_id(value: Any) -> int:
    text = _to_text(value)
    m = re.search(r"(\d{2})$", text)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except ValueError:
        return 0


def _format_race_no_text(value: Any) -> str:
    race_no = _race_number_from_id(value)
    return f"{race_no:02d}R" if race_no > 0 else "-"


def _find_race_id_by_number(race_ids: List[str], race_no: int) -> str:
    for race_id in race_ids:
        if _race_number_from_id(race_id) == int(race_no):
            return race_id
    return ""


def _pick_main_race_id(frame: pd.DataFrame, race_id_col: str = "レースID") -> str:
    if frame.empty or race_id_col not in frame.columns:
        return ""
    work = frame.copy()
    if "格付" in work.columns:
        work["_grade_sort"] = work["格付"].map(lambda x: _GRADE_ORDER.get(_to_text(x), 9))
    else:
        work["_grade_sort"] = 9
    work["_race_no"] = work[race_id_col].map(_race_number_from_id)
    work = work.sort_values(["_grade_sort", "_race_no"], ascending=[True, False])
    return _to_text(work.iloc[0].get(race_id_col, ""))


def _sort_program_order_frame(
    frame: pd.DataFrame,
    *,
    race_id_col: str,
    race_date_col: str,
    venue_col: str = "",
    ascending_day: bool = True,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    work = frame.copy()
    work["_sort_day"] = work.apply(lambda row: _parse_date_text(row.get(race_date_col, "")) or date.min, axis=1)
    work["_sort_race_no"] = work[race_id_col].map(_race_number_from_id) if race_id_col in work.columns else 0
    sort_cols = ["_sort_day"]
    ascending = [ascending_day]
    if venue_col and venue_col in work.columns:
        work["_sort_venue"] = work[venue_col].fillna("").astype(str).str.strip()
        sort_cols.append("_sort_venue")
        ascending.append(True)
    sort_cols.append("_sort_race_no")
    ascending.append(True)
    work = work.sort_values(sort_cols, ascending=ascending)
    return work.drop(columns=["_sort_day", "_sort_race_no", "_sort_venue"], errors="ignore").reset_index(drop=True)


def _weekly_row_state(row: pd.Series) -> str:
    rid = _to_text(row.get("race_id", ""))
    if rid.upper().startswith("AUTO"):
        return "仮データ"
    for key in ("top_horse", "top_jockey", "single_pick", "quinella_pick"):
        if _has_synthetic_marker(row.get(key, "")):
            return "仮データ"
    return "実データ"


def _weekly_overview_state(row: pd.Series) -> str:
    rid = _to_text(row.get("レースID", ""))
    if rid.upper().startswith("AUTO"):
        return "仮データ"
    for key in ("注目馬", "注目騎手"):
        if _has_synthetic_marker(row.get(key, "")):
            return "仮データ"
    return "実データ"


def _sort_by_race_id_safe(df: pd.DataFrame, column: str, ascending: bool) -> pd.DataFrame:
    out = df.copy()
    out[column] = out[column].map(lambda x: str(x).strip())
    return out.sort_values(column, ascending=ascending)


def _build_llm_top_alignment_label(data_top: Any, llm_top: Any) -> str:
    data_text = _to_text(data_top)
    llm_text = _to_text(llm_top)
    if not data_text or data_text == "-" or not llm_text or llm_text == "-":
        return "⚪ 未判定"
    if data_text == llm_text:
        return "🟢 一致"
    return "🟠 別軸"


def _build_llm_danger_sync_label(market_danger: Any, llm_danger: Any) -> str:
    market_text = _to_text(market_danger)
    llm_text = _to_text(llm_danger)
    if market_text and market_text != "-" and llm_text and llm_text != "-":
        if market_text == llm_text:
            return "🔴 両方警戒"
        return "🟠 別馬を警戒"
    if llm_text and llm_text != "-":
        return "🤖 LLM警戒"
    if market_text and market_text != "-":
        return "🔴 市場警戒"
    return "⚪ 未判定"


def _parse_popularity_rank_text(value: Any) -> int | None:
    text = _to_text(value)
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        try:
            num = int(digits)
            return num if num > 0 else None
        except Exception:
            return None
    try:
        num = int(float(value))
        return num if num > 0 else None
    except Exception:
        return None


def _build_llm_disagreement_reason(row: pd.Series | Dict[str, Any]) -> str:
    data_top = _to_text(row.get("本命馬", row.get("top_horse", "-")))
    llm_top = _to_text(row.get("LLM本命", row.get("llm_top_horse", "-")))
    if not data_top or data_top == "-" or not llm_top or llm_top == "-":
        return "-"
    if data_top == llm_top:
        return "データ本命と一致"

    reasons: List[str] = []
    dark_horse = _to_text(row.get("大穴候補", row.get("dark_horse", "-")))
    if llm_top and dark_horse and llm_top == dark_horse:
        reasons.append("LLMは穴候補を本命視")

    llm_danger = _to_text(row.get("LLM危険人気", row.get("llm_danger_favorite", "-")))
    if llm_danger and llm_danger == data_top:
        reasons.append("LLMはデータ本命を危険視")

    market_danger = _to_text(row.get("危険人気馬", row.get("danger_favorite", "-")))
    if market_danger and market_danger == data_top:
        reasons.append("市場でも本命側に警戒あり")

    top_pop = _parse_popularity_rank_text(row.get("本命人気", row.get("top_pop_rank", "")))
    if top_pop is not None and top_pop <= 3:
        reasons.append("上位人気から外している")

    adjustment_count = pd.to_numeric(
        pd.Series([row.get("補正本数", row.get("condition_adjustment_count", ""))]),
        errors="coerce",
    ).iloc[0]
    if pd.notna(adjustment_count) and int(float(adjustment_count)) > 0:
        reasons.append(f"条件補正{int(float(adjustment_count))}本を重視")

    if not reasons:
        reasons.append("候補の見方が分かれた")
    return " / ".join(reasons[:2])


def _llm_reason_tag_class(value: Any) -> str:
    text = _to_text(value)
    if "穴候補" in text:
        return "longshot"
    if "危険視" in text:
        return "danger"
    if "市場" in text or "人気" in text:
        return "market"
    if "条件補正" in text:
        return "adjust"
    return "generic"


def _render_llm_reason_tags_html(value: Any) -> str:
    parts = [_to_text(part) for part in _to_text(value).split("/") if _to_text(part)]
    if not parts:
        return ""
    return "<div class='llm-reason-tag-row'>" + "".join(
        f"<span class='llm-reason-tag {_llm_reason_tag_class(part)}'>{html_escape(part)}</span>"
        for part in parts
    ) + "</div>"


def _format_llm_reason_badges_text(value: Any) -> str:
    parts = [_to_text(part) for part in _to_text(value).split("/") if _to_text(part)]
    if not parts:
        return "-"
    formatted: List[str] = []
    for part in parts:
        if "穴候補" in part:
            formatted.append(f"🟠{part}")
        elif "危険視" in part:
            formatted.append(f"🔴{part}")
        elif "市場" in part or "人気" in part:
            formatted.append(f"🔵{part}")
        elif "条件補正" in part:
            formatted.append(f"🟣{part}")
        else:
            formatted.append(f"⚪{part}")
    return " / ".join(formatted)


def _format_llm_bucket_badges_text(value: Any) -> str:
    bucket = _to_text(value)
    if not bucket or bucket in {"-", "見方差"}:
        return "-" if bucket in {"", "-"} else "⚪見方差"
    if bucket == "穴寄り":
        return "🟠穴寄り"
    if bucket == "危険視":
        return "🔴危険視"
    if bucket == "人気逆張り":
        return "🔵人気逆張り"
    if bucket == "補正重視":
        return "🟣補正重視"
    return f"⚪{bucket}"


def _classify_llm_disagreement_bucket(value: Any) -> str:
    parts = [_to_text(item) for item in _to_text(value).split("/") if _to_text(item)]
    if any("穴候補" in part for part in parts):
        return "穴寄り"
    if any("危険視" in part for part in parts):
        return "危険視"
    if any("市場" in part or "人気" in part for part in parts):
        return "人気逆張り"
    if any("条件補正" in part for part in parts):
        return "補正重視"
    return "見方差"


def _llm_bucket_style_class(bucket: Any) -> str:
    bucket_text = _to_text(bucket)
    if bucket_text == "穴寄り":
        return "longshot"
    if bucket_text == "危険視":
        return "danger"
    if bucket_text == "人気逆張り":
        return "market"
    if bucket_text == "補正重視":
        return "adjust"
    return "neutral"


def _build_llm_bucket_explanation(bucket: Any, *, edge: Any = None) -> str:
    bucket_text = _to_text(bucket) or "見方差"
    edge_text = _format_signed_rate_metric(edge) if pd.notna(pd.to_numeric(pd.Series([edge]), errors="coerce").iloc[0]) else "-"
    if bucket_text == "穴寄り":
        return f"LLMが穴候補を上に取りやすい区分です。優勢差 {edge_text} なら、人気薄の拾い直しを先に見る価値があります。"
    if bucket_text == "危険視":
        return f"LLMがデータ本命の危うさを先に見ている区分です。優勢差 {edge_text} なら、本命の過信を避ける確認が効きます。"
    if bucket_text == "人気逆張り":
        return f"人気サイドから少し外して見る区分です。優勢差 {edge_text} なら、上位人気を疑うレースから先に見ると整理しやすいです。"
    if bucket_text == "補正重視":
        return f"開催・馬場・距離などの補正を強く読む区分です。優勢差 {edge_text} なら、条件替わりのレースほど先に確認したい流れです。"
    return f"LLMとデータの見方差そのものが効いている区分です。優勢差 {edge_text} を見ながら、割れ方の質を確かめるのが向いています。"


def _build_llm_bucket_bet_guidance(bucket: Any) -> tuple[List[str], List[str]]:
    bucket_text = _to_text(bucket) or "見方差"
    if bucket_text == "穴寄り":
        return ["ワイド", "複勝", "単勝"], ["三連単", "馬単"]
    if bucket_text == "危険視":
        return ["ワイド", "三連複", "複勝"], ["単勝", "馬単"]
    if bucket_text == "人気逆張り":
        return ["ワイド", "三連複", "複勝"], ["単勝", "馬単"]
    if bucket_text == "補正重視":
        return ["ワイド", "複勝", "三連複"], ["単勝", "三連単"]
    return ["複勝", "ワイド", "単勝"], ["三連単"]


def _build_llm_bucket_bet_memo(bucket: Any) -> str:
    bucket_text = _to_text(bucket) or "見方差"
    if bucket_text == "穴寄り":
        return "人気薄を拾う週なので、ワイドや複勝を軸にして単勝は薄く添える形が向きます。"
    if bucket_text == "危険視":
        return "本命の過信を避けたい流れです。ワイドや三連複で相手を広めに拾う見方が合います。"
    if bucket_text == "人気逆張り":
        return "上位人気を疑う週です。単勝一点より、複勝やワイドで逆張りの余地を残す方が組みやすいです。"
    if bucket_text == "補正重視":
        return "条件替わりの読みが効きやすいので、複勝やワイドを土台にして三連複を添える形が向いています。"
    return "見方差を拾う週なので、ベース配分を土台に相手候補だけ少し広げるのが無理なく入れます。"


def _render_llm_bucket_bet_badges_html(bucket: Any) -> str:
    bucket_class = _llm_bucket_style_class(bucket)
    recommended, avoid = _build_llm_bucket_bet_guidance(bucket)
    parts: List[str] = []
    parts.extend(
        f"<span class='llm-hit-badge recommend {bucket_class}'>寄せ {html_escape(bet)}</span>"
        for bet in recommended[:3]
        if _to_text(bet)
    )
    parts.extend(
        f"<span class='llm-hit-badge avoid {bucket_class}'>抑え {html_escape(bet)}</span>"
        for bet in avoid[:2]
        if _to_text(bet)
    )
    if not parts:
        return ""
    return "<div class='llm-hit-badge-row'>" + "".join(parts) + "</div>"


def _lookup_llm_disagreement_segment_stats(
    performance_df: pd.DataFrame | None,
    segment: Any,
) -> Dict[str, Any]:
    if performance_df is None or performance_df.empty or "区分" not in performance_df.columns:
        return {}
    segment_text = _to_text(segment)
    if not segment_text:
        return {}
    matched = performance_df[performance_df["区分"].map(_to_text) == segment_text].copy()
    if matched.empty:
        return {}
    row = matched.iloc[0]
    return {
        "segment": segment_text,
        "evaluated_races": int(pd.to_numeric(pd.Series([row.get("評価済みレース")]), errors="coerce").fillna(0).iloc[0]),
        "data_hit_rate": pd.to_numeric(pd.Series([row.get("データ本命勝率")]), errors="coerce").iloc[0],
        "llm_hit_rate": pd.to_numeric(pd.Series([row.get("LLM本命勝率")]), errors="coerce").iloc[0],
        "llm_edge": pd.to_numeric(pd.Series([row.get("LLM優勢差")]), errors="coerce").iloc[0],
    }


def _render_llm_segment_stats(stats: Dict[str, Any] | None) -> None:
    if not isinstance(stats, dict) or not stats:
        return
    cols = st.columns(4, gap="small")
    cols[0].metric("評価件数", f"{int(stats.get('evaluated_races', 0) or 0):,}")
    cols[1].metric("データ本命勝率", _format_rate_metric(stats.get("data_hit_rate")))
    cols[2].metric("LLM本命勝率", _format_rate_metric(stats.get("llm_hit_rate")))
    cols[3].metric("LLM優勢差", _format_signed_rate_metric(stats.get("llm_edge")))


def _build_selected_llm_alert_payload(
    weekly_source_df: pd.DataFrame | None,
    *,
    race_id: Any,
    performance_df: pd.DataFrame | None = None,
) -> Dict[str, Any]:
    race_id_text = _to_text(race_id)
    source = weekly_source_df.copy() if isinstance(weekly_source_df, pd.DataFrame) else pd.DataFrame()
    if source.empty or "race_id" not in source.columns or not race_id_text:
        return {}
    row_df = source[source["race_id"].fillna("").astype(str).str.strip() == race_id_text].copy()
    if row_df.empty:
        return {}
    row = row_df.iloc[0]
    data_top = _to_text(row.get("top_horse", ""))
    llm_top = _to_text(row.get("llm_top_horse", ""))
    if not data_top or not llm_top or data_top == llm_top:
        return {}
    reason = _build_llm_disagreement_reason(row)
    bucket = _classify_llm_disagreement_bucket(reason)
    stats = _lookup_llm_disagreement_segment_stats(performance_df, bucket)
    return {
        "bucket": bucket,
        "reason": reason,
        "data_top": data_top,
        "llm_top": llm_top,
        "llm_dark": _to_text(row.get("llm_dark_horse", "")),
        "llm_danger": _to_text(row.get("llm_danger_favorite", "")),
        "stats": stats,
    }


def _render_selected_llm_alert_card(payload: Dict[str, Any] | None) -> None:
    if not isinstance(payload, dict) or not payload:
        return
    bucket = _to_text(payload.get("bucket", "")) or "見方差"
    bucket_class = _llm_bucket_style_class(bucket)
    reason = _to_text(payload.get("reason", "")) or "-"
    bet_memo = _build_llm_bucket_bet_memo(bucket)
    stats = payload.get("stats", {})
    st.caption("LLM別軸の見方")
    st.markdown(
        """
<div class="memo-card llm-priority-card {bucket_class}">
  <div class="memo-chip {bucket_class}">LLM別軸警戒</div>
  <div class="memo-title">{bucket}</div>
  <div class="memo-line"><strong>データ本命:</strong> {data_top}</div>
  <div class="memo-line"><strong>LLM本命:</strong> {llm_top}</div>
  <div class="memo-line"><strong>理由:</strong> {reason}</div>
  <div class="memo-line"><strong>買い方メモ:</strong> {bet_memo}</div>
  {bet_badges}
</div>
""".format(
            bucket_class=html_escape(bucket_class),
            bucket=html_escape(bucket),
            data_top=html_escape(_render_name_text(payload.get("data_top", "-"))),
            llm_top=html_escape(_render_name_text(payload.get("llm_top", "-"))),
            reason=html_escape(reason),
            bet_memo=html_escape(bet_memo),
            bet_badges=_render_llm_bucket_bet_badges_html(bucket),
        ),
        unsafe_allow_html=True,
    )
    st.caption(_build_llm_bucket_explanation(bucket, edge=(stats or {}).get("llm_edge")))
    _render_llm_segment_stats(stats)


def _build_llm_disagreement_summary(frame: pd.DataFrame | None, *, limit: int = 4) -> Dict[str, Any]:
    work = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    if work.empty or "LLM本命比較" not in work.columns:
        return {"title": "", "summary": "", "chips": [], "lead_tag": "", "lead_count": 0}
    work = work[work["LLM本命比較"].map(lambda value: "別軸" in _to_text(value))].copy()
    if work.empty:
        return {
            "title": "LLM別軸傾向",
            "summary": "今週はデータ本命とLLM本命が大きく割れるレースは目立っていません。",
            "chips": ["別軸少なめ"],
            "lead_tag": "",
            "lead_count": 0,
        }
    reason_counts: Dict[str, int] = {}
    for value in work.get("LLM別軸理由", pd.Series(dtype=object)).tolist():
        key = _classify_llm_disagreement_bucket(value)
        reason_counts[key] = int(reason_counts.get(key, 0)) + 1
    sorted_reasons = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
    lead_tag, lead_count = sorted_reasons[0] if sorted_reasons else ("", 0)
    chips = [f"{tag} {count}件" for tag, count in sorted_reasons[: max(1, int(limit))]]
    if lead_tag == "穴寄り":
        summary = f"LLMは今週、穴寄りの馬を本命視するズレが {lead_count} 件で最多です。データ本命が堅い時も、穴候補の拾い直しに価値があります。"
    elif lead_tag == "危険視":
        summary = f"LLMは今週、データ本命を危険視するズレが {lead_count} 件で多めです。本命馬の過信を抑える確認が効きます。"
    elif lead_tag == "人気逆張り":
        summary = f"LLMは今週、人気サイドを外す逆張りが {lead_count} 件で多めです。人気の集中に対して別線を持つ週です。"
    elif lead_tag == "補正重視":
        summary = f"LLMは今週、条件補正を強めに見て本命をずらす傾向が {lead_count} 件あります。開催・馬場・距離の見直しが効きます。"
    else:
        summary = f"LLMとデータの見方の差が {lead_count} 件で目立っています。別軸レースから先に確認すると整理しやすいです。"
    return {
        "title": "LLM別軸傾向",
        "summary": summary,
        "chips": chips,
        "lead_tag": lead_tag,
        "lead_count": int(lead_count),
        "disagreement_count": int(len(work)),
    }


def _render_llm_disagreement_trend_card(summary: Dict[str, Any] | None) -> None:
    if not isinstance(summary, dict):
        return
    title = _to_text(summary.get("title", ""))
    if not title:
        return
    sub = _to_text(summary.get("summary", ""))
    chips = summary.get("chips", [])
    chip_html = ""
    if isinstance(chips, list) and chips:
        chip_html = "<div class='feedback-trend-row'>" + "".join(
            f"<span class='feedback-trend-chip'>{html_escape(_to_text(chip))}</span>"
            for chip in chips
            if _to_text(chip)
        ) + "</div>"
    disagreement_count = int(summary.get("disagreement_count", 0) or 0)
    st.markdown(
        """
<div class="memo-card" style="margin:0.25rem 0 1rem;">
  <div class="memo-chip">LLM別軸</div>
  <div class="memo-title">{title}</div>
  <div class="memo-line"><strong>件数:</strong> {count}件</div>
  <div class="memo-line"><strong>要点:</strong> {sub}</div>
  {chips}
</div>
""".format(
            title=html_escape(title),
            count=html_escape(f"{disagreement_count:,}"),
            sub=html_escape(sub or "-"),
            chips=chip_html,
        ),
        unsafe_allow_html=True,
    )
    shortcut_cols = st.columns(3, gap="small")
    if shortcut_cols[0].button("別軸だけ表示", key="llm_disagreement_only", width="stretch"):
        st.session_state["weekly_llm_alignment_filter"] = "別軸だけ"
        _set_ui_notice("LLMとデータが別軸のレースだけ表示します")
        st.rerun()
    if shortcut_cols[1].button("別軸を上に", key="llm_disagreement_top", width="stretch"):
        st.session_state["weekly_llm_alignment_filter"] = "別軸を上に集める"
        _set_ui_notice("LLMとデータが別軸のレースを上に集めます")
        st.rerun()
    if shortcut_cols[2].button("通常表示", key="llm_disagreement_reset", width="stretch"):
        st.session_state["weekly_llm_alignment_filter"] = "すべて"
        _set_ui_notice("LLM比較フィルタを通常表示に戻しました")
        st.rerun()


def _build_llm_disagreement_performance_comment(
    performance_df: pd.DataFrame | None,
    summary: Dict[str, Any] | None = None,
) -> str:
    if performance_df is None or performance_df.empty:
        return ""
    work = performance_df.copy()
    if "区分" not in work.columns:
        return ""
    overall = work[work["区分"].map(_to_text) == "別軸全体"]
    overall_row = overall.iloc[0] if not overall.empty else work.iloc[0]
    overall_edge = pd.to_numeric(pd.Series([overall_row.get("LLM優勢差")]), errors="coerce").iloc[0]
    overall_count = int(pd.to_numeric(pd.Series([overall_row.get("評価済みレース")]), errors="coerce").fillna(0).iloc[0])
    segment_rows = work[work["区分"].map(_to_text) != "別軸全体"].copy()
    if not segment_rows.empty:
        segment_rows["_edge_num"] = pd.to_numeric(segment_rows["LLM優勢差"], errors="coerce")
        segment_rows["_count_num"] = pd.to_numeric(segment_rows["評価済みレース"], errors="coerce").fillna(0)
        best_row = segment_rows.sort_values(["_edge_num", "_count_num"], ascending=[False, False], na_position="last").iloc[0]
        worst_row = segment_rows.sort_values(["_edge_num", "_count_num"], ascending=[True, False], na_position="last").iloc[0]
        best_segment = _to_text(best_row.get("区分", ""))
        best_edge = pd.to_numeric(pd.Series([best_row.get("LLM優勢差")]), errors="coerce").iloc[0]
        worst_segment = _to_text(worst_row.get("区分", ""))
        worst_edge = pd.to_numeric(pd.Series([worst_row.get("LLM優勢差")]), errors="coerce").iloc[0]
    else:
        best_segment = ""
        best_edge = np.nan
        worst_segment = ""
        worst_edge = np.nan

    lead_tag = _to_text((summary or {}).get("lead_tag", ""))
    if pd.notna(overall_edge) and float(overall_edge) >= 0.08:
        comment = f"別軸レース {overall_count}件では、LLM本命がデータ本命より当たりに寄っています。"
        if best_segment and pd.notna(best_edge) and float(best_edge) > 0:
            comment += f" とくに `{best_segment}` で LLM優勢差 {_format_signed_rate_metric(best_edge)} が出ています。"
        return comment
    if pd.notna(overall_edge) and float(overall_edge) <= -0.08:
        comment = f"別軸レース {overall_count}件では、まだデータ本命側が優勢です。"
        if worst_segment and pd.notna(worst_edge) and float(worst_edge) < 0:
            comment += f" `{worst_segment}` は LLM優勢差 {_format_signed_rate_metric(worst_edge)} で逆風です。"
        return comment
    if lead_tag:
        return f"別軸全体では拮抗ですが、今週は `{lead_tag}` 型のズレが多めです。グラフで区分ごとの差を先に見ると判断しやすいです。"
    return "別軸全体ではまだ拮抗しています。区分ごとの差を見て、LLMのズレが効く場面だけ拾うのが良さそうです。"


def _render_llm_disagreement_performance_charts(performance_df: pd.DataFrame | None) -> None:
    if performance_df is None or performance_df.empty:
        return
    work = performance_df.copy()
    if "区分" not in work.columns:
        return
    chart_df = work.copy()
    for col in ["データ本命勝率", "LLM本命勝率", "LLM優勢差"]:
        if col in chart_df.columns:
            chart_df[col] = pd.to_numeric(chart_df[col], errors="coerce")
    chart_df["区分表示"] = chart_df["区分"].map(_to_text).replace("", "-")
    rate_cols = [col for col in ["データ本命勝率", "LLM本命勝率"] if col in chart_df.columns]
    cols = st.columns(2, gap="large")
    if rate_cols:
        with cols[0]:
            st.caption("LLM別軸レース 勝率比較")
            st.bar_chart(chart_df.set_index("区分表示")[rate_cols])
    if "LLM優勢差" in chart_df.columns:
        with cols[1]:
            st.caption("LLM優勢差")
            st.bar_chart(chart_df.set_index("区分表示")[["LLM優勢差"]])


def _build_llm_disagreement_focus_payload(performance_df: pd.DataFrame | None) -> Dict[str, Any]:
    if performance_df is None or performance_df.empty or "区分" not in performance_df.columns:
        return {"best_segment": "", "best_edge": None, "edges": {}, "positive_segments": []}
    work = performance_df.copy()
    work = work[work["区分"].map(_to_text) != "別軸全体"].copy()
    if work.empty:
        return {"best_segment": "", "best_edge": None, "edges": {}, "positive_segments": []}
    work["_edge_num"] = pd.to_numeric(work["LLM優勢差"], errors="coerce")
    work["_count_num"] = pd.to_numeric(work["評価済みレース"], errors="coerce").fillna(0)
    edge_map = {
        _to_text(row.get("区分", "")): float(row["_edge_num"])
        for _, row in work.iterrows()
        if _to_text(row.get("区分", "")) and pd.notna(row["_edge_num"])
    }
    positive_segments = [
        _to_text(row.get("区分", ""))
        for _, row in work.sort_values(["_edge_num", "_count_num"], ascending=[False, False], na_position="last").iterrows()
        if pd.notna(row["_edge_num"]) and float(row["_edge_num"]) > 0.0 and _to_text(row.get("区分", ""))
    ]
    best_segment = positive_segments[0] if positive_segments else ""
    best_edge = edge_map.get(best_segment) if best_segment else None
    return {
        "best_segment": best_segment,
        "best_edge": best_edge,
        "edges": edge_map,
        "positive_segments": positive_segments,
    }


def _build_llm_disagreement_prompt_text(
    frame: pd.DataFrame | None,
    *,
    venue: Any = "",
    limit: int = 5,
) -> str:
    work = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    if work.empty:
        return "- 別軸レースなし"
    venue_text = _to_text(venue)
    if venue_text and "venue" in work.columns:
        filtered = work[work["venue"].map(_to_text) == venue_text].copy()
        if not filtered.empty:
            work = filtered
    if "LLM本命比較" in work.columns:
        work = work[work["LLM本命比較"].map(lambda value: "別軸" in _to_text(value))].copy()
    if work.empty:
        return "- 別軸レースなし"
    lines: List[str] = []
    for _, row in work.head(max(1, int(limit))).iterrows():
        lines.append(
            " / ".join(
                [
                    f"レース={_to_text(row.get('race_name', row.get('レース名', row.get('race_id', row.get('レースID', '-')))))}",
                    f"開催={_to_text(row.get('venue', row.get('開催', '-')))}",
                    f"データ本命={_to_text(row.get('top_horse', row.get('本命馬', '-')))}",
                    f"LLM本命={_to_text(row.get('llm_top_horse', row.get('LLM本命', '-')))}",
                    f"理由={_to_text(row.get('LLM別軸理由', '-'))}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- 別軸レースなし"


def _build_llm_disagreement_hit_prompt_text(
    feedback_df: pd.DataFrame | None,
    *,
    venue: Any = "",
    limit: int = 5,
) -> str:
    work = feedback_df.copy() if isinstance(feedback_df, pd.DataFrame) else pd.DataFrame()
    if work.empty:
        return "- LLM別軸ヒットなし"
    if "result_available" in work.columns:
        if work["result_available"].dtype == bool:
            work = work[work["result_available"]].copy()
        else:
            work = work[work["result_available"].map(lambda value: _to_text(value).lower() in {"true", "1"})].copy()
    if work.empty:
        return "- LLM別軸ヒットなし"
    venue_text = _to_text(venue)
    if venue_text and "venue" in work.columns:
        filtered = work[work["venue"].map(_to_text) == venue_text].copy()
        if not filtered.empty:
            work = filtered
    if "llm_disagreement" in work.columns:
        if work["llm_disagreement"].dtype == bool:
            work = work[work["llm_disagreement"]].copy()
        else:
            work = work[work["llm_disagreement"].map(lambda value: _to_text(value).lower() in {"true", "1"})].copy()
    if "llm_top_hit" in work.columns:
        if work["llm_top_hit"].dtype == bool:
            work = work[work["llm_top_hit"]].copy()
        else:
            work = work[work["llm_top_hit"].map(lambda value: _to_text(value).lower() in {"true", "1"})].copy()
    if work.empty:
        return "- LLM別軸ヒットなし"
    sort_cols = [col for col in ["race_date", "predicted_at", "race_id"] if col in work.columns]
    if sort_cols:
        work = work.sort_values(sort_cols, ascending=[False] * len(sort_cols), na_position="last")
    lines: List[str] = []
    for _, row in work.head(max(1, int(limit))).iterrows():
        lines.append(
            " / ".join(
                [
                    f"レース={_to_text(row.get('race_name', row.get('race_id', '-')))}",
                    f"開催={_to_text(row.get('venue', '-'))}",
                    f"データ本命={_to_text(row.get('top_horse', '-'))}",
                    f"LLM本命={_to_text(row.get('llm_top_horse', '-'))}",
                    f"勝ち馬={_to_text(row.get('actual_winner', '-'))}",
                    f"理由={_to_text(row.get('llm_disagreement_reason', '-'))}",
                ]
            )
        )
    return "\n".join(lines) if lines else "- LLM別軸ヒットなし"


def _build_llm_hit_focus_comment(performance_df: pd.DataFrame | None) -> str:
    focus_payload = _build_llm_disagreement_focus_payload(performance_df)
    best_segment = _to_text(focus_payload.get("best_segment", ""))
    best_edge = pd.to_numeric(pd.Series([focus_payload.get("best_edge")]), errors="coerce").iloc[0]
    if best_segment and pd.notna(best_edge) and float(best_edge) > 0:
        return f"LLM別軸ヒットは `{best_segment}` 型で強めです。別軸優先カードもこの型を先に上へ出しています。"
    return ""


def _build_llm_hit_weekly_summary(performance_df: pd.DataFrame | None) -> Dict[str, Any]:
    focus_payload = _build_llm_disagreement_focus_payload(performance_df)
    best_segment = _to_text(focus_payload.get("best_segment", ""))
    best_edge = pd.to_numeric(pd.Series([focus_payload.get("best_edge")]), errors="coerce").iloc[0]
    if not best_segment or pd.isna(best_edge) or float(best_edge) <= 0:
        return {}
    basis_map = {
        "穴寄り": "trend",
        "人気逆張り": "trend",
        "危険視": "analog",
        "補正重視": "analog",
        "見方差": "base",
    }
    basis_key = basis_map.get(best_segment, "base")
    if best_segment in {"穴寄り", "人気逆張り"}:
        summary = f"今週は LLM別軸ヒットが `{best_segment}` 型で強く、データ本命と割れた時の逆張りが機能しています。"
        bet_memo = "単勝一点よりも、ワイドや複勝で別軸馬を拾いながら単勝を薄く添える買い方が向きます。"
    elif best_segment in {"危険視", "補正重視"}:
        summary = f"今週は LLM別軸ヒットが `{best_segment}` 型で強く、危険視や補正寄りの読みがハマっています。"
        bet_memo = "本命の過信を避けて、ワイドや三連複の相手軸を広めに取る見方が合いやすい週です。"
    else:
        summary = f"今週は LLM別軸ヒットが `{best_segment}` 型で優勢です。別軸の見方差を活かす余地があります。"
        bet_memo = "ベース配分を土台にしつつ、相手候補だけ少し広げて差を拾う見方がしやすい流れです。"
    return {
        "title": "LLM別軸ヒット傾向",
        "summary": summary,
        "bet_memo": bet_memo,
        "best_segment": best_segment,
        "best_edge": float(best_edge),
        "basis_key": basis_key,
        "basis_label": _format_budget_basis_label(basis_key),
        "chips": [
            f"優勢区分 {best_segment}",
            f"LLM優勢差 {_format_signed_rate_metric(best_edge)}",
            f"配分ヒント {_format_budget_basis_label(basis_key)}",
        ],
    }


def _render_llm_hit_weekly_card(
    summary: Dict[str, Any] | None,
    *,
    trend_summary: Dict[str, Any] | None = None,
    allow_apply: bool = False,
    button_prefix: str = "llm_hit_weekly",
) -> None:
    if not isinstance(summary, dict) or not _to_text(summary.get("title", "")):
        return
    best_edge = pd.to_numeric(pd.Series([summary.get("best_edge")]), errors="coerce").iloc[0]
    severity_class = "strong" if pd.notna(best_edge) and float(best_edge) >= 0.18 else "moderate"
    basis_label = _to_text(summary.get("basis_label", "")) or _format_budget_basis_label(summary.get("basis_key", ""))
    bet_memo = _to_text(summary.get("bet_memo", "")) or ""
    highlight_text = ""
    if basis_label:
        if pd.notna(best_edge):
            highlight_text = f"今週は `{basis_label}` を少し強めに見る余地があります。"
        else:
            highlight_text = f"今週は `{basis_label}` 寄りで見直す余地があります。"
    chips = summary.get("chips", [])
    chip_html = ""
    if isinstance(chips, list) and chips:
        chip_html = "<div class='feedback-trend-row'>" + "".join(
            f"<span class='feedback-trend-chip'>{html_escape(_to_text(chip))}</span>"
            for chip in chips
            if _to_text(chip)
        ) + "</div>"
    basis_key = _normalize_budget_basis_key(summary.get("basis_key", ""))
    recommended_bets, avoid_bets = _build_budget_basis_bet_guidance(basis_key or "base", trend_summary)
    segment_class = _llm_bucket_style_class(summary.get("best_segment", ""))
    badge_html = ""
    if recommended_bets or avoid_bets:
        badge_parts: List[str] = []
        badge_parts.extend(
            f"<span class='llm-hit-badge recommend {segment_class}'>寄せ {_to_text(bet)}</span>"
            for bet in recommended_bets[:3]
            if _to_text(bet)
        )
        badge_parts.extend(
            f"<span class='llm-hit-badge avoid {segment_class}'>抑え {_to_text(bet)}</span>"
            for bet in avoid_bets[:2]
            if _to_text(bet)
        )
        if badge_parts:
            badge_html = "<div class='llm-hit-badge-row'>" + "".join(badge_parts) + "</div>"
    stance_html = ""
    if recommended_bets or avoid_bets:
        stance_html = """
<div class="feedback-trend-stance-grid" style="margin-top:0.55rem;">
  <div class="feedback-trend-stance-card {segment_class}">
    <div class="feedback-trend-stance-title">今週おすすめ券種</div>
    <div class="feedback-trend-stance-text">{recommended}</div>
  </div>
  <div class="feedback-trend-stance-card {segment_class}">
    <div class="feedback-trend-stance-title">抑えたい券種</div>
    <div class="feedback-trend-stance-text">{avoid}</div>
  </div>
</div>
""".format(
            segment_class=segment_class,
            recommended=html_escape(" / ".join(recommended_bets[:3]) if recommended_bets else "-"),
            avoid=html_escape(" / ".join(avoid_bets[:3]) if avoid_bets else "特になし"),
        )
    st.markdown(
        """
<div class="memo-card llm-hit-card {severity_class}">
  <div class="memo-chip">LLM別軸ヒット</div>
  <div class="memo-title">{title}</div>
  <div class="memo-line"><strong>要点:</strong> {summary}</div>
  {highlight}
  {bet_memo}
  {badges}
  {stance}
  {chips}
</div>
""".format(
            severity_class=severity_class,
            title=html_escape(_to_text(summary.get("title", ""))),
            summary=html_escape(_to_text(summary.get("summary", "")) or "-"),
            highlight=(
                f"<div class='llm-hit-highlight'>{html_escape(highlight_text)}</div>"
                if highlight_text
                else ""
            ),
            bet_memo=(
                f"<div class='memo-line'><strong>買い方メモ:</strong> {html_escape(bet_memo)}</div>"
                if bet_memo
                else ""
            ),
            badges=badge_html,
            stance=stance_html,
            chips=chip_html,
        ),
        unsafe_allow_html=True,
    )
    if allow_apply:
        if basis_key in {"trend", "analog", "base"}:
            apply_cols = st.columns(4, gap="small")
            current_key = _to_text(st.session_state.get("budget_basis_choice", "trend")) or "trend"
            auto_enabled = bool(st.session_state.get("budget_basis_auto_enabled", True))
            if apply_cols[0].button(
                f"{basis_label}を標準採用",
                key=f"{button_prefix}_apply_manual",
                width="stretch",
                disabled=(not auto_enabled and current_key == basis_key),
            ):
                _apply_budget_basis_from_ui(
                    basis_key,
                    summary=trend_summary,
                    auto_mode=False,
                    source_label="LLM別軸ヒット傾向",
                )
                st.rerun()
            if apply_cols[1].button(
                "半自動でこの傾向を優先",
                key=f"{button_prefix}_apply_auto",
                width="stretch",
                disabled=(auto_enabled and current_key == basis_key),
            ):
                _apply_budget_basis_from_ui(
                    basis_key,
                    summary=trend_summary,
                    auto_mode=True,
                    source_label="LLM別軸ヒット傾向",
                )
                st.rerun()
            top_bet = _to_text(recommended_bets[0]) if recommended_bets else ""
            if top_bet:
                if apply_cols[2].button(
                    f"{top_bet}を見る",
                    key=f"{button_prefix}_jump_bet",
                    width="stretch",
                ):
                    _request_open_bets_tab(top_bet)
                    st.rerun()
            else:
                apply_cols[2].caption("おすすめ券種なし")
            apply_cols[3].caption(f"配分ヒント: {basis_label}")


def _render_weekly_llm_alignment_banner(label: Any, *, large: bool = False) -> str:
    text = _to_text(label) or "⚪ 未判定"
    if "一致" in text:
        class_name = "agree"
    elif "別軸" in text:
        class_name = "diff"
    else:
        class_name = "pending"
    size_class = " large" if large else ""
    return (
        f"<div class='weekly-llm-banner {class_name}{size_class}'>"
        f"<span>LLM本命比較</span><span>{html_escape(text)}</span>"
        "</div>"
    )


def _llm_alignment_sort_priority(value: Any) -> int:
    text = _to_text(value)
    if "別軸" in text:
        return 0
    if "一致" in text:
        return 1
    return 2


def _apply_llm_alignment_view_mode(
    frame: pd.DataFrame,
    mode: Any,
    *,
    comparison_col: str = "LLM本命比較",
    race_id_col: str = "レースID",
    race_date_col: str = "日付",
    venue_col: str = "開催",
) -> pd.DataFrame:
    if frame.empty or comparison_col not in frame.columns:
        return frame
    mode_text = _to_text(mode)
    work = frame.copy()
    if mode_text == "別軸だけ":
        work = work[work[comparison_col].map(lambda value: "別軸" in _to_text(value))].copy()
        return _sort_program_order_frame(work, race_id_col=race_id_col, race_date_col=race_date_col, venue_col=venue_col)
    work = _sort_program_order_frame(work, race_id_col=race_id_col, race_date_col=race_date_col, venue_col=venue_col)
    if mode_text == "別軸を上に集める":
        work["_llm_alignment_priority"] = work[comparison_col].map(_llm_alignment_sort_priority)
        work = work.sort_values(["_llm_alignment_priority"], ascending=[True], kind="mergesort")
        work = work.drop(columns=["_llm_alignment_priority"], errors="ignore")
    return work


def _render_danger_cards(frame: pd.DataFrame, limit: int = 4) -> None:
    if frame.empty:
        return
    if "危険人気馬" not in frame.columns and "LLM危険人気" not in frame.columns:
        st.markdown(
            """
<div class="danger-grid">
  <div class="danger-card">
    <div class="danger-chip">危険人気</div>
    <div class="danger-title">市場データ不足</div>
    <div class="danger-line"><strong>状態:</strong> 人気やオッズが未取得のため未判定です。</div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        return
    work = frame.copy()
    if "危険人気馬" not in work.columns:
        work["危険人気馬"] = "-"
    if "LLM危険人気" not in work.columns:
        work["LLM危険人気"] = "-"
    if "LLM本命" not in work.columns:
        work["LLM本命"] = "-"
    work["危険人気馬"] = work["危険人気馬"].map(_to_text)
    work["LLM危険人気"] = work["LLM危険人気"].map(_to_text)
    work["LLM本命"] = work["LLM本命"].map(_to_text)
    work = work[
        ((work["危険人気馬"] != "") & (work["危険人気馬"] != "-"))
        | ((work["LLM危険人気"] != "") & (work["LLM危険人気"] != "-"))
    ].head(max(1, int(limit)))
    if work.empty:
        st.markdown(
            """
<div class="danger-grid">
  <div class="danger-card">
    <div class="danger-chip">危険人気</div>
    <div class="danger-title">市場データ不足</div>
    <div class="danger-line"><strong>状態:</strong> 今回は人気/オッズの実データ不足で危険人気を未判定にしています。</div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        return

    cards: List[str] = []
    for _, row in work.iterrows():
        market_danger = _to_text(row.get("危険人気馬", "-")) or "-"
        llm_danger = _to_text(row.get("LLM危険人気", "-")) or "-"
        danger_sync = _build_llm_danger_sync_label(market_danger, llm_danger)
        chip_label = "危険人気"
        if market_danger != "-" and llm_danger != "-":
            chip_label = "危険人気 + LLM"
        elif market_danger == "-" and llm_danger != "-":
            chip_label = "LLM危険人気"
        danger_line = (
            f"市場 {_render_name_text(market_danger)} / LLM {_render_name_text(llm_danger)}"
            if market_danger != "-" and llm_danger != "-"
            else _render_name_text(market_danger if market_danger != "-" else llm_danger)
        )
        cards.append(
            """
<div class="danger-card">
  <div class="danger-chip">{chip}</div>
  <div class="danger-title">{title}</div>
  <div class="danger-line"><strong>危険人気:</strong> {horse} {pop}</div>
  <div class="danger-line"><strong>同期状況:</strong> {sync}</div>
  <div class="danger-line"><strong>本命/LLM本命:</strong> {favorite} / {llm_favorite}</div>
  <div class="danger-line"><strong>大穴:</strong> {longshot}</div>
  <div class="danger-line"><strong>勝率/複勝率:</strong> {win_prob} / {place_prob}</div>
</div>
""".format(
                chip=html_escape(chip_label if chip_label else _to_text(row.get("格付", "重賞"))),
                title=html_escape(_to_text(row.get("レース", row.get("レース名", "-")))),
                horse=html_escape(danger_line),
                pop=html_escape(_to_text(row.get("危険人気", "-"))),
                sync=html_escape(danger_sync),
                favorite=html_escape(_render_name_text(row.get("本命馬", "-"))),
                llm_favorite=html_escape(_render_name_text(row.get("LLM本命", "-"))),
                longshot=html_escape(_render_name_text(row.get("大穴候補", "-"))),
                win_prob=html_escape(_to_text(row.get("勝率", "-"))),
                place_prob=html_escape(_to_text(row.get("複勝率", "-"))),
            )
        )
    st.markdown("<div class='danger-grid'>" + "".join(cards) + "</div>", unsafe_allow_html=True)


def _render_llm_priority_cards(
    frame: pd.DataFrame,
    source_entries_df: pd.DataFrame | None,
    *,
    performance_df: pd.DataFrame | None = None,
    llm_hit_summary: Dict[str, Any] | None = None,
    limit: int = 3,
    simulations_per_race: int = 4000,
    seed: int = 42,
) -> None:
    if frame.empty or "LLM本命比較" not in frame.columns:
        return
    work = frame[frame["LLM本命比較"].map(lambda value: "別軸" in _to_text(value))].copy()
    if work.empty:
        return
    focus_payload = _build_llm_disagreement_focus_payload(performance_df)
    best_segment = _to_text(focus_payload.get("best_segment", ""))
    best_edge = pd.to_numeric(pd.Series([focus_payload.get("best_edge")]), errors="coerce").iloc[0]
    hit_summary = llm_hit_summary if isinstance(llm_hit_summary, dict) and llm_hit_summary else _build_llm_hit_weekly_summary(performance_df)
    hit_best_segment = _to_text((hit_summary or {}).get("best_segment", ""))
    hit_best_edge = pd.to_numeric(pd.Series([(hit_summary or {}).get("best_edge")]), errors="coerce").iloc[0]
    edge_map = focus_payload.get("edges", {}) if isinstance(focus_payload.get("edges", {}), dict) else {}
    work["LLM別軸区分"] = work.get("LLM別軸理由", pd.Series(dtype=object)).map(_classify_llm_disagreement_bucket)
    work["_llm_edge_score"] = work["LLM別軸区分"].map(lambda value: float(edge_map.get(_to_text(value), 0.0) or 0.0))
    work["_llm_focus_bonus"] = work["LLM別軸区分"].map(lambda value: 1 if _to_text(value) == best_segment and best_segment else 0)
    work["_llm_hit_bonus"] = work["LLM別軸区分"].map(
        lambda value: 2 if _to_text(value) == hit_best_segment and hit_best_segment and pd.notna(hit_best_edge) and float(hit_best_edge) >= 0.18 else 0
    )
    work = work.sort_values(
        ["_llm_hit_bonus", "_llm_focus_bonus", "_llm_edge_score"],
        ascending=[False, False, False],
        kind="mergesort",
    )
    st.caption("LLMが別軸で見ているので先に確認したいレース")
    if best_segment and pd.notna(best_edge) and float(best_edge) > 0:
        st.caption(f"今は `{best_segment}` 型で LLM優勢差 {_format_signed_rate_metric(best_edge)} が出ているため、この型を先に上へ集めています。")
    if hit_best_segment and pd.notna(hit_best_edge) and float(hit_best_edge) >= 0.18:
        st.caption(
            f"今週は `LLM別軸ヒット傾向` でも `{hit_best_segment}` 型が {_format_signed_rate_metric(hit_best_edge)} と強いため、"
            " その区分をさらに先頭側へ寄せています。"
        )
    def _render_priority_rows(display_df: pd.DataFrame, *, key_prefix: str) -> None:
        if display_df.empty:
            st.caption("該当レースなし")
            return
        cards = st.columns(1 if len(display_df.head(limit)) == 1 else 2, gap="medium")
        for idx, (_, row) in enumerate(display_df.head(max(1, int(limit))).iterrows()):
            with cards[idx % len(cards)]:
                llm_reason_html = _render_llm_reason_tags_html(row.get("LLM別軸理由", "-"))
                reason_bucket = _to_text(row.get("LLM別軸区分", ""))
                bucket_class = _llm_bucket_style_class(reason_bucket)
                edge_text = _format_signed_rate_metric(row.get("_llm_edge_score"))
                bet_badges_html = _render_llm_bucket_bet_badges_html(reason_bucket)
                st.markdown(
                    """
<div class="memo-card llm-priority-card {bucket_class}">
  <div class="memo-chip {bucket_class}">LLM別軸</div>
  <div class="memo-title">{title}</div>
  <div class="memo-line"><strong>データ本命:</strong> {data_top}</div>
  <div class="memo-line"><strong>LLM本命:</strong> {llm_top}</div>
  <div class="memo-line"><strong>LLM穴/危険:</strong> {llm_dark} / {llm_danger}</div>
  <div class="memo-line"><strong>優先根拠:</strong> {bucket} / 優勢差 {edge}</div>
  {bet_badges}
  {reason_tags}
</div>
""".format(
                        bucket_class=html_escape(bucket_class),
                        title=html_escape(_to_text(row.get("レース", row.get("レースID", "-"))) or "-"),
                        data_top=html_escape(_render_name_text(row.get("本命馬", "-"))),
                        llm_top=html_escape(_render_name_text(row.get("LLM本命", "-"))),
                        llm_dark=html_escape(_render_name_text(row.get("LLM穴", "-"))),
                        llm_danger=html_escape(_render_name_text(row.get("LLM危険人気", "-"))),
                        bucket=html_escape(reason_bucket or "見方差"),
                        edge=html_escape(edge_text),
                        bet_badges=bet_badges_html,
                        reason_tags=llm_reason_html,
                    ),
                    unsafe_allow_html=True,
                )
                action_cols = st.columns(2, gap="small")
                with action_cols[0]:
                    if st.button("この別軸レースを詳細表示", key=f"{key_prefix}_open_{_to_text(row.get('レースID', idx))}_{idx}"):
                        _queue_weekly_display_row(row, source_entries_df)
                with action_cols[1]:
                    if st.button("このレースだけ再計算", key=f"{key_prefix}_refresh_{_to_text(row.get('レースID', idx))}_{idx}"):
                        try:
                            _refresh_weekly_display_row(
                                row,
                                source_entries_df=source_entries_df,
                                simulations_per_race=int(simulations_per_race),
                                seed=int(seed),
                                notice_prefix="LLM別軸レース再計算",
                            )
                        except Exception as exc:
                            st.error(f"別軸レースの再計算に失敗しました: {exc}")

    preferred_segments = [hit_best_segment, best_segment, "穴寄り", "危険視", "補正重視", "人気逆張り", "見方差"]
    available_segments = [
        seg for seg in preferred_segments
        if seg and seg in set(work["LLM別軸区分"].map(_to_text).tolist())
    ]
    dedup_segments: List[str] = []
    for seg in available_segments:
        if seg not in dedup_segments:
            dedup_segments.append(seg)

    tab_labels = ["優先"] + dedup_segments
    tabs = st.tabs(tab_labels)
    with tabs[0]:
        if hit_best_segment and pd.notna(hit_best_edge):
            st.caption(_build_llm_bucket_explanation(hit_best_segment, edge=hit_best_edge))
            st.markdown(_render_llm_bucket_bet_badges_html(hit_best_segment), unsafe_allow_html=True)
            _render_llm_segment_stats(_lookup_llm_disagreement_segment_stats(performance_df, hit_best_segment))
        elif best_segment and pd.notna(best_edge):
            st.caption(_build_llm_bucket_explanation(best_segment, edge=best_edge))
            st.markdown(_render_llm_bucket_bet_badges_html(best_segment), unsafe_allow_html=True)
            _render_llm_segment_stats(_lookup_llm_disagreement_segment_stats(performance_df, best_segment))
        _render_priority_rows(work, key_prefix="weekly_llm_priority_all")
    for tab_idx, segment in enumerate(dedup_segments, start=1):
        with tabs[tab_idx]:
            segment_edge = float(edge_map.get(segment, 0.0) or 0.0)
            st.caption(_build_llm_bucket_explanation(segment, edge=segment_edge))
            st.markdown(_render_llm_bucket_bet_badges_html(segment), unsafe_allow_html=True)
            _render_llm_segment_stats(_lookup_llm_disagreement_segment_stats(performance_df, segment))
            segment_df = work[work["LLM別軸区分"].map(_to_text) == segment].copy()
            _render_priority_rows(segment_df, key_prefix=f"weekly_llm_priority_{segment}")


def _queue_selected_race_for_prediction(
    *,
    race_id: Any,
    source_entries_df: pd.DataFrame | None,
    label: Any = "",
    venue: Any = "",
    field_size: Any = "",
) -> None:
    _set_selected_race_context_state(
        race_id=race_id,
        source_entries_df=source_entries_df,
        label=label,
        venue=venue,
        field_size=field_size,
    )
    st.rerun()


def _set_selected_race_context_state(
    *,
    race_id: Any,
    source_entries_df: pd.DataFrame | None,
    label: Any = "",
    venue: Any = "",
    field_size: Any = "",
) -> None:
    selected_race_id = _to_text(race_id)
    if not selected_race_id:
        return
    selected_context: Dict[str, Any] = {}
    if isinstance(source_entries_df, pd.DataFrame):
        selected_context = _extract_race_context(source_entries_df, selected_race_id)
    if not selected_context:
        selected_context = {
            "race_id": selected_race_id,
            "race_date": "",
            "race_name": "",
            "venue": _to_text(venue),
            "weather": "",
            "track_condition": "",
            "distance": "",
            "field_size": _to_text(field_size),
            "label": _to_text(label) or selected_race_id,
        }
    st.session_state["pending_selected_race_context"] = selected_context
    st.session_state["run_predict_mode"] = "selected_race"


def _queue_weekly_display_row(row: pd.Series, source_entries_df: pd.DataFrame | None) -> None:
    _queue_selected_race_for_prediction(
        race_id=row.get("レースID", row.get("race_id", "")),
        source_entries_df=source_entries_df,
        label=row.get("レース", row.get("label", "")),
        venue=row.get("開催", row.get("venue", "")),
        field_size=row.get("頭数", row.get("field_size", "")),
    )


def _refresh_weekly_display_row(
    row: pd.Series,
    *,
    source_entries_df: pd.DataFrame | None,
    simulations_per_race: int,
    seed: int,
    notice_prefix: str = "選択レース再計算",
) -> None:
    refreshed = _refresh_selected_weekly_prediction(
        _to_text(row.get("レースID", row.get("race_id", ""))),
        simulations_per_race=int(simulations_per_race),
        seed=int(seed),
    )
    _set_ui_notice(_build_weekly_notice_message(notice_prefix, refreshed.iloc[0]))
    _queue_weekly_display_row(row, source_entries_df)


def _weekly_card_win_rate_value(row: pd.Series) -> float:
    raw = _to_text(row.get("勝率", "")).replace("%", "").strip()
    if not raw:
        return 0.0
    value = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
    if pd.isna(value):
        return 0.0
    value_float = float(value)
    return value_float / 100.0 if value_float > 1.0 else value_float


def _weekly_card_race_number(row: pd.Series) -> int:
    return _race_number_from_id(row.get("レースID", ""))


def _build_weekly_notice_message(prefix: str, row: pd.Series | Dict[str, Any]) -> str:
    return weekly_notice_message(prefix, row)


def _pick_weekly_notice_row(frame: pd.DataFrame, preferred_race_id: Any = "") -> pd.Series:
    return weekly_notice_row(frame, preferred_race_id)


def _sort_weekly_card_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    work = frame.copy()
    work["_sort_day"] = work.apply(lambda row: _parse_date_text(row.get("日付", "")) or date.min, axis=1)
    work["_sort_race_no"] = work.apply(_weekly_card_race_number, axis=1)
    work["_sort_win"] = work.apply(_weekly_card_win_rate_value, axis=1)
    work = work.sort_values(["_sort_day", "_sort_race_no", "_sort_win"], ascending=[False, False, False])
    return work.drop(columns=["_sort_day", "_sort_race_no", "_sort_win"], errors="ignore")


def _build_weekly_race_card_html(row: pd.Series) -> str:
    chip_html = "".join(
        [
            f"<span class='weekly-race-chip grade'>{html_escape(_to_text(row.get('格付', '-')) or '-')}</span>",
            f"<span class='weekly-race-chip'>{html_escape(_to_text(row.get('開催', '-')) or '-')}</span>",
            f"<span class='weekly-race-chip'>{html_escape(_to_text(row.get('日付', '-')) or '-')}</span>",
        ]
    )
    meta_cards = [
        ("レース順", _format_race_no_text(row.get("レースID", ""))),
        ("距離", _to_text(row.get("距離", "-")) or "-"),
        ("馬場", _to_text(row.get("馬場", "-")) or "-"),
        ("頭数", f"{_to_text(row.get('頭数', '-'))}頭" if _to_text(row.get("頭数", "")) else "-"),
    ]
    if _to_text(row.get("本命人気", "")):
        meta_cards.append(("本命人気", _to_text(row.get("本命人気", "-")) or "-"))
    if _to_text(row.get("補正本数", "")):
        meta_cards.append(("条件補正", _to_text(row.get("補正本数", "-")) or "-"))
    if _to_text(row.get("買い方方針", "")) and _to_text(row.get("買い方方針", "")) != "-":
        meta_cards.append(("買い方方針", _to_text(row.get("買い方方針", "-")) or "-"))
    llm_alignment = _build_llm_top_alignment_label(
        row.get("本命馬", row.get("top_horse", "-")),
        row.get("LLM本命", row.get("llm_top_horse", "-")),
    )
    llm_alignment_banner = _render_weekly_llm_alignment_banner(llm_alignment) if llm_alignment != "⚪ 未判定" else ""
    llm_reason = _build_llm_disagreement_reason(row)
    if llm_alignment != "⚪ 未判定":
        meta_cards.append(("LLM本命比較", llm_alignment))
    if llm_reason not in {"", "-", "データ本命と一致"}:
        meta_cards.append(("LLM別軸理由", llm_reason))
    expectation_html = """
<div class="weekly-race-expectation">
  <div class="weekly-race-expectation-title">券種期待度</div>
  {badges}
</div>
""".format(badges=_render_strategy_expectation_badges_html(row.get("買い方方針", "")))
    meta_html = "".join(
        """
<div class="weekly-race-meta-card">
  <span class="weekly-race-meta-label">{label}</span>
  <div class="weekly-race-meta-value">{value}</div>
</div>
""".format(
            label=html_escape(label),
            value=(
                _render_llm_reason_tags_html(value)
                if label == "LLM別軸理由"
                else html_escape(value)
            ),
        )
        for label, value in meta_cards
    )
    ticket_text = "単勝 {single} / 馬連 {quinella} / 三連単 {trifecta}".format(
        single=_render_name_text(_to_text(row.get("単勝候補", "-"))),
        quinella=_render_name_text(_to_text(row.get("馬連候補", "-"))),
        trifecta=_render_name_text(_to_text(row.get("三連単候補", "-"))),
    )
    llm_text = ""
    llm_top = _render_name_text(_to_text(row.get("LLM本命", row.get("llm_top_horse", "-"))))
    llm_dark = _render_name_text(_to_text(row.get("LLM穴", row.get("llm_dark_horse", "-"))))
    llm_danger = _render_name_text(_to_text(row.get("LLM危険人気", row.get("llm_danger_favorite", "-"))))
    llm_source = _to_text(row.get("LLMソース", row.get("llm_pick_source", "")))
    if any(item not in {"", "-"} for item in [llm_top, llm_dark, llm_danger]):
        llm_text = "LLM 本命 {top} / 穴 {dark} / 危険 {danger}{source}".format(
            top=llm_top or "-",
            dark=llm_dark or "-",
            danger=llm_danger or "-",
            source=f" / {llm_source}" if llm_source and llm_source != "-" else "",
        )
        if llm_reason not in {"", "-", "データ本命と一致"}:
            llm_text += f" / 理由 {llm_reason}"
    return """
<div class="weekly-race-card">
  <div class="weekly-race-chiprow">{chips}</div>
  {llm_alignment_banner}
  <div class="weekly-race-title">{title}</div>
  <div class="weekly-race-meta">{meta}</div>
  <div class="weekly-race-meta-grid">{meta_cards}</div>
  <div class="weekly-race-ticket">{expectation}</div>
  <div class="weekly-race-picks">
    <div class="weekly-race-pick"><strong>◎</strong> {favorite}</div>
    <div class="weekly-race-pick"><strong>○</strong> {rival}</div>
    <div class="weekly-race-pick"><strong>▲</strong> {longshot}</div>
    <div class="weekly-race-pick"><strong>危</strong> {danger}</div>
  </div>
  {llm_block}
  <div class="weekly-race-ticket">{ticket}</div>
</div>
""".format(
        chips=chip_html,
        llm_alignment_banner=llm_alignment_banner,
        title=html_escape(_to_text(row.get("レース", row.get("レースID", "-"))) or "-"),
        meta=html_escape(
            "頭数 {field} / 勝率 {win} / 複勝率 {place}".format(
                field=_to_text(row.get("頭数", "-")) or "-",
                win=_to_text(row.get("勝率", "-")) or "-",
                place=_to_text(row.get("複勝率", "-")) or "-",
            )
        ),
        meta_cards=meta_html,
        expectation=expectation_html,
        favorite=html_escape(_render_name_text(row.get("◎", row.get("本命馬", "-")))),
        rival=html_escape(_render_name_text(row.get("○", "-"))),
        longshot=html_escape(_render_name_text(row.get("▲", row.get("大穴候補", "-")))),
        danger=html_escape(_render_name_text(row.get("危険人気馬", "-"))),
        llm_block=(
            "<div class='weekly-race-ticket'>"
            + html_escape(llm_text)
            + "</div>"
            if llm_text
            else ""
        ),
        ticket=html_escape(ticket_text),
    )


def _build_program_strategy_focus_html(
    row: pd.Series | Dict[str, Any],
    *,
    budget_total: int,
    bet_units: int,
    caution_bets: str,
) -> str:
    strategy = _to_text(row.get("買い方方針", "-")) or "-"
    main_bet = _render_name_text(row.get("単勝候補", "-"))
    support_bet = _render_name_text(row.get("ワイド候補", row.get("複勝候補", "-")))
    attack_bet = _render_name_text(row.get("三連単候補", row.get("三連複候補", "-")))
    total_budget = max(int(bet_units), int(budget_total) if int(budget_total) > 0 else int(bet_units) * 10)
    unit_value = max(int(bet_units), 100)
    if "ワイド" in strategy:
        main_ratio, support_ratio, attack_ratio = 0.45, 0.30, 0.25
    elif "単勝" in strategy or "頭" in strategy:
        main_ratio, support_ratio, attack_ratio = 0.45, 0.22, 0.33
    elif "三連複" in strategy:
        main_ratio, support_ratio, attack_ratio = 0.30, 0.25, 0.45
    elif "複勝" in strategy or "保守" in strategy:
        main_ratio, support_ratio, attack_ratio = 0.35, 0.40, 0.25
    else:
        main_ratio, support_ratio, attack_ratio = 0.34, 0.33, 0.33

    def _round_amount(value: float) -> int:
        return int(max(unit_value, round(float(value) / unit_value) * unit_value))

    main_amount = _round_amount(total_budget * main_ratio)
    support_amount = _round_amount(total_budget * support_ratio)
    attack_amount = max(unit_value, total_budget - main_amount - support_amount)
    ratio_text = f"本線 {int(round(main_ratio * 100))}% / 押さえ {int(round(support_ratio * 100))}% / 穴 {int(round(attack_ratio * 100))}%"
    expectation_html = _render_strategy_expectation_badges_html(strategy)
    allocation_bar = """
<div class="feedback-trend-allocation">
  <span class="feedback-trend-allocation-segment main" style="width:{main_width}%"></span>
  <span class="feedback-trend-allocation-segment cover" style="width:{cover_width}%"></span>
  <span class="feedback-trend-allocation-segment hole" style="width:{hole_width}%"></span>
</div>
""".format(
        main_width=html_escape(str(int(round(main_ratio * 100)))),
        cover_width=html_escape(str(int(round(support_ratio * 100)))),
        hole_width=html_escape(str(int(round(attack_ratio * 100)))),
    )
    return """
<div class="feedback-trend-stance">
  <div class="feedback-trend-stance-card">
    <div class="feedback-trend-stance-title">開催別の買い方方針</div>
    <div class="feedback-trend-stance-value">{strategy}</div>
  </div>
  <div class="feedback-trend-stance-card">
    <div class="feedback-trend-stance-title">主軸候補</div>
    <div class="feedback-trend-stance-value">{main_bet}<br>{main_amount}</div>
  </div>
  <div class="feedback-trend-stance-card">
    <div class="feedback-trend-stance-title">補助候補</div>
    <div class="feedback-trend-stance-value">{support_bet}<br>{support_amount}</div>
  </div>
  <div class="feedback-trend-stance-card">
    <div class="feedback-trend-stance-title">攻め筋 / 1レース目安</div>
    <div class="feedback-trend-stance-value">{attack_bet}<br>{attack_amount}</div>
  </div>
  <div class="feedback-trend-stance-card">
    <div class="feedback-trend-stance-title">抑えたい券種</div>
    <div class="feedback-trend-stance-value">{caution_bets}</div>
  </div>
  <div class="feedback-trend-stance-card">
    <div class="feedback-trend-stance-title">配分割合</div>
    <div class="feedback-trend-stance-value">{ratio_text}</div>
    {allocation_bar}
  </div>
  <div class="feedback-trend-stance-card">
    <div class="feedback-trend-stance-title">券種ごとの期待度</div>
    <div class="feedback-trend-stance-value">買い方方針から見た優先度</div>
    {expectation_html}
  </div>
</div>
""".format(
        strategy=html_escape(strategy),
        main_bet=html_escape(main_bet),
        support_bet=html_escape(support_bet),
        attack_bet=html_escape(attack_bet),
        main_amount=html_escape(f"{main_amount:,}円"),
        support_amount=html_escape(f"{support_amount:,}円"),
        attack_amount=html_escape(f"{attack_amount:,}円"),
        caution_bets=html_escape(_to_text(caution_bets) or "-"),
        ratio_text=html_escape(ratio_text),
        allocation_bar=allocation_bar,
        expectation_html=expectation_html,
    )


def _render_weekly_race_cards(
    frame: pd.DataFrame,
    source_entries_df: pd.DataFrame | None,
    *,
    limit: int = 6,
    simulations_per_race: int = 4000,
    seed: int = 42,
) -> None:
    if frame.empty or "レースID" not in frame.columns:
        return
    st.caption("注目レースカード")
    work = _sort_weekly_card_frame(frame)
    main_race_id = _pick_main_race_id(work, "レースID")
    main_row = pd.DataFrame()
    if main_race_id:
        main_row = work[work["レースID"].map(_to_text) == main_race_id].head(1).copy()
    if not main_row.empty:
        main_race = main_row.iloc[0]
        main_action_cols = st.columns([1.2, 1.25, 3.0], gap="small")
        with main_action_cols[0]:
            if st.button("メインレースへ", type="primary", key=f"weekly_cards_main_{main_race_id}"):
                _queue_weekly_display_row(main_race, source_entries_df)
        with main_action_cols[1]:
            if st.button("メインだけ再計算", key=f"weekly_cards_main_refresh_{main_race_id}"):
                try:
                    _refresh_weekly_display_row(
                        main_race,
                        source_entries_df=source_entries_df,
                        simulations_per_race=int(simulations_per_race),
                        seed=int(seed),
                        notice_prefix="メインレース再計算",
                    )
                except Exception as exc:
                    st.error(f"メインレース再計算に失敗しました: {exc}")
        with main_action_cols[2]:
            st.caption(
                "週のメイン想定: "
                f"{_to_text(main_race.get('レース', '-'))} / "
                f"本命 {_to_text(main_race.get('本命馬', '-'))} / "
                f"大穴 {_to_text(main_race.get('大穴候補', '-'))} / "
                f"条件補正 {_to_text(main_race.get('補正本数', '-'))}"
            )
    g1_rows = work[work["格付"] == "G1"].copy() if "格付" in work.columns else pd.DataFrame()
    featured_race_id = ""
    if not g1_rows.empty:
        featured_row = g1_rows.iloc[0]
        featured_race_id = _to_text(featured_row.get("レースID", ""))
        featured_llm_alignment = _build_llm_top_alignment_label(
            featured_row.get("本命馬", "-"),
            featured_row.get("LLM本命", "-"),
        )
        featured_llm_reason = _build_llm_disagreement_reason(featured_row)
        featured_llm_banner = (
            _render_weekly_llm_alignment_banner(featured_llm_alignment, large=True)
            if featured_llm_alignment != "⚪ 未判定"
            else ""
        )
        feature_expectation_html = """
<div class="weekly-race-expectation">
  <div class="weekly-race-expectation-title">券種期待度</div>
  {badges}
</div>
""".format(badges=_render_strategy_expectation_badges_html(featured_row.get("買い方方針", "")))
        feature_html = """
<div class="weekly-feature-card">
  <div class="weekly-race-chiprow">
    <span class="weekly-race-chip grade">G1</span>
    <span class="weekly-race-chip">今週メインレース</span>
    <span class="weekly-race-chip">{day}</span>
  </div>
  {llm_banner}
  <div class="weekly-feature-title">{title}</div>
  <div class="weekly-feature-sub">週末のメイン想定。G1 を最上段固定で表示しています。</div>
  <div class="weekly-feature-grid">
    <div class="weekly-feature-item"><strong>本命</strong>{favorite}</div>
    <div class="weekly-feature-item"><strong>対抗</strong>{rival}</div>
    <div class="weekly-feature-item"><strong>大穴</strong>{longshot}</div>
    <div class="weekly-feature-item"><strong>危険人気</strong>{danger}</div>
    <div class="weekly-feature-item"><strong>LLM別軸理由</strong>{llm_reason}</div>
    <div class="weekly-feature-item"><strong>条件補正</strong>{condition}</div>
    <div class="weekly-feature-item"><strong>買い方方針</strong>{strategy}</div>
  </div>
  <div class="weekly-race-ticket">{expectation}</div>
</div>
""".format(
            day=html_escape(_to_text(featured_row.get("日付", "-")) or "-"),
            llm_banner=featured_llm_banner,
            title=html_escape(_to_text(featured_row.get("レース", featured_row.get("レースID", "-"))) or "-"),
            favorite=html_escape(_render_name_text(featured_row.get("◎", featured_row.get("本命馬", "-")))),
            rival=html_escape(_render_name_text(featured_row.get("○", "-"))),
            longshot=html_escape(_render_name_text(featured_row.get("▲", featured_row.get("大穴候補", "-")))),
            danger=html_escape(_render_name_text(featured_row.get("危険人気馬", "-"))),
            llm_reason=html_escape(featured_llm_reason if featured_llm_reason not in {"", "-"} else "データ本命と一致"),
            condition=html_escape(_to_text(featured_row.get("補正本数", "-")) or "-"),
            strategy=html_escape(_to_text(featured_row.get("買い方方針", "-")) or "-"),
            expectation=feature_expectation_html,
        )
        st.markdown(feature_html, unsafe_allow_html=True)
        feature_action_cols = st.columns([1.2, 1.2], gap="small")
        with feature_action_cols[0]:
            if st.button("G1メインを詳細表示", type="primary", key=f"weekly_feature_{featured_race_id or 'g1'}"):
                _queue_weekly_display_row(featured_row, source_entries_df)
        with feature_action_cols[1]:
            if st.button("G1メインだけ再計算", key=f"weekly_feature_refresh_{featured_race_id or 'g1'}"):
                try:
                    _refresh_weekly_display_row(
                        featured_row,
                        source_entries_df=source_entries_df,
                        simulations_per_race=int(simulations_per_race),
                        seed=int(seed),
                        notice_prefix="選択レース再計算",
                    )
                except Exception as exc:
                    st.error(f"G1メイン再計算に失敗しました: {exc}")

    ordered_groups = [("G1", "G1 注目カード"), ("G2", "G2 注目カード"), ("G3", "G3 注目カード"), ("OTHER", "今週その他")]
    grouped_frames: List[tuple[str, str, pd.DataFrame]] = []
    for grade_key, label in ordered_groups:
        if "格付" not in work.columns:
            if grade_key == "OTHER":
                grouped_frames.append((grade_key, label, work.copy()))
            continue
        if grade_key == "OTHER":
            bucket = work[~work["格付"].isin(["G1", "G2", "G3"])].copy()
        else:
            bucket = work[work["格付"] == grade_key].copy()
            if grade_key == "G1" and featured_race_id:
                bucket = bucket[bucket["レースID"].map(_to_text) != featured_race_id].copy()
        if not bucket.empty:
            grouped_frames.append((grade_key, label, bucket.head(max(1, int(limit))).reset_index(drop=True)))

    if not grouped_frames:
        grouped_frames.append(("ALL", "今週注目カード", work.head(max(1, int(limit))).reset_index(drop=True)))

    for grade_key, label, card_rows in grouped_frames:
        st.markdown(f"<div class='weekly-grade-title'>{html_escape(label)}</div>", unsafe_allow_html=True)
        if grade_key != "ALL":
            st.markdown(
                "<div class='weekly-grade-sub'>{text}</div>".format(
                    text=html_escape(f"{label} は開催フィルタと格付けフィルタ後の上位レースです。")
                ),
                unsafe_allow_html=True,
            )
        col_count = 2 if len(card_rows) > 1 else 1
        columns = st.columns(col_count, gap="medium")
        for idx, (_, row) in enumerate(card_rows.iterrows()):
            with columns[idx % col_count]:
                st.markdown(_build_weekly_race_card_html(row), unsafe_allow_html=True)
                action_cols = st.columns(2, gap="small")
                with action_cols[0]:
                    if st.button("このレースを詳細表示", key=f"weekly_race_card_{grade_key}_{_to_text(row.get('レースID', idx))}"):
                        _queue_weekly_display_row(row, source_entries_df)
                with action_cols[1]:
                    if st.button("このレースだけ再計算", key=f"weekly_race_card_refresh_{grade_key}_{_to_text(row.get('レースID', idx))}"):
                        try:
                            _refresh_weekly_display_row(
                                row,
                                source_entries_df=source_entries_df,
                                simulations_per_race=int(simulations_per_race),
                                seed=int(seed),
                                notice_prefix="選択レース再計算",
                            )
                        except Exception as exc:
                            st.error(f"選択レース再計算に失敗しました: {exc}")


def _build_print_ticket_band_html(ticket_df: pd.DataFrame) -> str:
    if ticket_df.empty:
        return ""
    groups = [
        ("本線", "main", [("単勝", "単勝"), ("複勝", "複勝"), ("馬連", "馬連")]),
        ("押さえ", "cover", [("ワイド", "ワイド"), ("馬単", "馬単"), ("三連複", "三連複")]),
        ("穴", "hole", [("三連単", "三連単"), ("三連複", "三連複"), ("ワイド", "ワイド")]),
    ]
    cards: List[str] = []
    for title, class_name, items in groups:
        lines: List[str] = []
        for bet_type, label in items:
            row = _ticket_row_for_type(ticket_df, bet_type)
            if row is None:
                continue
            value = _to_text(row.get("本線", "-")) if class_name == "main" else _to_text(row.get("押さえ", row.get("本線", "-")))
            lines.append(
                "<div class='print-ticket-band-line'><strong>{label}</strong> {pick}</div>".format(
                    label=html_escape(label),
                    pick=html_escape(_render_name_text(value)),
                )
            )
        if not lines:
            lines.append("<div class='print-ticket-band-line'>候補なし</div>")
        cards.append(
            """
<div class="print-ticket-band {class_name}">
  <div class="print-ticket-band-chip">{title}</div>
  <div class="print-ticket-band-title">{subtitle}</div>
  {lines}
</div>
""".format(
                class_name=html_escape(class_name),
                title=html_escape(title),
                subtitle=html_escape("買い目の重心"),
                lines="".join(lines[:3]),
            )
        )
    return "<div class='print-ticket-band-grid'>" + "".join(cards) + "</div>"


def _build_ticket_amount_focus_html(ticket_df: pd.DataFrame) -> str:
    if ticket_df.empty or "券種" not in ticket_df.columns:
        return ""

    def _amount_to_int(value: Any) -> int:
        text = _to_text(value).replace("円", "").replace(",", "").strip()
        if not text or text == "-":
            return 0
        num = pd.to_numeric(pd.Series([text]), errors="coerce").iloc[0]
        return 0 if pd.isna(num) else int(round(float(num)))

    groups = [
        ("本線", "main", ["単勝", "複勝", "馬連"]),
        ("押さえ", "cover", ["ワイド", "馬単"]),
        ("穴", "hole", ["三連複", "三連単"]),
    ]
    cards: List[str] = []
    for label, class_name, bet_types in groups:
        bucket = ticket_df[ticket_df["券種"].map(_to_text).isin(bet_types)].copy()
        total = int(bucket["目安配分"].map(_amount_to_int).sum()) if ("目安配分" in bucket.columns and not bucket.empty) else 0
        lead_row = bucket.iloc[0] if not bucket.empty else None
        lead_confidence = _to_text(lead_row.get("期待度", "-")) if lead_row is not None else "-"
        lead_hit_rate = _to_text(lead_row.get("的中確率", "-")) if lead_row is not None else "-"
        lines: List[str] = []
        for _, row in bucket.head(3).iterrows():
            lines.append(
                "<div class='ticket-amount-line'><strong>{bet}</strong> {pick} / {amount}</div>".format(
                    bet=html_escape(_to_text(row.get("券種", "-"))),
                    pick=html_escape(_render_name_text(row.get("本線", "-"))),
                    amount=html_escape(_to_text(row.get("目安配分", "-"))),
                )
            )
        if not lines:
            lines.append("<div class='ticket-amount-line'>配分なし</div>")
        cards.append(
            """
<div class="ticket-amount-card {class_name}">
  <div class="ticket-amount-chip">{label}</div>
  <div class="ticket-amount-total">{amount}</div>
  <div class="ticket-amount-metric">期待度 {confidence} / 的中確率 {hit_rate}</div>
  {lines}
</div>
""".format(
                class_name=html_escape(class_name),
                label=html_escape(label),
                amount=html_escape(f"{total:,}円"),
                confidence=html_escape(lead_confidence or "-"),
                hit_rate=html_escape(lead_hit_rate or "-"),
                lines="".join(lines),
            )
        )
    return "<div class='ticket-amount-grid'>" + "".join(cards) + "</div>"


def _reorder_bet_type_list(bet_types: Iterable[str], highlighted_bet_type: Any = "") -> List[str]:
    target = _to_text(highlighted_bet_type)
    ordered = [_to_text(item) for item in bet_types if _to_text(item)]
    if target and target in ordered:
        ordered = [target] + [item for item in ordered if item != target]
    return ordered


def _reorder_ticket_df_by_bet_type(ticket_df: pd.DataFrame, highlighted_bet_type: Any = "") -> pd.DataFrame:
    if ticket_df.empty or "券種" not in ticket_df.columns:
        return ticket_df
    target = _to_text(highlighted_bet_type)
    if not target:
        return ticket_df
    lead = ticket_df[ticket_df["券種"].map(_to_text) == target].copy()
    if lead.empty:
        return ticket_df
    tail = ticket_df[ticket_df["券種"].map(_to_text) != target].copy()
    return pd.concat([lead, tail], ignore_index=True)


def _style_prediction_ticket_table(
    ticket_df: pd.DataFrame,
    highlighted_bet_type: Any = "",
    *,
    highlight_source: str = "",
) -> Any:
    if ticket_df.empty or "券種" not in ticket_df.columns:
        return ticket_df
    target = _to_text(highlighted_bet_type)
    if not target:
        return ticket_df
    source = _to_text(highlight_source)
    row_style = (
        "background-color: #fff1c2; color: #4a3100; font-weight: 800; border-top: 1px solid #f59e0b; border-bottom: 1px solid #f59e0b;"
        if source == "history"
        else "background-color: #e8f7ed; color: #14361f; font-weight: 700;"
    )

    def _row_style(row: pd.Series) -> List[str]:
        is_target = _to_text(row.get("券種", "")) == target
        return [row_style if is_target else "" for _ in row.index]

    return ticket_df.style.apply(_row_style, axis=1)


def _reorder_formatted_tables(
    formatted_tables: Dict[str, pd.DataFrame],
    highlighted_bet_type: Any = "",
) -> Dict[str, pd.DataFrame]:
    target = _to_text(highlighted_bet_type)
    ordered_keys = _reorder_bet_type_list(formatted_tables.keys(), target)
    return {key: formatted_tables[key] for key in ordered_keys if key in formatted_tables}


def _build_highlighted_bet_focus_html(
    ticket_df: pd.DataFrame,
    highlighted_bet_type: Any = "",
    amount_preview: List[Dict[str, Any]] | None = None,
    highlight_source: str = "",
) -> str:
    if ticket_df.empty or "券種" not in ticket_df.columns:
        return ""
    target = _to_text(highlighted_bet_type)
    if not target:
        return ""
    source = _to_text(highlight_source)
    focus_df = ticket_df[ticket_df["券種"].map(_to_text) == target].copy()
    if focus_df.empty:
        return ""
    row = focus_df.iloc[0]
    badges: List[str] = []
    for label, value in [
        ("本線", _to_text(row.get("本線", "-"))),
        ("押さえ", _to_text(row.get("押さえ", "-"))),
        ("期待度", _to_text(row.get("期待度", "-"))),
        ("目安配分", _to_text(row.get("目安配分", "-"))),
        ("配分基準", _to_text(row.get("配分基準", "-"))),
    ]:
        if value and value != "-":
            badges.append(
                "<span class='bet-focus-badge'>{label} {value}</span>".format(
                    label=html_escape(label),
                    value=html_escape(_render_name_text(value)),
                )
            )
    memo = _to_text(row.get("買い方メモ", "")) or "この券種の本線候補を先頭に表示しています。"
    amount_rows = amount_preview if isinstance(amount_preview, list) else []
    amount_badges = []
    for item in amount_rows[:3]:
        if not isinstance(item, dict):
            continue
        bet_text = _to_text(item.get("bet", ""))
        amount_text = _to_text(item.get("amount", ""))
        if bet_text and amount_text:
            amount_badges.append(
                "<span class='bet-focus-badge'>寄せ目安 {bet} {amount}</span>".format(
                    bet=html_escape(bet_text),
                    amount=html_escape(amount_text),
                )
            )
    amount_html = ""
    if amount_badges:
        amount_html = (
            "<div class='bet-focus-sub' style='margin-top:0.32rem;'><strong>LLMおまかせ履歴の金額目安</strong></div>"
            + "<div class='bet-focus-row'>"
            + "".join(amount_badges)
            + "</div>"
        )
    card_class = "bet-focus-card history-highlight" if source == "history" else "bet-focus-card"
    return """
<div class="{card_class}">
  <span class="bet-focus-chip">{chip}</span>
  <div class="bet-focus-title">{title}</div>
  <div class="bet-focus-sub">{memo}</div>
  <div class="bet-focus-row">{badges}</div>
  {amount_html}
</div>
""".format(
        card_class=card_class,
        chip=html_escape("履歴から確認中" if source == "history" else "おすすめ券種を先頭表示中"),
        title=html_escape(f"いま確認する券種: {target}"),
        memo=html_escape(memo),
        badges="".join(badges),
        amount_html=amount_html,
    )


def _render_bet_pick_cards(
    formatted_tables: Dict[str, pd.DataFrame],
    highlighted_bet_type: Any = "",
    *,
    highlight_chip_text: str = "おすすめから移動",
    highlight_source: str = "",
) -> None:
    bet_types = _reorder_bet_type_list(["単勝", "複勝", "馬連", "ワイド", "三連複", "三連単"], highlighted_bet_type)
    target = _to_text(highlighted_bet_type)
    chip_text = _to_text(highlight_chip_text) or "おすすめから移動"
    source = _to_text(highlight_source)
    cards: List[str] = []
    for bet_type in bet_types:
        table = formatted_tables.get(bet_type, pd.DataFrame())
        highlight_class = ""
        if bet_type == target:
            highlight_class = "history-highlight" if source == "history" else "highlight"
        cards.append(
            """
<div class="bet-pick-card {highlight_class}">
  {chip_html}
  <div class="bet-pick-title">{title}</div>
  <div class="bet-pick-line">{pick}</div>
</div>
""".format(
                highlight_class=highlight_class,
                chip_html=(
                    f"<span class='bet-pick-chip'>{html_escape(chip_text)}</span>" if bet_type == target else ""
                ),
                title=html_escape(bet_type),
                pick=html_escape(_render_name_text(_top_pick_text(table))),
            )
        )
    st.markdown("<div class='bet-pick-grid'>" + "".join(cards) + "</div>", unsafe_allow_html=True)


def _ticket_row_pick(row: pd.Series) -> str:
    for key in ("馬", "組み合わせ", "買い目"):
        text = _to_text(row.get(key, ""))
        if text:
            return text
    return "-"


def _ticket_support_picks(table: pd.DataFrame, limit: int = 2) -> str:
    if table.empty or len(table) <= 1:
        return "-"
    picks: List[str] = []
    for _, row in table.iloc[1 : 1 + max(1, int(limit))].iterrows():
        text = _ticket_row_pick(row)
        if text and text != "-" and text not in picks:
            picks.append(text)
    return " / ".join(picks) if picks else "-"


def _normalize_ticket_pick_text(value: Any) -> str:
    text = _to_text(value)
    if not text:
        return ""
    tokens = [_strip_gate_prefix(token) for token in text.split("-")]
    tokens = [token for token in tokens if token]
    return "-".join(tokens) if tokens else _strip_gate_prefix(text)


def _format_ticket_prob(value: Any) -> str:
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "-" if pd.isna(num) else f"{float(num):.2%}"


def _format_ticket_odds(value: Any) -> str:
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(num):
        return "-"
    if float(num) > 9999:
        return "∞"
    return f"{float(num):.1f}"


def _format_ticket_score(value: Any) -> str:
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "-" if pd.isna(num) else f"{float(num):.2f}"


def _ticket_confidence_label(value: Any) -> str:
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(num):
        return "-"
    score = float(num)
    if score >= 4.0:
        return "強め"
    if score >= 2.0:
        return "標準"
    return "押さえ"


def _ticket_style_label(bet_type: str) -> str:
    return {
        "単勝": "本命重視",
        "複勝": "堅め",
        "馬連": "標準",
        "ワイド": "安全寄り",
        "馬単": "差し込み",
        "三連複": "高配当",
        "三連単": "万馬券狙い",
    }.get(bet_type, "-")


def _ticket_note_text(
    bet_type: str,
    main_pick: str,
    *,
    top_horse: str,
    dark_horse: str,
    danger_horse: str,
) -> str:
    note_map = {
        "単勝": f"本命 {_render_name_text(top_horse or main_pick)} をそのまま狙う",
        "複勝": f"軸は {_render_name_text(main_pick)}。迷ったらここから",
        "馬連": f"本命 {_render_name_text(top_horse)} から相手へ流す形",
        "ワイド": f"安全寄り。穴 {_render_name_text(dark_horse)} を絡める判断向け",
        "馬単": f"1着 {_render_name_text(top_horse)} 固定寄りの買い方",
        "三連複": f"本命 {_render_name_text(top_horse)} と穴 {_render_name_text(dark_horse)} の両立狙い",
        "三連単": f"1着 {_render_name_text(top_horse)} 固定を基本に高配当を狙う",
    }
    note = note_map.get(bet_type, "-")
    if danger_horse and danger_horse != "-" and bet_type in {"単勝", "複勝", "馬連", "馬単"}:
        note += f" / 危険人気 {_render_name_text(danger_horse)} は評価下げ"
    return note


def _build_prediction_ticket(result: PredictionResult, style_tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    bet_order = ["単勝", "複勝", "馬連", "ワイド", "馬単", "三連複", "三連単"]
    top_horse = _to_text(result.horse_predictions.iloc[0].get("馬", "-")) if not result.horse_predictions.empty else "-"
    dark_table = style_tables.get("大穴", pd.DataFrame())
    danger_table = style_tables.get("危険人気", pd.DataFrame())
    dark_horse = _to_text(dark_table.iloc[0].get("馬", "-")) if not dark_table.empty else "-"
    danger_horse = _to_text(danger_table.iloc[0].get("馬", "-")) if not danger_table.empty else "-"

    budget_map: Dict[tuple[str, str], float] = {}
    if not result.budget_plan.empty and {"券種", "買い目", "推奨金額"}.issubset(result.budget_plan.columns):
        for _, row in result.budget_plan.iterrows():
            bet_type = _to_text(row.get("券種", ""))
            pick_name = _to_text(row.get("買い目", ""))
            amount = pd.to_numeric(pd.Series([row.get("推奨金額")]), errors="coerce").iloc[0]
            if bet_type and pick_name and pd.notna(amount):
                budget_map[(bet_type, pick_name)] = float(amount)

    rows: List[Dict[str, str]] = []
    for bet_type in bet_order:
        table = result.bet_recommendations.get(bet_type, pd.DataFrame())
        if table.empty:
            rows.append(
                {
                    "券種": bet_type,
                    "狙い": _ticket_style_label(bet_type),
                    "本線": "-",
                    "押さえ": "-",
                    "期待度": "-",
                    "的中確率": "-",
                    "参考オッズ": "-",
                    "理論オッズ": "-",
                    "目安配分": "-",
                    "買い方メモ": "出走頭数不足のため算出対象外",
                }
            )
            continue

        main_row = table.iloc[0]
        main_pick = _ticket_row_pick(main_row)
        support_pick = _ticket_support_picks(table, limit=2)
        score = main_row.get("推奨度", "")
        prob = main_row.get("的中確率", "")
        odds = main_row.get("理論オッズ", "")
        market_odds = main_row.get("単勝オッズ", main_row.get("複勝オッズ", ""))
        budget_amount = budget_map.get((bet_type, main_pick))
        budget_text = "-" if budget_amount is None else f"{int(round(float(budget_amount))):,}円"
        rows.append(
            {
                "券種": bet_type,
                "狙い": _ticket_style_label(bet_type),
                "本線": _render_name_text(main_pick),
                "押さえ": _render_name_text(support_pick),
                "期待度": _ticket_confidence_label(score),
                "的中確率": _format_ticket_prob(prob),
                "参考オッズ": _format_ticket_odds(market_odds),
                "理論オッズ": _format_ticket_odds(odds),
                "目安配分": budget_text,
                "買い方メモ": _ticket_note_text(
                    bet_type,
                    main_pick,
                    top_horse=top_horse,
                    dark_horse=dark_horse,
                    danger_horse=danger_horse,
                ),
            }
        )

    return pd.DataFrame(rows)


def _apply_budget_amounts_to_prediction_ticket(
    ticket_df: pd.DataFrame,
    budget_df: pd.DataFrame | None,
    *,
    amount_col: str,
    basis_label: str,
) -> pd.DataFrame:
    if ticket_df.empty:
        return ticket_df.copy()
    out = ticket_df.copy()
    if budget_df is None or budget_df.empty or amount_col not in budget_df.columns or "券種" not in budget_df.columns or "買い目" not in budget_df.columns:
        out["配分基準"] = basis_label if "目安配分" in out.columns else "ベース"
        return out
    work = budget_df.copy()
    amount_map: Dict[tuple[str, str], str] = {}
    for _, row in work.iterrows():
        bet_type = _to_text(row.get("券種", ""))
        pick_text = _normalize_ticket_pick_text(row.get("買い目", ""))
        amount_text = _to_text(row.get(amount_col, ""))
        if not bet_type or not pick_text or not amount_text or amount_text == "-":
            continue
        amount_map[(bet_type, pick_text)] = amount_text
    if "目安配分" not in out.columns:
        out["目安配分"] = "-"
    if "本線" in out.columns:
        out["目安配分"] = out.apply(
            lambda row: amount_map.get(
                (_to_text(row.get("券種", "")), _normalize_ticket_pick_text(row.get("本線", ""))),
                _to_text(row.get("目安配分", "-")) or "-",
            ),
            axis=1,
        )
    out["配分基準"] = basis_label
    return out


def _build_prediction_mark_items(
    result: PredictionResult,
    style_tables: Dict[str, pd.DataFrame],
    gate_lookup: Dict[str, str] | None = None,
) -> List[Dict[str, str]]:
    if result.horse_predictions.empty:
        return []

    top_row = result.horse_predictions.iloc[0]
    second_row = result.horse_predictions.iloc[1] if len(result.horse_predictions) > 1 else None
    third_row = result.horse_predictions.iloc[2] if len(result.horse_predictions) > 2 else None
    dark_table = style_tables.get("大穴", pd.DataFrame())
    danger_table = style_tables.get("危険人気", pd.DataFrame())
    spiritual_table = style_tables.get("スピリチュアル", pd.DataFrame())

    def _style_row(table: pd.DataFrame) -> pd.Series | None:
        if table.empty:
            return None
        return table.iloc[0]

    dark_row = _style_row(dark_table)
    danger_row = _style_row(danger_table)
    spiritual_row = _style_row(spiritual_table)
    gate_map = gate_lookup or {}

    return [
        {
            "mark": "◎",
            "label": "AI本命",
            "horse": _render_name_text_with_gate(top_row.get("馬", "-"), gate_map),
            "meta": f"{_to_text(top_row.get('騎手', '-'))} / 勝率{float(top_row.get('勝率', 0.0)):.2%} / 複勝率{float(top_row.get('複勝率', 0.0)):.2%}",
            "class_name": "primary",
            "bet": _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("単勝", pd.DataFrame())), gate_map),
            "note": "単勝の主軸。迷ったらここから入る形。",
        },
        {
            "mark": "○",
            "label": "対抗",
            "horse": _render_name_text_with_gate(second_row.get("馬", "-"), gate_map) if second_row is not None else "-",
            "meta": (
                f"{_to_text(second_row.get('騎手', '-'))} / 勝率{float(second_row.get('勝率', 0.0)):.2%} / 複勝率{float(second_row.get('複勝率', 0.0)):.2%}"
                if second_row is not None
                else "上位2番手が未算出です"
            ),
            "class_name": "rival",
            "bet": _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("馬連", pd.DataFrame())), gate_map),
            "note": "馬連・ワイドの相手本線として使う想定。",
        },
        {
            "mark": "▲",
            "label": "大穴",
            "horse": _render_name_text_with_gate(dark_row.get("馬", "-"), gate_map) if dark_row is not None else "-",
            "meta": _to_text(dark_row.get("理由", "人気薄狙い")) if dark_row is not None else "穴候補は未算出です",
            "class_name": "longshot",
            "bet": _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("三連複", pd.DataFrame())), gate_map),
            "note": "ワイド・三連複で一発を狙う候補。",
        },
        {
            "mark": "△",
            "label": "連下",
            "horse": _render_name_text_with_gate(third_row.get("馬", "-"), gate_map) if third_row is not None else "-",
            "meta": (
                f"{_to_text(third_row.get('騎手', '-'))} / 勝率{float(third_row.get('勝率', 0.0)):.2%} / 複勝率{float(third_row.get('複勝率', 0.0)):.2%}"
                if third_row is not None
                else "3番手が未算出です"
            ),
            "class_name": "support",
            "bet": _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("ワイド", pd.DataFrame())), gate_map),
            "note": "押さえ・相手候補。三連系の3列目でも使う。",
        },
        {
            "mark": "☆",
            "label": "遊び枠",
            "horse": _render_name_text_with_gate(spiritual_row.get("馬", "-"), gate_map) if spiritual_row is not None else "-",
            "meta": _to_text(spiritual_row.get("理由", "数秘予想")) if spiritual_row is not None else "スピリチュアル候補なし",
            "class_name": "spiritual",
            "bet": _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("三連単", pd.DataFrame())), gate_map),
            "note": "遊びの三連単や高配当メモ用。",
        },
        {
            "mark": "危",
            "label": "危険人気",
            "horse": _render_name_text_with_gate(danger_row.get("馬", "-"), gate_map) if danger_row is not None else "-",
            "meta": _to_text(danger_row.get("理由", "市場データ不足")) if danger_row is not None else "市場データ不足",
            "class_name": "danger",
            "bet": "評価下げ",
            "note": "単勝や1着固定での過信を避けたい人気馬。",
        },
    ]


def _ticket_row_for_type(ticket_df: pd.DataFrame, bet_type: str) -> pd.Series | None:
    if ticket_df.empty or "券種" not in ticket_df.columns:
        return None
    hit = ticket_df[ticket_df["券種"].map(_to_text) == bet_type]
    if hit.empty:
        return None
    return hit.iloc[0]


def _render_bet_slip_cards(ticket_df: pd.DataFrame) -> None:
    if ticket_df.empty:
        return
    groups = [
        ("本線", "main", [("単勝", "単勝"), ("複勝", "複勝"), ("馬連", "馬連")], "まず押さえる基本線"),
        ("押さえ", "cover", [("ワイド", "ワイド"), ("馬単", "馬単"), ("△", "連下")], "相手抜けや順番違いのケア"),
        ("穴", "hole", [("三連複", "三連複"), ("三連単", "三連単"), ("▲", "大穴")], "高配当を狙う攻め筋"),
    ]
    cards: List[str] = []
    for title, class_name, items, note in groups:
        rows: List[str] = []
        for key, label in items:
            if key in {"△", "▲"}:
                if key == "△":
                    row = _ticket_row_for_type(ticket_df, "ワイド")
                    value = _to_text(row.get("押さえ", "-")) if row is not None else "-"
                else:
                    row = _ticket_row_for_type(ticket_df, "三連複")
                    value = _to_text(row.get("押さえ", "-")) if row is not None else "-"
            else:
                row = _ticket_row_for_type(ticket_df, key)
                value = _to_text(row.get("本線", "-")) if row is not None else "-"
            rows.append(f"<div class='bet-slip-row'><strong>{html_escape(label)}</strong> {html_escape(_render_name_text(value))}</div>")
        rows.append(f"<div class='bet-slip-row'>{html_escape(note)}</div>")
        cards.append(
            """
<div class="bet-slip-card {class_name}">
  <div class="bet-slip-chip">{title}</div>
  <div class="bet-slip-title">{subtitle}</div>
  {rows}
</div>
""".format(
                class_name=html_escape(class_name),
                title=html_escape(title),
                subtitle=html_escape("馬券フォーマット"),
                rows="".join(rows),
            )
        )
    st.markdown("<div class='bet-slip-grid'>" + "".join(cards) + "</div>", unsafe_allow_html=True)


def _split_combo_names(value: Any) -> List[str]:
    text = _to_text(value)
    if not text or text == "-":
        return []
    return [token.strip() for token in text.split("-") if token.strip()]


def _first_distinct_name(values: List[str], excluded: List[str]) -> str:
    excluded_set = {_to_text(value) for value in excluded if _to_text(value)}
    for value in values:
        name = _to_text(value)
        if name and name not in excluded_set:
            return name
    return "-"


def _infer_weekly_mark_columns(row: pd.Series) -> Dict[str, str]:
    favorite = _to_text(row.get("本命馬", "-")) or "-"
    longshot = _to_text(row.get("大穴候補", "-")) or "-"
    rival = _first_distinct_name(
        _split_combo_names(row.get("馬連候補", "")) + _split_combo_names(row.get("ワイド候補", "")) + [_to_text(row.get("複勝候補", ""))],
        [favorite],
    )
    support = _first_distinct_name(
        _split_combo_names(row.get("ワイド候補", "")) + _split_combo_names(row.get("三連複候補", "")),
        [favorite, rival, longshot],
    )
    return {
        "◎": favorite,
        "○": rival,
        "▲": longshot,
        "△": support,
    }


def _bet_bucket_meta(bet_type: str) -> tuple[str, str]:
    mapping = {
        "単勝": ("main", "本線"),
        "複勝": ("main", "本線"),
        "馬連": ("main", "本線"),
        "ワイド": ("cover", "押さえ"),
        "馬単": ("cover", "押さえ"),
        "三連複": ("hole", "穴"),
        "三連単": ("hole", "穴"),
    }
    return mapping.get(_to_text(bet_type), ("cover", "押さえ"))


def _render_budget_bucket_cards(plan_df: pd.DataFrame) -> None:
    if plan_df.empty or not {"券種", "買い目", "推奨金額"}.issubset(plan_df.columns):
        return
    work = plan_df.copy()
    work["bucket_class"], work["bucket_label"] = zip(*work["券種"].map(_bet_bucket_meta))
    work["推奨金額_num"] = pd.to_numeric(work["推奨金額"], errors="coerce").fillna(0.0)

    cards: List[str] = []
    for class_name, label in [("main", "本線"), ("cover", "押さえ"), ("hole", "穴")]:
        bucket = work[work["bucket_class"] == class_name].copy()
        total_amount = int(bucket["推奨金額_num"].sum()) if not bucket.empty else 0
        lines: List[str] = []
        if bucket.empty:
            lines.append("<div class='budget-line'>配分なし</div>")
        else:
            for _, row in bucket.head(4).iterrows():
                lines.append(
                    "<div class='budget-line'><strong>{bet}</strong> {pick} / {amount}</div>".format(
                        bet=html_escape(_to_text(row.get("券種", "-"))),
                        pick=html_escape(_render_name_text(row.get("買い目", "-"))),
                        amount=html_escape(f"{int(float(row.get('推奨金額_num', 0.0))):,}円"),
                    )
                )
        cards.append(
            """
<div class="budget-card {class_name}">
  <div class="budget-chip">{label}</div>
  <div class="budget-total">{amount}</div>
  {lines}
</div>
""".format(
                class_name=html_escape(class_name),
                label=html_escape(label),
                amount=html_escape(f"{total_amount:,}円"),
                lines="".join(lines),
            )
        )
    st.markdown("<div class='budget-grid'>" + "".join(cards) + "</div>", unsafe_allow_html=True)


def _build_print_sheet_html(
    *,
    race_label: str,
    race_grade: str,
    race_date: Any,
    venue: Any,
    race_name: Any,
    weather: Any,
    track_condition: Any,
    distance: Any,
    field_size: int,
    mark_items: List[Dict[str, str]],
    ticket_df: pd.DataFrame,
) -> str:
    distance_num = pd.to_numeric(pd.Series([distance]), errors="coerce").iloc[0]
    distance_text = f"{int(float(distance_num))}m" if pd.notna(distance_num) else (_to_text(distance) or "-")
    race_date_text = _format_date_text(race_date)
    venue_text = _to_text(venue) or "-"
    race_name_text = _to_text(race_name) or "-"
    generated_at = datetime.now().strftime("%Y/%m/%d %H:%M")
    ticket_band_html = _build_print_ticket_band_html(ticket_df)
    ticket_amount_html = _build_ticket_amount_focus_html(ticket_df)
    rows = []
    for item in mark_items:
        rows.append(
            """
<tr>
  <td><span class="print-badge {class_name}">{mark}</span></td>
  <td><strong>{horse}</strong><br><span style="color:#5a7460;font-size:12px;">{label}</span></td>
  <td>{bet}</td>
  <td>{note}</td>
</tr>
""".format(
                class_name=html_escape(item["class_name"]),
                mark=html_escape(item["mark"]),
                horse=html_escape(item["horse"]),
                label=html_escape(item["label"]),
                bet=html_escape(item["bet"]),
                note=html_escape(item["note"]),
            )
        )
    ticket_rows = []
    if not ticket_df.empty:
        for _, row in ticket_df.head(7).iterrows():
            ticket_rows.append(
                """
<tr>
  <td>{bet_type}</td>
  <td>{main}</td>
  <td>{cover}</td>
  <td>{amount}</td>
</tr>
""".format(
                    bet_type=html_escape(_to_text(row.get("券種", "-"))),
                    main=html_escape(_to_text(row.get("本線", "-"))),
                    cover=html_escape(_to_text(row.get("押さえ", "-"))),
                    amount=html_escape(_to_text(row.get("目安配分", "-"))),
                )
            )
    return """
<div class="print-sheet-wrap">
  <div class="print-sheet-header">
    <div class="print-sheet-topline">
      <div class="print-sheet-logo">KEIBA AI TICKET</div>
      <div class="print-sheet-kicker">PRINT SHEET</div>
    </div>
    <div class="print-sheet-title">{title}</div>
    <div class="print-sheet-sub">{subtitle}</div>
    <div class="print-sheet-meta">
      <div class="print-sheet-meta-card">
        <div class="print-sheet-meta-label">開催日</div>
        <div class="print-sheet-meta-value">{race_date}</div>
      </div>
      <div class="print-sheet-meta-card">
        <div class="print-sheet-meta-label">開催</div>
        <div class="print-sheet-meta-value">{venue}</div>
      </div>
      <div class="print-sheet-meta-card">
        <div class="print-sheet-meta-label">レース名</div>
        <div class="print-sheet-meta-value">{race_name}</div>
      </div>
      <div class="print-sheet-meta-card emphasis">
        <div class="print-sheet-meta-label">買い目軸</div>
        <div class="print-sheet-meta-value">{core_pick}</div>
      </div>
      <div class="print-sheet-meta-card">
        <div class="print-sheet-meta-label">券種メモ</div>
        <div class="print-sheet-meta-value">{bet_focus}</div>
      </div>
      <div class="print-sheet-meta-card">
        <div class="print-sheet-meta-label">作成時刻</div>
        <div class="print-sheet-meta-value">{generated_at}</div>
      </div>
    </div>
  </div>
  {ticket_band_html}
  {ticket_amount_html}
  <table class="print-sheet-table">
    <thead>
      <tr><th>印</th><th>馬</th><th>狙い目</th><th>メモ</th></tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  <table class="print-sheet-table">
    <thead>
      <tr><th>券種</th><th>本線</th><th>押さえ</th><th>目安配分</th></tr>
    </thead>
    <tbody>
      {ticket_rows}
    </tbody>
  </table>
</div>
""".format(
        title=html_escape(race_label or "予想レース"),
        subtitle=html_escape(
            f"{race_grade or '未判定'} / 天気 {_to_text(weather) or '-'} / 馬場 {_to_text(track_condition) or '-'} / {distance_text} / {field_size}頭"
        ),
        race_date=html_escape(race_date_text or "-"),
        venue=html_escape(venue_text),
        race_name=html_escape(race_name_text),
        core_pick=html_escape(_to_text(mark_items[0]["horse"]) if mark_items else "-"),
        bet_focus=html_escape(_to_text(ticket_df.iloc[0]["本線"]) if (not ticket_df.empty and "本線" in ticket_df.columns) else "-"),
        generated_at=html_escape(generated_at),
        ticket_band_html=ticket_band_html,
        ticket_amount_html=ticket_amount_html,
        rows="".join(rows),
        ticket_rows="".join(ticket_rows),
    )


def _build_print_sheet_document(inner_html: str, *, title: str) -> str:
    return """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    @page {{
      size: A4 portrait;
      margin: 12mm;
    }}
    body {{
      margin: 0;
      background: #edf4ee;
      color: #17321c;
      font-family: "Hiragino Sans", "Yu Gothic", "Meiryo", sans-serif;
    }}
    .page {{
      max-width: 960px;
      margin: 0 auto;
      padding: 16px;
    }}
    .print-note {{
      margin: 0 0 12px;
      padding: 10px 12px;
      border-radius: 10px;
      background: #fdf9e6;
      color: #634b09;
      font-size: 13px;
      line-height: 1.6;
      border: 1px solid rgba(179, 138, 18, 0.18);
    }}
    .print-sheet-wrap {{
      border: 1px solid rgba(50, 95, 63, 0.18);
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 12px 24px rgba(33, 63, 41, 0.10);
      background: #fff;
    }}
    .print-sheet-header {{
      padding: 14px 16px 12px;
      background: linear-gradient(180deg, rgba(255, 254, 246, 0.98) 0%, rgba(242, 249, 244, 0.98) 100%);
      border-bottom: 1px solid rgba(66, 107, 77, 0.14);
    }}
    .print-sheet-topline {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .print-sheet-logo {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 12px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.08em;
      color: #1f6a37;
      background: rgba(220, 245, 226, 0.95);
    }}
    .print-sheet-kicker {{
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.08em;
      color: #1d6d36;
    }}
    .print-sheet-title {{
      margin-top: 6px;
      font-size: 24px;
      font-weight: 900;
      color: #17321c;
    }}
    .print-sheet-sub {{
      margin-top: 4px;
      font-size: 13px;
      color: #496151;
    }}
    .print-sheet-meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }}
    .print-sheet-meta-card {{
      border-radius: 10px;
      padding: 9px 10px;
      background: rgba(255, 255, 255, 0.78);
      border: 1px solid rgba(56, 107, 70, 0.16);
    }}
    .print-sheet-meta-card.emphasis {{
      background: linear-gradient(180deg, rgba(255, 249, 231, 0.96) 0%, rgba(255, 255, 248, 0.98) 100%);
      border-color: rgba(179, 138, 18, 0.20);
    }}
    .print-sheet-meta-label {{
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.06em;
      color: #54705d;
    }}
    .print-sheet-meta-value {{
      margin-top: 3px;
      font-size: 13px;
      font-weight: 800;
      line-height: 1.35;
      color: #17321c;
    }}
    .print-ticket-band-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 8px;
      padding: 12px 14px 4px;
      background: rgba(249, 252, 250, 0.92);
    }}
    .print-ticket-band {{
      border-radius: 10px;
      padding: 10px 11px;
      border: 1px solid rgba(56, 107, 70, 0.16);
      background: rgba(255, 255, 255, 0.82);
    }}
    .print-ticket-band.main {{
      background: linear-gradient(180deg, rgba(255, 249, 231, 0.96) 0%, rgba(255, 255, 248, 0.98) 100%);
      border-color: rgba(179, 138, 18, 0.22);
    }}
    .print-ticket-band.cover {{
      background: linear-gradient(180deg, rgba(238, 246, 255, 0.96) 0%, rgba(252, 254, 255, 0.98) 100%);
      border-color: rgba(52, 102, 166, 0.20);
    }}
    .print-ticket-band.hole {{
      background: linear-gradient(180deg, rgba(255, 244, 229, 0.96) 0%, rgba(255, 251, 246, 0.98) 100%);
      border-color: rgba(196, 116, 34, 0.22);
    }}
    .print-ticket-band-chip {{
      display: inline-flex;
      align-items: center;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 800;
      color: #17321c;
      background: rgba(255, 255, 255, 0.72);
    }}
    .print-ticket-band-title {{
      margin-top: 4px;
      font-size: 13px;
      font-weight: 900;
      color: #17321c;
    }}
    .print-ticket-band-line {{
      margin-top: 4px;
      font-size: 12px;
      line-height: 1.5;
      color: #2f4a36;
    }}
    .ticket-amount-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 8px;
      padding: 8px 14px 4px;
      background: rgba(249, 252, 250, 0.92);
    }}
    .ticket-amount-card {{
      border-radius: 10px;
      padding: 10px 11px;
      border: 1px solid rgba(56, 107, 70, 0.16);
      background: rgba(255, 255, 255, 0.82);
    }}
    .ticket-amount-card.main {{
      background: linear-gradient(180deg, rgba(255, 249, 231, 0.96) 0%, rgba(255, 255, 248, 0.98) 100%);
      border-color: rgba(179, 138, 18, 0.22);
    }}
    .ticket-amount-card.cover {{
      background: linear-gradient(180deg, rgba(238, 246, 255, 0.96) 0%, rgba(252, 254, 255, 0.98) 100%);
      border-color: rgba(52, 102, 166, 0.20);
    }}
    .ticket-amount-card.hole {{
      background: linear-gradient(180deg, rgba(255, 244, 229, 0.96) 0%, rgba(255, 251, 246, 0.98) 100%);
      border-color: rgba(196, 116, 34, 0.22);
    }}
    .ticket-amount-chip {{
      display: inline-flex;
      align-items: center;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 800;
      color: #17321c;
      background: rgba(255, 255, 255, 0.72);
    }}
    .ticket-amount-total {{
      margin-top: 4px;
      font-size: 20px;
      font-weight: 900;
      color: #17321c;
    }}
    .ticket-amount-metric {{
      margin-top: 4px;
      font-size: 11px;
      font-weight: 800;
      line-height: 1.5;
      color: #3b5a42;
    }}
    .ticket-amount-line {{
      margin-top: 4px;
      font-size: 12px;
      line-height: 1.5;
      color: #35513b;
    }}
    .print-sheet-table {{
      width: 100%;
      border-collapse: collapse;
      background: rgba(255, 255, 255, 0.96);
    }}
    .print-sheet-table th,
    .print-sheet-table td {{
      padding: 10px 12px;
      border-top: 1px solid rgba(70, 112, 82, 0.12);
      text-align: left;
      vertical-align: top;
      font-size: 13px;
      color: #274132;
    }}
    .print-sheet-table th {{
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.06em;
      background: rgba(244, 249, 245, 0.94);
    }}
    .print-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 28px;
      height: 28px;
      border-radius: 999px;
      color: #fff;
      font-size: 14px;
      font-weight: 900;
    }}
    .print-badge.primary {{ background: linear-gradient(180deg, #d3a532 0%, #9f7312 100%); }}
    .print-badge.rival {{ background: linear-gradient(180deg, #4d8bd6 0%, #2d63aa 100%); }}
    .print-badge.longshot {{ background: linear-gradient(180deg, #de8b34 0%, #ac5b11 100%); }}
    .print-badge.support {{ background: linear-gradient(180deg, #7f72d8 0%, #5948b4 100%); }}
    .print-badge.spiritual {{ background: linear-gradient(180deg, #5c93a9 0%, #356678 100%); }}
    .print-badge.danger {{ background: linear-gradient(180deg, #d35a46 0%, #a33122 100%); }}
    @media print {{
      body {{
        background: #fff;
      }}
      .page {{
        max-width: none;
        padding: 0;
      }}
      .print-note {{
        display: none;
      }}
      .print-sheet-wrap {{
        box-shadow: none;
        border-radius: 0;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="print-note">A4縦向け。ブラウザの印刷ダイアログで余白を「既定」または「最小」にすると収まりやすいです。</div>
    {inner_html}
  </div>
</body>
</html>
""".format(title=html_escape(title or "KEIBA Print Sheet"), inner_html=inner_html)


def _render_prediction_dashboard(
    result: PredictionResult,
    style_tables: Dict[str, pd.DataFrame],
    *,
    race_label: str,
    race_grade: str,
    weather: Any,
    track_condition: Any,
    distance: Any,
    field_size: int,
    gate_lookup: Dict[str, str] | None = None,
) -> None:
    if result.horse_predictions.empty:
        return

    distance_num = pd.to_numeric(pd.Series([distance]), errors="coerce").iloc[0]
    distance_text = f"{int(float(distance_num))}m" if pd.notna(distance_num) else (_to_text(distance) or "-")
    gate_map = gate_lookup or {}
    mark_items = _build_prediction_mark_items(result, style_tables, gate_lookup=gate_map)
    condition_labels = _extract_condition_adjustment_labels(result)
    condition_summary = _format_condition_adjustment_summary(condition_labels)

    ribbon_items = [
        ("単勝本線", _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("単勝", pd.DataFrame())), gate_map)),
        ("複勝本線", _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("複勝", pd.DataFrame())), gate_map)),
        ("ワイド本線", _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("ワイド", pd.DataFrame())), gate_map)),
        ("三連単本線", _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("三連単", pd.DataFrame())), gate_map)),
    ]

    hero_html = """
<div class="prediction-hero">
  <div class="prediction-kicker">本紙AI印</div>
  <div class="prediction-title">{title}</div>
  <div class="prediction-subtitle">{subtitle}</div>
  <div class="prediction-ribbon">{ribbon}</div>
</div>
""".format(
        title=html_escape(race_label or "予想レース"),
        subtitle=html_escape(
            f"{race_grade or '未判定'} / 天気 {_to_text(weather) or '-'} / 馬場 {_to_text(track_condition) or '-'} / {distance_text} / {field_size}頭"
        ),
        ribbon="".join(
            """
<div class="prediction-ribbon-card">
  <div class="prediction-ribbon-label">{label}</div>
  <div class="prediction-ribbon-value">{value}</div>
</div>
""".format(label=html_escape(label), value=html_escape(value))
            for label, value in ribbon_items
        ),
    )
    st.markdown(hero_html, unsafe_allow_html=True)
    if condition_labels:
        chips_html = "".join(
            f"<span style='display:inline-flex;align-items:center;padding:4px 10px;border-radius:999px;background:rgba(255,248,214,0.95);border:1px solid rgba(187,148,30,0.28);font-size:11px;font-weight:800;color:#745300;'>{html_escape(label)}</span>"
            for label in [_format_condition_segment_label(item) for item in condition_labels]
        )
        st.markdown(
            """
<div style="margin:10px 0 14px;padding:12px 14px;border-radius:16px;background:rgba(255,255,255,0.82);border:1px solid rgba(189,164,80,0.28);box-shadow:0 10px 24px rgba(116,83,0,0.08);">
  <div style="font-size:11px;font-weight:900;letter-spacing:0.08em;color:#8c6a12;">条件補正</div>
  <div style="margin-top:4px;font-size:20px;font-weight:900;color:#473312;">{count}</div>
  <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:8px;">{chips}</div>
</div>
""".format(
                count=html_escape(_format_condition_adjustment_count(len(condition_labels))),
                chips=chips_html,
            ),
            unsafe_allow_html=True,
        )
    else:
        st.caption("条件補正: 0本")
    strip_html = "".join(
        """
<div class="prediction-strip-item">
  <div class="prediction-strip-mark {class_name}">{mark}</div>
  <div>
    <div class="prediction-strip-main">{horse}</div>
    <div class="prediction-strip-sub">{label}</div>
  </div>
</div>
""".format(
            class_name=html_escape(item["class_name"]),
            mark=html_escape(item["mark"]),
            horse=html_escape(item["horse"]),
            label=html_escape(item["label"]),
        )
        for item in mark_items
    )
    st.markdown("<div class='prediction-strip'>" + strip_html + "</div>", unsafe_allow_html=True)
    card_html = "".join(
        """
<div class="prediction-mark-card {class_name}">
  <div class="prediction-mark-top">
    <div class="prediction-mark">{mark}</div>
    <div class="prediction-mark-label">{label}</div>
  </div>
  <div class="prediction-mark-name">{horse}</div>
  <div class="prediction-mark-meta">{meta}</div>
</div>
""".format(
            class_name=html_escape(item["class_name"]),
            mark=html_escape(item["mark"]),
            label=html_escape(item["label"]),
            horse=html_escape(item["horse"]),
            meta=html_escape(item["meta"]),
        )
        for item in mark_items
    )
    st.markdown("<div class='prediction-mark-grid'>" + card_html + "</div>", unsafe_allow_html=True)
    sheet_html = """
<div class="prediction-sheet">
  <div class="prediction-sheet-head">
    <div>印</div>
    <div>馬</div>
    <div>狙い目</div>
    <div>メモ</div>
  </div>
  {rows}
</div>
""".format(
        rows="".join(
            """
<div class="prediction-sheet-row">
  <div><span class="prediction-sheet-mark {class_name}">{mark}</span></div>
  <div>
    <div class="prediction-sheet-main">{horse}</div>
    <div class="prediction-sheet-sub">{label}</div>
  </div>
  <div class="prediction-sheet-bet">{bet}</div>
  <div class="prediction-sheet-note">{note}</div>
</div>
""".format(
                class_name=html_escape(item["class_name"]),
                mark=html_escape(item["mark"]),
                horse=html_escape(item["horse"]),
                label=html_escape(item["label"]),
                bet=html_escape(item["bet"]),
                note=html_escape(f"{item['note']} / {item['meta']}"),
            )
            for item in mark_items
        )
    )
    st.markdown(sheet_html, unsafe_allow_html=True)


def _build_grade_bet_memo_lines(row: pd.Series, grade_name: str, memo_mode: str = "標準") -> List[str]:
    risk = _render_name_text(row.get("危険人気馬", "-"))
    risk_text = f"危険人気 {risk}" if risk != "-" else "危険人気 市場データ不足"
    mode_text = _to_text(memo_mode) or "標準"
    if mode_text == "堅め":
        return [
            f"軸: 複勝 { _render_name_text(row.get('複勝候補', '-')) } / 単勝 { _render_name_text(row.get('単勝候補', '-')) }",
            f"連系本線: ワイド { _render_name_text(row.get('ワイド候補', '-')) } / 馬連 { _render_name_text(row.get('馬連候補', '-')) }",
            f"押さえ: 馬単 { _render_name_text(row.get('馬単候補', '-')) } / 三連複 { _render_name_text(row.get('三連複候補', '-')) }",
            f"注意: {risk_text}",
        ]
    if mode_text == "穴狙い":
        return [
            f"穴軸: 大穴 { _render_name_text(row.get('大穴候補', '-')) } / 複勝 { _render_name_text(row.get('複勝候補', '-')) }",
            f"連系: ワイド { _render_name_text(row.get('ワイド候補', '-')) } / 馬連 { _render_name_text(row.get('馬連候補', '-')) }",
            f"高配当: 三連複 { _render_name_text(row.get('三連複候補', '-')) } / 三連単 { _render_name_text(row.get('三連単候補', '-')) }",
            f"警戒: {risk_text} / 本命 { _render_name_text(row.get('本命馬', '-')) }",
        ]
    if grade_name == "G1":
        return [
            f"本線: 単勝 { _render_name_text(row.get('単勝候補', '-')) } / 複勝 { _render_name_text(row.get('複勝候補', '-')) }",
            f"連系: 馬連 { _render_name_text(row.get('馬連候補', '-')) } / ワイド { _render_name_text(row.get('ワイド候補', '-')) }",
            f"夢: 三連複 { _render_name_text(row.get('三連複候補', '-')) } / 三連単 { _render_name_text(row.get('三連単候補', '-')) }",
            f"注意: {risk_text}",
        ]
    return [
        f"軸候補: 複勝 { _render_name_text(row.get('複勝候補', '-')) } / 単勝 { _render_name_text(row.get('単勝候補', '-')) }",
        f"連系本線: ワイド { _render_name_text(row.get('ワイド候補', '-')) } / 馬連 { _render_name_text(row.get('馬連候補', '-')) }",
        f"穴狙い: 三連複 { _render_name_text(row.get('三連複候補', '-')) } / 三連単 { _render_name_text(row.get('三連単候補', '-')) }",
        f"警戒: {risk_text} / 大穴 { _render_name_text(row.get('大穴候補', '-')) }",
    ]


def _render_grade_bet_memo_cards(frame: pd.DataFrame, grade_name: str, memo_mode: str = "標準", limit: int = 4) -> None:
    if frame.empty:
        return
    cards: List[str] = []
    for _, row in frame.head(max(1, int(limit))).iterrows():
        lines = "".join(
            f"<div class='memo-line'>{html_escape(line)}</div>"
            for line in _build_grade_bet_memo_lines(row, grade_name, memo_mode)
        )
        cards.append(
            """
<div class="memo-card">
  <div class="memo-chip">{grade}</div>
  <div class="memo-title">{title}</div>
  {lines}
</div>
""".format(
                grade=html_escape(f"{grade_name} | {memo_mode}"),
                title=html_escape(_to_text(row.get("レース", row.get("レース名", "-")))),
                lines=lines,
            )
        )
    st.markdown("<div class='memo-grid'>" + "".join(cards) + "</div>", unsafe_allow_html=True)


def _collect_venue_options(*frames: pd.DataFrame) -> List[str]:
    options = set()
    for frame in frames:
        if not isinstance(frame, pd.DataFrame) or frame.empty or "venue" not in frame.columns:
            continue
        series = frame["venue"].fillna("").astype(str).str.strip()
        options.update(value for value in series if value and value not in ("-", "nan", "None"))
    return sorted(options)


def _apply_venue_filter(
    frame: pd.DataFrame,
    column: str,
    selected_venues: List[str],
    all_venues: List[str],
) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame
    cleaned_selected = [str(value).strip() for value in selected_venues if str(value).strip()]
    if not cleaned_selected or set(cleaned_selected) >= set(all_venues):
        return frame
    out = frame.copy()
    out[column] = out[column].fillna("").astype(str).str.strip()
    return out[out[column].isin(cleaned_selected)].copy()


def _infer_race_grade(race_name: Any) -> str:
    text = _to_text(race_name)
    if not text or text in ("-", "nan", "None"):
        return "未判定"
    normalized = (
        text.replace("Ｇ", "G")
        .replace("Ⅰ", "1")
        .replace("Ⅱ", "2")
        .replace("Ⅲ", "3")
        .replace("Ｉ", "1")
        .replace("ＩＩ", "2")
        .replace("ＩＩＩ", "3")
    )
    explicit_patterns = (
        (r"(?:J\.)?G\s*1|GI\b|Jpn1|Grade\s*1", "G1"),
        (r"(?:J\.)?G\s*2|GII\b|Jpn2|Grade\s*2", "G2"),
        (r"(?:J\.)?G\s*3|GIII\b|Jpn3|Grade\s*3", "G3"),
    )
    for pattern, grade in explicit_patterns:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return grade
    for alias, grade in _RACE_GRADE_ALIASES.items():
        if alias in text:
            return grade
    return "未判定"


def _ensure_race_grade_column(frame: pd.DataFrame, name_col: str = "race_name", grade_col: str = "race_grade") -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    if grade_col not in out.columns:
        if name_col in out.columns:
            out[grade_col] = out[name_col].map(_infer_race_grade)
        else:
            out[grade_col] = "未判定"
    else:
        out[grade_col] = out[grade_col].map(lambda x: _infer_race_grade(x) if _to_text(x) in ("", "-", "nan", "None") else _to_text(x))
    return out


def _collect_grade_options(*frames: pd.DataFrame, grade_col: str = "race_grade") -> List[str]:
    options = {"G1", "G2", "G3", "未判定"}
    for frame in frames:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        work = _ensure_race_grade_column(frame, grade_col=grade_col)
        if grade_col not in work.columns:
            continue
        series = work[grade_col].fillna("").astype(str).str.strip()
        options.update(value for value in series if value)
    return sorted(options, key=lambda x: (_GRADE_ORDER.get(x, 50), x))


def _apply_grade_filter(
    frame: pd.DataFrame,
    selected_grades: List[str],
    all_grades: List[str],
    *,
    grade_col: str = "race_grade",
    name_col: str = "race_name",
) -> pd.DataFrame:
    if frame.empty:
        return frame
    work = _ensure_race_grade_column(frame, name_col=name_col, grade_col=grade_col)
    cleaned_selected = [str(value).strip() for value in selected_grades if str(value).strip()]
    if not cleaned_selected or set(cleaned_selected) >= set(all_grades):
        return work
    return work[work[grade_col].isin(cleaned_selected)].copy()


def _current_week_bounds(today: date | None = None) -> tuple[date, date]:
    ref = today or datetime.now().date()
    week_start = ref - timedelta(days=ref.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def _parse_date_text(value: Any) -> date | None:
    text = _to_text(value)
    if not text or text in ("-", "nan", "None"):
        return None
    normalized = text.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").strip()
    for candidate in (text, normalized):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
        except Exception:
            pass
        for fmt, width in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
            try:
                return datetime.strptime(candidate[:width], fmt).date()
            except Exception:
                pass
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except Exception:
            return None
    return None


def _parse_race_day_from_row(
    row: pd.Series,
    *,
    race_id_col: str = "race_id",
    race_date_col: str = "race_date",
    fetched_col: str = "fetched_date",
) -> date | None:
    race_date = _parse_date_text(row.get(race_date_col, ""))
    if race_date is not None:
        return race_date

    rid = _to_text(row.get(race_id_col, ""))
    digits = re.sub(r"\D", "", rid)
    if len(digits) >= 8:
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except Exception:
            pass

    fetched_date = _parse_date_text(row.get(fetched_col, ""))
    if fetched_date is not None:
        return fetched_date
    return None


def _filter_target_day(
    frame: pd.DataFrame,
    target_day: date,
    *,
    race_id_col: str = "race_id",
    race_date_col: str = "race_date",
    fetched_col: str = "fetched_date",
) -> pd.DataFrame:
    if frame.empty:
        return frame
    work = frame.copy()
    race_days = work.apply(
        lambda row: _parse_race_day_from_row(
            row,
            race_id_col=race_id_col,
            race_date_col=race_date_col,
            fetched_col=fetched_col,
        ),
        axis=1,
    )
    keep_mask = race_days.map(lambda d: bool(d is not None and d == target_day))
    filtered = work[keep_mask].copy()
    filtered.attrs["target_day"] = target_day.isoformat()
    return filtered


def _normalize_local_llm_base_url(base_url: str) -> str:
    text = str(base_url or "").strip()
    return text.rstrip("/") if text else LOCAL_LLM_BASE_URL_DEFAULT


def _ollama_list_models(base_url: str, timeout_sec: int) -> List[str]:
    req = urllib.request.Request(f"{_normalize_local_llm_base_url(base_url)}/api/tags", method="GET")
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    models = payload.get("models", []) if isinstance(payload, dict) else []
    out: List[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name:
            out.append(name)
    return out


def _build_local_llm_keiba_prompt(
    *,
    race_label: str,
    race_grade: str,
    weather: str,
    track_condition: str,
    distance: Any,
    llm_style: str,
    top_table: pd.DataFrame,
    longshot_table: pd.DataFrame,
    risk_table: pd.DataFrame,
    spiritual_table: pd.DataFrame,
    similar_history_text: str = "",
    result_sample_text: str = "",
    memory_sample_text: str = "",
    feedback_sample_text: str = "",
    prediction_ticket_text: str = "",
    odds_shift_alert_text: str = "",
    condition_adjustment_text: str = "",
    feature_diff_text: str = "",
    analog_horse_text: str = "",
    reflection_feedback_text: str = "",
    llm_disagreement_text: str = "",
    llm_disagreement_hit_text: str = "",
    reasoning_mode: str = "",
) -> str:
    def _table_lines(table: pd.DataFrame, limit: int) -> str:
        if table.empty:
            return "- 候補なし"
        lines: List[str] = []
        for _, row in table.head(limit).iterrows():
            gate_text = _to_text(row.get("馬番", "-"))
            lines.append(
                " / ".join(
                    [
                        f"馬番={gate_text}",
                        f"馬={_to_text(row.get('馬', '-'))}",
                        f"人気={_to_text(row.get('人気', '-'))}",
                        f"勝率={_to_text(row.get('勝率', '-'))}",
                        f"複勝率={_to_text(row.get('複勝率', '-'))}",
                        f"理由={_to_text(row.get('理由', '-'))}",
                    ]
                )
            )
        return "\n".join(lines)

    distance_text = "-" if pd.isna(pd.to_numeric(distance, errors="coerce")) else f"{int(float(distance))}m"
    style_text = {
        "保守": "過度な穴狙いは避け、勝率と安定感を優先する。",
        "万馬券狙い": "大穴と人気の盲点を優先し、三連系の夢を残す。",
        "バランス": "本命と穴のバランスを取り、根拠の薄い断定は避ける。",
    }.get(_to_text(llm_style), "本命と穴のバランスを取る。")
    reasoning_text = {
        "標準": "通常モード。全体バランスを見て整理する。",
        "強化": "自己点検モード。中間分析を挟んで矛盾を減らす。",
        "反省": "反省モード。外れたレースの共通点を優先して、同じ外し方を避ける。",
    }.get(_to_text(reasoning_mode), "通常モード。")
    return (
        "あなたは競馬のローカル補助AIです。以下のデータだけを根拠に、予想整理メモを日本語で簡潔に作成してください。\n"
        "出力ルール:\n"
        "- ちょうど6行\n"
        "- 各行は必ず次のラベルで開始: 総評:, 本命視点:, 一発候補:, 危険人気馬:, 買い目案:, 注意:\n"
        "- 断定しない\n"
        "- データにない情報は作らない\n\n"
        f"レース: {race_label}\n"
        f"格付け: {race_grade}\n"
        f"天気: {weather}\n"
        f"馬場: {track_condition}\n"
        f"距離: {distance_text}\n\n"
        f"今回の方針: {style_text}\n\n"
        f"推論モード: {reasoning_text}\n\n"
        "データ本命上位:\n"
        f"{_table_lines(top_table, 3)}\n\n"
        "大穴上位:\n"
        f"{_table_lines(longshot_table, 4)}\n\n"
        "危険人気候補:\n"
        f"{_table_lines(risk_table, 3)}\n\n"
        "スピリチュアル上位:\n"
        f"{_table_lines(spiritual_table, 2)}\n\n"
        "馬ごとの特徴量差分:\n"
        f"{feature_diff_text or '- 差分なし'}\n\n"
        "名前が違っても近い個体の実績:\n"
        f"{analog_horse_text or '- 類似個体なし'}\n\n"
        "近い条件の過去レース:\n"
        f"{similar_history_text or '- 候補なし'}\n"
        "\nローカル結果サンプル:\n"
        f"{result_sample_text or '- サンプルなし'}\n"
        "\n過去の実結果フィードバック:\n"
        f"{feedback_sample_text or '- フィードバックなし'}\n"
        "\n外れレースの反省材料:\n"
        f"{reflection_feedback_text or '- 反省材料なし'}\n"
        "\n今週のLLM別軸レース:\n"
        f"{llm_disagreement_text or '- 別軸レースなし'}\n"
        "\nLLM別軸で当たったレース:\n"
        f"{llm_disagreement_hit_text or '- 別軸ヒットなし'}\n"
        "\n今回の予想票:\n"
        f"{prediction_ticket_text or '- 予想票なし'}\n"
        "\n今回の条件補正:\n"
        f"{condition_adjustment_text or '- 補正なし'}\n"
        "\n人気急変アラート:\n"
        f"{odds_shift_alert_text or '- 人気急変なし'}\n"
        "\n過去のローカル予想メモ:\n"
        f"{memory_sample_text or '- メモなし'}\n"
    )


def _run_local_llm_keiba_comment(
    *,
    base_url: str,
    model: str,
    timeout_sec: int,
    prompt: str,
    temperature: float = 0.4,
) -> str:
    payload = {
        "model": str(model).strip() or LOCAL_LLM_MODEL_DEFAULT,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": float(temperature)},
    }
    req = urllib.request.Request(
        f"{_normalize_local_llm_base_url(base_url)}/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    text = str(body.get("response", "")).strip() if isinstance(body, dict) else ""
    if not text:
        raise ValueError("ローカルLLMの応答が空です")
    return text


def _run_local_llm_keiba_enhanced_comment(
    *,
    base_url: str,
    model: str,
    timeout_sec: int,
    prompt: str,
    temperature: float,
    reasoning_mode: str,
) -> tuple[str, str]:
    mode_text = _to_text(reasoning_mode)
    if mode_text not in {"強化", "反省"}:
        final_text = _run_local_llm_keiba_comment(
            base_url=base_url,
            model=model,
            timeout_sec=timeout_sec,
            prompt=prompt,
            temperature=temperature,
        )
        return final_text, ""

    if mode_text == "反省":
        analysis_prompt = (
            prompt
            + "\n追加指示:\n"
            + "- 「外れレースの反省材料」と「馬ごとの特徴量差分」を優先して読む\n"
            + "- 「今週のLLM別軸レース」を見て、データ本命と逆を向いた共通点も拾う\n"
            + "- 「LLM別軸で当たったレース」を見て、逆を向いて当てた成功パターンも拾う\n"
            + "- 過去メモの タグ= を見て、人気ズレ・馬場注意・距離注意・補正不足 を拾う\n"
            + "- 過去に外した共通点と、今回見直す点を5行以内で整理する\n"
            + "- 出力ラベルは 反省:, 過信:, 見直し:, 穴示唆:, 注意: を使う\n"
        )
        analysis_text = _run_local_llm_keiba_comment(
            base_url=base_url,
            model=model,
            timeout_sec=timeout_sec,
            prompt=analysis_prompt,
            temperature=max(0.15, float(temperature) - 0.15),
        )
        final_prompt = (
            prompt
            + "\n反省メモ:\n"
            + analysis_text
            + "\n\n追加指示:\n"
            + "- 反省メモを最優先し、同じ外し方を避ける\n"
            + "- タグ= に出ている外し方を繰り返さない\n"
            + "- 今週のLLM別軸レースで多いズレ方も参考にする\n"
            + "- 逆を向いて当てた `LLM別軸ヒット` があれば、その成功パターンも残す\n"
            + "- 人気や印だけでなく、馬ごとの特徴量差分と類似個体の実績を必ず根拠に入れる\n"
            + "- ちょうど6行\n"
            + "- 各行は 総評:, 本命視点:, 一発候補:, 危険人気馬:, 買い目案:, 注意: で開始する\n"
        )
        final_text = _run_local_llm_keiba_comment(
            base_url=base_url,
            model=model,
            timeout_sec=timeout_sec,
            prompt=final_prompt,
            temperature=max(0.15, float(temperature) * 0.85),
        )
        return final_text, analysis_text

    analysis_prompt = (
        prompt
        + "\n追加指示:\n"
        + "- まず候補を比較して、どのデータを重く見るかを整理する\n"
        + "- 出力は5行以内\n"
        + "- ラベルは 観点:, 本命候補:, 穴候補:, 危険人気:, 注意: を使う\n"
    )
    analysis_text = _run_local_llm_keiba_comment(
        base_url=base_url,
        model=model,
        timeout_sec=timeout_sec,
        prompt=analysis_prompt,
        temperature=max(0.15, float(temperature) - 0.1),
    )
    final_prompt = (
        prompt
        + "\n中間分析:\n"
        + analysis_text
        + "\n\n追加指示:\n"
        + "- 中間分析の矛盾を自分で点検してから最終メモを出す\n"
        + "- ちょうど6行\n"
        + "- 各行は 総評:, 本命視点:, 一発候補:, 危険人気馬:, 買い目案:, 注意: で開始する\n"
    )
    final_text = _run_local_llm_keiba_comment(
        base_url=base_url,
        model=model,
        timeout_sec=timeout_sec,
        prompt=final_prompt,
        temperature=max(0.15, float(temperature) * 0.9),
    )
    return final_text, analysis_text


def _store_weekly_predictions_preview(frame: pd.DataFrame) -> pd.DataFrame:
    filtered = prepare_weekly_predictions_preview(frame)
    st.session_state["weekly_predictions_preview"] = filtered.to_dict(orient="records")
    return filtered


def _refresh_selected_weekly_prediction(
    race_id: str,
    *,
    simulations_per_race: int,
    seed: int,
) -> pd.DataFrame:
    selected_race_id = _to_text(race_id)
    if not selected_race_id:
        raise ValueError("race_id が空です")

    history_path = Path(st.session_state.get("auto_history_path", str(AUTO_HISTORY_PATH)))
    entries_path = Path(st.session_state.get("auto_entries_path", str(AUTO_ENTRIES_PATH)))
    history_df = _read_csv_if_exists(history_path)
    entries_df = _read_csv_if_exists(entries_path)
    if history_df is None or history_df.empty:
        raise ValueError(f"履歴データがありません: {history_path}")
    if entries_df is None or entries_df.empty:
        raise ValueError(f"今週出走データがありません: {entries_path}")
    if "race_id" not in entries_df.columns:
        raise ValueError("出走データに race_id がありません")

    race_entries = entries_df[entries_df["race_id"].fillna("").astype(str).str.strip() == selected_race_id].copy()
    if race_entries.empty:
        raise ValueError(f"対象レースが見つかりません: {selected_race_id}")

    feature_weights = _load_auto_feature_weights()
    condition_adjustments = _load_auto_condition_adjustments()
    refreshed = _build_weekly_auto_predictions(
        history_df,
        race_entries,
        simulations_per_race=int(simulations_per_race),
        seed=int(seed),
        feature_weights=feature_weights,
        condition_adjustments=condition_adjustments,
    )
    if refreshed.empty:
        raise ValueError("対象レースの再計算結果が空です")

    current_weekly = _read_csv_if_exists(WEEKLY_PREDICTIONS_PATH)
    merged = merge_selected_weekly_prediction(current_weekly, refreshed, selected_race_id)
    save_weekly_predictions(merged, WEEKLY_PREDICTIONS_PATH)
    st.session_state["weekly_predictions_path"] = str(WEEKLY_PREDICTIONS_PATH)
    _store_weekly_predictions_preview(merged)
    return refreshed


def _build_weekly_race_overview(entries_df: pd.DataFrame) -> pd.DataFrame:
    if entries_df.empty:
        return pd.DataFrame()
    work = _ensure_race_grade_column(entries_df.copy())
    if "race_id" not in work.columns:
        work["race_id"] = "RACE_AUTO"

    agg_items: Dict[str, Any] = {}
    if "race_date" in work.columns:
        agg_items["日付"] = ("race_date", "first")
    elif "fetched_date" in work.columns:
        agg_items["日付"] = ("fetched_date", "first")
    if "race_name" in work.columns:
        agg_items["レース名"] = ("race_name", "first")
    if "race_grade" in work.columns:
        agg_items["格付"] = ("race_grade", "first")
    if "venue" in work.columns:
        agg_items["開催"] = ("venue", "first")
    if "horse" in work.columns:
        agg_items["頭数"] = ("horse", "count")
        agg_items["注目馬"] = ("horse", lambda s: _join_names(s, limit=4))
    if "jockey" in work.columns:
        agg_items["注目騎手"] = ("jockey", lambda s: _join_names(s, limit=4))
    if "weather" in work.columns:
        agg_items["天気予報"] = ("weather", "first")
    if "track_condition" in work.columns:
        agg_items["馬場"] = ("track_condition", "first")
    if "distance" in work.columns:
        agg_items["距離"] = ("distance", "first")
    if "forecast_precip_prob" in work.columns:
        agg_items["降水確率"] = ("forecast_precip_prob", "max")
    if "forecast_temp_max_c" in work.columns:
        agg_items["最高気温"] = ("forecast_temp_max_c", "max")

    if not agg_items:
        return pd.DataFrame()
    out = work.groupby("race_id").agg(**agg_items).reset_index().rename(columns={"race_id": "レースID"})
    out = _sort_by_race_id_safe(out, "レースID", ascending=True)

    if "日付" in out.columns:
        out["日付"] = out["日付"].map(_format_date_text)
    if "レース名" in out.columns:
        out["レース名"] = out["レース名"].map(lambda x: "-" if _to_text(x) in ("", "nan", "None") else _to_text(x))
    if "距離" in out.columns:
        out["距離"] = pd.to_numeric(out["距離"], errors="coerce").map(lambda x: "-" if pd.isna(x) else f"{int(float(x))}m")
    if "降水確率" in out.columns:
        out["降水確率"] = pd.to_numeric(out["降水確率"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{float(x):.0f}%"
        )
    if "最高気温" in out.columns:
        out["最高気温"] = pd.to_numeric(out["最高気温"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{float(x):.1f}C"
        )
    return out


def _build_recent_history_overview(history_df: pd.DataFrame, limit: int = 12) -> pd.DataFrame:
    if history_df.empty or "race_id" not in history_df.columns:
        return pd.DataFrame()
    work = history_df.copy()
    agg_items: Dict[str, Any] = {}
    if "venue" in work.columns:
        agg_items["開催"] = ("venue", "first")
    if "horse" in work.columns:
        agg_items["頭数"] = ("horse", "count")
    if "weather" in work.columns:
        agg_items["天気"] = ("weather", "first")
    if "track_condition" in work.columns:
        agg_items["馬場"] = ("track_condition", "first")
    if "distance" in work.columns:
        agg_items["距離"] = ("distance", "first")
    if "finish" in work.columns:
        agg_items["平均着順"] = ("finish", "mean")

    out = work.groupby("race_id").agg(**agg_items).reset_index().rename(columns={"race_id": "レースID"})
    out = _sort_by_race_id_safe(out, "レースID", ascending=False).head(max(1, int(limit)))

    if "距離" in out.columns:
        out["距離"] = pd.to_numeric(out["距離"], errors="coerce").map(lambda x: "-" if pd.isna(x) else f"{int(float(x))}m")
    if "平均着順" in out.columns:
        out["平均着順"] = pd.to_numeric(out["平均着順"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{float(x):.2f}"
        )
    return out


def _build_similar_history_table(
    history_df: pd.DataFrame,
    *,
    venue: Any,
    weather: Any,
    track_condition: Any,
    distance: Any,
    limit: int = 5,
) -> pd.DataFrame:
    if history_df.empty or "race_id" not in history_df.columns:
        return pd.DataFrame()

    work = history_df.copy()
    agg_items: Dict[str, Any] = {}
    if "venue" in work.columns:
        agg_items["開催"] = ("venue", "first")
    if "weather" in work.columns:
        agg_items["天気"] = ("weather", "first")
    if "track_condition" in work.columns:
        agg_items["馬場"] = ("track_condition", "first")
    if "distance" in work.columns:
        agg_items["距離"] = ("distance", "first")
    if "horse" in work.columns:
        agg_items["頭数"] = ("horse", "count")
    if "finish" in work.columns:
        agg_items["平均着順"] = ("finish", "mean")
        agg_items["勝ち馬"] = (
            "horse",
            lambda s: _to_text(s.loc[s.index[0]])
            if not s.empty
            else "-",
        )
    if "jockey" in work.columns and "finish" in work.columns:
        agg_items["勝ち騎手"] = (
            "jockey",
            lambda s: _to_text(s.loc[s.index[0]])
            if not s.empty
            else "-",
        )
    if not agg_items:
        return pd.DataFrame()

    race_level = work.groupby("race_id").agg(**agg_items).reset_index().rename(columns={"race_id": "レースID"})
    if "finish" in work.columns and "horse" in work.columns:
        winners = work.copy()
        winners["finish_num"] = pd.to_numeric(winners["finish"], errors="coerce")
        winners = winners[winners["finish_num"] == 1].copy()
        if not winners.empty:
            win_map = winners.groupby("race_id").agg(
                勝ち馬=("horse", "first"),
                勝ち騎手=("jockey", "first") if "jockey" in winners.columns else ("horse", "first"),
            ).reset_index().rename(columns={"race_id": "レースID"})
            race_level = race_level.drop(columns=[c for c in ["勝ち馬", "勝ち騎手"] if c in race_level.columns]).merge(
                win_map, on="レースID", how="left"
            )

    venue_text = _to_text(venue)
    weather_text = _to_text(weather)
    track_text = _to_text(track_condition)
    distance_num = pd.to_numeric(pd.Series([distance]), errors="coerce").iloc[0]

    score = pd.Series(0.0, index=race_level.index, dtype=float)
    if "開催" in race_level.columns and venue_text:
        score += race_level["開催"].map(lambda x: 2.8 if _to_text(x) == venue_text else 0.0)
    if "天気" in race_level.columns and weather_text:
        score += race_level["天気"].map(lambda x: 0.7 if _to_text(x) == weather_text else 0.0)
    if "馬場" in race_level.columns and track_text:
        score += race_level["馬場"].map(lambda x: 1.0 if _to_text(x) == track_text else 0.0)
    if "距離" in race_level.columns and pd.notna(distance_num):
        dist_diff = (pd.to_numeric(race_level["距離"], errors="coerce") - float(distance_num)).abs()
        score += (1.2 - (dist_diff.clip(lower=0.0, upper=1200.0) / 1000.0)).clip(lower=0.0).fillna(0.0)

    race_level["一致度"] = score
    race_level = race_level[race_level["一致度"] > 0].copy()
    if race_level.empty:
        return pd.DataFrame()

    if "距離" in race_level.columns:
        race_level["距離"] = pd.to_numeric(race_level["距離"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{int(float(x))}m"
        )
    if "平均着順" in race_level.columns:
        race_level["平均着順"] = pd.to_numeric(race_level["平均着順"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{float(x):.2f}"
        )
    race_level["日付"] = race_level["レースID"].map(_format_date_text)
    race_level["レース"] = race_level.apply(
        lambda row: _format_race_label(row.get("レースID", ""), row.get("開催", ""), row.get("日付", ""), ""),
        axis=1,
    )
    race_level["一致度"] = pd.to_numeric(race_level["一致度"], errors="coerce").map(lambda x: f"{float(x):.2f}")
    race_level = _sort_by_race_id_safe(race_level, "レースID", ascending=False)
    race_level["一致度_num"] = pd.to_numeric(race_level["一致度"], errors="coerce")
    race_level = race_level.sort_values(["一致度_num", "レースID"], ascending=[False, False]).head(max(1, int(limit)))
    race_level = race_level.drop(columns=["一致度_num"], errors="ignore")
    cols = ["レース", "一致度", "開催", "天気", "馬場", "距離", "勝ち馬", "勝ち騎手", "頭数", "平均着順", "レースID"]
    return race_level[[c for c in cols if c in race_level.columns]].reset_index(drop=True)


def _similar_history_to_prompt_text(table: pd.DataFrame, limit: int = 4) -> str:
    if table.empty:
        return "- 候補なし"
    lines: List[str] = []
    for _, row in table.head(max(1, int(limit))).iterrows():
        lines.append(
            " / ".join(
                [
                    f"レース={_to_text(row.get('レース', '-'))}",
                    f"一致度={_to_text(row.get('一致度', '-'))}",
                    f"勝ち馬={_to_text(row.get('勝ち馬', '-'))}",
                    f"勝ち騎手={_to_text(row.get('勝ち騎手', '-'))}",
                    f"馬場={_to_text(row.get('馬場', '-'))}",
                    f"距離={_to_text(row.get('距離', '-'))}",
                ]
            )
        )
    return "\n".join(lines)


def _build_racecourse_overview(entries_df: pd.DataFrame, history_df: pd.DataFrame) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []

    if not entries_df.empty and "venue" in entries_df.columns:
        ent = entries_df.copy()
        ent["venue"] = ent["venue"].fillna("").astype(str).str.strip()
        ent = ent[ent["venue"] != ""]
        if not ent.empty:
            agg_items: Dict[str, Any] = {}
            if "race_id" in ent.columns:
                agg_items["今週レース数"] = ("race_id", "nunique")
            if "horse" in ent.columns:
                agg_items["今週出走頭数"] = ("horse", "count")
            if "weather" in ent.columns:
                agg_items["今週天気予報"] = ("weather", "first")
            if "forecast_precip_prob" in ent.columns:
                agg_items["降水確率"] = ("forecast_precip_prob", "max")
            if agg_items:
                up = ent.groupby("venue").agg(**agg_items).reset_index().rename(columns={"venue": "競馬場"})
                frames.append(up)

    if not history_df.empty and "venue" in history_df.columns:
        hist = history_df.copy()
        hist["venue"] = hist["venue"].fillna("").astype(str).str.strip()
        hist = hist[hist["venue"] != ""]
        if not hist.empty:
            agg_items_hist: Dict[str, Any] = {}
            if "race_id" in hist.columns:
                agg_items_hist["過去レース数"] = ("race_id", "nunique")
            if "finish" in hist.columns:
                agg_items_hist["過去平均着順"] = ("finish", "mean")
                agg_items_hist["過去勝率"] = ("finish", lambda s: float((pd.to_numeric(s, errors="coerce") == 1).mean()))
            if agg_items_hist:
                past = hist.groupby("venue").agg(**agg_items_hist).reset_index().rename(columns={"venue": "競馬場"})
                frames.append(past)

    if not frames:
        return pd.DataFrame()
    merged = frames[0]
    for f in frames[1:]:
        merged = merged.merge(f, on="競馬場", how="outer")
    if "過去平均着順" in merged.columns:
        merged["過去平均着順"] = pd.to_numeric(merged["過去平均着順"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{float(x):.2f}"
        )
    if "過去勝率" in merged.columns:
        merged["過去勝率"] = pd.to_numeric(merged["過去勝率"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{float(x):.2%}"
        )
    if "降水確率" in merged.columns:
        merged["降水確率"] = pd.to_numeric(merged["降水確率"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{float(x):.0f}%"
        )
    sort_cols = [c for c in ["今週レース数", "今週出走頭数"] if c in merged.columns]
    if sort_cols:
        merged = merged.sort_values(sort_cols, ascending=False)
    return merged.reset_index(drop=True)


def _apply_auto_update_report(report: AutoUpdateReport) -> None:
    st.session_state["auto_history_path"] = str(report.history_path)
    st.session_state["auto_entries_path"] = str(report.entries_path)
    if report.weights_path is not None:
        st.session_state["auto_weights_path"] = str(report.weights_path)
    st.session_state["auto_last_report"] = {
        "history_rows": report.history_rows,
        "entries_rows": report.entries_rows,
        "history_races": report.history_races,
        "weekly_races": report.weekly_races,
        "tuned": report.tuned,
        "notes": list(report.notes[-10:]),
    }


def _run_auto_update_pipeline(
    *,
    months_back: int,
    weekly_days_ahead: int,
    incremental: bool,
    full_refresh: bool,
    history_backfill_days: int,
    append_only: bool,
    entries_cache_hours: int,
    auto_forecast_weather: bool,
    weather_cache_hours: int,
    fallback_max_days: int,
    run_tuning: bool,
    update_history: bool = True,
    update_entries: bool = True,
    history_race_id_allowlist: List[str] | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> AutoUpdateReport:
    report = fetch_auto_data(
        data_dir=DATA_DIR,
        months_back=int(months_back),
        weekly_days_ahead=int(weekly_days_ahead),
        incremental=bool(incremental),
        full_refresh=bool(full_refresh),
        history_backfill_days=int(history_backfill_days),
        append_only=bool(append_only),
        entries_cache_hours=max(0, int(entries_cache_hours)),
        update_history=bool(update_history),
        update_entries=bool(update_entries),
        auto_forecast_weather=bool(auto_forecast_weather),
        weather_cache_hours=max(0, int(weather_cache_hours)),
        fallback_max_days=int(fallback_max_days),
        run_tuning=bool(run_tuning),
        tuning_trials=40,
        tuning_val_races=30,
        tuning_simulations=1500,
        history_race_id_allowlist=history_race_id_allowlist,
        progress_callback=progress_callback,
    )
    _apply_auto_update_report(report)
    return report


def _prediction_row_race_day(row: pd.Series | Dict[str, Any]) -> date | None:
    parsed = _parse_date_text(row.get("race_date", ""))
    if parsed is not None:
        return parsed
    digits = re.sub(r"\D", "", _to_text(row.get("race_id", "")))
    if len(digits) >= 8:
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except Exception:
            return None
    return None


def _load_result_fetch_state() -> Dict[str, Any]:
    payload = _read_json_if_exists(RESULT_FETCH_STATE_PATH)
    if not isinstance(payload, dict):
        return {"attempts": {}}
    attempts = payload.get("attempts", {})
    payload["attempts"] = attempts if isinstance(attempts, dict) else {}
    return payload


def _save_result_fetch_state(payload: Dict[str, Any]) -> None:
    out = dict(payload) if isinstance(payload, dict) else {"attempts": {}}
    attempts = out.get("attempts", {})
    out["attempts"] = attempts if isinstance(attempts, dict) else {}
    out["updated_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        RESULT_FETCH_STATE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _recent_result_fetch_skip_ids(*, cooldown_hours: float = 6.0) -> set[str]:
    state = _load_result_fetch_state()
    attempts = state.get("attempts", {})
    if not isinstance(attempts, dict):
        return set()
    out: set[str] = set()
    now_value = datetime.now()
    for race_id, payload in attempts.items():
        if not isinstance(payload, dict):
            continue
        last_attempt = _parse_timestamp_value(payload.get("last_attempted_at", ""))
        if last_attempt is None:
            continue
        now_for_attempt = datetime.now(last_attempt.tzinfo) if last_attempt.tzinfo else now_value
        age_hours = (now_for_attempt - last_attempt).total_seconds() / 3600.0
        if 0 <= age_hours < max(0.1, float(cooldown_hours)):
            out.add(_to_text(race_id))
    return {race_id for race_id in out if race_id}


def _record_result_fetch_attempts(race_ids: List[str], *, status: str = "attempted") -> None:
    cleaned = list(dict.fromkeys([_to_text(race_id) for race_id in race_ids if _to_text(race_id)]))
    if not cleaned:
        return
    state = _load_result_fetch_state()
    attempts = state.get("attempts", {})
    if not isinstance(attempts, dict):
        attempts = {}
    now_text = datetime.now().isoformat(timespec="seconds")
    for race_id in cleaned:
        existing = attempts.get(race_id, {})
        if not isinstance(existing, dict):
            existing = {}
        attempts[race_id] = {
            "last_attempted_at": now_text,
            "attempt_count": int(existing.get("attempt_count", 0) or 0) + 1,
            "last_status": _to_text(status) or "attempted",
        }
    state["attempts"] = attempts
    state["last_attempted_count"] = int(len(cleaned))
    state["last_attempt_status"] = _to_text(status) or "attempted"
    _save_result_fetch_state(state)


def _pending_prediction_race_ids_for_result_update(
    feedback_df: pd.DataFrame | None = None,
    *,
    cap: int = 300,
) -> List[str]:
    source = feedback_df.copy() if isinstance(feedback_df, pd.DataFrame) else pd.DataFrame()
    if source.empty:
        loaded_feedback = _read_csv_if_exists(PREDICTION_FEEDBACK_PATH)
        source = loaded_feedback.copy() if isinstance(loaded_feedback, pd.DataFrame) else pd.DataFrame()
    if source.empty:
        archive_df = _read_csv_if_exists(PREDICTION_ARCHIVE_PATH)
        source = archive_df.copy() if isinstance(archive_df, pd.DataFrame) else pd.DataFrame()
    if source.empty or "race_id" not in source.columns:
        return []
    work = source.copy()
    work["race_id"] = work["race_id"].map(_to_text)
    work = work[work["race_id"] != ""].copy()
    if work.empty:
        return []
    if "result_available" in work.columns:
        work = work[~_truthy_series(work["result_available"])].copy()
    if work.empty:
        return []
    work["_race_day"] = work.apply(_prediction_row_race_day, axis=1)
    today_value = date.today()
    work = work[work["_race_day"].map(lambda value: bool(value is not None and value <= today_value))].copy()
    if work.empty:
        return []
    work = work.sort_values(["_race_day", "race_id"], ascending=[True, True], na_position="last")
    race_ids = [race_id for race_id in work["race_id"].tolist() if race_id]
    race_ids = list(dict.fromkeys(race_ids))
    skip_ids = _recent_result_fetch_skip_ids(cooldown_hours=6.0)
    if skip_ids:
        unskipped = [race_id for race_id in race_ids if race_id not in skip_ids]
        race_ids = unskipped or race_ids
    if int(cap) > 0:
        race_ids = race_ids[: int(cap)]
    return race_ids


def _recent_prediction_race_ids_for_result_update(days_back: int = 2, days_ahead: int = 0) -> List[str]:
    archive_df = _read_csv_if_exists(PREDICTION_ARCHIVE_PATH)
    if archive_df is None or archive_df.empty or "race_id" not in archive_df.columns:
        return []

    lower = date.today() - timedelta(days=max(0, int(days_back)))
    upper = date.today() + timedelta(days=max(0, int(days_ahead)))
    work = archive_df.copy()
    work["race_id"] = work["race_id"].map(_to_text)
    work["_race_day"] = work.apply(_prediction_row_race_day, axis=1)
    work = work[work["_race_day"].notna()].copy()
    work = work[(work["_race_day"] >= lower) & (work["_race_day"] <= upper)].copy()
    if work.empty:
        return []
    race_ids = [race_id for race_id in work["race_id"].tolist() if race_id]
    return list(dict.fromkeys(race_ids))


def _run_condition_adjustment_light_tuning(
    *,
    trials: int = 18,
    val_races: int = 12,
    simulations: int = 1200,
) -> Dict[str, Any]:
    history_path = Path(st.session_state.get("auto_history_path", str(AUTO_HISTORY_PATH)))
    weights_path = Path(st.session_state.get("auto_weights_path", str(AUTO_WEIGHTS_PATH)))
    prediction_archive_df = _read_csv_if_exists(PREDICTION_ARCHIVE_PATH)
    feature_archive_df = _read_csv_if_exists(PREDICTION_FEATURE_ARCHIVE_PATH)

    if not history_path.exists():
        raise ValueError(f"履歴データがありません: {history_path}")
    if prediction_archive_df is None or prediction_archive_df.empty:
        raise ValueError("予想アーカイブがありません。先に今週AI予想を更新してください。")
    if feature_archive_df is None or feature_archive_df.empty:
        raise ValueError("予測特徴量アーカイブがありません。先にレース予想を実行してください。")

    archive_work = prediction_archive_df.copy()
    archive_work["condition_adjustment_count_num"] = pd.to_numeric(
        archive_work.get("condition_adjustment_count", pd.Series(index=archive_work.index, dtype=float)),
        errors="coerce",
    ).fillna(0).astype(int)
    tuned_race_ids = archive_work.loc[archive_work["condition_adjustment_count_num"] > 0, "race_id"].map(_to_text)
    tuned_race_ids = [race_id for race_id in tuned_race_ids.tolist() if race_id]
    if not tuned_race_ids:
        raise ValueError("条件補正が効いた保存済みレースがまだありません。先に今週AI予想を更新してください。")

    feature_work = feature_archive_df.copy()
    feature_work["race_id"] = feature_work["race_id"].map(_to_text)
    feature_work = feature_work[feature_work["race_id"].isin(set(tuned_race_ids))].copy()
    if feature_work.empty:
        raise ValueError("条件補正レースに対応する特徴量アーカイブがありません。対象レースの詳細予想を一度表示してください。")

    filtered_feature_path = DATA_DIR / "prediction_feature_archive_condition_only.csv"
    _write_csv(filtered_feature_path, feature_work)

    cmd = [
        sys.executable,
        str(APP_DIR / "tools" / "tune_feature_weights.py"),
        "--history",
        str(history_path),
        "--out",
        str(weights_path),
        "--trials",
        str(max(6, int(trials))),
        "--val-races",
        str(max(4, int(val_races))),
        "--simulations",
        str(max(400, int(simulations))),
        "--prediction-features",
        str(filtered_feature_path),
    ]
    completed = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        timeout=900,
    )
    st.session_state["auto_weights_path"] = str(weights_path)
    return {
        "weights_path": str(weights_path),
        "feature_rows": int(len(feature_work)),
        "race_count": int(feature_work["race_id"].nunique()),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _run_reflection_light_tuning(
    *,
    trials: int = 16,
    val_races: int = 10,
    simulations: int = 1000,
) -> Dict[str, Any]:
    history_path = Path(st.session_state.get("auto_history_path", str(AUTO_HISTORY_PATH)))
    weights_path = Path(st.session_state.get("auto_weights_path", str(AUTO_WEIGHTS_PATH)))
    feature_archive_path = PREDICTION_FEATURE_ARCHIVE_PATH

    if not history_path.exists():
        raise ValueError(f"履歴データがありません: {history_path}")
    if not feature_archive_path.exists():
        raise ValueError("予測特徴量アーカイブがありません。先にレース予想を実行してください。")

    cmd = [
        sys.executable,
        str(APP_DIR / "tools" / "tune_feature_weights.py"),
        "--history",
        str(history_path),
        "--out",
        str(weights_path),
        "--trials",
        str(max(6, int(trials))),
        "--val-races",
        str(max(4, int(val_races))),
        "--simulations",
        str(max(400, int(simulations))),
        "--prediction-features",
        str(feature_archive_path),
        "--focus",
        "reflection",
    ]
    completed = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        timeout=900,
    )
    st.session_state["auto_weights_path"] = str(weights_path)
    result: Dict[str, Any] = {
        "weights_path": str(weights_path),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "feature_rows": 0,
        "race_count": 0,
        "reflection_rows": 0,
    }
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {"feature_rows", "race_count", "reflection_rows"}:
            try:
                result[key] = int(float(value.strip()))
            except Exception:
                continue
    return result


def _format_probability_tables(result: PredictionResult) -> Dict[str, pd.DataFrame]:
    formatted: Dict[str, pd.DataFrame] = {}
    for name, table in result.bet_recommendations.items():
        if table.empty:
            formatted[name] = table
            continue
        out = table.copy()
        for col in ("的中確率",):
            if col in out.columns:
                out[col] = out[col].map(lambda x: f"{x:.2%}")
        for col in ("推奨度",):
            if col in out.columns:
                out[col] = out[col].map(lambda x: f"{x:.2f}")
        for col in ("理論オッズ", "単勝オッズ", "複勝オッズ"):
            if col in out.columns:
                out[col] = out[col].map(
                    lambda x: "-" if pd.isna(x) else ("∞" if float(x) > 9999 else f"{float(x):.2f}")
                )
        for col in ("単勝期待値", "複勝期待値"):
            if col in out.columns:
                out[col] = out[col].map(lambda x: "-" if pd.isna(x) else f"{float(x):+.2f}")
        formatted[name] = out
    return formatted


def _extract_feature_weights_from_payload(payload: Dict[str, Any] | None) -> Dict[str, float] | None:
    if not isinstance(payload, dict):
        return None
    source = payload["best_weights"] if isinstance(payload.get("best_weights"), dict) else payload
    if not isinstance(source, dict):
        return None
    weights: Dict[str, float] = {}
    for key, value in source.items():
        try:
            weights[str(key)] = float(value)
        except Exception:
            continue
    return weights or None


def _extract_condition_adjustments_from_payload(payload: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    adjustments = payload.get("condition_adjustments")
    return adjustments if isinstance(adjustments, dict) else None


def _load_auto_model_payload() -> Dict[str, Any] | None:
    auto_weights_path = Path(st.session_state.get("auto_weights_path", str(AUTO_WEIGHTS_PATH)))
    return read_weights_json(auto_weights_path)


def _load_auto_feature_weights() -> Dict[str, float] | None:
    return _extract_feature_weights_from_payload(_load_auto_model_payload())


def _load_auto_condition_adjustments() -> Dict[str, Any] | None:
    return _extract_condition_adjustments_from_payload(_load_auto_model_payload())


def _build_weight_change_table(
    before_payload: Dict[str, Any] | None,
    after_payload: Dict[str, Any] | None,
    *,
    top_n: int = 14,
) -> pd.DataFrame:
    before_weights = _extract_feature_weights_from_payload(before_payload) or {}
    after_weights = _extract_feature_weights_from_payload(after_payload) or {}
    all_keys = sorted(set(before_weights) | set(after_weights))
    if not all_keys:
        return pd.DataFrame(columns=["特徴量", "前", "後", "差分", "倍率", "変化"])

    label_map = {
        "horse_win": "馬勝率",
        "horse_place": "馬複勝率",
        "jockey_win": "騎手勝率",
        "jockey_place": "騎手複勝率",
        "trainer_win": "厩舎勝率",
        "trainer_place": "厩舎複勝率",
        "gate_place": "枠適性",
        "weather_place": "天気適性",
        "track_place": "馬場適性",
        "distance_fit": "距離適性",
        "form_score": "調子",
        "condition_score": "状態",
        "paddock_score": "気配",
        "weight_diff_score": "馬体重",
        "odds_shift_score": "人気急変",
        "market_score": "市場評価",
    }
    rows: List[Dict[str, Any]] = []
    for key in all_keys:
        before_value = before_weights.get(key)
        after_value = after_weights.get(key)
        if before_value is None and after_value is None:
            continue
        before_num = float(before_value) if before_value is not None else 0.0
        after_num = float(after_value) if after_value is not None else 0.0
        diff = after_num - before_num
        ratio = (after_num / before_num) if before_num not in (0, 0.0) else None
        rows.append(
            {
                "特徴量": label_map.get(key, key),
                "前": before_num,
                "後": after_num,
                "差分": diff,
                "倍率": ratio,
                "変化": "強化" if diff > 0 else ("抑制" if diff < 0 else "維持"),
                "_abs_diff": abs(diff),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["特徴量", "前", "後", "差分", "倍率", "変化"])
    out = out.sort_values(["_abs_diff", "特徴量"], ascending=[False, True]).head(max(1, int(top_n))).drop(columns=["_abs_diff"])
    return out.reset_index(drop=True)


def _store_weight_change_table(
    before_payload: Dict[str, Any] | None,
    after_payload: Dict[str, Any] | None,
    *,
    mode_label: str,
) -> pd.DataFrame:
    table = _build_weight_change_table(before_payload, after_payload)
    if not table.empty:
        out = table.copy()
        out.insert(0, "学習モード", mode_label)
        _write_csv(WEIGHT_CHANGE_PATH, out)
        st.session_state["latest_weight_change_table"] = out.to_dict(orient="records")
    else:
        st.session_state["latest_weight_change_table"] = []
    before_adjustments = _extract_condition_adjustments_from_payload(before_payload) or {}
    after_adjustments = _extract_condition_adjustments_from_payload(after_payload) or {}
    st.session_state["latest_weight_change_meta"] = {
        "mode": mode_label,
        "before_segments": int(before_adjustments.get("segment_count", 0)) if isinstance(before_adjustments, dict) else 0,
        "after_segments": int(after_adjustments.get("segment_count", 0)) if isinstance(after_adjustments, dict) else 0,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
    }
    return table


def _load_latest_weight_change_table() -> pd.DataFrame:
    records = st.session_state.get("latest_weight_change_table")
    if isinstance(records, list) and records:
        return pd.DataFrame(records)
    loaded = _read_csv_if_exists(WEIGHT_CHANGE_PATH)
    return loaded if loaded is not None else pd.DataFrame()


def _build_weight_change_focus_tables(table: pd.DataFrame, limit: int = 4) -> tuple[pd.DataFrame, pd.DataFrame]:
    if table.empty or "差分" not in table.columns:
        empty = pd.DataFrame(columns=["特徴量", "差分", "倍率", "変化"])
        return empty, empty
    work = table.copy()
    work["差分_num"] = pd.to_numeric(work["差分"], errors="coerce")
    up = work[work["差分_num"] > 0].sort_values(["差分_num", "特徴量"], ascending=[False, True]).head(max(1, int(limit))).copy()
    down = work[work["差分_num"] < 0].sort_values(["差分_num", "特徴量"], ascending=[True, True]).head(max(1, int(limit))).copy()
    keep_cols = [col for col in ["特徴量", "差分", "倍率", "変化"] if col in work.columns]
    return up[keep_cols].reset_index(drop=True), down[keep_cols].reset_index(drop=True)


def _maybe_run_auto_self_improvement(
    feedback_df: pd.DataFrame | None,
    *,
    enabled: bool,
    sync_feedback_memory: bool,
    auto_reflection_learning: bool,
    auto_refresh_weekly: bool,
    min_new_results_for_reflection: int,
    min_missed_results_for_reflection: int,
    reflection_cooldown_minutes: int,
    weekly_simulations: int,
    weekly_seed: int = 42,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "new_result_rows": 0,
        "memory_rows_added": 0,
        "reflection_ran": False,
        "weekly_races_updated": 0,
        "message": "",
        "weekly_df": pd.DataFrame(),
        "weight_change_table": pd.DataFrame(),
    }
    state = _load_auto_improve_state()
    if not enabled or feedback_df is None or feedback_df.empty:
        _save_auto_improve_state_checkpoint(state)
        return report

    work = feedback_df.copy()
    if "result_available" not in work.columns:
        _save_auto_improve_state_checkpoint(state)
        return report

    result_mask = _truthy_series(work["result_available"])
    work = work[result_mask].copy()
    if work.empty:
        _save_auto_improve_state_checkpoint(state)
        return report

    work["feedback_key"] = work.apply(_feedback_row_key, axis=1)
    work = work.sort_values(["race_date", "race_id", "predicted_at"], ascending=[True, True, True], na_position="last")
    memory_synced_keys = set(_trim_text_list(list(state.get("memory_synced_keys", []))))
    reflection_trained_keys = set(_trim_text_list(list(state.get("reflection_trained_keys", []))))

    new_result_rows = work[~work["feedback_key"].isin(memory_synced_keys)].copy()
    report["new_result_rows"] = int(len(new_result_rows))
    if sync_feedback_memory and not new_result_rows.empty:
        added = 0
        for _, row in new_result_rows.tail(max(1, int(len(new_result_rows)))).iterrows():
            _append_local_llm_memory_sample(_build_feedback_memory_payload(row))
            memory_synced_keys.add(_to_text(row.get("feedback_key", "")))
            added += 1
        state["last_memory_sync_at"] = datetime.now().isoformat(timespec="seconds")
        state["last_memory_sync_count"] = int(added)
        state["last_memory_sync_summary"] = _build_feedback_memory_summary(new_result_rows.iloc[-1]) if added else "-"
        report["memory_rows_added"] = int(added)

    pending_reflection_rows = work[~work["feedback_key"].isin(reflection_trained_keys)].copy()
    if "top_horse_hit" in pending_reflection_rows.columns:
        missed_mask = ~_truthy_series(pending_reflection_rows["top_horse_hit"])
        missed_rows = pending_reflection_rows[missed_mask].copy()
    else:
        missed_rows = pending_reflection_rows.copy()

    cooldown_ok = True
    last_reflection_at = _to_text(state.get("last_auto_reflection_at", ""))
    if last_reflection_at:
        try:
            last_run = datetime.fromisoformat(last_reflection_at.replace("Z", "+00:00"))
            cooldown_ok = (datetime.now() - last_run) >= timedelta(minutes=max(1, int(reflection_cooldown_minutes)))
        except Exception:
            cooldown_ok = True

    should_run_reflection = bool(
        auto_reflection_learning
        and not pending_reflection_rows.empty
        and cooldown_ok
        and (
            len(pending_reflection_rows) >= max(1, int(min_new_results_for_reflection))
            or len(missed_rows) >= max(1, int(min_missed_results_for_reflection))
        )
    )

    if should_run_reflection:
        before_payload = _load_auto_model_payload()
        tuning_result = _run_reflection_light_tuning(
            trials=10,
            val_races=8,
            simulations=900,
        )
        after_payload = _load_auto_model_payload()
        weight_change_table = _store_weight_change_table(before_payload, after_payload, mode_label="自動反省再学習")
        report["weight_change_table"] = weight_change_table
        report["reflection_ran"] = True
        state["last_auto_reflection_at"] = datetime.now().isoformat(timespec="seconds")
        state["last_auto_reflection_result"] = (
            f"対象 {int(tuning_result.get('race_count', 0)):,} レース / "
            f"反省 {int(tuning_result.get('reflection_rows', 0)):,} 行"
        )
        for key in pending_reflection_rows["feedback_key"].map(_to_text).tolist():
            if key:
                reflection_trained_keys.add(key)
        if auto_refresh_weekly:
            weekly_df = _run_weekly_auto_prediction_pipeline(
                simulations_per_race=max(1000, int(weekly_simulations)),
                seed=int(weekly_seed),
            )
            weekly_df = _store_weekly_predictions_preview(weekly_df)
            _sync_prediction_archive(
                _annotate_prediction_archive_budget_basis(
                    weekly_df,
                    basis_key=st.session_state.get("budget_basis_choice", "trend"),
                    basis_label=_format_budget_basis_label(st.session_state.get("budget_basis_choice", "trend")),
                    auto_mode=bool(st.session_state.get("budget_basis_auto_enabled", True)),
                )
            )
            report["weekly_df"] = weekly_df
            report["weekly_races_updated"] = int(len(weekly_df))
    elif auto_reflection_learning and not pending_reflection_rows.empty and not cooldown_ok:
        state["last_auto_reflection_result"] = "クールダウン中のため次回へ持ち越し"

    state["memory_synced_keys"] = _trim_text_list(list(memory_synced_keys))
    state["reflection_trained_keys"] = _trim_text_list(list(reflection_trained_keys))
    state["last_new_result_count"] = int(report["new_result_rows"])
    state["last_pending_reflection_count"] = int(len(pending_reflection_rows))
    state["last_pending_miss_count"] = int(len(missed_rows))
    _save_auto_improve_state_checkpoint(
        state,
        force=bool(
            int(report["memory_rows_added"]) > 0
            or bool(report["reflection_ran"])
            or int(report["weekly_races_updated"]) > 0
        ),
    )

    message_parts: List[str] = []
    if report["memory_rows_added"] > 0:
        message_parts.append(f"LLM学習メモ {int(report['memory_rows_added'])}件追記")
    if report["reflection_ran"]:
        message_parts.append("反省再学習を自動実行")
    if report["weekly_races_updated"] > 0:
        message_parts.append(f"今週AI予想 {int(report['weekly_races_updated'])}レース更新")
    report["message"] = " / ".join(message_parts)
    return report


def _market_snapshot_for_horse(entries_df: pd.DataFrame, horse_name: str) -> Dict[str, float | int | None]:
    snapshot: Dict[str, float | int | None] = {
        "popularity": None,
        "odds": None,
        "place_odds": None,
        "odds_shift": None,
    }
    if entries_df.empty:
        return snapshot
    horse_text = _to_text(horse_name)
    if not horse_text or "horse" not in entries_df.columns:
        return snapshot

    work = entries_df.copy()
    work["horse"] = work["horse"].map(_to_text)
    hit = work[work["horse"] == horse_text].copy()
    if hit.empty:
        return snapshot

    def _first_numeric(series: pd.Series, *, positive_only: bool) -> float | None:
        numeric = pd.to_numeric(series, errors="coerce")
        numeric = numeric[numeric.notna()]
        if positive_only:
            numeric = numeric[numeric > 0]
        if numeric.empty:
            return None
        return float(numeric.iloc[0])

    if "popularity" in hit.columns:
        pop_value = _first_numeric(hit["popularity"], positive_only=True)
        if pop_value is not None:
            snapshot["popularity"] = int(pop_value)
    if "odds" in hit.columns:
        snapshot["odds"] = _first_numeric(hit["odds"], positive_only=True)
    if "place_odds" in hit.columns:
        snapshot["place_odds"] = _first_numeric(hit["place_odds"], positive_only=True)
    if "odds_shift" in hit.columns:
        shift_value = _first_numeric(hit["odds_shift"], positive_only=False)
        if shift_value is not None:
            snapshot["odds_shift"] = float(shift_value)

    if snapshot["popularity"] is None and "odds" in work.columns:
        ranked = work.copy()
        ranked["odds_num"] = pd.to_numeric(ranked["odds"], errors="coerce")
        ranked = ranked[ranked["odds_num"].notna() & (ranked["odds_num"] > 0)]
        if not ranked.empty:
            ranked = ranked.sort_values(["odds_num", "horse"], ascending=[True, True]).reset_index(drop=True)
            ranked["pop_rank"] = ranked.index + 1
            ranked_hit = ranked[ranked["horse"] == horse_text]
            if not ranked_hit.empty:
                snapshot["popularity"] = int(ranked_hit.iloc[0]["pop_rank"])

    return snapshot


def _popularity_rank_for_horse(entries_df: pd.DataFrame, horse_name: str) -> tuple[int | None, float | None]:
    snapshot = _market_snapshot_for_horse(entries_df, horse_name)
    rank = snapshot.get("popularity")
    odds_val = snapshot.get("odds")
    return (int(rank) if isinstance(rank, (int, float)) and int(rank) > 0 else None, float(odds_val) if isinstance(odds_val, (int, float)) else None)


def _normalize_numeric_series(values: pd.Series) -> pd.Series:
    series = pd.to_numeric(values, errors="coerce")
    if series.dropna().empty:
        return pd.Series(0.0, index=series.index, dtype=float)
    low = float(series.min())
    high = float(series.max())
    if abs(high - low) < 1e-9:
        return pd.Series(0.5, index=series.index, dtype=float)
    return ((series - low) / (high - low)).fillna(0.0)


def _digit_root(value: Any) -> int:
    text = "".join(ch for ch in _to_text(value) if ch.isdigit())
    if not text:
        text = str(sum(ord(ch) for ch in _to_text(value)))
    total = sum(int(ch) for ch in text if ch.isdigit())
    if total <= 0:
        return 1
    while total >= 10:
        total = sum(int(ch) for ch in str(total))
    return max(1, total)


def _spiritual_number(value: Any) -> int:
    text = _to_text(value)
    if not text:
        return 1
    total = sum(ord(ch) for ch in text)
    return _digit_root(total)


def _format_popularity_label(value: Any) -> str:
    text = _to_text(value)
    if text.endswith("番人気"):
        return text
    try:
        if pd.isna(value):
            return "-"
    except Exception:
        pass
    try:
        num = int(float(value))
    except Exception:
        return "-"
    return f"{num}番人気" if num > 0 else "-"


def _format_condition_adjustment_count(value: Any) -> str:
    try:
        count = int(float(value))
    except Exception:
        return "-"
    return f"{count}本" if count > 0 else "0本"


def _format_condition_segment_label(value: Any) -> str:
    text = _to_text(value)
    if not text:
        return "-"
    if ":" not in text:
        return text
    prefix, raw_value = text.split(":", 1)
    prefix = _to_text(prefix)
    raw_value = _to_text(raw_value)
    if prefix == "venue":
        return f"開催 {raw_value}"
    if prefix == "race_grade":
        return f"格付 {raw_value or '未判定'}"
    if prefix == "weather":
        return f"天気 {raw_value}"
    if prefix == "track_condition":
        return f"馬場 {raw_value}"
    if prefix == "distance_bucket":
        return {
            "sprint": "距離帯 短距離",
            "mile": "距離帯 マイル",
            "middle": "距離帯 中距離",
            "long": "距離帯 長距離",
        }.get(raw_value, f"距離帯 {raw_value}")
    if prefix == "field_size_bucket":
        return {
            "small": "頭数帯 少頭数",
            "medium": "頭数帯 標準",
            "large": "頭数帯 多頭数",
        }.get(raw_value, f"頭数帯 {raw_value}")
    return text


def _extract_condition_adjustment_labels(result: PredictionResult) -> List[str]:
    if result.horse_predictions.empty or "条件補正" not in result.horse_predictions.columns:
        return []
    series = result.horse_predictions["条件補正"].map(_to_text)
    text = next((value for value in series.tolist() if value and value != "-"), "")
    if not text:
        return []
    labels: List[str] = []
    for part in [chunk.strip() for chunk in text.split("/")]:
        normalized = _to_text(part)
        if normalized and normalized not in labels:
            labels.append(normalized)
    return labels


def _format_condition_adjustment_summary(labels: List[str]) -> str:
    normalized = [_format_condition_segment_label(label) for label in labels if _to_text(label)]
    normalized = [label for label in normalized if label and label != "-"]
    return " / ".join(normalized) if normalized else "-"


def _style_pick_columns(table: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "馬番",
        "馬",
        "騎手",
        "アラート",
        "人気",
        "単勝オッズ",
        "直前オッズ差",
        "勝率",
        "複勝率",
        "スタイル指数",
        "理由",
    ]
    use_cols = [col for col in cols if col in table.columns]
    out = table[use_cols].copy()
    if "勝率" in out.columns:
        out["勝率"] = pd.to_numeric(out["勝率"], errors="coerce").map(lambda x: "-" if pd.isna(x) else f"{float(x):.2%}")
    if "複勝率" in out.columns:
        out["複勝率"] = pd.to_numeric(out["複勝率"], errors="coerce").map(lambda x: "-" if pd.isna(x) else f"{float(x):.2%}")
    if "単勝オッズ" in out.columns:
        out["単勝オッズ"] = pd.to_numeric(out["単勝オッズ"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{float(x):.1f}"
        )
    if "直前オッズ差" in out.columns:
        out["直前オッズ差"] = pd.to_numeric(out["直前オッズ差"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{float(x):+.1f}"
        )
    if "スタイル指数" in out.columns:
        out["スタイル指数"] = pd.to_numeric(out["スタイル指数"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{float(x):.2f}"
        )
    if "人気" in out.columns:
        out["人気"] = out["人気"].map(_format_popularity_label)
    return out


def _move_horse_to_bottom(table: pd.DataFrame, horse_name: Any) -> pd.DataFrame:
    if table.empty or "馬" not in table.columns:
        return table
    target = _to_text(horse_name)
    if not target:
        return table
    mask = table["馬"].map(_to_text) == target
    if not mask.any() or mask.all():
        return table
    return pd.concat([table.loc[~mask], table.loc[mask]], axis=0)


def _build_market_risk_table(result: PredictionResult, entries_df: pd.DataFrame) -> pd.DataFrame:
    if result.horse_predictions.empty or entries_df.empty:
        return pd.DataFrame()

    work = result.horse_predictions.copy()
    work["馬"] = work["馬"].map(_to_text)
    work["騎手"] = work["騎手"].map(_to_text) if "騎手" in work.columns else "-"
    win_num = pd.to_numeric(work.get("勝率", pd.Series(index=work.index, dtype=float)), errors="coerce").fillna(0.0)
    place_num = pd.to_numeric(work.get("複勝率", pd.Series(index=work.index, dtype=float)), errors="coerce").fillna(0.0)
    ev_num = pd.to_numeric(work.get("単勝期待値", pd.Series(index=work.index, dtype=float)), errors="coerce").fillna(0.0)

    pop_ranks: List[int | None] = []
    odds_vals: List[float | None] = []
    place_odds_vals: List[float | None] = []
    odds_shift_vals: List[float | None] = []
    for horse_name in work["馬"].tolist():
        snapshot = _market_snapshot_for_horse(entries_df, horse_name)
        pop_rank = snapshot.get("popularity")
        odds_val = snapshot.get("odds")
        place_odds_val = snapshot.get("place_odds")
        odds_shift_val = snapshot.get("odds_shift")
        pop_ranks.append(int(pop_rank) if isinstance(pop_rank, (int, float)) and int(pop_rank) > 0 else None)
        odds_vals.append(float(odds_val) if isinstance(odds_val, (int, float)) else None)
        place_odds_vals.append(float(place_odds_val) if isinstance(place_odds_val, (int, float)) else None)
        odds_shift_vals.append(float(odds_shift_val) if isinstance(odds_shift_val, (int, float)) else None)
    work["人気"] = pd.Series(pop_ranks, index=work.index, dtype="float")
    work["単勝オッズ"] = pd.Series(odds_vals, index=work.index, dtype="float")
    work["複勝オッズ"] = pd.Series(place_odds_vals, index=work.index, dtype="float")
    work["直前オッズ差"] = pd.Series(odds_shift_vals, index=work.index, dtype="float")
    model_rank_map = win_num.rank(method="min", ascending=False)
    zero_series = pd.Series(0.0, index=work.index, dtype=float)
    has_popularity = work["人気"].notna().any()
    has_odds = work["単勝オッズ"].notna().any()
    has_odds_shift = (
        work["直前オッズ差"].notna().any()
        and pd.to_numeric(work["直前オッズ差"], errors="coerce").fillna(0.0).abs().max() > 1e-9
    )

    if has_popularity:
        market_favorite = 1.0 - _normalize_numeric_series(work["人気"].fillna(work["人気"].max()))
        work = work[work["人気"].fillna(99) <= 5].copy()
    elif has_odds:
        market_favorite = 1.0 - _normalize_numeric_series(work["単勝オッズ"].fillna(work["単勝オッズ"].max()))
        work = work[work["単勝オッズ"].fillna(9999) <= work["単勝オッズ"].fillna(9999).nsmallest(min(5, len(work))).max()].copy()
    else:
        return pd.DataFrame()

    if work.empty:
        return pd.DataFrame()

    market_favorite = market_favorite.loc[work.index]
    model_weakness = 1.0 - _normalize_numeric_series(win_num.loc[work.index])
    place_weakness = 1.0 - _normalize_numeric_series(place_num.loc[work.index])
    ev_weakness = 1.0 - _normalize_numeric_series(ev_num.loc[work.index].clip(lower=-1.5, upper=1.5))
    work_popularity = pd.to_numeric(work["人気"], errors="coerce")
    work_model_rank = pd.to_numeric(model_rank_map.loc[work.index], errors="coerce")
    market_gap = (work_model_rank - work_popularity).where(
        work_popularity.notna() & (work_popularity > 0) & work_model_rank.notna(),
        0.0,
    ).clip(lower=0.0)
    gap_risk = _normalize_numeric_series(market_gap) if has_popularity else zero_series.loc[work.index]
    odds_shift_num = pd.to_numeric(work["直前オッズ差"], errors="coerce").fillna(0.0)
    drift_risk = _normalize_numeric_series(odds_shift_num.clip(lower=0.0)) if has_odds_shift else zero_series.loc[work.index]
    steam_support = _normalize_numeric_series((-odds_shift_num).clip(lower=0.0)) if has_odds_shift else zero_series.loc[work.index]
    work["スタイル指数"] = (
        market_favorite * 0.42
        + model_weakness * 0.18
        + place_weakness * 0.10
        + ev_weakness * 0.06
        + gap_risk * (0.16 if has_popularity else 0.0)
        + drift_risk * (0.14 if has_odds_shift else 0.0)
        - steam_support * (0.08 if has_odds_shift else 0.0)
    )
    reasons: List[str] = []
    for idx, row in work.iterrows():
        model_rank = int(float(model_rank_map.loc[idx])) if pd.notna(model_rank_map.loc[idx]) else 0
        market_rank = int(float(row.get("人気"))) if pd.notna(pd.to_numeric(row.get("人気"), errors="coerce")) else 0
        gap = model_rank - market_rank if market_rank > 0 and model_rank > 0 else None
        odds_text = "-" if pd.isna(row.get("単勝オッズ")) else f"{float(row.get('単勝オッズ')):.1f}"
        odds_shift_text = "-"
        if pd.notna(pd.to_numeric(row.get("直前オッズ差"), errors="coerce")):
            odds_shift_text = f"{float(row.get('直前オッズ差')):+.1f}"
        reasons.append(
            f"市場{_format_popularity_label(row.get('人気'))} / モデル{model_rank}番手"
            + (f" / 人気差+{gap}" if gap is not None and gap > 0 else "")
            + (f" / 直前オッズ差{odds_shift_text}" if has_odds_shift else "")
            + f" / 単勝{odds_text} / 勝率{float(win_num.loc[idx]):.1%} / 複勝率{float(place_num.loc[idx]):.1%} / 単勝期待値{float(ev_num.loc[idx]):+.2f}"
        )
    work["理由"] = pd.Series(reasons, index=work.index)
    return _style_pick_columns(work.sort_values(["スタイル指数", "勝率"], ascending=[False, True]).head(5))


def _build_odds_shift_alert_table(
    result: PredictionResult,
    entries_df: pd.DataFrame,
    *,
    threshold: float = 0.8,
) -> pd.DataFrame:
    if result.horse_predictions.empty or entries_df.empty:
        return pd.DataFrame()

    work = result.horse_predictions.copy()
    work["馬"] = work["馬"].map(_to_text)
    work["騎手"] = work["騎手"].map(_to_text) if "騎手" in work.columns else "-"
    pop_ranks: List[int | None] = []
    odds_vals: List[float | None] = []
    odds_shift_vals: List[float | None] = []
    for horse_name in work["馬"].tolist():
        snapshot = _market_snapshot_for_horse(entries_df, horse_name)
        pop_rank = snapshot.get("popularity")
        odds_val = snapshot.get("odds")
        odds_shift_val = snapshot.get("odds_shift")
        pop_ranks.append(int(pop_rank) if isinstance(pop_rank, (int, float)) and int(pop_rank) > 0 else None)
        odds_vals.append(float(odds_val) if isinstance(odds_val, (int, float)) else None)
        odds_shift_vals.append(float(odds_shift_val) if isinstance(odds_shift_val, (int, float)) else None)

    work["人気"] = pd.Series(pop_ranks, index=work.index, dtype="float")
    work["単勝オッズ"] = pd.Series(odds_vals, index=work.index, dtype="float")
    work["直前オッズ差"] = pd.Series(odds_shift_vals, index=work.index, dtype="float")
    work["スタイル指数"] = pd.to_numeric(work["直前オッズ差"], errors="coerce").abs()
    work = work[work["スタイル指数"].fillna(0.0) >= float(threshold)].copy()
    if work.empty:
        return pd.DataFrame()

    work["アラート"] = work["直前オッズ差"].map(
        lambda value: "人気急落" if pd.notna(pd.to_numeric(value, errors="coerce")) and float(value) > 0 else "人気急上昇"
    )

    def _build_odds_shift_reason(row: pd.Series) -> str:
        odds_value = pd.to_numeric(pd.Series([row.get("単勝オッズ")]), errors="coerce").iloc[0]
        shift_value = pd.to_numeric(pd.Series([row.get("直前オッズ差")]), errors="coerce").iloc[0]
        odds_text = "-" if pd.isna(odds_value) else f"{float(odds_value):.1f}"
        shift_text = "-" if pd.isna(shift_value) else f"{float(shift_value):+.1f}"
        return f"{_format_popularity_label(row.get('人気'))} / 単勝{odds_text} / 直前オッズ差{shift_text}"

    work["理由"] = work.apply(
        _build_odds_shift_reason,
        axis=1,
    )
    return _style_pick_columns(work.sort_values(["スタイル指数", "勝率"], ascending=[False, False]).head(5))


def _render_odds_shift_alert_cards(
    table: pd.DataFrame,
    *,
    gate_lookup: Dict[str, str] | None = None,
    limit: int = 3,
) -> None:
    if table.empty:
        return
    work = _decorate_frame_gate_columns(table.head(max(1, int(limit))).copy(), gate_lookup or {}, ["馬"])
    section_html: List[str] = []
    for alert_label, tone in [("人気急落", "#a33122"), ("人気急上昇", "#8f3a0a")]:
        subset = work[work["アラート"].map(_to_text) == alert_label].copy() if "アラート" in work.columns else pd.DataFrame()
        if subset.empty:
            continue
        cards: List[str] = []
        for _, row in subset.iterrows():
            cards.append(
                """
<div class="danger-card">
  <div class="danger-chip">{chip}</div>
  <div class="danger-title">{horse}</div>
  <div class="danger-line"><strong>状態:</strong> {alert}</div>
  <div class="danger-line"><strong>人気/単勝:</strong> {pop} / {odds}</div>
  <div class="danger-line"><strong>直前オッズ差:</strong> <span style="color:{tone};font-weight:900;">{shift}</span></div>
</div>
""".format(
                    chip=html_escape(alert_label),
                    horse=html_escape(_render_name_text(row.get("馬", "-"))),
                    alert=html_escape(alert_label),
                    pop=html_escape(_to_text(row.get("人気", "-"))),
                    odds=html_escape(_to_text(row.get("単勝オッズ", "-"))),
                    tone=html_escape(tone),
                    shift=html_escape(_to_text(row.get("直前オッズ差", "-"))),
                )
            )
        section_html.append(
            """
<div style="margin-bottom:12px;">
  <div style="margin:0 0 6px 2px;font-size:12px;font-weight:900;color:{tone};">{label}</div>
  <div class="danger-grid">{cards}</div>
</div>
""".format(tone=html_escape(tone), label=html_escape(alert_label), cards="".join(cards))
        )
    if section_html:
        st.markdown("".join(section_html), unsafe_allow_html=True)


def _build_prediction_style_tables(
    result: PredictionResult,
    entries_df: pd.DataFrame,
    *,
    race_id: str = "",
    race_date: str = "",
) -> Dict[str, pd.DataFrame]:
    if result.horse_predictions.empty:
        return {}

    work = result.horse_predictions.copy()
    work["馬"] = work["馬"].map(_to_text)
    work["騎手"] = work["騎手"].map(_to_text) if "騎手" in work.columns else "-"
    odds_num = pd.to_numeric(work.get("単勝オッズ", pd.Series(index=work.index, dtype=float)), errors="coerce")
    win_num = pd.to_numeric(work.get("勝率", pd.Series(index=work.index, dtype=float)), errors="coerce").fillna(0.0)
    place_num = pd.to_numeric(work.get("複勝率", pd.Series(index=work.index, dtype=float)), errors="coerce").fillna(0.0)
    ev_num = pd.to_numeric(work.get("単勝期待値", pd.Series(index=work.index, dtype=float)), errors="coerce").fillna(0.0)

    pop_ranks: List[int | None] = []
    fallback_odds: List[float | None] = []
    for horse_name in work["馬"].tolist():
        pop_rank, entry_odds = _popularity_rank_for_horse(entries_df, horse_name)
        pop_ranks.append(pop_rank)
        fallback_odds.append(entry_odds)
    pop_series = pd.Series(pop_ranks, index=work.index, dtype="float")
    fallback_odds_series = pd.Series(fallback_odds, index=work.index, dtype="float")
    odds_num = odds_num.fillna(fallback_odds_series)

    condition_mix = pd.concat(
        [
            pd.to_numeric(work.get("form_factor", pd.Series(index=work.index, dtype=float)), errors="coerce"),
            pd.to_numeric(work.get("condition_factor", pd.Series(index=work.index, dtype=float)), errors="coerce"),
            pd.to_numeric(work.get("paddock_factor", pd.Series(index=work.index, dtype=float)), errors="coerce"),
        ],
        axis=1,
    ).mean(axis=1).fillna(0.0)

    work["人気"] = pop_series
    work["単勝オッズ"] = odds_num

    data_table = work.sort_values(["勝率", "複勝率"], ascending=False).copy()
    data_table["スタイル指数"] = (
        _normalize_numeric_series(win_num) * 0.65
        + _normalize_numeric_series(place_num) * 0.20
        + _normalize_numeric_series(condition_mix) * 0.15
    )
    data_reasons: List[str] = []
    for idx, row in data_table.iterrows():
        data_reasons.append(
            f"勝率{float(win_num.loc[idx]):.1%} / 複勝率{float(place_num.loc[idx]):.1%} / 調子{float(condition_mix.loc[idx]):.2f}"
        )
    data_table["理由"] = pd.Series(data_reasons, index=data_table.index)
    favorite_horse = _to_text(data_table.iloc[0].get("馬", "")) if not data_table.empty else ""

    longshot_table = work.copy()
    anti_favorite = 1.0 - _normalize_numeric_series(win_num)
    market_pop = pop_series.fillna(pop_series.median() if pop_series.notna().any() else 0.0)
    market_odds = odds_num.fillna(odds_num.median() if odds_num.notna().any() else 0.0)
    market_data_ready = bool(pop_series.notna().any() or odds_num.notna().any())
    if market_data_ready:
        longshot_table["スタイル指数"] = (
            _normalize_numeric_series(market_pop) * 0.28
            + _normalize_numeric_series(market_odds) * 0.24
            + anti_favorite * 0.18
            + _normalize_numeric_series(place_num) * 0.12
            + _normalize_numeric_series(ev_num.clip(lower=0.0)) * 0.08
            + _normalize_numeric_series(condition_mix) * 0.10
        )
    else:
        longshot_table["スタイル指数"] = (
            anti_favorite * 0.44
            + _normalize_numeric_series(place_num) * 0.22
            + _normalize_numeric_series(condition_mix) * 0.18
            + _normalize_numeric_series(ev_num.clip(lower=0.0)) * 0.08
            + _normalize_numeric_series(win_num) * 0.08
        )
    longshot_reasons: List[str] = []
    for idx, row in longshot_table.iterrows():
        odds_label = "-" if pd.isna(row.get("単勝オッズ")) else f"{float(row.get('単勝オッズ')):.1f}"
        prefix = "人気薄妙味" if market_data_ready else "人気情報不足のため抑えめ勝率型"
        longshot_reasons.append(
            f"{prefix} / {_format_popularity_label(row.get('人気'))} / 単勝{odds_label} / 勝率{float(win_num.loc[idx]):.1%}"
        )
    longshot_table["理由"] = pd.Series(longshot_reasons, index=longshot_table.index)
    longshot_table = longshot_table.sort_values(["スタイル指数", "複勝率", "勝率"], ascending=False)
    longshot_table = _move_horse_to_bottom(longshot_table, favorite_horse)

    spiritual_table = work.copy()
    lucky_number = _digit_root(f"{race_id}{race_date}")
    gate_map = pd.Series(dtype=float)
    if not entries_df.empty and "horse" in entries_df.columns and "gate" in entries_df.columns:
        gate_map = pd.to_numeric(entries_df.drop_duplicates("horse").set_index("horse")["gate"], errors="coerce")
    horse_wave = spiritual_table["馬"].map(_spiritual_number)
    jockey_wave = spiritual_table["騎手"].map(_spiritual_number)
    gate_wave = spiritual_table["馬"].map(lambda horse: _digit_root(gate_map.get(horse, "")))
    spiritual_score = []
    spiritual_reason = []
    for idx, row in spiritual_table.iterrows():
        h_wave = int(horse_wave.loc[idx])
        j_wave = int(jockey_wave.loc[idx])
        g_wave = int(gate_wave.loc[idx])
        matches = sum(1 for value in (h_wave, j_wave, g_wave) if value == lucky_number)
        resonance = 0.35 if h_wave == j_wave else 0.0
        soft_data = float(_normalize_numeric_series(win_num).loc[idx]) * 0.25
        score = matches * 0.9 + resonance + soft_data + (0.15 if g_wave == h_wave else 0.0)
        spiritual_score.append(score)
        spiritual_reason.append(
            f"ラッキー数{lucky_number} / 馬名波動{h_wave} / 騎手波動{j_wave} / ゲート波動{g_wave}"
        )
    spiritual_table["スタイル指数"] = pd.Series(spiritual_score, index=spiritual_table.index)
    spiritual_table["理由"] = pd.Series(spiritual_reason, index=spiritual_table.index)
    spiritual_table = spiritual_table.sort_values(["スタイル指数", "勝率"], ascending=False)
    risk_table = _build_market_risk_table(result, entries_df)

    return {
        "データ本命": _style_pick_columns(data_table.head(5)),
        "大穴": _style_pick_columns(longshot_table.head(5)),
        "危険人気": risk_table,
        "スピリチュアル": _style_pick_columns(spiritual_table.head(5)),
    }


def _build_weekly_auto_predictions(
    history_df: pd.DataFrame,
    entries_df: pd.DataFrame,
    *,
    simulations_per_race: int,
    seed: int,
    feature_weights: Dict[str, float] | None,
    condition_adjustments: Dict[str, Any] | None,
) -> pd.DataFrame:
    if entries_df.empty:
        return pd.DataFrame()
    race_groups: List[tuple[str, pd.DataFrame]]
    if "race_id" in entries_df.columns:
        race_groups = [(str(rid), g.copy()) for rid, g in entries_df.groupby("race_id", sort=True)]
    else:
        race_groups = [("RACE_AUTO", entries_df.copy())]

    rows: List[Dict[str, Any]] = []
    feature_frames: List[pd.DataFrame] = []
    for i, (race_id, race_entries) in enumerate(race_groups):
        if len(race_entries) < 2:
            continue
        weather_value = str(race_entries["weather"].dropna().iloc[0]) if "weather" in race_entries.columns else "晴"
        track_value = str(race_entries["track_condition"].dropna().iloc[0]) if "track_condition" in race_entries.columns else "良"
        distance_series = pd.to_numeric(race_entries.get("distance", pd.Series([1600.0])), errors="coerce").dropna()
        distance_value = float(distance_series.iloc[0]) if len(distance_series) > 0 else 1600.0
        venue_value = str(race_entries["venue"].dropna().iloc[0]) if ("venue" in race_entries.columns and len(race_entries["venue"].dropna()) > 0) else "-"
        race_name_value = (
            _to_text(race_entries["race_name"].dropna().iloc[0])
            if ("race_name" in race_entries.columns and len(race_entries["race_name"].dropna()) > 0)
            else "-"
        )
        race_grade_value = _infer_race_grade(race_name_value)
        race_date_value = (
            _to_text(race_entries["race_date"].dropna().iloc[0])
            if ("race_date" in race_entries.columns and len(race_entries["race_date"].dropna()) > 0)
            else (
                _to_text(race_entries["fetched_date"].dropna().iloc[0])
                if ("fetched_date" in race_entries.columns and len(race_entries["fetched_date"].dropna()) > 0)
                else ""
            )
        )

        result = predict_race(
            history_df=history_df,
            entries_df=race_entries,
            weather=weather_value,
            track_condition=track_value,
            distance=distance_value,
            simulations=max(500, int(simulations_per_race)),
            seed=int(seed) + i,
            budget=0.0,
            bet_units=100,
            feature_weights=feature_weights,
            condition_adjustments=condition_adjustments,
            venue=venue_value,
            race_grade=race_grade_value,
        )
        if result.horse_predictions.empty:
            continue
        condition_labels = _extract_condition_adjustment_labels(result)
        feature_frames.append(
            _build_prediction_feature_rows(
                result,
                race_id=race_id,
                race_date=race_date_value,
                race_name=race_name_value,
                race_grade=race_grade_value,
                venue=venue_value,
                weather=weather_value,
                track_condition=track_value,
                distance=distance_value,
                field_size=len(race_entries),
            )
        )
        style_tables = _build_prediction_style_tables(
            result,
            race_entries,
            race_id=str(race_id),
            race_date=race_date_value,
        )
        odds_shift_alert_table = _build_odds_shift_alert_table(result, race_entries)
        top = result.horse_predictions.iloc[0]
        top_horse = str(top.get("馬", "-"))
        pop_rank, top_odds = _popularity_rank_for_horse(race_entries, top_horse)
        win_pick = result.bet_recommendations.get("単勝", pd.DataFrame())
        place_pick = result.bet_recommendations.get("複勝", pd.DataFrame())
        quinella_pick = result.bet_recommendations.get("馬連", pd.DataFrame())
        wide_pick = result.bet_recommendations.get("ワイド", pd.DataFrame())
        exacta_pick = result.bet_recommendations.get("馬単", pd.DataFrame())
        trio_pick = result.bet_recommendations.get("三連複", pd.DataFrame())
        trifecta_pick = result.bet_recommendations.get("三連単", pd.DataFrame())
        longshot_pick = style_tables.get("大穴", pd.DataFrame())
        risk_pick = style_tables.get("危険人気", pd.DataFrame())
        spiritual_pick = style_tables.get("スピリチュアル", pd.DataFrame())
        rows.append(
            {
                "race_id": race_id,
                "race_date": race_date_value,
                "race_name": race_name_value,
                "race_grade": race_grade_value,
                "venue": venue_value,
                "weather": weather_value,
                "track_condition": track_value,
                "distance": distance_value,
                "field_size": int(len(race_entries)),
                "top_horse": top_horse,
                "top_jockey": str(top.get("騎手", "-")),
                "top_pop_rank": pop_rank,
                "top_horse_odds": top_odds,
                "dark_horse": str(longshot_pick.iloc[0]["馬"]) if (not longshot_pick.empty and "馬" in longshot_pick.columns) else "-",
                "dark_horse_pop": str(longshot_pick.iloc[0]["人気"]) if (not longshot_pick.empty and "人気" in longshot_pick.columns) else "-",
                "danger_favorite": str(risk_pick.iloc[0]["馬"]) if (not risk_pick.empty and "馬" in risk_pick.columns) else "-",
                "danger_favorite_pop": str(risk_pick.iloc[0]["人気"]) if (not risk_pick.empty and "人気" in risk_pick.columns) else "-",
                "spiritual_horse": str(spiritual_pick.iloc[0]["馬"]) if (not spiritual_pick.empty and "馬" in spiritual_pick.columns) else "-",
                "condition_adjustment_count": int(len(condition_labels)),
                "condition_adjustments": _format_condition_adjustment_summary(condition_labels),
                "odds_shift_alert": (
                    f"{_to_text(odds_shift_alert_table.iloc[0].get('馬', '-'))} / "
                    f"{_to_text(odds_shift_alert_table.iloc[0].get('アラート', '-'))} / "
                    f"{_to_text(odds_shift_alert_table.iloc[0].get('直前オッズ差', '-'))}"
                    if not odds_shift_alert_table.empty
                    else "-"
                ),
                "win_prob": float(top.get("勝率", 0.0)),
                "place_prob": float(top.get("複勝率", 0.0)),
                "single_pick": str(win_pick.iloc[0]["馬"]) if (not win_pick.empty and "馬" in win_pick.columns) else "-",
                "place_pick": str(place_pick.iloc[0]["馬"]) if (not place_pick.empty and "馬" in place_pick.columns) else "-",
                "quinella_pick": str(quinella_pick.iloc[0]["組み合わせ"]) if (not quinella_pick.empty and "組み合わせ" in quinella_pick.columns) else "-",
                "wide_pick": str(wide_pick.iloc[0]["組み合わせ"]) if (not wide_pick.empty and "組み合わせ" in wide_pick.columns) else "-",
                "exacta_pick": str(exacta_pick.iloc[0]["組み合わせ"]) if (not exacta_pick.empty and "組み合わせ" in exacta_pick.columns) else "-",
                "trio_pick": str(trio_pick.iloc[0]["組み合わせ"]) if (not trio_pick.empty and "組み合わせ" in trio_pick.columns) else "-",
                "trifecta_pick": str(trifecta_pick.iloc[0]["組み合わせ"]) if (not trifecta_pick.empty and "組み合わせ" in trifecta_pick.columns) else "-",
            }
        )
    if not rows:
        return pd.DataFrame()
    if feature_frames:
        _sync_prediction_feature_archive(pd.concat(feature_frames, ignore_index=True))
    out = pd.DataFrame(rows)
    out["race_id"] = out["race_id"].map(lambda x: str(x).strip())
    return out.sort_values("race_id").reset_index(drop=True)


def _run_weekly_auto_prediction_pipeline(
    *,
    simulations_per_race: int,
    seed: int,
) -> pd.DataFrame:
    history_path = Path(st.session_state.get("auto_history_path", str(AUTO_HISTORY_PATH)))
    entries_path = Path(st.session_state.get("auto_entries_path", str(AUTO_ENTRIES_PATH)))
    history_df = _read_csv_if_exists(history_path)
    entries_df = _read_csv_if_exists(entries_path)
    if history_df is None or history_df.empty:
        raise ValueError(f"履歴データがありません: {history_path}")
    if entries_df is None or entries_df.empty:
        raise ValueError(f"今週出走データがありません: {entries_path}")
    model_payload = _load_auto_model_payload()
    feature_weights = _extract_feature_weights_from_payload(model_payload)
    condition_adjustments = _extract_condition_adjustments_from_payload(model_payload)
    summary = _build_weekly_auto_predictions(
        history_df,
        entries_df,
        simulations_per_race=int(simulations_per_race),
        seed=int(seed),
        feature_weights=feature_weights,
        condition_adjustments=condition_adjustments,
    )
    if not summary.empty:
        save_weekly_predictions(summary, WEEKLY_PREDICTIONS_PATH)
        st.session_state["weekly_predictions_path"] = str(WEEKLY_PREDICTIONS_PATH)
    return summary


def _render_schema_help() -> None:
    with st.expander("CSVフォーマット（履歴/出走馬）"):
        st.markdown(
            """
- 履歴CSV 必須カラム: `race_id, horse, jockey, trainer, weather, track_condition, distance, finish`
- 履歴CSV 任意カラム: `odds, place_odds, gate, form_score, condition_score, weight_diff, paddock_score, odds_shift`
- 出走馬CSV 必須カラム: `horse, jockey, trainer`
- 出走馬CSV 任意カラム: `odds, place_odds, gate, form_score, condition_score, weight_diff, paddock_score, odds_shift, weather, track_condition, distance`
- `form_score` と `condition_score` は 0-100 を想定（高いほど好調）
- `paddock_score` は 0-100、`weight_diff` は当日馬体重増減(kg)、`odds_shift` は直前オッズ差（マイナスで人気上昇）
"""
        )


_inject_style()

st.title("競馬予想アプリ MVP")
st.caption("過去成績 + 天気 + 馬場状態 + 調子スコア から、買い目を確率ベースで提案します")
_render_ui_notice()
_render_result_sync_summary()

if "easy_operation_mode" not in st.session_state:
    st.session_state["easy_operation_mode"] = True
if "llm_hands_free_mode" not in st.session_state:
    st.session_state["llm_hands_free_mode"] = True
easy_operation_mode = bool(st.session_state.get("easy_operation_mode", True))
llm_hands_free_mode = bool(st.session_state.get("llm_hands_free_mode", True))

run_predict_mode = _to_text(st.session_state.pop("run_predict_mode", ""))
run_predict_from_auto = bool(run_predict_mode in {"selected_race", "auto_batch"})
scroll_to_detail_after_rerun = bool(st.session_state.pop("scroll_to_detail_after_rerun", False))
pending_selected_race_context = st.session_state.pop("pending_selected_race_context", None)
if isinstance(pending_selected_race_context, dict) and pending_selected_race_context:
    _apply_selected_race_context_to_inputs(pending_selected_race_context, force=True)

with st.sidebar:
    st.subheader("基本設定")
    sidebar_budget_basis_label = _format_budget_basis_label(st.session_state.get("budget_basis_choice", "trend"))
    data_mode = st.radio(
        "読み込み方法",
        options=("サンプル", "CSVアップロード", "自動取得データ"),
        index=2,
        key="data_mode_selector",
    )

    auto_ready = has_keibascraper()
    if auto_ready:
        st.caption("`keibascraper` 導入済み: 自動取得が利用できます。")
    else:
        st.warning("自動取得には `pip install keibascraper` が必要です。")

    public_status = _read_json_if_exists(PUBLIC_TUNNEL_STATUS_PATH)
    public_health = _read_json_if_exists(PUBLIC_HEALTH_STATUS_PATH)
    public_watch = _read_json_if_exists(PUBLIC_WATCH_STATE_PATH)
    local_runtime_status = _read_json_if_exists(LOCAL_RUNTIME_STATUS_PATH)
    auto_improve_status = _load_auto_improve_state()
    auto_cycle_status = _read_json_if_exists(AUTO_CYCLE_STATUS_PATH)
    auto_cycle_config = _read_json_if_exists(AUTO_CYCLE_CONFIG_PATH)
    auto_agent_status = _read_json_if_exists(AUTO_AGENT_STATUS_PATH)
    auto_agent_report = _read_json_if_exists(AUTO_AGENT_REPORT_PATH)
    prediction_harness_status = _load_or_refresh_prediction_harness_status()
    auto_agent_basis_hint = _extract_auto_agent_basis_hint(auto_agent_status)
    llm_hit_weekly_summary: Dict[str, Any] = {}
    llm_hands_free_history_rows = _read_jsonl_if_exists(LLM_HANDS_FREE_HISTORY_PATH, limit=30)
    with st.expander("ローカル確認", expanded=not easy_operation_mode):
        render_local_confirmation_header(
            local_runtime_status,
            app_path=APP_DIR / "app.py",
            weekly_predictions_path=WEEKLY_PREDICTIONS_PATH,
            budget_basis_label=sidebar_budget_basis_label,
            format_toggle_label=_format_toggle_label,
            format_file_timestamp=_format_file_timestamp,
            format_file_age=_format_file_age,
        )
        render_sidebar_budget_basis_cards(st.session_state.get("budget_basis_choice", "trend"))
        current_sidebar_basis = _to_text(st.session_state.get("budget_basis_choice", "trend"))
        sidebar_feedback_df = _load_prediction_feedback_snapshot()
        sidebar_feedback_trend_summary = _build_feedback_trend_summary(sidebar_feedback_df, lookback_days=7)
        sidebar_basis_performance_df = build_budget_basis_performance_table(sidebar_feedback_df)
        persisted_budget_basis_auto_enabled = bool(auto_improve_status.get("budget_basis_auto_enabled", True))
        if "budget_basis_auto_enabled" not in st.session_state:
            st.session_state["budget_basis_auto_enabled"] = persisted_budget_basis_auto_enabled
        sidebar_auto_basis_enabled = st.toggle(
            "標準配分を半自動で切替",
            key="budget_basis_auto_enabled",
            help="今週の反省傾向を見て、`今週傾向 / 類似個体 / ベース` を自動で切り替えます。手動で選ぶと自動切替は一旦OFFになります。",
        )
        sidebar_basis_decision = _build_budget_basis_decision_snapshot(
            sidebar_feedback_trend_summary,
            ["trend", "analog", "base"],
            performance_df=sidebar_basis_performance_df,
            agent_hint=auto_agent_basis_hint,
            llm_hit_summary=llm_hit_weekly_summary,
        )
        sidebar_auto_basis_key = _to_text(sidebar_basis_decision.get("final_key", "base")) or "base"
        sidebar_auto_basis_reason = _to_text(sidebar_basis_decision.get("final_reason", "")) or "現在の標準配分を使います。"
        _maybe_notify_budget_basis_decision_change(sidebar_basis_decision, auto_enabled=sidebar_auto_basis_enabled)
        if sidebar_auto_basis_enabled != persisted_budget_basis_auto_enabled:
            _persist_budget_basis_preference(
                auto_enabled=sidebar_auto_basis_enabled,
                auto_choice=(sidebar_auto_basis_key if sidebar_auto_basis_enabled else None),
            )
        auto_basis_label = _format_budget_basis_label(sidebar_auto_basis_key)
        if sidebar_auto_basis_enabled:
            current_sidebar_basis = sidebar_auto_basis_key
            st.session_state["budget_basis_choice"] = current_sidebar_basis
            st.caption(f"半自動の推奨: {auto_basis_label}")
            st.caption(sidebar_auto_basis_reason)
            _render_budget_basis_decision_cards(sidebar_basis_decision)
        else:
            st.caption("半自動切替はOFFです。下のボタンで標準配分を手動で選べます。")
        sidebar_budget_basis_label = _format_budget_basis_label(current_sidebar_basis)
        st.caption(f"現在採用中: {_format_budget_basis_label(current_sidebar_basis)}")
        selected_sidebar_basis = render_sidebar_budget_basis_selector()
        if selected_sidebar_basis:
            st.session_state["budget_basis_auto_enabled"] = False
            _persist_budget_basis_preference(auto_enabled=False, manual_choice=selected_sidebar_basis)
            if current_sidebar_basis == selected_sidebar_basis:
                notice_payload = _build_budget_basis_notice_payload(selected_sidebar_basis, sidebar_feedback_trend_summary)
                notice_message = {
                    "trend": "今週傾向反映の標準配分を表示します",
                    "analog": "類似個体補正の標準配分を表示します",
                    "base": "ベース配分の標準配分を表示します",
                }.get(selected_sidebar_basis, "標準配分を表示します")
                _set_ui_notice(
                    notice_message,
                    title=notice_payload["title"],
                    chip=notice_payload["chip"],
                    detail=notice_payload["detail"],
                    fit_case=notice_payload.get("fit_case", ""),
                    unfit_case=notice_payload.get("unfit_case", ""),
                    level=notice_payload["level"],
                )
            st.session_state["budget_basis_choice"] = selected_sidebar_basis
            _request_open_budget_tab()
            st.rerun()
        render_local_confirmation_footer(
            local_runtime_status,
            parquet_cache_status(AUTO_HISTORY_PATH),
            auto_entries_path=AUTO_ENTRIES_PATH,
            format_file_timestamp=_format_file_timestamp,
            format_file_age=_format_file_age,
            format_storage_size=_format_storage_size,
            format_timestamp_text=_format_timestamp_text,
            format_age_text=_format_age_text,
        )
    st.divider()
    render_public_access_panel(
        public_status,
        public_health,
        public_watch,
        format_timestamp_text=_format_timestamp_text,
        format_health_label=_format_health_label,
        format_health_message_label=_format_health_message_label,
        format_watch_status_label=_format_watch_status_label,
        format_watch_event_label=_format_watch_event_label,
        format_restart_result_label=_format_restart_result_label,
        format_notify_result_label=_format_notify_result_label,
    )

    st.divider()
    local_llm_settings = render_local_llm_panel(
        easy_operation_mode=easy_operation_mode,
        default_base_url=LOCAL_LLM_BASE_URL_DEFAULT,
        default_model=LOCAL_LLM_MODEL_DEFAULT,
        default_style=LOCAL_LLM_STYLE_DEFAULT,
        list_models=_ollama_list_models,
    )
    local_llm_mode = local_llm_settings.mode
    local_llm_style = local_llm_settings.style
    local_llm_reasoning_mode = local_llm_settings.reasoning_mode
    local_llm_base_url = local_llm_settings.base_url
    local_llm_model = local_llm_settings.model
    local_llm_timeout_sec = local_llm_settings.timeout_sec
    render_llm_alignment_shortcuts(
        easy_operation_mode=easy_operation_mode,
        set_ui_notice=_set_ui_notice,
    )

    st.divider()
    operation_mode_settings = render_update_operation_header()
    easy_operation_mode = operation_mode_settings.easy_operation_mode
    llm_hands_free_mode = operation_mode_settings.llm_hands_free_mode
    _render_auto_cycle_visible_progress(auto_cycle_status, auto_cycle_config)
    _render_in_page_operation_status()
    _render_free_prediction_harness_status(prediction_harness_status)
    render_llm_hands_free_history_panel(
        llm_hands_free_history_rows,
        llm_hands_free_mode=llm_hands_free_mode,
        build_history_table=_build_llm_hands_free_history_table,
        render_latest_cards=_render_llm_hands_free_latest_cards,
        with_one_based_index=_with_one_based_index,
        format_timestamp_text=_format_timestamp_text,
    )
    llm_hands_free_progress_slot = st.empty()
    llm_hands_free_progress_detail_slot = st.empty()

    def _update_llm_hands_free_visible_progress(
        progress_value: float,
        message: str,
        *,
        status: str = "running",
    ) -> None:
        if not bool(llm_hands_free_mode):
            return
        active_payload = st.session_state.get("llm_hands_free_active_action")
        if not isinstance(active_payload, dict):
            return
        action_label = _to_text(active_payload.get("action_label", "")) or "自動実行"
        reason_text = _to_text(active_payload.get("reason", ""))
        queued_age = _format_age_text(active_payload.get("queued_at", ""))
        status_label = {
            "queued": "実行待ち",
            "running": "実行中",
            "completed": "完了",
            "failed": "失敗",
        }.get(_to_text(status), _to_text(status) or "実行中")
        pct = max(0, min(100, int(round(float(progress_value) * 100))))
        if status == "queued":
            pct = max(1, pct)
        label_text = f"LLMおまかせ: {action_label} / {message} ({pct}%)"
        llm_hands_free_progress_slot.progress(pct, text=label_text)
        detail_parts = [f"状態: {status_label}"]
        if queued_age != "-":
            detail_parts.append(f"開始: {queued_age}")
        if reason_text:
            detail_parts.append(f"理由: {reason_text}")
        llm_hands_free_progress_detail_slot.caption(" / ".join(detail_parts))

    if llm_hands_free_mode and isinstance(st.session_state.get("llm_hands_free_active_action"), dict):
        _update_llm_hands_free_visible_progress(0.01, "実行待ち", status="queued")
    st.caption(
        f"現在の標準配分: {sidebar_budget_basis_label}"
        + ("（半自動）" if bool(st.session_state.get("budget_basis_auto_enabled", True)) else "（手動）")
    )
    update_profile_settings = render_update_profile_settings(easy_operation_mode=easy_operation_mode)
    update_profile = update_profile_settings.profile
    auto_tune = update_profile_settings.auto_tune
    auto_forecast_weather = update_profile_settings.auto_forecast_weather
    auto_weekly_ai = update_profile_settings.auto_weekly_ai
    auto_run_on_open = update_profile_settings.auto_run_on_open
    auto_improve_settings = render_auto_improve_panel(
        auto_improve_status,
        easy_operation_mode=easy_operation_mode,
        format_timestamp_text=_format_timestamp_text,
    )
    auto_self_improve = auto_improve_settings.enabled
    auto_sync_feedback_memory = auto_improve_settings.sync_feedback_memory
    auto_reflection_learning = auto_improve_settings.reflection_learning
    auto_refresh_weekly_after_reflection = auto_improve_settings.refresh_weekly_after_reflection
    auto_reflection_min_new_results = auto_improve_settings.min_new_results
    auto_reflection_min_missed_results = auto_improve_settings.min_missed_results
    auto_reflection_cooldown_minutes = auto_improve_settings.cooldown_minutes
    render_auto_cycle_panel(
        auto_cycle_status,
        auto_cycle_config,
        easy_operation_mode=easy_operation_mode,
        format_timestamp_text=_format_timestamp_text,
        format_auto_cycle_mode_label=_format_auto_cycle_mode_label,
        format_auto_cycle_mode_detail=_format_auto_cycle_mode_detail,
        format_next_run_text=_format_next_run_text,
        format_next_run_remaining_text=_format_next_run_remaining_text,
    )
    render_auto_agent_panel(
        auto_agent_status,
        auto_agent_report,
        auto_agent_basis_hint,
        easy_operation_mode=easy_operation_mode,
        format_timestamp_text=_format_timestamp_text,
    )

    auto_detail_settings = render_auto_update_detail_settings(easy_operation_mode=easy_operation_mode)
    auto_months_back = auto_detail_settings.months_back
    auto_week_days = auto_detail_settings.week_days
    auto_backfill_days = auto_detail_settings.backfill_days
    auto_fallback_days = auto_detail_settings.fallback_days
    auto_entries_cache_hours = auto_detail_settings.entries_cache_hours
    auto_weather_cache_hours = auto_detail_settings.weather_cache_hours
    weekly_ai_simulations = auto_detail_settings.weekly_ai_simulations
    auto_result_batch_cap = auto_detail_settings.result_batch_cap

    def _execute_auto_update(
        profile_name: str,
        *,
        force_tuning: bool,
        update_history: bool = True,
        update_entries: bool = True,
        history_race_id_allowlist: List[str] | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> AutoUpdateReport:
        params = resolve_update_profile(
            profile_name,
            force_tuning=force_tuning,
            months_back=int(auto_months_back),
            weekly_days_ahead=int(auto_week_days),
            fallback_max_days=int(auto_fallback_days),
            history_backfill_days=int(auto_backfill_days),
            entries_cache_hours=int(auto_entries_cache_hours),
            auto_tune=bool(auto_tune),
        )
        return _run_auto_update_pipeline(
            months_back=int(params["months_back"]),
            weekly_days_ahead=int(params["weekly_days_ahead"]),
            incremental=bool(params["incremental"]),
            full_refresh=bool(params["full_refresh"]),
            history_backfill_days=int(params["history_backfill_days"]),
            append_only=bool(params["append_only"]),
            entries_cache_hours=int(params["entries_cache_hours"]),
            auto_forecast_weather=bool(auto_forecast_weather),
            weather_cache_hours=int(auto_weather_cache_hours),
            fallback_max_days=int(params["fallback_max_days"]),
            run_tuning=bool(params["run_tuning"]),
            update_history=bool(update_history),
            update_entries=bool(update_entries),
            history_race_id_allowlist=history_race_id_allowlist,
            progress_callback=progress_callback,
        )

    def _run_auto_update_with_gauge(
        gauge_label: str,
        *,
        profile_name: str,
        force_tuning: bool,
        update_history: bool = True,
        update_entries: bool = True,
        history_race_id_allowlist: List[str] | None = None,
    ) -> AutoUpdateReport:
        gauge_placeholder = st.empty()
        detail_placeholder = st.empty()
        progress_bar = gauge_placeholder.progress(0, text=f"{gauge_label}: 準備中 (0%)")
        _set_in_page_operation_status(label=gauge_label, progress_pct=0, phase="準備中", state="running")
        _update_llm_hands_free_visible_progress(0.01, "準備中", status="running")

        def _on_progress(progress_value: float, message: str) -> None:
            pct = max(0, min(100, int(round(float(progress_value) * 100))))
            progress_bar.progress(pct, text=f"{gauge_label}: {message} ({pct}%)")
            detail_placeholder.caption(f"更新進捗: {message}")
            _set_in_page_operation_status(label=gauge_label, progress_pct=pct, phase=message, state="running")
            _update_llm_hands_free_visible_progress(progress_value, message, status="running")

        try:
            report = _execute_auto_update(
                profile_name,
                force_tuning=force_tuning,
                update_history=update_history,
                update_entries=update_entries,
                history_race_id_allowlist=history_race_id_allowlist,
                progress_callback=_on_progress,
            )
        except Exception:
            detail_placeholder.warning("更新進捗: 失敗")
            _set_in_page_operation_status(label=gauge_label, progress_pct=100, phase="失敗", state="failed")
            _update_llm_hands_free_visible_progress(1.0, "失敗", status="failed")
            raise

        progress_bar.progress(100, text=f"{gauge_label}: 完了 (100%)")
        detail_placeholder.caption("更新進捗: 完了")
        _set_in_page_operation_status(label=gauge_label, progress_pct=100, phase="完了", state="completed")
        _update_llm_hands_free_visible_progress(1.0, "完了", status="completed")
        return report

    def _run_recent_result_refresh(
        *,
        run_reflection_tuning: bool,
        action_label: str,
        status_label: str,
    ) -> AutoUpdateReport:
        pending_feedback_df = _load_prediction_feedback_snapshot()
        result_batch_cap = max(1, int(auto_result_batch_cap))
        pending_race_ids = _pending_prediction_race_ids_for_result_update(pending_feedback_df, cap=result_batch_cap)
        recent_race_ids = [] if pending_race_ids else _recent_prediction_race_ids_for_result_update(days_back=2, days_ahead=0)
        targeted_race_ids = pending_race_ids or recent_race_ids
        st.session_state["last_result_refresh_targeted_race_ids"] = targeted_race_ids
        with st.status(status_label, expanded=True) as update_status:
            if pending_race_ids:
                update_status.write(f"結果待ちレースのうち {len(pending_race_ids)} 件を優先して結果取得・採点します")
                update_status.write(f"無料取得で詰まりにくいよう、1回上限は {result_batch_cap} 件にしています")
            elif recent_race_ids:
                update_status.write(f"対象を直近予想レース {len(recent_race_ids)} 件に絞って結果取得します")
            else:
                update_status.write("対象レースが絞れなかったため通常の差分更新で実行します")
            update_status.write("再試行中: 通信が重い取得はタイムアウト後に自動で再試行します")
            report = _run_auto_update_with_gauge(
                action_label,
                profile_name="標準（差分更新）",
                force_tuning=bool(run_reflection_tuning),
                update_history=True,
                update_entries=False,
                history_race_id_allowlist=targeted_race_ids or None,
            )
            for line in collect_auto_update_status_lines(report.notes):
                update_status.write(line)
            update_status.update(label=f"{action_label} 完了", state="complete")
        return report

    def _run_weekly_ai_update(
        *,
        label: str,
        spinner_text: str,
        start_progress: float,
        saving_progress: float,
        notice_prefix: str = "今週AI予想を更新",
        show_success: bool = True,
    ) -> pd.DataFrame:
        _set_in_page_operation_status(label=label, progress_pct=int(round(start_progress * 100)), phase="作成中", state="running")
        _update_llm_hands_free_visible_progress(start_progress, "今週AI予想を作成中", status="running")
        with st.spinner(spinner_text):
            weekly_df = _run_weekly_auto_prediction_pipeline(
                simulations_per_race=int(weekly_ai_simulations),
                seed=42,
            )
        _set_in_page_operation_status(label=label, progress_pct=int(round(saving_progress * 100)), phase="保存中", state="running")
        _update_llm_hands_free_visible_progress(saving_progress, "予想を保存", status="running")
        weekly_df = _store_weekly_predictions_preview(weekly_df)
        notice_row = _pick_weekly_notice_row(weekly_df, st.session_state.get("selected_detail_race_id", ""))
        if not notice_row.empty:
            _set_ui_notice(_build_weekly_notice_message(notice_prefix, notice_row))
        else:
            _set_ui_notice(f"今週AI予想を更新しました: {len(weekly_df):,} レース")
        _set_in_page_operation_status(label=label, progress_pct=100, phase="完了", state="completed")
        _update_llm_hands_free_visible_progress(1.0, "完了", status="completed")
        if show_success:
            st.success(f"今週AI予想を更新: {len(weekly_df):,} レース")
        return weekly_df

    def _run_weekly_ai_if_enabled() -> None:
        if not auto_weekly_ai:
            return
        _run_weekly_ai_update(
            label="今週AI予想",
            spinner_text="今週AI予想を作成中...",
            start_progress=0.92,
            saving_progress=0.98,
        )

    if not auto_run_on_open:
        st.session_state["auto_bootstrap_done"] = False

    if (
        auto_ready
        and auto_run_on_open
        and data_mode == "自動取得データ"
        and not st.session_state.get("auto_bootstrap_done", False)
    ):
        try:
            report = _run_auto_update_with_gauge(
                "ページ起動時の自動更新",
                profile_name=update_profile,
                force_tuning=False,
            )
            st.session_state["auto_bootstrap_done"] = True
            _set_ui_notice(
                f"起動時自動更新: history {report.history_rows}行 / entries {report.entries_rows}行 / races {report.weekly_races}",
                level="info",
            )
            st.success(
                f"起動時自動更新: history {report.history_rows}行 / entries {report.entries_rows}行 / races {report.weekly_races}"
            )
            _run_weekly_ai_if_enabled()
            _render_auto_update_status_block(report.notes)
        except Exception as exc:
            st.error(f"自動更新に失敗しました: {exc}")

    queued_operation_action = _to_text(st.session_state.pop("queued_operation_action", ""))
    queued_weekly_fast = bool(queued_operation_action == "weekly_fast" and auto_ready)
    queued_latest_only = bool(queued_operation_action == "latest_only" and auto_ready)
    queued_selected_mode_update = bool(queued_operation_action == "selected_mode_update" and auto_ready)
    queued_train_only = bool(queued_operation_action == "train_only")
    queued_results_only = bool(queued_operation_action == "results_only" and auto_ready)
    queued_reflection_only = bool(queued_operation_action == "reflection_only")
    queued_results_train = bool(queued_operation_action == "results_train" and auto_ready)
    queued_weekly_only = bool(queued_operation_action == "weekly_only")
    run_easy_latest_only = False
    run_easy_weekly_only = False
    run_easy_results_only = False
    run_easy_reflection_only = False
    auto_history_for_train = Path(st.session_state.get("auto_history_path", str(AUTO_HISTORY_PATH)))
    easy_action_clicks = render_easy_action_buttons(
        easy_operation_mode=easy_operation_mode,
        auto_ready=auto_ready,
        history_exists=auto_history_for_train.exists(),
    )
    run_easy_latest_only = easy_action_clicks.latest_only
    run_easy_weekly_only = easy_action_clicks.weekly_only
    run_easy_results_only = easy_action_clicks.results_only
    run_easy_reflection_only = easy_action_clicks.reflection_only
    standard_controls_container = st.expander("通常操作（詳細）", expanded=False) if easy_operation_mode else st.container()
    with standard_controls_container:
        standard_update_clicks = render_standard_update_buttons(auto_ready=auto_ready)

        if standard_update_clicks.weekly_fast or queued_weekly_fast:
            try:
                report = _run_auto_update_with_gauge(
                    "今週出走表のみを高速更新",
                    profile_name="高速（最新追記）",
                    force_tuning=False,
                    update_history=False,
                    update_entries=True,
                )
                _set_ui_notice(f"今週だけ更新完了: entries {report.entries_rows}行 / races {report.weekly_races}")
                st.success(f"今週だけ更新完了: entries {report.entries_rows}行 / races {report.weekly_races}")
                if queued_weekly_fast:
                    _finalize_llm_hands_free_active_action(
                        "weekly_fast",
                        outcome_summary=f"出走 {report.entries_rows:,}行 / 今週 {report.weekly_races:,}レース",
                    )
                if auto_weekly_ai:
                    st.caption("高速化のため予想自動作成はスキップしました。必要なら `今週AI予想だけ更新` を実行してください。")
                _render_auto_update_status_block(report.notes)
            except Exception as exc:
                if queued_weekly_fast:
                    _finalize_llm_hands_free_active_action("weekly_fast", outcome_summary=f"失敗: {exc}", status="failed")
                st.error(f"今週だけ高速更新に失敗しました: {exc}")

        if run_easy_latest_only or standard_update_clicks.latest_only or queued_latest_only:
            try:
                report = _run_auto_update_with_gauge(
                    "最新追記モードで更新",
                    profile_name="高速（最新追記）",
                    force_tuning=False,
                )
                _set_ui_notice(f"高速更新完了: history {report.history_rows}行 / entries {report.entries_rows}行")
                st.success(f"高速更新完了: history {report.history_rows}行 / entries {report.entries_rows}行")
                _run_weekly_ai_if_enabled()
                if queued_latest_only:
                    _finalize_llm_hands_free_active_action(
                        "latest_only",
                        outcome_summary=f"履歴 {report.history_rows:,}行 / 出走 {report.entries_rows:,}行 / 今週 {report.weekly_races:,}レース",
                    )
                _render_auto_update_status_block(report.notes)
            except Exception as exc:
                if queued_latest_only:
                    _finalize_llm_hands_free_active_action("latest_only", outcome_summary=f"失敗: {exc}", status="failed")
                st.error(f"高速更新に失敗しました: {exc}")

        if standard_update_clicks.selected_mode_update or queued_selected_mode_update:
            try:
                report = _run_auto_update_with_gauge(
                    "自動取得を実行",
                    profile_name=update_profile,
                    force_tuning=False,
                )
                _set_ui_notice(
                    f"自動更新完了: history {report.history_rows}行 / entries {report.entries_rows}行 / races {report.weekly_races}"
                )
                st.success(
                    f"自動更新完了: history {report.history_rows}行 / entries {report.entries_rows}行 / races {report.weekly_races}"
                )
                _run_weekly_ai_if_enabled()
                if queued_selected_mode_update:
                    _finalize_llm_hands_free_active_action(
                        "selected_mode_update",
                        outcome_summary=f"履歴 {report.history_rows:,}行 / 出走 {report.entries_rows:,}行 / 今週 {report.weekly_races:,}レース",
                    )
                _render_auto_update_status_block(report.notes)
            except Exception as exc:
                if queued_selected_mode_update:
                    _finalize_llm_hands_free_active_action("selected_mode_update", outcome_summary=f"失敗: {exc}", status="failed")
                st.error(f"自動更新に失敗しました: {exc}")

        if st.button("学習だけ実行", disabled=(not auto_history_for_train.exists())) or (
            queued_train_only and auto_history_for_train.exists()
        ):
            try:
                report = _run_auto_update_with_gauge(
                    "履歴CSVから重み最適化",
                    profile_name=update_profile,
                    force_tuning=True,
                    update_history=False,
                    update_entries=False,
                )
                _set_ui_notice(f"学習完了: history {report.history_rows}行 を使用")
                st.success(f"学習完了: history {report.history_rows}行 を使用")
                if queued_train_only:
                    _finalize_llm_hands_free_active_action(
                        "train_only",
                        outcome_summary=f"学習完了 / 履歴 {report.history_rows:,}行",
                    )
                _render_auto_update_status_block(report.notes)
            except Exception as exc:
                if queued_train_only:
                    _finalize_llm_hands_free_active_action("train_only", outcome_summary=f"失敗: {exc}", status="failed")
                st.error(f"学習実行に失敗しました: {exc}")

        if st.button(
            "条件補正レースだけ軽量再学習",
            disabled=(not auto_history_for_train.exists()),
            help="保存済み予想のうち、条件補正が効いたレースだけを使って軽めに再学習します。",
        ):
            try:
                before_payload = _load_auto_model_payload()
                with st.status("条件補正レースだけで軽量再学習中...", expanded=True) as tune_status:
                    tune_status.write("対象レースを抽出中...")
                    tuning_result = _run_condition_adjustment_light_tuning(
                        trials=18,
                        val_races=12,
                        simulations=1200,
                    )
                    tune_status.write(
                        f"対象 {int(tuning_result['race_count']):,} レース / "
                        f"{int(tuning_result['feature_rows']):,} 行"
                    )
                    tune_status.update(label="条件補正レースだけ軽量再学習 完了", state="complete")
                after_payload = _load_auto_model_payload()
                weight_change_table = _store_weight_change_table(before_payload, after_payload, mode_label="条件補正レースだけ軽量再学習")
                _set_ui_notice(
                    f"軽量再学習完了: 条件補正レース {int(tuning_result['race_count']):,} / 特徴量 {int(tuning_result['feature_rows']):,} 行"
                )
                st.success(
                    f"軽量再学習完了: 条件補正レース {int(tuning_result['race_count']):,} / 特徴量 {int(tuning_result['feature_rows']):,} 行"
                )
                if not weight_change_table.empty:
                    st.caption("重み変化を保存しました。`アーカイブ > 成績評価` で確認できます。")
                _run_weekly_ai_if_enabled()
            except Exception as exc:
                st.error(f"条件補正レースの軽量再学習に失敗しました: {exc}")

        if st.button("取得→学習→予想を一括実行", type="primary", disabled=not auto_ready):
            try:
                report = _run_auto_update_with_gauge(
                    "自動取得 + 重み最適化",
                    profile_name=update_profile,
                    force_tuning=True,
                )
                _set_ui_notice(
                    f"一括更新完了: history {report.history_rows}行 / entries {report.entries_rows}行 / races {report.weekly_races}"
                )
                st.success(
                    f"一括更新完了: history {report.history_rows}行 / entries {report.entries_rows}行 / races {report.weekly_races}"
                )
                _run_weekly_ai_if_enabled()
                _render_auto_update_status_block(report.notes)
                run_predict_from_auto = True
                run_predict_mode = "auto_batch"
            except Exception as exc:
                st.error(f"一括実行に失敗しました: {exc}")

        post_race_clicks = render_post_race_action_buttons(
            auto_ready=auto_ready,
            history_exists=auto_history_for_train.exists(),
        )
        run_result_only_clicked = post_race_clicks.results_only
        run_reflection_only_clicked = post_race_clicks.reflection_only
        run_results_train_clicked = post_race_clicks.results_train
        run_weekly_only_clicked = post_race_clicks.weekly_only

    if run_easy_results_only or run_result_only_clicked or queued_results_only:
        try:
            before_feedback_df = _load_prediction_feedback_snapshot()
            before_feedback_summary = aggregate_prediction_feedback(before_feedback_df)
            report = _run_recent_result_refresh(
                run_reflection_tuning=False,
                action_label="結果取得だけ",
                status_label="最新結果を取得して履歴更新中...",
            )
            after_feedback_df = _load_prediction_feedback_snapshot()
            after_feedback_summary = aggregate_prediction_feedback(after_feedback_df)
            delta_text = feedback_summary_delta_text(before_feedback_summary, after_feedback_summary)
            delta_snapshot = feedback_summary_delta_snapshot(before_feedback_summary, after_feedback_summary)
            current_basis_label = _format_budget_basis_label(st.session_state.get("budget_basis_choice", "trend"))
            current_basis_key = _to_text(st.session_state.get("budget_basis_choice", "trend")) or "trend"
            current_basis_mode = "半自動" if bool(st.session_state.get("budget_basis_auto_enabled", True)) else "手動"
            basis_delta_text = _build_budget_basis_performance_delta_text(
                before_feedback_df,
                after_feedback_df,
                basis_label=current_basis_label,
                basis_mode=current_basis_mode,
            )
            bet_guidance_change = _build_bet_guidance_change_payload(
                basis_key=current_basis_key,
                before_summary=before_feedback_summary,
                after_summary=after_feedback_summary,
            )
            fetched_race_items = _build_newly_evaluated_race_items(before_feedback_df, after_feedback_df, limit=6)
            new_result_count = feedback_new_result_count(before_feedback_summary, after_feedback_summary)
            result_notice_text = result_refresh_notice_text(
                history_rows=report.history_rows,
                history_races=report.history_races,
                learned=False,
            )
            _set_result_sync_summary(
                "結果データを取り込みました",
                result_refresh_summary_detail(
                    new_result_count=new_result_count,
                    history_rows=report.history_rows,
                    history_races=report.history_races,
                ),
                delta_text,
                chip=result_refresh_chip(new_result_count),
                basis_key=_to_text(st.session_state.get("budget_basis_choice", "trend")) or "trend",
                basis_label=current_basis_label,
                basis_mode=current_basis_mode,
                basis_delta_text=basis_delta_text,
                race_items=fetched_race_items,
            )
            _set_ui_notice(result_notice_text)
            targeted_result_ids = normalize_race_ids(st.session_state.get("last_result_refresh_targeted_race_ids", []))
            remaining_targeted = remaining_targeted_result_ids(after_feedback_df, targeted_result_ids)
            _record_result_fetch_attempts(
                remaining_targeted or targeted_result_ids,
                status=result_fetch_attempt_status(new_result_count),
            )
            _request_open_archive_eval_tab()
            st.success(result_notice_text)
            if delta_text:
                st.info(f"成績差分: {delta_text}")
            else:
                st.warning(
                    "成績差分: 新規結果は増えていません。今回確認したレースIDはしばらくスキップして、次回は別の結果待ちレースを優先します。"
                )
            if queued_results_only:
                _finalize_llm_hands_free_active_action(
                    "results_only",
                    outcome_summary=f"新規結果 {new_result_count:,}件 / {delta_text or '成績差分なし'}",
                    extra={
                        "new_result_count": int(new_result_count),
                        "delta_text": delta_text,
                        "delta_snapshot": delta_snapshot,
                        "bet_guidance_change": bet_guidance_change,
                    },
                )
            _render_auto_update_status_block(report.notes)
        except Exception as exc:
            if queued_results_only:
                _finalize_llm_hands_free_active_action("results_only", outcome_summary=f"失敗: {exc}", status="failed")
            st.error(f"結果取得だけ に失敗しました: {exc}")

    if run_easy_reflection_only or run_reflection_only_clicked or (queued_reflection_only and auto_history_for_train.exists()):
        try:
            before_payload = _load_auto_model_payload()
            _set_in_page_operation_status(label="反省再学習だけ", progress_pct=15, phase="外れレースを抽出中", state="running")
            _update_llm_hands_free_visible_progress(0.15, "外れレースを抽出中", status="running")
            with st.status("外れレースを優先して反省再学習中...", expanded=True) as tune_status:
                tune_status.write("外れレースの特徴量を抽出中...")
                tuning_result = _run_reflection_light_tuning(
                    trials=16,
                    val_races=10,
                    simulations=1000,
                )
                tune_status.write(
                    f"対象 {int(tuning_result.get('race_count', 0)):,} レース / "
                    f"{int(tuning_result.get('feature_rows', 0)):,} 行 / "
                    f"反省対象 {int(tuning_result.get('reflection_rows', 0)):,} 行"
                )
                tune_status.update(label="反省再学習だけ 完了", state="complete")
            _set_in_page_operation_status(label="反省再学習だけ", progress_pct=90, phase="重み変化を確認", state="running")
            _update_llm_hands_free_visible_progress(0.9, "重み変化を確認", status="running")
            after_payload = _load_auto_model_payload()
            weight_change_table = _store_weight_change_table(before_payload, after_payload, mode_label="反省再学習だけ")
            _set_ui_notice(
                f"反省再学習完了: 対象 {int(tuning_result.get('race_count', 0)):,} レース / "
                f"反省 {int(tuning_result.get('reflection_rows', 0)):,} 行"
            )
            st.success(
                f"反省再学習完了: 対象 {int(tuning_result.get('race_count', 0)):,} レース / "
                f"反省 {int(tuning_result.get('reflection_rows', 0)):,} 行"
            )
            if not weight_change_table.empty:
                st.caption("重み変化を保存しました。`アーカイブ > 成績評価` で確認できます。")
            _run_weekly_ai_if_enabled()
            _set_in_page_operation_status(label="反省再学習だけ", progress_pct=100, phase="完了", state="completed")
            _update_llm_hands_free_visible_progress(1.0, "完了", status="completed")
            if queued_reflection_only:
                _finalize_llm_hands_free_active_action(
                    "reflection_only",
                    outcome_summary=(
                        f"反省 {int(tuning_result.get('reflection_rows', 0)):,}行 / "
                        f"対象 {int(tuning_result.get('race_count', 0)):,}レース"
                    ),
                )
        except Exception as exc:
            _set_in_page_operation_status(label="反省再学習だけ", progress_pct=100, phase="失敗", state="failed")
            _update_llm_hands_free_visible_progress(1.0, "失敗", status="failed")
            if queued_reflection_only:
                _finalize_llm_hands_free_active_action("reflection_only", outcome_summary=f"失敗: {exc}", status="failed")
            st.error(f"反省再学習に失敗しました: {exc}")

    if run_results_train_clicked or queued_results_train:
        try:
            before_feedback_df = _load_prediction_feedback_snapshot()
            before_feedback_summary = aggregate_prediction_feedback(before_feedback_df)
            report = _run_recent_result_refresh(
                run_reflection_tuning=True,
                action_label="結果取得→履歴更新→再学習",
                status_label="最新結果を取得して履歴更新・再学習中...",
            )
            after_feedback_df = _load_prediction_feedback_snapshot()
            after_feedback_summary = aggregate_prediction_feedback(after_feedback_df)
            delta_text = feedback_summary_delta_text(before_feedback_summary, after_feedback_summary)
            delta_snapshot = feedback_summary_delta_snapshot(before_feedback_summary, after_feedback_summary)
            current_basis_key = _to_text(st.session_state.get("budget_basis_choice", "trend")) or "trend"
            bet_guidance_change = _build_bet_guidance_change_payload(
                basis_key=current_basis_key,
                before_summary=before_feedback_summary,
                after_summary=after_feedback_summary,
            )
            result_notice_text = result_refresh_notice_text(
                history_rows=report.history_rows,
                history_races=report.history_races,
                learned=True,
            )
            _set_ui_notice(result_notice_text)
            st.success(result_notice_text)
            if queued_results_train:
                _finalize_llm_hands_free_active_action(
                    "results_train",
                    outcome_summary=result_refresh_outcome_summary(
                        history_rows=report.history_rows,
                        history_races=report.history_races,
                        learned=True,
                    ),
                    extra={
                        "delta_text": delta_text,
                        "delta_snapshot": delta_snapshot,
                        "bet_guidance_change": bet_guidance_change,
                    },
                )
            _run_weekly_ai_if_enabled()
            _render_auto_update_status_block(report.notes)
        except Exception as exc:
            if queued_results_train:
                _finalize_llm_hands_free_active_action("results_train", outcome_summary=f"失敗: {exc}", status="failed")
            st.error(f"結果取得→履歴更新→再学習に失敗しました: {exc}")

    if run_easy_weekly_only or run_weekly_only_clicked or queued_weekly_only:
        try:
            weekly_df = _run_weekly_ai_update(
                label="今週AI予想だけ更新",
                spinner_text="今週AI予想を更新中...",
                start_progress=0.15,
                saving_progress=0.85,
            )
            if queued_weekly_only:
                _finalize_llm_hands_free_active_action(
                    "weekly_only",
                    outcome_summary=f"今週AI予想 {len(weekly_df):,}レース",
                )
        except Exception as exc:
            _set_in_page_operation_status(label="今週AI予想だけ更新", progress_pct=100, phase="失敗", state="failed")
            _update_llm_hands_free_visible_progress(1.0, "失敗", status="failed")
            if queued_weekly_only:
                _finalize_llm_hands_free_active_action("weekly_only", outcome_summary=f"失敗: {exc}", status="failed")
            st.error(f"今週AI予想の更新に失敗しました: {exc}")

    render_latest_update_caption(st.session_state.get("auto_last_report"))

    current_auto_race_context: Dict[str, Any] = {}
    if data_mode == "自動取得データ":
        preview_entries_path = Path(st.session_state.get("auto_entries_path", str(AUTO_ENTRIES_PATH)))
        preview_entries_df = _read_csv_if_exists(preview_entries_path)
        if preview_entries_df is not None and not preview_entries_df.empty:
            preview_entries_df = pipeline_filter_current_week(preview_entries_df)
            current_auto_race_context = _extract_race_context(
                preview_entries_df,
                st.session_state.get("selected_detail_race_id", ""),
            )
            if current_auto_race_context:
                _apply_selected_race_context_to_inputs(current_auto_race_context)

    st.divider()
    st.subheader("予想条件")
    if current_auto_race_context:
        st.caption(f"詳細予想の初期値: {_to_text(current_auto_race_context.get('label', '-'))}")
    weather = st.selectbox("天気", WEATHER_OPTIONS, index=0, key="predict_weather")
    track_condition = st.selectbox("馬場状態", TRACK_OPTIONS, index=0, key="predict_track_condition")
    distance = st.number_input("距離 (m)", min_value=1000, max_value=3600, value=1600, step=100, key="predict_distance")
    simulations = st.slider("シミュレーション回数", min_value=2000, max_value=50000, value=15000, step=1000)
    seed = st.number_input("乱数シード", min_value=1, max_value=99999, value=42, step=1)
    budget = st.number_input("予算 (円)", min_value=0, max_value=500000, value=10000, step=500, key="predict_budget_total")
    unit = st.number_input("最小購入単位 (円)", min_value=100, max_value=5000, value=100, step=100, key="predict_bet_unit")
    weight_json = st.file_uploader("重みJSON（任意）", type=["json"], key="feature_weights")

    template_history, template_entries = export_template_csv()
    st.download_button(
        "履歴CSVテンプレートを保存",
        data=_to_csv_download(template_history.head(120)),
        file_name="keiba_history_template.csv",
        mime="text/csv",
    )
    st.download_button(
        "出走馬CSVテンプレートを保存",
        data=_to_csv_download(template_entries),
        file_name="keiba_entries_template.csv",
        mime="text/csv",
    )

st.markdown("<div id='home-predictions-anchor'></div>", unsafe_allow_html=True)
st.markdown(
    "**操作の流れ:** `今週だけ高速更新`（最速） or `最新だけ更新`（履歴も追記） → 出走馬データ確認 → `予想を実行` / レース後は `結果取得だけ` → 必要なら `反省再学習だけ` または `結果取得→履歴更新→再学習`"
)
latest_report_main = st.session_state.get("auto_last_report")
auto_self_improve_report: Dict[str, Any] = {}
render_latest_update_metrics(latest_report_main)
if _to_text(auto_self_improve_report.get("message", "")):
    st.info(f"自動改善: {_to_text(auto_self_improve_report.get('message', ''))}")

header_entries_df = None
header_history_df = None
if data_mode == "自動取得データ":
    header_entries_path = Path(st.session_state.get("auto_entries_path", str(AUTO_ENTRIES_PATH)))
    header_history_path = Path(st.session_state.get("auto_history_path", str(AUTO_HISTORY_PATH)))
    header_entries_df = _read_csv_if_exists(header_entries_path)
    header_history_df = _read_csv_if_exists(header_history_path)

weekly_prediction_df = pd.DataFrame(st.session_state.get("weekly_predictions_preview", []))
if weekly_prediction_df.empty:
    weekly_path = Path(st.session_state.get("weekly_predictions_path", str(WEEKLY_PREDICTIONS_PATH)))
    loaded_weekly = _read_csv_if_exists(weekly_path)
    if loaded_weekly is not None and (not loaded_weekly.empty):
        weekly_prediction_df = loaded_weekly
weekly_prediction_source_df = pipeline_ensure_weekly_prediction_columns(weekly_prediction_df.copy())
weekly_prediction_df = prepare_weekly_predictions_preview(weekly_prediction_df)
weekly_prediction_df = _ensure_race_grade_column(weekly_prediction_df)
if isinstance(header_entries_df, pd.DataFrame):
    header_entries_df = pipeline_filter_current_week(header_entries_df)
    header_entries_df = _ensure_race_grade_column(header_entries_df)
prediction_archive_df = pd.DataFrame()
prediction_feedback_df = pd.DataFrame()
prediction_feedback_summary: Dict[str, Any] = {}
prediction_feedback_trend_summary: Dict[str, Any] = {}
feedback_trend_strategy_snapshot: Dict[str, str] = {
    "style": "-",
    "main_bets": "-",
    "sub_bets": "-",
    "caution": "-",
}
analog_strategy_snapshot: Dict[str, str] = {
    "style": "-",
    "main_bets": "-",
    "sub_bets": "-",
    "caution": "-",
}
bet_type_performance_df = pd.DataFrame()
budget_basis_performance_df = pd.DataFrame()
bet_type_feedback_rows_df = pd.DataFrame()
condition_adjustment_performance_df = pd.DataFrame()
condition_segment_performance_df = pd.DataFrame()
llm_disagreement_performance_df = pd.DataFrame()
llm_hit_weekly_summary = {}
if data_mode == "自動取得データ":
    prediction_archive_df = _sync_prediction_archive(
        _annotate_prediction_archive_budget_basis(
            weekly_prediction_source_df,
            basis_key=st.session_state.get("budget_basis_choice", "trend"),
            basis_label=_format_budget_basis_label(st.session_state.get("budget_basis_choice", "trend")),
            auto_mode=bool(st.session_state.get("budget_basis_auto_enabled", True)),
        )
    )
    prediction_feedback_df = _sync_prediction_feedback_from_files(
        header_history_path if isinstance(header_history_path, Path) else Path(header_history_path)
    )
    prediction_feedback_summary = aggregate_prediction_feedback(prediction_feedback_df)
    prediction_feedback_trend_summary = _build_feedback_trend_summary(prediction_feedback_df, lookback_days=7)
    budget_basis_performance_df = build_budget_basis_performance_table(prediction_feedback_df)
    llm_disagreement_performance_df = build_llm_disagreement_performance_table(prediction_feedback_df)
    llm_hit_weekly_summary = _build_llm_hit_weekly_summary(llm_disagreement_performance_df)
    auto_self_improve_report = _maybe_run_auto_self_improvement(
        prediction_feedback_df,
        enabled=bool(auto_self_improve),
        sync_feedback_memory=bool(auto_sync_feedback_memory),
        auto_reflection_learning=bool(auto_reflection_learning),
        auto_refresh_weekly=bool(auto_refresh_weekly_after_reflection),
        min_new_results_for_reflection=int(auto_reflection_min_new_results),
        min_missed_results_for_reflection=int(auto_reflection_min_missed_results),
        reflection_cooldown_minutes=int(auto_reflection_cooldown_minutes),
        weekly_simulations=int(weekly_ai_simulations),
        weekly_seed=42,
    )
    refreshed_weekly_df = auto_self_improve_report.get("weekly_df", pd.DataFrame())
    if isinstance(refreshed_weekly_df, pd.DataFrame) and not refreshed_weekly_df.empty:
        weekly_prediction_source_df = pipeline_ensure_weekly_prediction_columns(refreshed_weekly_df.copy())
        weekly_prediction_df = prepare_weekly_predictions_preview(refreshed_weekly_df.copy())

operation_guide_snapshot = _build_operation_guide_snapshot(
    data_mode=data_mode,
    entries_path=(header_entries_path if data_mode == "自動取得データ" else AUTO_ENTRIES_PATH),
    weekly_predictions_path=Path(st.session_state.get("weekly_predictions_path", str(WEEKLY_PREDICTIONS_PATH))),
    weights_path=AUTO_WEIGHTS_PATH,
    feedback_path=PREDICTION_FEEDBACK_PATH,
    feedback_summary=prediction_feedback_summary,
    entries_rows=(len(header_entries_df) if isinstance(header_entries_df, pd.DataFrame) else 0),
    weekly_rows=len(weekly_prediction_df),
)
_render_autonomous_overview_card(
    auto_cycle_status,
    auto_cycle_config,
    prediction_feedback_summary,
    entries_rows=(len(header_entries_df) if isinstance(header_entries_df, pd.DataFrame) else 0),
    weekly_rows=len(weekly_prediction_df),
    history_path=(header_history_path if data_mode == "自動取得データ" else AUTO_HISTORY_PATH),
)
_render_operation_guide(operation_guide_snapshot)
_maybe_queue_llm_hands_free_action(
    operation_guide_snapshot,
    enabled=bool(llm_hands_free_mode),
    data_mode=data_mode,
    auto_ready=bool(auto_ready),
)

week_start_value, week_end_value = _current_week_bounds()
today_value = date.today()
today_weekly_df = _filter_target_day(weekly_prediction_df, today_value)
today_entries_df = (
    _filter_target_day(header_entries_df, today_value)
    if isinstance(header_entries_df, pd.DataFrame)
    else pd.DataFrame()
)
has_today_scope = (not today_weekly_df.empty) or (not today_entries_df.empty)
weekly_scope_selection = render_weekly_scope_selector(
    has_today_scope=has_today_scope,
    today_value=today_value,
    week_start_value=week_start_value,
    week_end_value=week_end_value,
)
selected_display_scope = weekly_scope_selection.selected_scope
display_scope_label = weekly_scope_selection.display_label
if weekly_scope_selection.selected_scope == "今日":
    weekly_prediction_df = today_weekly_df.copy()
    header_entries_df = today_entries_df.copy()
llm_alignment_options = ("すべて", "別軸を上に集める", "別軸だけ")
weekly_gate_lookup = _build_race_gate_lookup(
    header_entries_df if isinstance(header_entries_df, pd.DataFrame) else pd.DataFrame()
)
weekly_venue_options = _collect_venue_options(
    weekly_prediction_df,
    header_entries_df if isinstance(header_entries_df, pd.DataFrame) else pd.DataFrame(),
)
weekly_grade_options = _collect_grade_options(
    weekly_prediction_df,
    header_entries_df if isinstance(header_entries_df, pd.DataFrame) else pd.DataFrame(),
)
selected_weekly_venues = weekly_venue_options.copy()
selected_weekly_grades = weekly_grade_options.copy()
weekly_filter_selection = render_weekly_filter_controls(
    venue_options=weekly_venue_options,
    grade_options=weekly_grade_options,
    llm_alignment_options=llm_alignment_options,
    current_llm_alignment=st.session_state.get("weekly_llm_alignment_filter", "すべて"),
    display_scope_label=display_scope_label,
)
selected_weekly_venues = weekly_filter_selection.venues
selected_weekly_grades = weekly_filter_selection.grades
selected_weekly_llm_alignment = weekly_filter_selection.llm_alignment
view_weekly_display = pd.DataFrame()
view_overview_display = pd.DataFrame()
if not weekly_prediction_df.empty:
    st.subheader(f"{display_scope_label}AI自動予想（全レース）")
    if "race_id" in weekly_prediction_df.columns and weekly_prediction_df["race_id"].fillna("").astype(str).str.upper().str.startswith("AUTO").any():
        st.info("現在は仮データが含まれます（例: AUTO..., 馬xx（仮））。`最新だけ更新` で実名データ取得を再試行してください。")
    view_weekly = _apply_venue_filter(weekly_prediction_df.copy(), "venue", selected_weekly_venues, weekly_venue_options)
    view_weekly = _apply_grade_filter(view_weekly, selected_weekly_grades, weekly_grade_options)
    view_weekly = _sort_program_order_frame(view_weekly, race_id_col="race_id", race_date_col="race_date", venue_col="venue")
    if "venue" not in view_weekly.columns:
        view_weekly["venue"] = ""
    if "venue" in view_weekly.columns:
        view_weekly["venue"] = view_weekly["venue"].fillna("").astype(str).str.strip().replace("", "-")
    view_weekly["race_label"] = view_weekly.apply(
        lambda row: _format_race_label(
            row.get("race_id", ""),
            row.get("venue", ""),
            row.get("race_date", ""),
            row.get("race_name", ""),
        ),
        axis=1,
    )
    view_weekly["data_state"] = view_weekly.apply(_weekly_row_state, axis=1)
    view_weekly = prepare_weekly_display_columns(view_weekly)
    view_weekly = _decorate_columns_with_gate(
        view_weekly,
        race_id_col="レースID",
        gate_lookup_by_race=weekly_gate_lookup,
        target_columns=[
            "本命馬",
            "大穴候補",
            "危険人気馬",
            "スピ候補",
            "LLM本命",
            "LLM穴",
            "LLM危険人気",
            "単勝候補",
            "複勝候補",
            "馬連候補",
            "ワイド候補",
            "馬単候補",
            "三連複候補",
            "三連単候補",
        ],
    )
    mark_frame = view_weekly.apply(_infer_weekly_mark_columns, axis=1, result_type="expand")
    for mark_col in ["◎", "○", "▲", "△"]:
        if mark_col in mark_frame.columns:
            view_weekly[mark_col] = mark_frame.apply(
                lambda row: _render_name_text_with_gate(
                    row.get(mark_col, ""),
                    weekly_gate_lookup.get(_to_text(row.get("レースID", "")), {}),
                ),
                axis=1,
            )
    if isinstance(header_history_df, pd.DataFrame) and isinstance(header_entries_df, pd.DataFrame) and not header_history_df.empty and not header_entries_df.empty:
        view_weekly["型要約"] = view_weekly.apply(
            lambda row: _build_weekly_mark_type_summary(
                row,
                history_df=header_history_df,
                entries_df=header_entries_df,
            ),
            axis=1,
        )
        view_weekly["型要約"] = view_weekly["型要約"].map(_format_weekly_mark_type_badges)
    view_weekly["LLM本命比較"] = view_weekly.apply(
        lambda row: _build_llm_top_alignment_label(row.get("本命馬", "-"), row.get("LLM本命", "-")),
        axis=1,
    )
    view_weekly["LLM別軸理由_raw"] = view_weekly.apply(_build_llm_disagreement_reason, axis=1)
    view_weekly["LLM警戒区分"] = view_weekly["LLM別軸理由_raw"].map(
        lambda text: "-" if _to_text(text) in {"", "-", "データ本命と一致"} else _classify_llm_disagreement_bucket(text)
    )
    view_weekly["LLM警戒区分"] = view_weekly["LLM警戒区分"].map(_format_llm_bucket_badges_text)
    view_weekly["LLM別軸理由"] = view_weekly["LLM別軸理由_raw"].map(
        lambda text: "-" if _to_text(text) in {"", "-", "データ本命と一致"} else _to_text(text)
    )
    view_weekly["LLM別軸理由"] = view_weekly["LLM別軸理由"].map(_format_llm_reason_badges_text)
    view_weekly["LLM危険連動"] = view_weekly.apply(
        lambda row: _build_llm_danger_sync_label(row.get("危険人気馬", "-"), row.get("LLM危険人気", "-")),
        axis=1,
    )
    view_weekly = _apply_llm_alignment_view_mode(
        view_weekly,
        selected_weekly_llm_alignment,
        comparison_col="LLM本命比較",
        race_id_col="レースID",
        race_date_col="日付",
        venue_col="開催",
    )
    view_weekly["買い方方針"] = _build_feedback_trend_weekly_label(prediction_feedback_trend_summary)
    view_weekly["券種期待度"] = _format_strategy_expectation_badges_text(
        _build_feedback_trend_weekly_label(prediction_feedback_trend_summary)
    )
    view_weekly["買い方方針"] = view_weekly["買い方方針"].map(_format_weekly_buying_style_badges)
    for col in ("勝率", "複勝率"):
        if col in view_weekly.columns:
            view_weekly[col] = pd.to_numeric(view_weekly[col], errors="coerce").map(
                lambda x: "-" if pd.isna(x) else f"{float(x):.2%}"
            )
    if "本命人気" in view_weekly.columns:
        view_weekly["本命人気"] = pd.to_numeric(view_weekly["本命人気"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{int(float(x))}番人気"
        )
    if "本命単勝オッズ" in view_weekly.columns:
        view_weekly["本命単勝オッズ"] = pd.to_numeric(view_weekly["本命単勝オッズ"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{float(x):.1f}"
        )
    if "大穴人気" in view_weekly.columns:
        view_weekly["大穴人気"] = view_weekly["大穴人気"].map(lambda x: _format_popularity_label(x))
    if "危険人気" in view_weekly.columns:
        view_weekly["危険人気"] = view_weekly["危険人気"].map(lambda x: _format_popularity_label(x))
    if "補正本数" in view_weekly.columns:
        view_weekly["補正本数"] = view_weekly["補正本数"].map(_format_condition_adjustment_count)
    if "日付" in view_weekly.columns:
        view_weekly["日付"] = view_weekly["日付"].map(_format_date_text)
    if "距離" in view_weekly.columns:
        view_weekly["距離"] = pd.to_numeric(view_weekly["距離"], errors="coerce").map(
            lambda x: "-" if pd.isna(x) else f"{int(float(x))}m"
        )
    if view_weekly.empty:
        st.info("選択した開催場所/格付けに一致する今週AI予想はありません。")
    else:
        _render_llm_priority_cards(
            view_weekly,
            header_entries_df,
            performance_df=llm_disagreement_performance_df,
            llm_hit_summary=llm_hit_weekly_summary,
            limit=3,
            simulations_per_race=int(weekly_ai_simulations),
            seed=42,
        )
        st.caption("危険人気アラート")
        _render_danger_cards(view_weekly, limit=4)
        _render_weekly_race_cards(
            view_weekly,
            header_entries_df,
            limit=3,
            simulations_per_race=int(weekly_ai_simulations),
            seed=42,
        )
        view_weekly_display = render_weekly_prediction_tables(
            view_weekly,
            display_scope_label=display_scope_label,
            selected_llm_alignment=selected_weekly_llm_alignment,
            with_one_based_index=_with_one_based_index,
            to_text=_to_text,
        )
    if "本命人気" in view_weekly.columns and (view_weekly["本命人気"] == "-").all():
        st.caption("本命人気はオッズ/人気データ取得時に表示されます。")

if data_mode == "自動取得データ":
    st.subheader(f"{display_scope_label}のレース情報")
    if header_entries_df is None or header_entries_df.empty:
        st.caption(f"{display_scope_label}のレース情報は未取得です。サイドバーの `最新だけ更新` を実行してください。")
    else:
        filtered_entries_df = _apply_venue_filter(header_entries_df, "venue", selected_weekly_venues, weekly_venue_options)
        filtered_entries_df = _apply_grade_filter(filtered_entries_df, selected_weekly_grades, weekly_grade_options)
        weekly_overview = _build_weekly_race_overview(filtered_entries_df)
        if weekly_overview.empty:
            st.caption("今週レース情報を集計できませんでした。")
        else:
            view_overview = weekly_overview.copy()
            view_overview = _sort_program_order_frame(view_overview, race_id_col="レースID", race_date_col="日付", venue_col="開催")
            if "開催" not in view_overview.columns:
                view_overview["開催"] = "-"
            if "レースID" in view_overview.columns:
                view_overview.insert(
                    0,
                    "レース",
                    view_overview.apply(
                        lambda row: _format_race_label(
                            row.get("レースID", ""),
                            row.get("開催", ""),
                            row.get("日付", ""),
                            row.get("レース名", ""),
                        ),
                        axis=1,
                    ),
                )
            if "注目馬" in view_overview.columns:
                view_overview = _decorate_columns_with_gate(
                    view_overview,
                    race_id_col="レースID",
                    gate_lookup_by_race=weekly_gate_lookup,
                    target_columns=["注目馬"],
                )
            if "注目騎手" in view_overview.columns:
                view_overview["注目騎手"] = view_overview["注目騎手"].map(_render_name_text)
            if "日付" in view_overview.columns:
                view_overview["日付"] = view_overview["日付"].map(_format_date_text)
            view_overview["データ状態"] = view_overview.apply(_weekly_overview_state, axis=1)
            if (view_overview["データ状態"] == "仮データ").any():
                st.info("`馬xx（仮）` と表示される行は実名が未取得です。更新ボタンで再取得すると実名化される場合があります。")
            view_overview_display = render_weekly_race_overview_table(
                view_overview,
                with_one_based_index=_with_one_based_index,
            )

if data_mode == "自動取得データ":
    selector_frame = _build_detail_race_selector_frame(view_weekly_display, view_overview_display)
    if not selector_frame.empty:
        selector_frame = _sort_program_order_frame(selector_frame, race_id_col="race_id", race_date_col="label", venue_col="venue")
        st.subheader("開催別レース順")
        venue_program_options = [v for v in selector_frame["venue"].fillna("").astype(str).str.strip().tolist() if v and v != "-"]
        dedup_program_options: List[str] = []
        for venue_name in venue_program_options:
            if venue_name not in dedup_program_options:
                dedup_program_options.append(venue_name)
        if dedup_program_options:
            default_program_venue = "中京" if "中京" in dedup_program_options else dedup_program_options[0]
            current_program_venue = _to_text(st.session_state.get("program_order_venue", default_program_venue))
            if current_program_venue not in dedup_program_options:
                current_program_venue = default_program_venue
            venue_program_col, race_program_info_col = st.columns([1.8, 1.0], gap="small")
            with venue_program_col:
                selected_program_venue = st.selectbox(
                    "レース順で見る開催",
                    options=dedup_program_options,
                    index=dedup_program_options.index(current_program_venue),
                    key="program_order_venue",
                )
            venue_program_frame = selector_frame[selector_frame["venue"] == selected_program_venue].copy()
            venue_program_frame = _sort_program_order_frame(
                venue_program_frame.assign(日付=venue_program_frame["label"].map(_parse_date_text)),
                race_id_col="race_id",
                race_date_col="日付",
                venue_col="venue",
            )
            with race_program_info_col:
                st.metric("開催レース数", f"{len(venue_program_frame):,}")
                if not venue_program_frame.empty:
                    st.metric("最初のレース", _format_race_no_text(venue_program_frame.iloc[0]["race_id"]))
            if not venue_program_frame.empty:
                merge_cols = [
                    c
                    for c in [
                        "レースID",
                        "本命馬",
                        "大穴候補",
                        "単勝候補",
                        "複勝候補",
                        "馬連候補",
                        "ワイド候補",
                        "三連複候補",
                        "三連単候補",
                        "補正本数",
                        "条件補正",
                        "人気急変",
                        "買い方方針",
                        "LLM警戒区分",
                        "天気予報",
                        "馬場",
                        "距離",
                        "本命騎手",
                    ]
                    if c in view_weekly_display.columns
                ]
                program_display = venue_program_frame.rename(
                    columns={
                        "race_id": "レースID",
                        "label": "レース",
                        "venue": "開催",
                        "grade": "格付",
                        "field_size": "頭数",
                    }
                ).copy()
                if merge_cols:
                    program_display = program_display.merge(
                        view_weekly_display[merge_cols],
                        on="レースID",
                        how="left",
                    )
                program_display.insert(0, "レース順", program_display["レースID"].map(_format_race_no_text))
                for col in ["本命馬", "大穴候補", "三連単候補", "本命騎手"]:
                    if col in program_display.columns:
                        program_display[col] = program_display[col].map(_render_name_text)
                if "買い方方針" in program_display.columns:
                    program_display["買い方方針"] = program_display["買い方方針"].map(_format_weekly_buying_style_badges)
                if "買い方方針" in program_display.columns and "券種期待度" not in program_display.columns:
                    raw_strategy_label = _build_feedback_trend_weekly_label(prediction_feedback_trend_summary)
                    program_display["券種期待度"] = _format_strategy_expectation_badges_text(raw_strategy_label)
                program_selection = render_program_order_panel(
                    program_display,
                    selected_program_venue=selected_program_venue,
                    current_race_id=st.session_state.get("program_selected_race_id", ""),
                    with_one_based_index=_with_one_based_index,
                    to_text=_to_text,
                )
                current_program_row = program_selection.current_row
                if program_selection.action == "show":
                    _queue_weekly_display_row(current_program_row, header_entries_df)
                elif program_selection.action == "refresh":
                    try:
                        _refresh_weekly_display_row(
                            current_program_row,
                            source_entries_df=header_entries_df,
                            simulations_per_race=int(weekly_ai_simulations),
                            seed=42,
                            notice_prefix="選択レース再計算",
                        )
                    except Exception as exc:
                        st.error(f"開催別レース再計算に失敗しました: {exc}")
                st.markdown(
                    _build_program_strategy_focus_html(
                        current_program_row,
                        budget_total=int(budget),
                        bet_units=int(unit),
                        caution_bets=feedback_trend_strategy_snapshot.get("caution", "-"),
                    ),
                    unsafe_allow_html=True,
                )

                reader_default_venue = "中京" if "中京" in dedup_program_options else selected_program_venue
                current_reader_venue = _to_text(st.session_state.get("venue_reader_venue", reader_default_venue))
                if current_reader_venue not in dedup_program_options:
                    current_reader_venue = reader_default_venue
                st.subheader(f"{current_reader_venue} 1Rから順に読むモード" if current_reader_venue == "中京" else "開催別 1Rから順に読むモード")
                reader_venue_col, reader_info_col = st.columns([1.8, 1.0], gap="small")
                with reader_venue_col:
                    selected_reader_venue = st.selectbox(
                        "読む開催",
                        options=dedup_program_options,
                        index=dedup_program_options.index(current_reader_venue),
                        key="venue_reader_venue",
                    )
                autoplay_active = bool(st.session_state.get("venue_reader_autoplay", False))
                autoplay_venue = _to_text(st.session_state.get("venue_reader_autoplay_venue", ""))
                if autoplay_active and autoplay_venue and autoplay_venue != selected_reader_venue:
                    st.session_state["venue_reader_autoplay"] = False
                    st.session_state["venue_reader_autoplay_venue"] = ""
                    autoplay_active = False
                venue_reader_frame = selector_frame[selector_frame["venue"] == selected_reader_venue].copy()
                if not venue_reader_frame.empty:
                    venue_reader_frame = venue_reader_frame.rename(
                        columns={
                            "race_id": "レースID",
                            "label": "レース",
                            "venue": "開催",
                            "grade": "格付",
                            "field_size": "頭数",
                        }
                    ).copy()
                    venue_reader_frame = _sort_program_order_frame(
                        venue_reader_frame.assign(日付=venue_reader_frame["レース"].map(_parse_date_text)),
                        race_id_col="レースID",
                        race_date_col="日付",
                        venue_col="開催",
                    )
                    if merge_cols:
                        venue_reader_frame = venue_reader_frame.merge(
                            view_weekly_display[merge_cols],
                            on="レースID",
                            how="left",
                        )
                    venue_reader_frame.insert(0, "レース順", venue_reader_frame["レースID"].map(_format_race_no_text))
                    for col in ["本命馬", "大穴候補", "単勝候補", "複勝候補", "馬連候補", "ワイド候補", "三連複候補", "三連単候補"]:
                        if col in venue_reader_frame.columns:
                            venue_reader_frame[col] = venue_reader_frame[col].map(_render_name_text)
                    reader_id_candidates = venue_reader_frame["レースID"].map(_to_text).tolist()
                    main_reader_race_id = _pick_main_race_id(venue_reader_frame, "レースID")
                    jump_targets = {
                        "1R": _find_race_id_by_number(reader_id_candidates, 1),
                        "メイン": main_reader_race_id,
                        "6R": _find_race_id_by_number(reader_id_candidates, 6),
                        "12R": _find_race_id_by_number(reader_id_candidates, 12),
                    }
                    reader_selection = render_venue_reader_panel(
                        venue_reader_frame,
                        selected_reader_venue=selected_reader_venue,
                        current_race_id=st.session_state.get("venue_reader_race_id", ""),
                        autoplay_active=autoplay_active,
                        jump_targets=jump_targets,
                        to_text=_to_text,
                        render_name_text=_render_name_text,
                    )
                    reader_ids = reader_selection.race_ids
                    current_reader_index = reader_selection.current_index
                    current_reader_row = reader_selection.current_row
                    current_reader_race_id = reader_selection.current_race_id
                    if reader_selection.action == "show":
                        _queue_weekly_display_row(current_reader_row, header_entries_df)
                    elif reader_selection.action == "refresh":
                        try:
                            _refresh_weekly_display_row(
                                current_reader_row,
                                source_entries_df=header_entries_df,
                                simulations_per_race=int(weekly_ai_simulations),
                                seed=42,
                                notice_prefix=f"{selected_reader_venue}読むモード再計算",
                            )
                        except Exception as exc:
                            st.error(f"{selected_reader_venue} 読むモード再計算に失敗しました: {exc}")
                    elif reader_selection.action == "open_next" and not reader_selection.next_row.empty:
                        _request_scroll_to_detail()
                        _queue_weekly_display_row(reader_selection.next_row, header_entries_df)
                    elif reader_selection.action == "autoplay_start":
                        st.session_state["venue_reader_autoplay"] = True
                        st.session_state["venue_reader_autoplay_venue"] = selected_reader_venue
                        _request_scroll_to_detail()
                        _queue_weekly_display_row(current_reader_row, header_entries_df)
                    autoplay_active = bool(st.session_state.get("venue_reader_autoplay", False))
                    autoplay_venue = _to_text(st.session_state.get("venue_reader_autoplay_venue", ""))
                    if autoplay_active and autoplay_venue == selected_reader_venue:
                        selected_detail_race_id = _to_text(st.session_state.get("selected_detail_race_id", ""))
                        if selected_detail_race_id != current_reader_race_id:
                            current_race_no = _to_text(current_reader_row.get("レース順", "-"))
                            st.info(f"{selected_reader_venue} 自動送り: まず {current_race_no} の詳細を開きます。")
                            _request_scroll_to_detail()
                            _set_selected_race_context_state(
                                race_id=current_reader_row.get("レースID", ""),
                                source_entries_df=header_entries_df,
                                label=current_reader_row.get("レース", ""),
                                venue=current_reader_row.get("開催", ""),
                                field_size=current_reader_row.get("頭数", ""),
                            )
                            _render_reload_after_delay(250)
                        elif current_reader_index >= len(reader_ids) - 1:
                            st.session_state["venue_reader_autoplay"] = False
                            st.session_state["venue_reader_autoplay_venue"] = ""
                            st.success(f"{selected_reader_venue} 自動送りを終了しました。最終レースまで到達しています。")
                        else:
                            next_reader_row = venue_reader_frame.iloc[current_reader_index + 1]
                            next_race_id = _to_text(next_reader_row.get("レースID", ""))
                            next_race_no = _to_text(next_reader_row.get("レース順", "-"))
                            st.info(f"{selected_reader_venue} 自動送り中: {next_race_no} を1.8秒後に開きます。")
                            st.session_state["venue_reader_race_id"] = next_race_id
                            _request_scroll_to_detail()
                            _set_selected_race_context_state(
                                race_id=next_race_id,
                                source_entries_df=header_entries_df,
                                label=next_reader_row.get("レース", ""),
                                venue=next_reader_row.get("開催", ""),
                                field_size=next_reader_row.get("頭数", ""),
                            )
                            _render_reload_after_delay(1800)
        detail_selection = render_weekly_detail_selector_panel(
            selector_frame,
            current_race_id=st.session_state.get("selected_detail_race_id", ""),
            to_text=_to_text,
        )
        if detail_selection.action == "show":
            selected_row = detail_selection.selected_row
            _queue_selected_race_for_prediction(
                race_id=detail_selection.selected_race_id,
                source_entries_df=header_entries_df,
                label=detail_selection.selected_label,
                venue=selected_row.get("venue", ""),
                field_size=selected_row.get("field_size", ""),
            )
        elif detail_selection.action == "refresh":
            try:
                selected_row = detail_selection.selected_row
                with st.spinner("選択レースだけ再計算中..."):
                    refreshed = _refresh_selected_weekly_prediction(
                        detail_selection.selected_race_id,
                        simulations_per_race=int(weekly_ai_simulations),
                        seed=42,
                    )
                refreshed_row = refreshed.iloc[0]
                _set_ui_notice(_build_weekly_notice_message("選択レース再計算", refreshed_row))
                _queue_selected_race_for_prediction(
                    race_id=detail_selection.selected_race_id,
                    source_entries_df=header_entries_df,
                    label=detail_selection.selected_label,
                    venue=selected_row.get("venue", ""),
                    field_size=selected_row.get("field_size", ""),
                )
            except Exception as exc:
                st.error(f"選択レース再計算に失敗しました: {exc}")

render_graded_focus_section(
    view_weekly_display,
    view_overview_display,
    with_one_based_index=_with_one_based_index,
    render_grade_bet_memo_cards=_render_grade_bet_memo_cards,
)

if data_mode == "自動取得データ":
    archive_home_tab, archive_data_tab = st.tabs(["予想ホーム", "アーカイブ"])
    with archive_home_tab:
        _render_feedback_trend_card(prediction_feedback_trend_summary)
        llm_disagreement_summary = _build_llm_disagreement_summary(weekly_prediction_df, limit=4)
        _render_llm_disagreement_trend_card(llm_disagreement_summary)
        _render_llm_hit_weekly_card(
            llm_hit_weekly_summary,
            trend_summary=prediction_feedback_trend_summary,
            allow_apply=True,
            button_prefix="archive_home_llm_hit",
        )
        if not llm_disagreement_performance_df.empty:
            llm_overall_row = llm_disagreement_performance_df.iloc[0]
            llm_metric_cols = st.columns(4)
            llm_metric_cols[0].metric("別軸評価済み", f"{int(llm_overall_row.get('評価済みレース', 0) or 0):,}")
            llm_metric_cols[1].metric("データ本命勝率", _format_rate_metric(llm_overall_row.get("データ本命勝率")))
            llm_metric_cols[2].metric("LLM本命勝率", _format_rate_metric(llm_overall_row.get("LLM本命勝率")))
            llm_metric_cols[3].metric("LLM優勢差", _format_signed_rate_metric(llm_overall_row.get("LLM優勢差")))
            st.caption("LLMとデータが別軸だったレースだけを抜き出した成績です。LLM側のズレが実際に当たりへ寄与しているかを見ます。")
            st.caption(_build_llm_disagreement_performance_comment(llm_disagreement_performance_df, llm_disagreement_summary))
            focus_comment = _build_llm_hit_focus_comment(llm_disagreement_performance_df)
            if focus_comment:
                st.caption(focus_comment)
            _render_llm_disagreement_performance_charts(llm_disagreement_performance_df)
        if prediction_feedback_summary:
            render_feedback_summary_metrics(
                prediction_feedback_summary,
                format_rate_metric=_format_rate_metric,
                format_roi_metric=_format_roi_metric,
            )
            st.caption(
                "結果待ちは当日までの未取得分だけを数えます。未来予想と日付不明分は分けて扱います。"
            )
            pending_home_count = int(prediction_feedback_summary.get("pending_races", 0) or 0)
            if pending_home_count > 0:
                st.warning(f"結果待ちが {pending_home_count:,} 件あります。`結果待ちを確認して採点` で未評価レースを優先取得します。")
                if st.button("結果待ちを確認して採点", key="archive_home_score_pending_results", type="primary"):
                    _queue_operation_action("結果取得だけ")
            if int(prediction_feedback_summary.get("undated_predictions", 0)) > 0:
                st.caption(f"日付不明の保存予想: {int(prediction_feedback_summary.get('undated_predictions', 0)):,} 件")
        st.caption("過去データと予想差分は右の `アーカイブ` タブに移しました。ホーム側は短く保ちます。")
    with archive_data_tab:
        st.subheader("評価・過去データ")
        archive_eval_tab, archive_history_tab, archive_course_tab = st.tabs(["成績評価", "過去レース", "競馬場情報"])
        with archive_eval_tab:
            st.markdown('<div id="archive-eval-anchor"></div>', unsafe_allow_html=True)
            render_feedback_summary_metrics(
                prediction_feedback_summary,
                format_rate_metric=_format_rate_metric,
                format_roi_metric=_format_roi_metric,
                include_hit_rates=False,
            )
            st.caption(
                "保存した予想と取得済み結果を自動で突き合わせます。レース後に `結果取得→履歴更新→再学習` を押すと差分集計まで更新されます。"
            )
            eval_sub_cols = st.columns(3)
            eval_sub_cols[0].metric("未来予想", f"{int(prediction_feedback_summary.get('upcoming_races', 0)):,}")
            eval_sub_cols[1].metric("日付不明", f"{int(prediction_feedback_summary.get('undated_predictions', 0)):,}")
            latest_weight_change_df = _load_latest_weight_change_table()
            latest_weight_meta = st.session_state.get("latest_weight_change_meta", {})
            eval_sub_cols[2].metric("最新重み更新", _to_text(latest_weight_meta.get("mode", "-")) or "-")
            pending_eval_count = int(prediction_feedback_summary.get("pending_races", 0) or 0)
            if pending_eval_count > 0:
                st.info(f"未採点の結果待ちが {pending_eval_count:,} 件あります。押すと結果待ちレースIDだけを優先して取得し、予想との差分を自動採点します。")
                if st.button("結果待ちをまとめて確認・採点", key="archive_eval_score_pending_results", type="primary"):
                    _queue_operation_action("結果取得だけ")
            archive_detail_loaded = render_archive_detail_toggle(key="archive_detail_loaded")
            if archive_detail_loaded:
                archive_detail_frames = build_archive_detail_frames(
                    prediction_feedback_df,
                    build_bet_type_performance_table=build_bet_type_performance_table,
                    build_bet_type_feedback_rows=build_bet_type_feedback_rows,
                    build_condition_adjustment_performance_table=build_condition_adjustment_performance_table,
                    build_condition_segment_performance_table=build_condition_segment_performance_table,
                )
                bet_type_performance_df = archive_detail_frames.bet_type_performance
                bet_type_feedback_rows_df = archive_detail_frames.bet_type_feedback_rows
                condition_adjustment_performance_df = archive_detail_frames.condition_adjustment_performance
                condition_segment_performance_df = archive_detail_frames.condition_segment_performance
            else:
                st.caption("詳細集計は未読み込みです。必要な時だけONにすると、通常表示が軽くなります。")
            if not budget_basis_performance_df.empty:
                best_basis_row = budget_basis_performance_df.iloc[0]
                st.caption(
                    "好調な配分基準: "
                    f"{_to_text(best_basis_row.get('配分基準', '-'))} / "
                    f"{_to_text(best_basis_row.get('採用モード', '-'))} / "
                    f"単勝回収率 {_format_roi_metric(best_basis_row.get('単勝回収率'))}"
                )
                st.caption(
                    f"勝ち筋コメント: {_build_budget_basis_winning_comment(best_basis_row, prediction_feedback_trend_summary)}"
                )
            render_weight_change_table(
                latest_weight_change_df,
                latest_weight_meta=latest_weight_meta,
                build_weight_change_focus_tables=_build_weight_change_focus_tables,
                format_timestamp_text=_format_timestamp_text,
                with_one_based_index=_with_one_based_index,
            )
            render_bet_type_performance_table(
                bet_type_performance_df,
                format_rate_metric=_format_rate_metric,
                format_roi_metric=_format_roi_metric,
                with_one_based_index=_with_one_based_index,
            )
            render_budget_basis_performance_table(
                budget_basis_performance_df,
                trend_summary=prediction_feedback_trend_summary,
                build_winning_comment=_build_budget_basis_winning_comment,
                format_rate_metric=_format_rate_metric,
                format_roi_metric=_format_roi_metric,
                with_one_based_index=_with_one_based_index,
            )
            render_condition_performance_tables(
                condition_adjustment_performance_df,
                condition_segment_performance_df,
                format_rate_metric=_format_rate_metric,
                format_roi_metric=_format_roi_metric,
                with_one_based_index=_with_one_based_index,
            )
            if not llm_disagreement_performance_df.empty:
                _render_llm_hit_weekly_card(
                    llm_hit_weekly_summary,
                    trend_summary=prediction_feedback_trend_summary,
                    allow_apply=True,
                    button_prefix="archive_eval_llm_hit",
                )
                st.caption(_build_llm_disagreement_performance_comment(llm_disagreement_performance_df, llm_disagreement_summary))
                focus_comment = _build_llm_hit_focus_comment(llm_disagreement_performance_df)
                if focus_comment:
                    st.caption(focus_comment)
                _render_llm_disagreement_performance_charts(llm_disagreement_performance_df)
                render_llm_disagreement_performance_table(
                    llm_disagreement_performance_df,
                    format_rate_metric=_format_rate_metric,
                    format_signed_rate_metric=_format_signed_rate_metric,
                    with_one_based_index=_with_one_based_index,
                )
            render_bet_type_feedback_rows(
                bet_type_feedback_rows_df,
                bet_type_performance_df,
                result_status_text=_result_status_text,
                format_race_label=_format_race_label,
                format_date_text=_format_date_text,
                format_timestamp_text=_format_timestamp_text,
                format_hit_mark=_format_hit_mark,
                with_one_based_index=_with_one_based_index,
            )
            render_prediction_feedback_table(
                prediction_feedback_df,
                archive_detail_loaded=archive_detail_loaded,
                result_status_text=_result_status_text,
                format_race_label=_format_race_label,
                format_date_text=_format_date_text,
                format_timestamp_text=_format_timestamp_text,
                format_hit_mark=_format_hit_mark,
                format_condition_adjustment_count=_format_condition_adjustment_count,
                with_one_based_index=_with_one_based_index,
            )
        with archive_history_tab:
            st.caption("過去レース情報")
            if header_history_df is None or header_history_df.empty:
                st.caption("過去データがありません。")
            else:
                hm1, hm2, hm3 = st.columns(3)
                hm1.metric("履歴行数", f"{len(header_history_df):,}")
                hm2.metric("履歴レース数", f"{int(header_history_df['race_id'].nunique()) if 'race_id' in header_history_df.columns else 0:,}")
                hm3.metric("登録馬数", f"{int(header_history_df['horse'].nunique()) if 'horse' in header_history_df.columns else 0:,}")
                history_overview = _build_recent_history_overview(header_history_df, limit=12)
                if history_overview.empty:
                    st.caption("過去レースの集計情報はありません。")
                else:
                    st.dataframe(history_overview, width="stretch", height=250)
        with archive_course_tab:
            st.caption("競馬場情報")
            course_entries = header_entries_df if header_entries_df is not None else pd.DataFrame()
            course_history = header_history_df if header_history_df is not None else pd.DataFrame()
            course_overview = _build_racecourse_overview(course_entries, course_history)
            if course_overview.empty:
                st.caption("競馬場情報はまだ不足しています。")
            else:
                st.dataframe(course_overview, width="stretch", height=330)
    if st.session_state.get("open_archive_eval_after_rerun", False):
        _render_open_archive_eval_script()
        st.session_state["open_archive_eval_after_rerun"] = False
    if st.session_state.get("open_home_predictions_after_rerun", False):
        _render_open_home_predictions_script()
        st.session_state["open_home_predictions_after_rerun"] = False
    if st.session_state.get("open_budget_tab_after_rerun", False):
        _render_open_budget_tab_script()
        st.session_state["open_budget_tab_after_rerun"] = False
    if st.session_state.get("open_bets_tab_after_rerun", False):
        _render_open_bets_tab_script(_to_text(st.session_state.get("open_bets_target_bet_type", "")))
        st.session_state["open_bets_tab_after_rerun"] = False
        st.session_state.pop("open_bets_target_bet_type", None)

col_left, col_right = st.columns([1.05, 1.0], gap="large")
st.markdown("<div id='detail-predict-anchor'></div>", unsafe_allow_html=True)
if scroll_to_detail_after_rerun:
    _render_scroll_to_detail_anchor()

history_df: pd.DataFrame
entries_df: pd.DataFrame

with col_left:
    st.subheader("1) 過去成績データ")
    if data_mode == "サンプル":
        sample_races = st.slider("サンプル履歴レース数", min_value=80, max_value=600, value=280, step=20)
        history_df = generate_sample_history(seed=int(seed), n_races=int(sample_races))
        st.info("サンプル履歴を生成しています。実データを使う場合はサイドバーの読み込み方法を変更してください。")
    elif data_mode == "CSVアップロード":
        uploaded_history = st.file_uploader("履歴CSVをアップロード", type=["csv"], key="history")
        if uploaded_history is None:
            st.warning("履歴CSVをアップロードしてください")
            st.stop()
        history_df = pd.read_csv(uploaded_history)
    else:
        history_path = Path(st.session_state.get("auto_history_path", str(AUTO_HISTORY_PATH)))
        loaded = _read_csv_if_exists(history_path)
        if loaded is None:
            st.warning(f"自動取得履歴がありません: {history_path}")
            st.stop()
        history_df = loaded
        st.caption(f"自動取得履歴を使用: `{history_path}`")

    st.caption(f"履歴件数: {len(history_df):,} 行")
    if easy_operation_mode:
        st.caption("かんたん操作モードでは履歴の中身はたたんでいます。必要な時だけ開いて確認します。")
        with st.expander("履歴データを確認", expanded=False):
            st.dataframe(history_df.head(20), width="stretch")
    else:
        st.dataframe(history_df.head(20), width="stretch")

with col_right:
    st.subheader("2) 出走馬データ")
    if data_mode == "サンプル":
        field_size = st.slider("出走頭数", min_value=8, max_value=18, value=12, step=1)
        entries_df = generate_sample_entries(
            history_df,
            weather=weather,
            track_condition=track_condition,
            distance=int(distance),
            field_size=int(field_size),
            seed=int(seed) + 1,
        )
    elif data_mode == "CSVアップロード":
        uploaded_entries = st.file_uploader("出走馬CSVをアップロード", type=["csv"], key="entries")
        if uploaded_entries is None:
            st.warning("出走馬CSVをアップロードしてください")
            st.stop()
        entries_df = pd.read_csv(uploaded_entries)
    else:
        entries_path = Path(st.session_state.get("auto_entries_path", str(AUTO_ENTRIES_PATH)))
        loaded = _read_csv_if_exists(entries_path)
        if loaded is None:
            st.warning(f"自動取得の出走馬データがありません: {entries_path}")
            st.stop()
        selected_context = _extract_race_context(loaded, st.session_state.get("selected_detail_race_id", ""))
        if selected_context and "race_id" in loaded.columns:
            selected_race_id = _to_text(selected_context.get("race_id", ""))
            entries_df = loaded[loaded["race_id"].fillna("").astype(str).str.strip() == selected_race_id].copy()
            st.caption(
                f"自動取得出走馬データを使用: `{entries_path}` / 詳細予想対象: {_to_text(selected_context.get('label', '-'))}"
            )
        else:
            entries_df = loaded
            st.caption(f"自動取得出走馬データを使用: `{entries_path}`")

    st.caption(
        "`form_score` / `condition_score` / `paddock_score` / `weight_diff` / `odds_shift` を編集すると直前情報を反映できます"
    )
    if easy_operation_mode:
        st.caption("かんたん操作モードでは出走馬の編集欄もたたんでいます。必要な時だけ開いて直前情報を直せます。")
        with st.expander("出走馬データを確認 / 直前情報を修正", expanded=False):
            entries_df = st.data_editor(
                entries_df,
                width="stretch",
                num_rows="dynamic",
                height=430,
                key="entries_editor",
            )
    else:
        entries_df = st.data_editor(
            entries_df,
            width="stretch",
            num_rows="dynamic",
            height=430,
            key="entries_editor",
        )
    if {"horse", "jockey"}.issubset(entries_df.columns):
        with st.expander("出走馬一覧（馬名 / 騎手）", expanded=(data_mode == "自動取得データ" and not easy_operation_mode)):
            name_cols = [
                c
                for c in [
                    "race_id",
                    "venue",
                    "horse",
                    "jockey",
                    "trainer",
                    "weather",
                    "forecast_precip_prob",
                    "forecast_temp_max_c",
                    "odds",
                    "place_odds",
                ]
                if c in entries_df.columns
            ]
            if name_cols:
                horse_name_df = entries_df[name_cols].copy()
                if "forecast_precip_prob" in horse_name_df.columns:
                    horse_name_df["forecast_precip_prob"] = pd.to_numeric(
                        horse_name_df["forecast_precip_prob"], errors="coerce"
                    ).map(lambda x: "-" if pd.isna(x) else f"{float(x):.0f}%")
                if "forecast_temp_max_c" in horse_name_df.columns:
                    horse_name_df["forecast_temp_max_c"] = pd.to_numeric(
                        horse_name_df["forecast_temp_max_c"], errors="coerce"
                    ).map(lambda x: "-" if pd.isna(x) else f"{float(x):.1f}C")
                sort_cols = [c for c in ["race_id", "horse"] if c in horse_name_df.columns]
                if sort_cols:
                    horse_name_df = horse_name_df.sort_values(sort_cols)
                st.dataframe(horse_name_df.reset_index(drop=True), width="stretch", height=240)

_render_schema_help()

run_predict_manual = st.button("予想を実行", type="primary")
run_predict = bool(run_predict_manual or run_predict_from_auto)
if run_predict_from_auto:
    if run_predict_mode == "selected_race":
        st.caption("今週一覧から選んだレースで詳細予想を表示します。")
    else:
        st.caption("一括実行モード: 取得済みデータと最新重みで予想を開始します。")
if not run_predict:
    st.stop()

feature_weights = None
condition_adjustments = None
if weight_json is not None:
    try:
        payload = json.loads(weight_json.read().decode("utf-8"))
        feature_weights = _extract_feature_weights_from_payload(payload)
        condition_adjustments = _extract_condition_adjustments_from_payload(payload)
        if feature_weights is None:
            raise ValueError("JSON形式が不正です")
        st.caption("重みJSONを適用して予想します")
    except Exception as exc:
        st.error(f"重みJSONの読み込みに失敗しました: {exc}")
        st.stop()
else:
    auto_weights_path = Path(st.session_state.get("auto_weights_path", str(AUTO_WEIGHTS_PATH)))
    payload = read_weights_json(auto_weights_path)
    feature_weights = _extract_feature_weights_from_payload(payload)
    condition_adjustments = _extract_condition_adjustments_from_payload(payload)
    if feature_weights is not None:
        st.caption(f"自動学習済み重みを適用: `{auto_weights_path}`")
        feedback_meta = payload.get("feedback_learning", {}) if isinstance(payload, dict) else {}
        if isinstance(feedback_meta, dict) and feedback_meta.get("applied"):
            st.caption(
                "差分学習を反映: "
                f"{int(feedback_meta.get('rows', 0)):,} 行 / "
                f"上位予想サンプル {int(feedback_meta.get('top_rank_rows', 0)):,}"
            )
        if isinstance(condition_adjustments, dict) and bool(condition_adjustments.get("applied")):
            st.caption(
                "条件別補正を適用: "
                f"{int(condition_adjustments.get('segment_count', 0)):,} セグメント"
            )

race_id_value = ""
if "race_id" in entries_df.columns and len(entries_df["race_id"].dropna()) > 0:
    race_id_value = _to_text(entries_df["race_id"].dropna().iloc[0])
race_date_value = ""
if "race_date" in entries_df.columns and len(entries_df["race_date"].dropna()) > 0:
    race_date_value = _to_text(entries_df["race_date"].dropna().iloc[0])
elif "fetched_date" in entries_df.columns and len(entries_df["fetched_date"].dropna()) > 0:
    race_date_value = _to_text(entries_df["fetched_date"].dropna().iloc[0])
race_name_value = ""
if "race_name" in entries_df.columns and len(entries_df["race_name"].dropna()) > 0:
    race_name_value = _to_text(entries_df["race_name"].dropna().iloc[0])
venue_value = ""
if "venue" in entries_df.columns and len(entries_df["venue"].dropna()) > 0:
    venue_value = _to_text(entries_df["venue"].dropna().iloc[0])
race_grade_value = _infer_race_grade(race_name_value)

try:
    result = predict_race(
        history_df=history_df,
        entries_df=entries_df,
        weather=weather,
        track_condition=track_condition,
        distance=float(distance),
        simulations=int(simulations),
        seed=int(seed),
        budget=float(budget),
        bet_units=int(unit),
        feature_weights=feature_weights,
        condition_adjustments=condition_adjustments,
        venue=venue_value,
        race_grade=race_grade_value,
    )
except Exception as exc:
    st.error(f"予想処理でエラーが発生しました: {exc}")
    st.stop()

gate_lookup = _build_gate_lookup(entries_df)
result_learning_samples_df = _sync_result_learning_samples(history_df)
local_llm_memory_rows = _read_jsonl_if_exists(LOCAL_LLM_MEMORY_PATH, limit=120)
race_label_value = _format_race_label(race_id_value, venue_value, race_date_value, race_name_value)
style_tables = _build_prediction_style_tables(
    result,
    entries_df,
    race_id=race_id_value,
    race_date=race_date_value,
)
llm_odds_shift_alert_table = _build_odds_shift_alert_table(result, entries_df)
similar_history_table = _build_similar_history_table(
    history_df,
    venue=venue_value,
    weather=weather,
    track_condition=track_condition,
    distance=distance,
    limit=6,
)
similar_history_prompt_text = _similar_history_to_prompt_text(similar_history_table, limit=4)
result_sample_prompt_text = _build_result_sample_prompt_text(
    result_learning_samples_df,
    venue=venue_value,
    track_condition=track_condition,
    distance=distance,
    limit=4,
)
llm_memory_prompt_text = _build_llm_memory_prompt_text(
    local_llm_memory_rows,
    llm_style=local_llm_style,
    limit=3,
)
feedback_sample_prompt_text = _build_feedback_sample_prompt_text(
    prediction_feedback_df,
    venue=venue_value,
    track_condition=track_condition,
    distance=distance,
    race_grade=race_grade_value,
    limit=4,
)
reflection_feedback_prompt_text = _build_feedback_sample_prompt_text(
    prediction_feedback_df,
    venue=venue_value,
    track_condition=track_condition,
    distance=distance,
    race_grade=race_grade_value,
    misses_only=True,
    limit=5,
)
ticket_prompt_text = _build_prediction_ticket_prompt_text(_build_prediction_ticket(result, style_tables), limit=6)
condition_adjustment_prompt_text = _format_condition_adjustment_summary(_extract_condition_adjustment_labels(result))
odds_shift_alert_prompt_text = _build_odds_shift_alert_prompt_text(llm_odds_shift_alert_table, limit=3)
horse_feature_diff_prompt_text = _build_horse_feature_diff_prompt_text(result, limit=6)
analog_horse_table = _build_analog_horse_history_table(
    history_df,
    entries_df,
    result,
    venue=venue_value,
    track_condition=track_condition,
    distance=distance,
    limit_horses=5,
    analogs_per_horse=2,
)
analog_horse_prompt_text = _analog_horse_history_to_prompt_text(analog_horse_table, limit=8)
llm_disagreement_prompt_text = _build_llm_disagreement_prompt_text(
    weekly_prediction_source_df if isinstance(weekly_prediction_source_df, pd.DataFrame) else weekly_prediction_df,
    venue=venue_value,
    limit=5,
)
llm_disagreement_hit_prompt_text = _build_llm_disagreement_hit_prompt_text(
    prediction_feedback_df,
    venue=venue_value,
    limit=5,
)
analog_budget_bias_df = _build_analog_budget_bias_table(analog_horse_table)
selected_race_result_snapshot = _build_race_result_snapshot(history_df, race_id_value)
_sync_prediction_feature_archive(
    _build_prediction_feature_rows(
        result,
        race_id=race_id_value,
        race_date=race_date_value,
        race_name=race_name_value,
        race_grade=race_grade_value,
        venue=venue_value,
        weather=weather,
        track_condition=track_condition,
        distance=distance,
        field_size=len(entries_df),
    )
)

st.success("予想が完了しました")
_render_prediction_dashboard(
    result,
    style_tables,
    race_label=race_label_value,
    race_grade=race_grade_value,
    weather=weather,
    track_condition=track_condition,
    distance=distance,
    field_size=int(len(entries_df)),
    gate_lookup=gate_lookup,
)

condition_labels = _extract_condition_adjustment_labels(result)
top_pop_rank, top_odds = _popularity_rank_for_horse(entries_df, _to_text(result.horse_predictions.iloc[0].get("馬", "")))
summary_col1, summary_col2, summary_col3, summary_col4, summary_col5, summary_col6 = st.columns(6)
top_horse = result.horse_predictions.iloc[0]
summary_col1.metric("本命候補", _render_name_text_with_gate(top_horse["馬"], gate_lookup))
summary_col2.metric("騎手", str(top_horse.get("騎手", "-")))
summary_col3.metric("本命人気", _format_popularity_label(top_pop_rank))
summary_col4.metric("勝率", f"{float(top_horse['勝率']):.2%}")
summary_col5.metric("複勝率", f"{float(top_horse['複勝率']):.2%}")
danger_table = style_tables.get("危険人気", pd.DataFrame())
summary_col6.metric(
    "危険人気",
    _render_name_text_with_gate(danger_table.iloc[0]["馬"], gate_lookup)
    if (not danger_table.empty and "馬" in danger_table.columns)
    else "-",
)
if condition_labels:
    st.caption(
        "条件補正: "
        f"{_format_condition_adjustment_count(len(condition_labels))} / "
        f"{_format_condition_adjustment_summary(condition_labels)}"
    )
odds_shift_alert_table = _build_odds_shift_alert_table(result, entries_df)
if not odds_shift_alert_table.empty:
    st.caption("人気急変アラート")
    _render_odds_shift_alert_cards(odds_shift_alert_table, gate_lookup=gate_lookup, limit=3)

ticket_metric_cols = st.columns(4)
ticket_metric_cols[0].metric("単勝本線", _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("単勝", pd.DataFrame())), gate_lookup))
ticket_metric_cols[1].metric("複勝本線", _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("複勝", pd.DataFrame())), gate_lookup))
ticket_metric_cols[2].metric("ワイド本線", _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("ワイド", pd.DataFrame())), gate_lookup))
ticket_metric_cols[3].metric("三連単本線", _render_name_text_with_gate(_top_pick_text(result.bet_recommendations.get("三連単", pd.DataFrame())), gate_lookup))

_render_single_race_feedback_trend_focus(prediction_feedback_trend_summary)

selected_llm_alert_payload = _build_selected_llm_alert_payload(
    weekly_prediction_source_df if isinstance(weekly_prediction_source_df, pd.DataFrame) else pd.DataFrame(),
    race_id=race_id_value,
    performance_df=llm_disagreement_performance_df,
)
_render_selected_llm_alert_card(selected_llm_alert_payload)

strategy_header_cols = st.columns(4)
strategy_header_cols[0].metric("今日の型", feedback_trend_strategy_snapshot.get("style", "-"))
strategy_header_cols[1].metric("主軸券種", feedback_trend_strategy_snapshot.get("main_bets", "-"))
strategy_header_cols[2].metric("補助券種", feedback_trend_strategy_snapshot.get("sub_bets", "-"))
strategy_header_cols[3].metric("抑えたい券種", feedback_trend_strategy_snapshot.get("caution", "-"))

if not analog_budget_bias_df.empty:
    st.caption("今日の型ベース戦略")
    strategy_cols = st.columns(4)
    strategy_cols[0].metric("券種スタイル", analog_strategy_snapshot.get("style", "-"))
    strategy_cols[1].metric("攻め筋", analog_strategy_snapshot.get("main_bets", "-"))
    strategy_cols[2].metric("補助", analog_strategy_snapshot.get("sub_bets", "-"))
    strategy_cols[3].metric("抑えたい券種", analog_strategy_snapshot.get("caution", "-"))

view_horse = result.horse_predictions.copy()
popularity_rows: List[int | None] = []
for horse_name in view_horse["馬"].tolist():
    pop_rank, _ = _popularity_rank_for_horse(entries_df, horse_name)
    popularity_rows.append(pop_rank)
view_horse["人気"] = pd.Series(popularity_rows, index=view_horse.index, dtype="float")
view_horse = _decorate_frame_gate_columns(view_horse, gate_lookup, ["馬"])
for col in ("勝率", "複勝率", "horse_win_rate", "horse_place_rate", "weather_fit", "track_fit", "distance_fit"):
    if col in view_horse.columns:
        view_horse[col] = view_horse[col].map(lambda x: f"{float(x):.2%}")
for col in ("form_factor", "condition_factor", "market_factor"):
    if col in view_horse.columns:
        view_horse[col] = view_horse[col].map(lambda x: f"{float(x):.2f}")
for col in ("paddock_factor", "weight_diff_factor", "odds_shift_factor"):
    if col in view_horse.columns:
        view_horse[col] = view_horse[col].map(lambda x: f"{float(x):.2f}")
for col in ("理論単勝オッズ", "単勝オッズ", "複勝オッズ"):
    if col in view_horse.columns:
        view_horse[col] = view_horse[col].map(lambda x: "-" if pd.isna(x) else f"{float(x):.2f}")
for col in ("単勝期待値", "複勝期待値"):
    if col in view_horse.columns:
        view_horse[col] = view_horse[col].map(lambda x: "-" if pd.isna(x) else f"{float(x):+.2f}")
if "人気" in view_horse.columns:
    view_horse["人気"] = view_horse["人気"].map(_format_popularity_label)

formatted_tables = _format_probability_tables(result)
prediction_ticket_df = _build_prediction_ticket(result, style_tables)
for style_name, style_table in list(style_tables.items()):
    style_tables[style_name] = _decorate_frame_gate_columns(
        style_table,
        gate_lookup,
        ["馬"],
    )
formatted_tables = {
    name: _decorate_frame_gate_columns(table, gate_lookup, ["馬", "組み合わせ"])
    for name, table in formatted_tables.items()
}
prediction_ticket_df = _decorate_frame_gate_columns(
    prediction_ticket_df,
    gate_lookup,
    ["本線", "押さえ"],
)
prediction_mark_items = _build_prediction_mark_items(result, style_tables, gate_lookup=gate_lookup)
analog_strategy_snapshot = _build_analog_strategy_snapshot(analog_budget_bias_df)
feedback_trend_strategy_snapshot = _build_feedback_trend_strategy_snapshot(prediction_feedback_trend_summary)
mark_analog_profile_df = _build_mark_analog_profile_table(analog_horse_table, prediction_mark_items, result.budget_plan)
analog_adjusted_budget_plan_df = _build_analog_adjusted_budget_plan(
    result.budget_plan,
    analog_budget_bias_df,
    bet_units=int(unit),
)
trend_budget_source_df = analog_adjusted_budget_plan_df if not analog_adjusted_budget_plan_df.empty else result.budget_plan
trend_adjusted_budget_plan_df = _build_feedback_trend_adjusted_budget_plan(
    trend_budget_source_df,
    prediction_feedback_trend_summary,
    bet_units=int(unit),
)
budget_basis_catalog: Dict[str, Dict[str, Any]] = {
    "base": {
        "label": "ベース配分",
        "plan_df": result.budget_plan,
        "amount_col": "推奨金額",
    }
}
if not analog_adjusted_budget_plan_df.empty:
    budget_basis_catalog["analog"] = {
        "label": "類似個体補正",
        "plan_df": analog_adjusted_budget_plan_df,
        "amount_col": "型補正後金額",
    }
if not trend_adjusted_budget_plan_df.empty:
    budget_basis_catalog["trend"] = {
        "label": "今週傾向反映",
        "plan_df": trend_adjusted_budget_plan_df,
        "amount_col": "今週傾向後金額",
    }
default_budget_basis_key = "trend" if "trend" in budget_basis_catalog else "analog" if "analog" in budget_basis_catalog else "base"
persisted_auto_basis_enabled = bool(auto_improve_status.get("budget_basis_auto_enabled", True)) if isinstance(auto_improve_status, dict) else True
if "budget_basis_auto_enabled" not in st.session_state:
    st.session_state["budget_basis_auto_enabled"] = persisted_auto_basis_enabled
selected_budget_basis_auto_mode = bool(st.session_state.get("budget_basis_auto_enabled", persisted_auto_basis_enabled))
budget_basis_decision = _build_budget_basis_decision_snapshot(
    prediction_feedback_trend_summary,
    budget_basis_catalog.keys(),
    performance_df=budget_basis_performance_df,
    agent_hint=auto_agent_basis_hint,
    llm_hit_summary=llm_hit_weekly_summary,
)
auto_budget_basis_key = _to_text(budget_basis_decision.get("final_key", "base")) or "base"
auto_budget_basis_reason = _to_text(budget_basis_decision.get("final_reason", "")) or "現在の標準配分を使います。"
if selected_budget_basis_auto_mode:
    selected_budget_basis_key = auto_budget_basis_key if auto_budget_basis_key in budget_basis_catalog else default_budget_basis_key
    st.session_state["budget_basis_choice"] = selected_budget_basis_key
else:
    selected_budget_basis_key = _to_text(st.session_state.get("budget_basis_choice", default_budget_basis_key))
    if selected_budget_basis_key not in budget_basis_catalog:
        selected_budget_basis_key = default_budget_basis_key
    st.session_state["budget_basis_choice"] = selected_budget_basis_key
selected_budget_basis = budget_basis_catalog[selected_budget_basis_key]
standard_budget_plan_df = selected_budget_basis["plan_df"]
standard_budget_amount_col = _to_text(selected_budget_basis.get("amount_col", "推奨金額")) or "推奨金額"
standard_budget_basis_label = _to_text(selected_budget_basis.get("label", "ベース配分")) or "ベース配分"
standard_budget_focus_cards_df = _prepare_budget_focus_cards_df(
    standard_budget_plan_df,
    amount_col=standard_budget_amount_col,
)
standard_ticket_df = _apply_budget_amounts_to_prediction_ticket(
    prediction_ticket_df,
    standard_budget_plan_df,
    amount_col=standard_budget_amount_col,
    basis_label=standard_budget_basis_label,
)
print_sheet_html = _build_print_sheet_html(
    race_label=race_label_value,
    race_grade=race_grade_value,
    race_date=race_date_value,
    venue=venue_value,
    race_name=race_name_value,
    weather=weather,
    track_condition=track_condition,
    distance=distance,
    field_size=int(len(entries_df)),
    mark_items=prediction_mark_items,
    ticket_df=standard_ticket_df,
)
print_sheet_document = _build_print_sheet_document(print_sheet_html, title=race_label_value or "KEIBA Print Sheet")
style_metric_labels = ["データ本命", "大穴", "危険人気", "スピリチュアル"]
preferred_cols = [
    "馬番",
    "馬",
    "人気",
    "騎手",
    "調教師",
    "勝率",
    "複勝率",
    "単勝オッズ",
    "複勝オッズ",
    "単勝期待値",
    "複勝期待値",
]
lead_cols = [c for c in preferred_cols if c in view_horse.columns]
trail_cols = [c for c in view_horse.columns if c not in lead_cols]
view_horse = view_horse[lead_cols + trail_cols]

if easy_operation_mode:
    tab_pred, tab_styles, tab_bets, tab_budget, tab_more = st.tabs(
        ["馬ごとの予測", "3本立て予想", "買い目提案", "予算配分", "詳細"]
    )
else:
    tab_pred, tab_styles, tab_history, tab_llm, tab_chart, tab_bets, tab_budget = st.tabs(
        ["馬ごとの予測", "3本立て予想", "過去類似", "ローカルLLM", "勝率チャート", "買い目提案", "予算配分"]
    )
with tab_pred:
    st.dataframe(view_horse, width="stretch", height=420)

with tab_styles:
    st.caption("`データ本命` は確率モデル、`大穴` は人気薄妙味、`危険人気` は市場ほど信用しづらい人気馬、`スピリチュアル` は数秘系の遊び予想です。")
    if not danger_table.empty:
        single_danger_frame = pd.DataFrame(
            [
                {
                    "レース": race_label_value or "-",
                    "格付": race_grade_value,
                    "危険人気馬": str(danger_table.iloc[0].get("馬", "-")),
                    "危険人気": str(danger_table.iloc[0].get("人気", "-")),
                    "本命馬": str(style_tables.get("データ本命", pd.DataFrame()).iloc[0].get("馬", "-")) if not style_tables.get("データ本命", pd.DataFrame()).empty else "-",
                    "大穴候補": str(style_tables.get("大穴", pd.DataFrame()).iloc[0].get("馬", "-")) if not style_tables.get("大穴", pd.DataFrame()).empty else "-",
                    "勝率": f"{float(top_horse['勝率']):.2%}",
                    "複勝率": f"{float(top_horse['複勝率']):.2%}",
                }
            ]
        )
        _render_danger_cards(single_danger_frame, limit=1)
    style_tabs = st.tabs(["データ本命", "大穴", "危険人気", "スピリチュアル"])
    for idx, style_name in enumerate(style_metric_labels):
        with style_tabs[idx]:
            table = style_tables.get(style_name, pd.DataFrame())
            if table.empty:
                st.caption("算出できませんでした。")
            else:
                st.dataframe(table, width="stretch", height=260)

if easy_operation_mode:
    with tab_more:
        st.caption("詳しい分析はここにまとめています。必要な時だけ開けば大丈夫です。")
        detail_cols = st.columns(3)
        detail_cols[0].metric("まず見る", "過去類似", f"{len(similar_history_table):,}件")
        detail_cols[1].metric("次に見る", "ローカルLLM", local_llm_mode if local_llm_mode != "off" else "OFF")
        detail_cols[2].metric("最後に見る", "勝率チャート", f"{len(result.horse_predictions):,}頭")
        with st.expander("過去類似", expanded=False):
            st.caption("開催・馬場・距離が近い過去レースを優先表示しています。")
            hist_info_cols = st.columns(3)
            hist_info_cols[0].metric("結果サンプル数", f"{len(result_learning_samples_df):,}")
            hist_info_cols[1].metric("近似結果候補", f"{len(similar_history_table):,}")
            hist_info_cols[2].metric("取得済み結果", "あり" if not selected_race_result_snapshot.empty else "未取得")
            if not selected_race_result_snapshot.empty:
                st.caption("選択レースの取得済み結果")
                st.dataframe(_with_one_based_index(selected_race_result_snapshot), width="stretch", height=210)
            if similar_history_table.empty:
                st.caption("近い条件の過去レースはまだ見つかりません。")
            else:
                st.dataframe(similar_history_table, width="stretch", height=260)
            if not result_learning_samples_df.empty:
                with st.expander("ローカル結果サンプル", expanded=False):
                    sample_preview = result_learning_samples_df.head(12).copy()
                    if "distance" in sample_preview.columns:
                        sample_preview["distance"] = pd.to_numeric(sample_preview["distance"], errors="coerce").map(
                            lambda x: "-" if pd.isna(x) else f"{int(float(x))}m"
                        )
                    sample_preview = sample_preview.rename(
                        columns={
                            "race_date": "日付",
                            "venue": "開催",
                            "weather": "天気",
                            "track_condition": "馬場",
                            "distance": "距離",
                            "field_size": "頭数",
                            "winner": "1着",
                            "second": "2着",
                            "third": "3着",
                        }
                    )
                    preview_cols = [c for c in ["日付", "開催", "天気", "馬場", "距離", "頭数", "1着", "2着", "3着", "race_id"] if c in sample_preview.columns]
                    st.dataframe(_with_one_based_index(sample_preview[preview_cols]), width="stretch", height=260)
        with st.expander("ローカルLLM", expanded=False):
            st.caption("ローカルLLMは `Ollama` 前提です。万馬券を保証するものではなく、穴目線の整理補助として使います。")
            llm_text = _to_text(st.session_state.get("keiba_local_llm_comment", ""))
            analysis_text = _to_text(st.session_state.get("keiba_local_llm_analysis", ""))
            llm_summary_lines = [line.strip() for line in llm_text.splitlines() if line.strip()]
            llm_summary_preview = "\n".join(llm_summary_lines[:6])
            llm_focus_cards = _build_local_llm_focus_cards(llm_text)
            top_llm_cols = st.columns(4)
            top_llm_cols[0].metric("レース", race_label_value or "-")
            top_llm_cols[1].metric("モード", local_llm_mode)
            top_llm_cols[2].metric("スタイル", local_llm_style)
            top_llm_cols[3].metric("保存メモ", f"{len(local_llm_memory_rows):,}")
            if llm_text:
                st.caption("最新のLLM要約")
                llm_focus_html = _render_local_llm_focus_cards(llm_focus_cards)
                if llm_focus_html:
                    st.markdown(llm_focus_html, unsafe_allow_html=True)
                if llm_summary_preview:
                    st.caption(llm_summary_preview)
            else:
                st.caption("まだLLM要約はありません。必要な時だけ下の詳細から生成できます。")
            with st.expander("LLMの詳細を見る", expanded=False):
                detail_llm_cols = st.columns(4)
                detail_llm_cols[0].metric("格付け", race_grade_value)
                detail_llm_cols[1].metric("推論", local_llm_reasoning_mode)
                detail_llm_cols[2].metric("モデル", local_llm_model or LOCAL_LLM_MODEL_DEFAULT)
                detail_llm_cols[3].metric("結果サンプル", f"{len(result_learning_samples_df):,}")
                if local_llm_mode == "off":
                    st.caption("サイドバーの `ローカルLLM（任意）` で `auto` か `ollama` を選ぶと使えます。")
                else:
                    if local_llm_reasoning_mode == "反省":
                        st.caption("反省モードは、外れたレースの実結果フィードバックを優先して読みます。")
                    if st.button("ローカルLLMで予想メモ生成", key="local_llm_keiba_generate"):
                        try:
                            prompt = _build_local_llm_keiba_prompt(
                                race_label=race_label_value or "-",
                                race_grade=race_grade_value,
                                weather=weather,
                                track_condition=track_condition,
                                distance=distance,
                                llm_style=local_llm_style,
                                top_table=style_tables.get("データ本命", pd.DataFrame()),
                                longshot_table=style_tables.get("大穴", pd.DataFrame()),
                                risk_table=style_tables.get("危険人気", pd.DataFrame()),
                                spiritual_table=style_tables.get("スピリチュアル", pd.DataFrame()),
                                similar_history_text=similar_history_prompt_text,
                                result_sample_text=result_sample_prompt_text,
                                memory_sample_text=llm_memory_prompt_text,
                                feedback_sample_text=feedback_sample_text,
                                prediction_ticket_text=ticket_prompt_text,
                                odds_shift_alert_text=odds_shift_alert_prompt_text,
                                condition_adjustment_text=condition_adjustment_prompt_text,
                                feature_diff_text=horse_feature_diff_prompt_text,
                                analog_horse_text=analog_horse_prompt_text,
                                reflection_feedback_text=reflection_feedback_prompt_text,
                                llm_disagreement_text=llm_disagreement_prompt_text,
                                llm_disagreement_hit_text=llm_disagreement_hit_prompt_text,
                                reasoning_mode=local_llm_reasoning_mode,
                            )
                            with st.spinner("ローカルLLMで万馬券メモを生成中..."):
                                llm_text, analysis_text = _run_local_llm_keiba_enhanced_comment(
                                    base_url=local_llm_base_url,
                                    model=local_llm_model,
                                    timeout_sec=int(local_llm_timeout_sec),
                                    prompt=prompt,
                                    temperature={"保守": 0.2, "バランス": 0.35, "万馬券狙い": 0.55}.get(local_llm_style, 0.35),
                                    reasoning_mode=local_llm_reasoning_mode,
                                )
                            st.session_state["keiba_local_llm_comment"] = llm_text
                            st.session_state["keiba_local_llm_analysis"] = analysis_text
                            _append_local_llm_memory_sample(
                                {
                                    "saved_at": datetime.now().isoformat(timespec="seconds"),
                                    "race_label": race_label_value or "-",
                                    "race_grade": race_grade_value,
                                    "llm_style": local_llm_style,
                                    "reasoning_mode": local_llm_reasoning_mode,
                                    "weather": _to_text(weather),
                                    "track_condition": _to_text(track_condition),
                                    "distance": int(float(distance)) if pd.notna(pd.to_numeric(distance, errors="coerce")) else _to_text(distance),
                                    "summary": llm_text.splitlines()[0] if llm_text else "-",
                                }
                            )
                            local_llm_memory_rows = _read_jsonl_if_exists(LOCAL_LLM_MEMORY_PATH, limit=120)
                            st.rerun()
                        except Exception as exc:
                            st.error(f"ローカルLLM生成に失敗しました: {exc}")
                    st.caption("ローカル結果サンプル、実結果フィードバック、今週のLLM別軸レース、LLM別軸ヒット、予想票、条件補正、人気急変、馬ごとの差分、類似個体、保存済みメモをまとめてプロンプトに入れています。")
                    if llm_text:
                        st.code(llm_text, language=None)
                        if analysis_text:
                            analysis_title = "反省メモ（外れレース優先）" if local_llm_reasoning_mode == "反省" else "中間分析（自己点検用）"
                            with st.expander(analysis_title, expanded=False):
                                st.code(analysis_text, language=None)
                    with st.expander("馬ごとの特徴量差分（LLM入力）", expanded=False):
                        st.code(horse_feature_diff_prompt_text or "- 差分なし", language=None)
                    with st.expander("今週のLLM別軸レース要約", expanded=False):
                        st.code(llm_disagreement_prompt_text or "- 別軸レースなし", language=None)
                    with st.expander("LLM別軸ヒット要約", expanded=False):
                        st.code(llm_disagreement_hit_prompt_text or "- 別軸ヒットなし", language=None)
                    if not analog_horse_table.empty:
                        analog_type_summary = _build_analog_type_summary(analog_horse_table)
                        if not analog_type_summary.empty:
                            type_cols = st.columns(max(1, len(analog_type_summary)))
                            for idx, (_, summary_row) in enumerate(analog_type_summary.iterrows()):
                                type_cols[idx].metric(_to_text(summary_row.get("参照型", "-")), f"{int(summary_row.get('件数', 0))}件")
                            analog_tendency_df = _build_analog_betting_tendency_table(analog_horse_table)
                            if not analog_tendency_df.empty:
                                st.caption("類似個体の型ごとの買い方傾向")
                                st.dataframe(analog_tendency_df, width="stretch", height=180, hide_index=True)
                        analog_view = analog_horse_table.copy()
                        analog_view["類似度"] = pd.to_numeric(analog_view["類似度"], errors="coerce").map(
                            lambda value: "-" if pd.isna(value) else f"{float(value):.2f}"
                        )
                        with st.expander("類似個体（名前が違っても近い参照）", expanded=False):
                            st.dataframe(analog_view, width="stretch", height=260)
        with st.expander("勝率チャート", expanded=False):
            chart_df = result.horse_predictions[["馬", "勝率", "複勝率"]].copy()
            chart_df["馬"] = chart_df["馬"].map(lambda value: _render_name_text_with_gate(value, gate_lookup))
            chart_df = chart_df.set_index("馬")
            st.bar_chart(chart_df)
else:
    with tab_history:
        st.caption("開催・馬場・距離が近い過去レースを優先表示しています。")
        hist_info_cols = st.columns(3)
        hist_info_cols[0].metric("結果サンプル数", f"{len(result_learning_samples_df):,}")
        hist_info_cols[1].metric("近似結果候補", f"{len(similar_history_table):,}")
        hist_info_cols[2].metric("取得済み結果", "あり" if not selected_race_result_snapshot.empty else "未取得")
        if not selected_race_result_snapshot.empty:
            st.caption("選択レースの取得済み結果")
            st.dataframe(_with_one_based_index(selected_race_result_snapshot), width="stretch", height=210)
        if similar_history_table.empty:
            st.caption("近い条件の過去レースはまだ見つかりません。")
        else:
            st.dataframe(similar_history_table, width="stretch", height=260)
        if not result_learning_samples_df.empty:
            with st.expander("ローカル結果サンプル", expanded=False):
                sample_preview = result_learning_samples_df.head(12).copy()
                if "distance" in sample_preview.columns:
                    sample_preview["distance"] = pd.to_numeric(sample_preview["distance"], errors="coerce").map(
                        lambda x: "-" if pd.isna(x) else f"{int(float(x))}m"
                    )
                sample_preview = sample_preview.rename(
                    columns={
                        "race_date": "日付",
                        "venue": "開催",
                        "weather": "天気",
                        "track_condition": "馬場",
                        "distance": "距離",
                        "field_size": "頭数",
                        "winner": "1着",
                        "second": "2着",
                        "third": "3着",
                    }
                )
                preview_cols = [c for c in ["日付", "開催", "天気", "馬場", "距離", "頭数", "1着", "2着", "3着", "race_id"] if c in sample_preview.columns]
                st.dataframe(_with_one_based_index(sample_preview[preview_cols]), width="stretch", height=260)

    with tab_llm:
        st.caption("ローカルLLMは `Ollama` 前提です。万馬券を保証するものではなく、穴目線の整理補助として使います。")
        llm_cols = st.columns(8)
        llm_cols[0].metric("レース", race_label_value or "-")
        llm_cols[1].metric("格付け", race_grade_value)
        llm_cols[2].metric("モード", local_llm_mode)
        llm_cols[3].metric("スタイル", local_llm_style)
        llm_cols[4].metric("推論", local_llm_reasoning_mode)
        llm_cols[5].metric("モデル", local_llm_model or LOCAL_LLM_MODEL_DEFAULT)
        llm_cols[6].metric("結果サンプル", f"{len(result_learning_samples_df):,}")
        llm_cols[7].metric("保存メモ", f"{len(local_llm_memory_rows):,}")
        if local_llm_mode == "off":
            st.caption("サイドバーの `ローカルLLM（任意）` で `auto` か `ollama` を選ぶと使えます。")
        else:
            if local_llm_reasoning_mode == "反省":
                st.caption("反省モードは、外れたレースの実結果フィードバックを優先して読みます。")
            with st.expander("馬ごとの特徴量差分（LLM入力）", expanded=False):
                st.code(horse_feature_diff_prompt_text or "- 差分なし", language=None)
            with st.expander("今週のLLM別軸レース要約", expanded=False):
                st.code(llm_disagreement_prompt_text or "- 別軸レースなし", language=None)
            with st.expander("LLM別軸ヒット要約", expanded=False):
                st.code(llm_disagreement_hit_prompt_text or "- 別軸ヒットなし", language=None)
            if not analog_horse_table.empty:
                analog_type_summary = _build_analog_type_summary(analog_horse_table)
                if not analog_type_summary.empty:
                    type_cols = st.columns(max(1, len(analog_type_summary)))
                    for idx, (_, summary_row) in enumerate(analog_type_summary.iterrows()):
                        type_cols[idx].metric(_to_text(summary_row.get("参照型", "-")), f"{int(summary_row.get('件数', 0))}件")
                    analog_tendency_df = _build_analog_betting_tendency_table(analog_horse_table)
                    if not analog_tendency_df.empty:
                        st.caption("類似個体の型ごとの買い方傾向")
                        st.dataframe(analog_tendency_df, width="stretch", height=180, hide_index=True)
                analog_view = analog_horse_table.copy()
                analog_view["類似度"] = pd.to_numeric(analog_view["類似度"], errors="coerce").map(
                    lambda value: "-" if pd.isna(value) else f"{float(value):.2f}"
                )
                with st.expander("類似個体（名前が違っても近い参照）", expanded=False):
                    st.dataframe(analog_view, width="stretch", height=260)
            if st.button("ローカルLLMで予想メモ生成", key="local_llm_keiba_generate"):
                try:
                    prompt = _build_local_llm_keiba_prompt(
                        race_label=race_label_value or "-",
                        race_grade=race_grade_value,
                        weather=weather,
                        track_condition=track_condition,
                        distance=distance,
                        llm_style=local_llm_style,
                        top_table=style_tables.get("データ本命", pd.DataFrame()),
                        longshot_table=style_tables.get("大穴", pd.DataFrame()),
                        risk_table=style_tables.get("危険人気", pd.DataFrame()),
                        spiritual_table=style_tables.get("スピリチュアル", pd.DataFrame()),
                        similar_history_text=similar_history_prompt_text,
                        result_sample_text=result_sample_prompt_text,
                        memory_sample_text=llm_memory_prompt_text,
                        feedback_sample_text=feedback_sample_text,
                        prediction_ticket_text=ticket_prompt_text,
                        odds_shift_alert_text=odds_shift_alert_prompt_text,
                        condition_adjustment_text=condition_adjustment_prompt_text,
                        feature_diff_text=horse_feature_diff_prompt_text,
                        analog_horse_text=analog_horse_prompt_text,
                        reflection_feedback_text=reflection_feedback_prompt_text,
                        llm_disagreement_text=llm_disagreement_prompt_text,
                        llm_disagreement_hit_text=llm_disagreement_hit_prompt_text,
                        reasoning_mode=local_llm_reasoning_mode,
                    )
                    with st.spinner("ローカルLLMで万馬券メモを生成中..."):
                        llm_text, analysis_text = _run_local_llm_keiba_enhanced_comment(
                            base_url=local_llm_base_url,
                            model=local_llm_model,
                            timeout_sec=int(local_llm_timeout_sec),
                            prompt=prompt,
                            temperature={"保守": 0.2, "バランス": 0.35, "万馬券狙い": 0.55}.get(local_llm_style, 0.35),
                            reasoning_mode=local_llm_reasoning_mode,
                        )
                    st.session_state["keiba_local_llm_comment"] = llm_text
                    st.session_state["keiba_local_llm_analysis"] = analysis_text
                    _append_local_llm_memory_sample(
                        {
                            "saved_at": datetime.now().isoformat(timespec="seconds"),
                            "race_label": race_label_value or "-",
                            "race_grade": race_grade_value,
                            "llm_style": local_llm_style,
                            "reasoning_mode": local_llm_reasoning_mode,
                            "weather": _to_text(weather),
                            "track_condition": _to_text(track_condition),
                            "distance": int(float(distance)) if pd.notna(pd.to_numeric(distance, errors="coerce")) else _to_text(distance),
                            "summary": llm_text.splitlines()[0] if llm_text else "-",
                        }
                    )
                    local_llm_memory_rows = _read_jsonl_if_exists(LOCAL_LLM_MEMORY_PATH, limit=120)
                except Exception as exc:
                    st.error(f"ローカルLLM生成に失敗しました: {exc}")
            st.caption("ローカル結果サンプル、実結果フィードバック、今週のLLM別軸レース、LLM別軸ヒット、予想票、条件補正、人気急変、馬ごとの差分、類似個体、保存済みメモをまとめてプロンプトに入れています。")
            llm_text = _to_text(st.session_state.get("keiba_local_llm_comment", ""))
            analysis_text = _to_text(st.session_state.get("keiba_local_llm_analysis", ""))
            if llm_text:
                st.code(llm_text, language=None)
                if analysis_text:
                    analysis_title = "反省メモ（外れレース優先）" if local_llm_reasoning_mode == "反省" else "中間分析（自己点検用）"
                    with st.expander(analysis_title, expanded=False):
                        st.code(analysis_text, language=None)
            else:
                st.caption("未生成です。`ollama serve` の後にボタンを押してください。")

    with tab_chart:
        chart_df = result.horse_predictions[["馬", "勝率", "複勝率"]].copy()
        chart_df["馬"] = chart_df["馬"].map(lambda value: _render_name_text_with_gate(value, gate_lookup))
        chart_df = chart_df.set_index("馬")
        st.bar_chart(chart_df)

with tab_bets:
    st.markdown("<div id='bet-plan-anchor'></div>", unsafe_allow_html=True)
    llm_mode_bucket = ""
    if selected_llm_alert_payload:
        llm_mode_bucket = _to_text(selected_llm_alert_payload.get("bucket", "")) or "見方差"
        llm_mode_class = _llm_bucket_style_class(llm_mode_bucket)
        st.caption("LLM別軸モード")
        st.markdown(
            """
<div class="memo-card llm-priority-card {bucket_class}" style="margin:0.2rem 0 0.85rem;">
  <div class="memo-chip {bucket_class}">別軸モード</div>
  <div class="memo-title">{bucket}</div>
  <div class="memo-line"><strong>このレースで向く買い方:</strong> {memo}</div>
  {bet_badges}
</div>
""".format(
                bucket_class=html_escape(llm_mode_class),
                bucket=html_escape(llm_mode_bucket),
                memo=html_escape(_build_llm_bucket_bet_memo(llm_mode_bucket)),
                bet_badges=_render_llm_bucket_bet_badges_html(llm_mode_bucket),
            ),
            unsafe_allow_html=True,
        )
    highlighted_bet_type = _to_text(st.session_state.pop("highlight_bet_type_name", ""))
    highlighted_bet_amount_preview = st.session_state.pop("highlight_bet_amount_preview", None)
    highlighted_bet_source = _to_text(st.session_state.pop("highlight_bet_source_name", ""))
    if not highlighted_bet_source and highlighted_bet_type:
        highlighted_bet_source = "manual"
    if not highlighted_bet_type and llm_mode_bucket and not standard_ticket_df.empty and "券種" in standard_ticket_df.columns:
        available_bet_types = standard_ticket_df["券種"].map(_to_text).tolist()
        recommended_bet_types, _ = _build_llm_bucket_bet_guidance(llm_mode_bucket)
        highlighted_bet_type = next(
            (bet_type for bet_type in recommended_bet_types if _to_text(bet_type) in available_bet_types),
            "",
        )
        if highlighted_bet_type:
            highlighted_bet_source = "llm_auto"
    if highlighted_bet_source == "llm_auto":
        highlight_chip_text = "LLM別軸で先頭表示"
    elif highlighted_bet_source == "history":
        highlight_chip_text = "履歴から確認中"
    else:
        highlight_chip_text = "おすすめから移動"
    bet_view_ticket_df = _reorder_ticket_df_by_bet_type(standard_ticket_df, highlighted_bet_type)
    bet_view_tables = _reorder_formatted_tables(formatted_tables, highlighted_bet_type)
    if highlighted_bet_type:
        if highlighted_bet_source == "llm_auto":
            st.info(f"LLM別軸モードに合わせて `{highlighted_bet_type}` を先頭表示しています。")
        elif highlighted_bet_source == "history":
            st.success(f"`{highlighted_bet_type}` を履歴のおすすめ券種から開きました。強めにハイライトしています。")
        else:
            st.success(f"`{highlighted_bet_type}` を開きました。下の同名セクションをハイライトしています。")
        highlighted_focus_html = _build_highlighted_bet_focus_html(
            standard_ticket_df,
            highlighted_bet_type,
            amount_preview=highlighted_bet_amount_preview,
            highlight_source=highlighted_bet_source,
        )
        if highlighted_focus_html:
            st.markdown(highlighted_focus_html, unsafe_allow_html=True)
    st.caption("予想票")
    if not standard_budget_focus_cards_df.empty:
        basis_mode_suffix = "（半自動）" if selected_budget_basis_auto_mode else "（手動）"
        st.caption(f"現在の標準配分: {standard_budget_basis_label} {basis_mode_suffix}")
        _render_budget_bucket_cards(standard_budget_focus_cards_df)
    if not mark_analog_profile_df.empty:
        mark_cards_html = _render_mark_bet_cards_html(mark_analog_profile_df)
        if mark_cards_html:
            st.caption("印ごとの推奨券種")
            st.markdown(mark_cards_html, unsafe_allow_html=True)
        st.caption("印ごとの類似個体タイプ")
        st.dataframe(mark_analog_profile_df, width="stretch", height=180, hide_index=True)
    if not analog_budget_bias_df.empty:
        st.caption("類似個体の型から見た券種ごとの寄せ方")
        analog_bias_view = analog_budget_bias_df.copy()
        analog_bias_view["型補正倍率"] = pd.to_numeric(analog_bias_view["型補正倍率"], errors="coerce").map(
            lambda value: "-" if pd.isna(value) else f"{float(value):.2f}x"
        )
        st.dataframe(analog_bias_view, width="stretch", height=220, hide_index=True)
    st.caption("券種ごとの買い方一覧")
    amount_focus_html = _build_ticket_amount_focus_html(standard_ticket_df)
    if amount_focus_html:
        st.caption("本線 / 押さえ / 穴 の推奨金額")
        st.markdown(amount_focus_html, unsafe_allow_html=True)
    st.caption("馬券フォーマット")
    _render_bet_slip_cards(standard_ticket_df)
    st.caption("印刷用まとめ")
    st.markdown(print_sheet_html, unsafe_allow_html=True)
    st.download_button(
        "印刷用HTMLを保存",
        data=print_sheet_document.encode("utf-8"),
        file_name="keiba_print_sheet.html",
        mime="text/html",
        key="download_print_sheet_html",
    )
    render_prediction_ticket_table(
        standard_ticket_df,
        bet_view_ticket_df,
        highlighted_bet_type=highlighted_bet_type,
        highlighted_bet_source=highlighted_bet_source,
        with_one_based_index=_with_one_based_index,
        style_prediction_ticket_table=lambda frame, bet_type, source: _style_prediction_ticket_table(
            frame,
            bet_type,
            highlight_source=source,
        ),
    )
    st.caption("券種ピック")
    _render_bet_pick_cards(
        bet_view_tables,
        highlighted_bet_type,
        highlight_chip_text=highlight_chip_text,
        highlight_source=highlighted_bet_source,
    )
    render_bet_candidate_tables(
        bet_view_tables,
        highlighted_bet_type=highlighted_bet_type,
        highlighted_bet_source=highlighted_bet_source,
        bet_type_anchor_id=_bet_type_anchor_id,
        to_text=_to_text,
    )

with tab_budget:
    st.markdown("<div id='budget-plan-anchor'></div>", unsafe_allow_html=True)
    if result.budget_plan.empty:
        st.caption("予算配分案を作成できませんでした。推奨度が十分な買い目がない可能性があります。")
    else:
        budget_action_cols = st.columns([1.1, 1, 1, 1, 1], gap="small")
        budget_action_cols[0].metric("現在の標準配分", standard_budget_basis_label, "半自動ON" if selected_budget_basis_auto_mode else "手動")
        if budget_action_cols[1].button(
            "今週傾向を標準に採用",
            key="budget_basis_apply_trend",
            disabled=("trend" not in budget_basis_catalog or selected_budget_basis_key == "trend"),
            width="stretch",
        ):
            st.session_state["budget_basis_auto_enabled"] = False
            st.session_state["budget_basis_choice"] = "trend"
            _persist_budget_basis_preference(auto_enabled=False, manual_choice="trend")
            _set_ui_notice(
                "標準配分を今週傾向反映に切り替えました",
                title="今週傾向を標準採用中",
                chip="標準配分 更新",
                detail="買い目提案 / 予想票CSV / 印刷用まとめも、今週傾向反映の配分にそろえました。",
            )
            st.rerun()
        if budget_action_cols[2].button(
            "類似個体を標準に採用",
            key="budget_basis_apply_analog",
            disabled=("analog" not in budget_basis_catalog or selected_budget_basis_key == "analog"),
            width="stretch",
        ):
            st.session_state["budget_basis_auto_enabled"] = False
            st.session_state["budget_basis_choice"] = "analog"
            _persist_budget_basis_preference(auto_enabled=False, manual_choice="analog")
            _set_ui_notice(
                "標準配分を類似個体補正に切り替えました",
                title="類似個体補正を標準採用中",
                chip="標準配分 更新",
                detail="買い目提案 / 予想票CSV / 印刷用まとめも、類似個体補正の配分にそろえました。",
            )
            st.rerun()
        if budget_action_cols[3].button(
            "ベースに戻す",
            key="budget_basis_apply_base",
            disabled=(selected_budget_basis_key == "base"),
            width="stretch",
        ):
            st.session_state["budget_basis_auto_enabled"] = False
            st.session_state["budget_basis_choice"] = "base"
            _persist_budget_basis_preference(auto_enabled=False, manual_choice="base")
            _set_ui_notice(
                "標準配分をベース配分に戻しました",
                title="ベース配分を標準採用中",
                chip="標準配分 更新",
                detail="買い目提案 / 予想票CSV / 印刷用まとめも、ベース配分に戻しています。",
                level="info",
            )
            st.rerun()
        if budget_action_cols[4].button(
            "半自動に戻す",
            key="budget_basis_apply_auto",
            disabled=selected_budget_basis_auto_mode,
            width="stretch",
        ):
            st.session_state["budget_basis_auto_enabled"] = True
            _persist_budget_basis_preference(auto_enabled=True, auto_choice=auto_budget_basis_key)
            notice_payload = _build_budget_basis_notice_payload(auto_budget_basis_key, prediction_feedback_trend_summary)
            _set_ui_notice(
                f"標準配分を半自動に戻しました: {auto_budget_basis_reason}",
                title=notice_payload["title"],
                chip="半自動ON",
                detail=notice_payload["detail"],
                fit_case=notice_payload.get("fit_case", ""),
                unfit_case=notice_payload.get("unfit_case", ""),
                level=notice_payload["level"],
            )
            st.rerun()
        if selected_budget_basis_auto_mode:
            st.caption(
                f"買い目提案・予想票CSV・印刷用まとめには、現在 `{standard_budget_basis_label}` を半自動採用しています。"
            )
            st.caption(f"半自動の判断: {auto_budget_basis_reason}")
            _render_budget_basis_decision_cards(budget_basis_decision, allow_jump=True, button_prefix="budget_basis")
        else:
            st.caption(f"買い目提案・予想票CSV・印刷用まとめには、現在 `{standard_budget_basis_label}` を標準採用しています。")
        budget_cols = st.columns(3, gap="large")
        with budget_cols[0]:
            if standard_budget_plan_df.empty:
                st.caption("標準配分はまだ算出できません。")
            else:
                st.caption(f"標準配分（現在採用中: {standard_budget_basis_label}）")
                _render_budget_bucket_cards(standard_budget_focus_cards_df)
                st.dataframe(standard_budget_plan_df, width="stretch", height=320, hide_index=True)
        with budget_cols[1]:
            comparison_plan_df = trend_adjusted_budget_plan_df if selected_budget_basis_key != "trend" and not trend_adjusted_budget_plan_df.empty else analog_adjusted_budget_plan_df
            comparison_label = "推奨配分（今週傾向反映）" if selected_budget_basis_key != "trend" and not trend_adjusted_budget_plan_df.empty else "類似個体で寄せた配分"
            comparison_amount_col = "今週傾向後金額" if selected_budget_basis_key != "trend" and not trend_adjusted_budget_plan_df.empty else "型補正後金額"
            comparison_focus_cards_df = _prepare_budget_focus_cards_df(comparison_plan_df, amount_col=comparison_amount_col)
            if comparison_plan_df.empty:
                st.caption("比較用の補正配分はまだ算出できません。")
            else:
                st.caption(comparison_label)
                _render_budget_bucket_cards(comparison_focus_cards_df)
                st.dataframe(comparison_plan_df, width="stretch", height=320, hide_index=True)
        with budget_cols[2]:
            st.caption("ベース配分")
            _render_budget_bucket_cards(result.budget_plan)
            st.dataframe(result.budget_plan, width="stretch")

st.info(
    "このMVPは確率モデルによる支援ツールです。最終判断はオッズ変動・直前気配・馬体重などの最新情報と合わせて行ってください。"
)
