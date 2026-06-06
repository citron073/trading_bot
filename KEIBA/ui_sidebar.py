from __future__ import annotations

from dataclasses import dataclass
from html import escape as html_escape
from pathlib import Path
from typing import Any, Callable, Dict

import pandas as pd
import streamlit as st


TextFormatter = Callable[[Any], str]
ModelListFetcher = Callable[[str, int], list[str]]
TwoPayloadFormatter = Callable[[Any, Any], str]
FrameDecorator = Callable[[pd.DataFrame], pd.DataFrame]
HistoryTableBuilder = Callable[[list[Dict[str, Any]]], pd.DataFrame]
LatestCardsRenderer = Callable[[list[Dict[str, Any]]], None]


@dataclass(frozen=True)
class LocalLLMSettings:
    mode: str
    style: str
    reasoning_mode: str
    base_url: str
    model: str
    timeout_sec: int


@dataclass(frozen=True)
class AutoImproveSettings:
    enabled: bool
    sync_feedback_memory: bool
    reflection_learning: bool
    refresh_weekly_after_reflection: bool
    min_new_results: int
    min_missed_results: int
    cooldown_minutes: int


@dataclass(frozen=True)
class AutoUpdateDetailSettings:
    months_back: int = 24
    week_days: int = 7
    backfill_days: int = 14
    fallback_days: int = 120
    entries_cache_hours: int = 4
    weather_cache_hours: int = 6
    weekly_ai_simulations: int = 4000
    result_batch_cap: int = 24


@dataclass(frozen=True)
class OperationModeSettings:
    easy_operation_mode: bool
    llm_hands_free_mode: bool


@dataclass(frozen=True)
class UpdateProfileSettings:
    profile: str
    auto_tune: bool
    auto_forecast_weather: bool
    auto_weekly_ai: bool
    auto_run_on_open: bool


@dataclass(frozen=True)
class EasyActionClicks:
    latest_only: bool = False
    weekly_only: bool = False
    results_only: bool = False
    reflection_only: bool = False


@dataclass(frozen=True)
class StandardUpdateClicks:
    weekly_fast: bool = False
    latest_only: bool = False
    selected_mode_update: bool = False


@dataclass(frozen=True)
class PostRaceActionClicks:
    results_only: bool = False
    reflection_only: bool = False
    results_train: bool = False
    weekly_only: bool = False


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def render_public_access_panel(
    public_status: Dict[str, Any] | None,
    public_health: Dict[str, Any] | None,
    public_watch: Dict[str, Any] | None,
    *,
    format_timestamp_text: TextFormatter,
    format_health_label: TextFormatter,
    format_health_message_label: TextFormatter,
    format_watch_status_label: TextFormatter,
    format_watch_event_label: TextFormatter,
    format_restart_result_label: TextFormatter,
    format_notify_result_label: TextFormatter,
) -> None:
    public_status = public_status if isinstance(public_status, dict) else {}
    public_health = public_health if isinstance(public_health, dict) else {}
    public_watch = public_watch if isinstance(public_watch, dict) else {}
    provider_name = _text(public_status.get("provider", ""))
    provider_label = {
        "cloudflared_named": "Cloudflare Tunnel (固定URL)",
        "cloudflared": "Cloudflare Tunnel",
        "ngrok": "ngrok",
    }.get(provider_name, "")

    with st.expander("外部公開", expanded=False):
        public_url = _text(public_status.get("public_url", ""))
        if public_url:
            if provider_label:
                st.caption(f"公開方式: {provider_label}")
            st.caption("外から見るURL")
            st.code(public_url, language=None)
            st.caption(
                "最終更新: "
                f"{format_timestamp_text(public_status.get('updated_at', ''))} / "
                f"ローカル: {_text(public_status.get('local_url', '-'))}"
            )
            meta_cols = st.columns(3)
            meta_cols[0].metric("方式", provider_label or "-")
            meta_cols[1].metric("起動時刻", format_timestamp_text(public_status.get("started_at", "")))
            meta_cols[2].metric("トンネルPID", _text(public_status.get("tunnel_pid", "-")))
        else:
            st.caption("まだ外部公開は起動していません。")

        st.markdown(
            """
- 起動: `./start_public.sh`
- 常駐: `./install_public_launchagent.sh`
- 監視: `./install_public_watch_launchagent.sh`
- 確認: `./keiba_public_healthcheck.sh`
"""
        )
        if provider_name == "cloudflared_named":
            st.success("固定URL運用中です。")
        elif provider_name == "cloudflared":
            st.info("Cloudflare Quick Tunnel は公開URLが起動ごとに変わります。URL固定は名前付きトンネル設定が必要です。")
        elif provider_name == "ngrok":
            st.warning("無料ngrokは警告ページと通信量上限があります。長時間運用には向きません。")
        else:
            st.caption("固定URLにしたい場合は `./setup_named_tunnel.sh` を一度実行してください。")

        if public_health:
            st.caption("公開状態")
            health_cols = st.columns(4)
            health_cols[0].metric("ローカル疎通", format_health_label(public_health.get("local_ok")))
            health_cols[1].metric("外部疎通", format_health_label(public_health.get("public_ok")))
            health_cols[2].metric("HTTP", _text(public_health.get("public_http_status", "-")))
            health_cols[3].metric("常駐", format_health_label(public_health.get("launchagent_loaded")))
            st.caption(f"最終確認: {format_timestamp_text(public_health.get('checked_at', ''))}")
            if _text(public_health.get("message", "")):
                st.caption(f"状態メモ: {format_health_message_label(public_health.get('message', ''))}")

        if public_watch:
            st.caption("監視状態")
            watch_cols = st.columns(3)
            watch_cols[0].metric("監視", format_watch_status_label(public_watch.get("status", "-")))
            watch_cols[1].metric("前回イベント", format_watch_event_label(public_watch.get("last_event_type", "-")))
            watch_cols[2].metric("自動復旧", format_restart_result_label(public_watch.get("last_restart_result", "-")))
            st.caption(f"前回通知: {format_timestamp_text(public_watch.get('last_notified_at', ''))}")
            st.caption(f"前回再起動: {format_timestamp_text(public_watch.get('last_restart_at', ''))}")
            if _text(public_watch.get("last_notify_result", "")):
                st.caption(f"通知方法: {format_notify_result_label(public_watch.get('last_notify_result', ''))}")
            with st.expander("公開詳細", expanded=False):
                st.caption(f"監視生状態: {_text(public_watch.get('status', '-'))}")
                st.caption(f"通知生結果: {_text(public_watch.get('last_notify_result', '-'))}")
                st.caption(f"再起動生結果: {_text(public_watch.get('last_restart_result', '-'))}")


def render_local_llm_panel(
    *,
    easy_operation_mode: bool,
    default_base_url: str,
    default_model: str,
    default_style: str,
    list_models: ModelListFetcher,
) -> LocalLLMSettings:
    style_options = ("バランス", "万馬券狙い", "保守")
    style_index = style_options.index(default_style) if default_style in style_options else 0

    with st.expander("ローカルLLM（任意）", expanded=False if easy_operation_mode else False):
        mode = st.selectbox(
            "ローカルLLMモード",
            options=("off", "auto", "ollama"),
            index=0,
            help="`auto/ollama` は localhost の Ollama を使います。",
        )
        style = st.selectbox(
            "LLMスタイル",
            options=style_options,
            index=style_index,
            help="説明文の重心だけを変えます。最終判断はオッズと出走表で確認してください。",
        )
        reasoning_mode = st.selectbox(
            "LLM推論モード",
            options=("標準", "強化", "反省"),
            index=0,
            help="`強化` は自己点検、`反省` は外れたレースの共通点を優先して読みます。少し遅くなります。",
        )
        base_url = st.text_input("Ollama URL", value=default_base_url, help="通常は http://127.0.0.1:11434")
        model = st.text_input("モデル名", value=default_model)
        timeout_sec = int(st.number_input("LLMタイムアウト(秒)", min_value=3, max_value=180, value=20, step=1))
        if mode != "off":
            try:
                installed_models = list_models(base_url, timeout_sec)
                st.caption(f"利用可能モデル: {', '.join(installed_models[:6]) if installed_models else 'なし'}")
            except Exception as exc:
                st.caption(f"ローカルLLM未接続: {exc}")
            st.caption("例: `ollama serve` / `ollama pull qwen2.5:1.5b`")

    return LocalLLMSettings(
        mode=str(mode),
        style=str(style),
        reasoning_mode=str(reasoning_mode),
        base_url=str(base_url),
        model=str(model),
        timeout_sec=timeout_sec,
    )


def render_llm_alignment_shortcuts(
    *,
    easy_operation_mode: bool,
    set_ui_notice: Callable[[str], None],
) -> None:
    if easy_operation_mode:
        return

    with st.expander("LLM比較ショートカット", expanded=False):
        current_filter = _text(st.session_state.get("weekly_llm_alignment_filter", "すべて")) or "すべて"
        st.caption(f"現在: {current_filter}")
        cols = st.columns(3, gap="small")
        if cols[0].button("別軸だけ", key="sidebar_llm_diff_only", width="stretch"):
            st.session_state["weekly_llm_alignment_filter"] = "別軸だけ"
            set_ui_notice("LLMとデータが別軸のレースだけ表示します")
            st.rerun()
        if cols[1].button("別軸を上に", key="sidebar_llm_diff_top", width="stretch"):
            st.session_state["weekly_llm_alignment_filter"] = "別軸を上に集める"
            set_ui_notice("LLMとデータが別軸のレースを上に集めます")
            st.rerun()
        if cols[2].button("通常表示", key="sidebar_llm_diff_reset", width="stretch"):
            st.session_state["weekly_llm_alignment_filter"] = "すべて"
            set_ui_notice("LLM比較フィルタを通常表示に戻しました")
            st.rerun()


def render_llm_hands_free_history_panel(
    rows: list[Dict[str, Any]],
    *,
    llm_hands_free_mode: bool,
    build_history_table: HistoryTableBuilder,
    render_latest_cards: LatestCardsRenderer,
    with_one_based_index: FrameDecorator,
    format_timestamp_text: TextFormatter,
) -> None:
    if not llm_hands_free_mode:
        return

    latest = rows[-1] if rows and isinstance(rows[-1], dict) else {}
    st.caption("LLMおまかせ自動運用: いま必要な操作だけを上から順に自動で回します。")
    if latest:
        st.caption(
            "直近の自動実行: "
            f"{format_timestamp_text(latest.get('at', ''))} / "
            f"{_text(latest.get('action_label', '-'))}"
        )

    with st.expander("LLMおまかせ履歴", expanded=False):
        history_table = build_history_table(rows)
        render_latest_cards(rows)
        if not history_table.empty:
            st.dataframe(with_one_based_index(history_table), width="stretch", height=220)


def render_sidebar_budget_basis_cards(active_key: Any) -> None:
    current = _text(active_key)
    items = [
        ("trend", "今週傾向", "推奨"),
        ("analog", "類似個体", "補正"),
        ("base", "ベース", "標準"),
    ]
    html = "<div class='sidebar-basis-grid'>" + "".join(
        """
<div class="sidebar-basis-chip {classes}">
  <span class="label">{label}</span>
  <span class="value">{value}</span>
  {active_mark}
</div>
""".format(
            classes=html_escape(("active " + key) if key == current else ""),
            label=html_escape(label),
            value=html_escape(value),
            active_mark=("<span class='active-mark'>現在採用中</span>" if key == current else ""),
        )
        for key, label, value in items
    ) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_sidebar_budget_basis_selector() -> str:
    cols = st.columns(3, gap="small")
    button_specs = [
        ("trend", "今週傾向", "sidebar_open_budget_trend"),
        ("analog", "類似個体", "sidebar_open_budget_analog"),
        ("base", "ベース", "sidebar_open_budget_base"),
    ]
    for idx, (key, label, button_key) in enumerate(button_specs):
        if cols[idx].button(label, key=button_key, width="stretch"):
            return key
    return ""


def render_local_confirmation_header(
    local_runtime_status: Dict[str, Any] | None,
    *,
    app_path: Path,
    weekly_predictions_path: Path,
    budget_basis_label: str,
    format_toggle_label: TextFormatter,
    format_file_timestamp: TextFormatter,
    format_file_age: TextFormatter,
) -> None:
    local_runtime_status = local_runtime_status if isinstance(local_runtime_status, dict) else {}
    local_url = _text(local_runtime_status.get("local_url", "")) or "http://127.0.0.1:8511"
    st.caption("保存後の確認を優先するローカル開発モードです。")
    st.code(local_url, language=None)
    local_cols = st.columns(4)
    local_cols[0].metric("モード", "ローカル")
    local_cols[1].metric("Hot Reload", format_toggle_label(local_runtime_status.get("run_on_save")))
    local_cols[2].metric("app.py更新", format_file_timestamp(app_path), format_file_age(app_path))
    local_cols[3].metric("予想CSV更新", format_file_timestamp(weekly_predictions_path), format_file_age(weekly_predictions_path))
    st.caption(f"標準配分: {budget_basis_label}")


def render_local_confirmation_footer(
    local_runtime_status: Dict[str, Any] | None,
    history_cache_status: Dict[str, Any] | None,
    *,
    auto_entries_path: Path,
    format_file_timestamp: TextFormatter,
    format_file_age: TextFormatter,
    format_storage_size: TextFormatter,
    format_timestamp_text: TextFormatter,
    format_age_text: TextFormatter,
) -> None:
    st.caption(f"出走CSV更新: {format_file_timestamp(auto_entries_path)} / {format_file_age(auto_entries_path)}")
    history_cache_status = history_cache_status if isinstance(history_cache_status, dict) else {}
    if bool(history_cache_status.get("enabled")):
        cache_text = "準備済み" if bool(history_cache_status.get("fresh")) else "準備中"
        st.caption(
            "履歴高速化: "
            f"Parquet {cache_text} / "
            f"CSV {format_storage_size(history_cache_status.get('source_size'))} / "
            f"cache {format_storage_size(history_cache_status.get('size'))}"
        )
    if isinstance(local_runtime_status, dict):
        st.caption(
            "ローカル状態更新: "
            f"{format_timestamp_text(local_runtime_status.get('updated_at', ''))} / {format_age_text(local_runtime_status.get('updated_at', ''))}"
        )
    st.markdown(
        """
- 起動: `./run_keiba.sh`
- 公開停止: `./switch_to_local_mode.sh`
- 安定優先: `./run_keiba.sh --stable`
"""
    )


def render_update_operation_header() -> OperationModeSettings:
    st.subheader("更新")
    easy_operation_mode = bool(
        st.toggle(
            "かんたん操作モード",
            key="easy_operation_mode",
            help="迷ったら主要な操作だけ意識できる表示にします。",
        )
    )
    llm_hands_free_mode = bool(
        st.toggle(
            "LLMおまかせ自動運用",
            key="llm_hands_free_mode",
            help="状態を見て `最新取得 / 結果反映 / 反省再学習 / 今週予想更新` を順番に自動実行します。定時自動運用が入っていれば画面を閉じていても進みます。",
        )
    )
    st.caption("最速は `今週だけ高速更新`。学習は必要時だけで十分です。")
    if easy_operation_mode:
        st.info("迷ったら上の `次にやること` のボタンだけで大丈夫です。普段よく使うのは `最新だけ更新 / 今週AI予想だけ更新 / 結果取得だけ / 反省再学習だけ` です。")
    return OperationModeSettings(
        easy_operation_mode=easy_operation_mode,
        llm_hands_free_mode=llm_hands_free_mode,
    )


def render_update_profile_settings(*, easy_operation_mode: bool) -> UpdateProfileSettings:
    if easy_operation_mode:
        profile = "高速（最新追記）"
        auto_tune = False
        auto_forecast_weather = True
        auto_weekly_ai = True
        auto_run_on_open = False
        with st.expander("更新の細かい設定", expanded=False):
            st.caption("かんたん操作モードでは、基本はこのままで大丈夫です。必要な時だけ変えてください。")
            profile = st.radio(
                "更新モード",
                options=("高速（最新追記）", "標準（差分更新）", "フル（再取得+学習）"),
                index=0,
                key="easy_update_profile",
            )
            auto_tune = bool(st.toggle("データ更新時に学習も実行", value=False, key="easy_auto_tune"))
            auto_forecast_weather = bool(st.toggle("天気予報を自動取得して反映", value=True, key="easy_auto_forecast_weather"))
            auto_weekly_ai = bool(st.toggle("更新後に今週AI予想を自動作成", value=True, key="easy_auto_weekly_ai"))
            auto_run_on_open = bool(st.toggle("ページ起動時に自動更新（1セッション1回）", value=False, key="easy_auto_run_on_open"))
        return UpdateProfileSettings(
            profile=str(profile),
            auto_tune=auto_tune,
            auto_forecast_weather=auto_forecast_weather,
            auto_weekly_ai=auto_weekly_ai,
            auto_run_on_open=auto_run_on_open,
        )

    profile = st.radio(
        "更新モード",
        options=("高速（最新追記）", "標準（差分更新）", "フル（再取得+学習）"),
        index=0,
    )
    return UpdateProfileSettings(
        profile=str(profile),
        auto_tune=bool(st.toggle("データ更新時に学習も実行", value=False)),
        auto_forecast_weather=bool(st.toggle("天気予報を自動取得して反映", value=True)),
        auto_weekly_ai=bool(st.toggle("更新後に今週AI予想を自動作成", value=True)),
        auto_run_on_open=bool(st.toggle("ページ起動時に自動更新（1セッション1回）", value=False)),
    )


def render_auto_cycle_panel(
    auto_cycle_status: Dict[str, Any] | None,
    auto_cycle_config: Dict[str, Any] | None,
    *,
    easy_operation_mode: bool,
    format_timestamp_text: TextFormatter,
    format_auto_cycle_mode_label: TextFormatter,
    format_auto_cycle_mode_detail: TextFormatter,
    format_next_run_text: TwoPayloadFormatter,
    format_next_run_remaining_text: TwoPayloadFormatter,
) -> None:
    status = auto_cycle_status if isinstance(auto_cycle_status, dict) else {}
    config = auto_cycle_config if isinstance(auto_cycle_config, dict) else {}

    with st.expander("定時自動運用", expanded=False if easy_operation_mode else False):
        interval_text = "-"
        if config.get("interval_sec") is not None:
            try:
                interval_text = f"{int(config.get('interval_sec', 0)) // 60}分ごと"
            except Exception:
                interval_text = "-"
        cycle_mode_label = format_auto_cycle_mode_label(config)
        cycle_mode_detail = format_auto_cycle_mode_detail(config)
        next_run_text = format_next_run_text(status, config)
        next_run_remaining_text = format_next_run_remaining_text(status, config)
        cycle_cols = st.columns(5)
        cycle_cols[0].metric("状態", "稼働中" if bool(status.get("running")) else ("正常" if bool(status.get("last_success")) else "-"))
        cycle_cols[1].metric("最終実行", format_timestamp_text(status.get("last_completed_at", "")))
        cycle_cols[2].metric("間隔", interval_text)
        cycle_cols[3].metric("モード", cycle_mode_label)
        cycle_cols[4].metric("進捗", f"{_safe_int(status.get('progress_pct'))}%")
        if cycle_mode_detail != "-":
            st.caption(f"実行内容: {cycle_mode_detail}")
        if cycle_mode_label != "-":
            st.caption(f"次回予定モード: {cycle_mode_label}")
        if next_run_text != "-":
            if next_run_remaining_text != "-":
                st.caption(f"次回実行予定: {next_run_text} ({next_run_remaining_text})")
            else:
                st.caption(f"次回実行予定: {next_run_text}")
        if _text(status.get("last_phase", "")):
            st.caption(f"現在フェーズ: {_text(status.get('last_phase', '-'))}")
        if _safe_int(status.get("targeted_races")) > 0:
            st.caption(f"対象レース: {_safe_int(status.get('targeted_races')):,}件")
        agent_policy = (
            status.get("agent", {}).get("llm_policy", {})
            if isinstance(status.get("agent"), dict)
            else {}
        )
        if isinstance(agent_policy, dict) and agent_policy:
            llm_policy_label = (
                "使用"
                if bool(agent_policy.get("run_review")) or bool(agent_policy.get("run_race_picks"))
                else ("待機" if bool(agent_policy.get("available")) else "未接続")
            )
            if bool(agent_policy.get("slow_cooldown")):
                llm_policy_label = "前回遅延で軽量化"
            st.caption(
                "LLM自動判断: "
                f"{llm_policy_label} / "
                f"タイムアウト {_safe_int(agent_policy.get('timeout_sec'))}秒 / "
                f"対象 {_safe_int(agent_policy.get('max_llm_races'))}R"
            )
        if _text(status.get("last_summary", "")):
            st.caption(f"直近サマリ: {_text(status.get('last_summary', '-'))}")
        if _text(status.get("last_tuning_summary", "")):
            st.caption(f"学習状況: {_text(status.get('last_tuning_summary', '-'))}")
        if _text(status.get("error", "")):
            st.caption(f"直近エラー: {_text(status.get('error', '-'))}")
        st.markdown(
            """
- 導入: `./install_local_auto_launchagent.sh`
- 停止: `./uninstall_local_auto_launchagent.sh`
- 手動1回: `python3 keiba_auto_cycle.py`
- 重い実行: `python3 keiba_auto_cycle.py --refresh-entries --run-tuning`
"""
        )


def render_auto_agent_panel(
    auto_agent_status: Dict[str, Any] | None,
    auto_agent_report: Dict[str, Any] | None,
    auto_agent_basis_hint: Dict[str, Any] | None,
    *,
    easy_operation_mode: bool,
    format_timestamp_text: TextFormatter,
) -> None:
    status = auto_agent_status if isinstance(auto_agent_status, dict) else {}
    report = auto_agent_report if isinstance(auto_agent_report, dict) else {}
    basis_hint = auto_agent_basis_hint if isinstance(auto_agent_basis_hint, dict) else {}

    with st.expander("自律エージェント", expanded=False if easy_operation_mode else False):
        agent_cols = st.columns(4)
        agent_cols[0].metric("最終レビュー", format_timestamp_text(report.get("generated_at", "")))
        weekly_predictions = status.get("weekly_predictions", {}) if isinstance(status.get("weekly_predictions"), dict) else {}
        memory_sync = status.get("memory_sync", {}) if isinstance(status.get("memory_sync"), dict) else {}
        llm_review = status.get("llm_review", {}) if isinstance(status.get("llm_review"), dict) else {}
        agent_cols[1].metric("週次予想", f"{_safe_int(weekly_predictions.get('rows')):,}" if weekly_predictions else "-")
        agent_cols[2].metric("メモ追記", f"{_safe_int(memory_sync.get('rows_added')):,}" if memory_sync else "-")
        agent_cols[3].metric("LLM状態", "正常" if bool(llm_review.get("ok")) else ("待機" if status else "-"))
        if _text(status.get("message", "")):
            st.caption(f"自律サマリ: {_text(status.get('message', ''))}")
        if basis_hint:
            st.caption(
                "自律配分ヒント: "
                f"{_text(basis_hint.get('budget_basis_label', '-'))} / "
                f"{_text(basis_hint.get('reason', '-'))}"
            )
            if basis_hint.get("recommended_bets"):
                st.caption("寄せたい券種: " + " / ".join(str(item) for item in basis_hint.get("recommended_bets", [])))
            if basis_hint.get("avoid_bets"):
                st.caption("抑えたい券種: " + " / ".join(str(item) for item in basis_hint.get("avoid_bets", [])))
        if weekly_predictions:
            st.caption(f"LLM列更新: {_safe_int(weekly_predictions.get('llm_rows')):,}レース")
        if _text(report.get("text", "")):
            st.code(_text(report.get("text", "")), language=None)
        else:
            st.caption("まだ自律レビューはありません。`python3 keiba_auto_cycle.py` または定時自動運用の後に表示されます。")


def render_auto_improve_panel(
    auto_improve_status: Dict[str, Any] | None,
    *,
    easy_operation_mode: bool,
    format_timestamp_text: TextFormatter,
) -> AutoImproveSettings:
    status = auto_improve_status if isinstance(auto_improve_status, dict) else {}
    with st.expander("自動改善", expanded=not easy_operation_mode):
        enabled = st.toggle("結果確定後に自動改善を回す", value=True)
        sync_feedback_memory = st.toggle("実結果からLLM学習メモを自動追記", value=True)
        reflection_learning = st.toggle("外れレースを使って自動反省再学習", value=True)
        refresh_weekly_after_reflection = st.toggle("自動改善後に今週AI予想も更新", value=True)
        min_new_results = int(st.slider("自動反省の最小新規結果数", min_value=1, max_value=8, value=2, step=1))
        min_missed_results = int(st.slider("自動反省の最小外れ件数", min_value=1, max_value=5, value=1, step=1))
        cooldown_minutes = int(st.slider("自動反省のクールダウン(分)", min_value=5, max_value=180, value=45, step=5))
        improve_cols = st.columns(3)
        improve_cols[0].metric("前回自動反省", format_timestamp_text(status.get("last_auto_reflection_at", "")))
        improve_cols[1].metric("前回メモ追記", format_timestamp_text(status.get("last_memory_sync_at", "")))
        improve_cols[2].metric("前回新結果", f"{_safe_int(status.get('last_new_result_count')):,}")
        if _text(status.get("last_auto_reflection_result", "")):
            st.caption(f"自動反省: {_text(status.get('last_auto_reflection_result', '-'))}")
        if _text(status.get("last_memory_sync_summary", "")):
            st.caption(f"直近メモ: {_text(status.get('last_memory_sync_summary', '-'))}")

    return AutoImproveSettings(
        enabled=bool(enabled),
        sync_feedback_memory=bool(sync_feedback_memory),
        reflection_learning=bool(reflection_learning),
        refresh_weekly_after_reflection=bool(refresh_weekly_after_reflection),
        min_new_results=min_new_results,
        min_missed_results=min_missed_results,
        cooldown_minutes=cooldown_minutes,
    )


def render_auto_update_detail_settings(*, easy_operation_mode: bool) -> AutoUpdateDetailSettings:
    if easy_operation_mode:
        return AutoUpdateDetailSettings()

    with st.expander("詳細設定（標準/フル）", expanded=False):
        return AutoUpdateDetailSettings(
            months_back=int(st.slider("過去取得期間 (月)", min_value=3, max_value=60, value=24, step=1)),
            week_days=int(st.slider("今週取得日数", min_value=3, max_value=14, value=7, step=1)),
            backfill_days=int(st.slider("差分再取得の巻き戻し日数", min_value=0, max_value=30, value=14, step=1)),
            fallback_days=int(st.slider("代替取得の最大遡り日数", min_value=30, max_value=365, value=120, step=5)),
            entries_cache_hours=int(st.slider("出走表キャッシュ時間", min_value=0, max_value=24, value=4, step=1)),
            weather_cache_hours=int(st.slider("天気予報キャッシュ時間", min_value=1, max_value=24, value=6, step=1)),
            weekly_ai_simulations=int(st.slider("今週AI予想シミュレーション/レース", min_value=1000, max_value=12000, value=4000, step=500)),
            result_batch_cap=int(st.slider("結果待ちの1回確認件数", min_value=8, max_value=80, value=24, step=4)),
        )


def render_easy_action_buttons(
    *,
    easy_operation_mode: bool,
    auto_ready: bool,
    history_exists: bool,
) -> EasyActionClicks:
    if not easy_operation_mode:
        return EasyActionClicks()

    st.caption("よく使う操作")
    st.markdown(
        """
<div class="easy-action-grid">
  <div class="easy-action-card">
    <div class="easy-action-title">最新だけ更新</div>
    <div class="easy-action-sub">まず情報を取り込む時に使います。</div>
  </div>
  <div class="easy-action-card">
    <div class="easy-action-title">今週AI予想だけ更新</div>
    <div class="easy-action-sub">今週の予想を作り直したい時に使います。</div>
  </div>
  <div class="easy-action-card">
    <div class="easy-action-title">結果取得だけ</div>
    <div class="easy-action-sub">レース後に結果だけ反映します。</div>
  </div>
  <div class="easy-action-card">
    <div class="easy-action-title">反省再学習だけ</div>
    <div class="easy-action-sub">外れが増えた後に学習を入れます。</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    top_cols = st.columns(2, gap="small")
    bottom_cols = st.columns(2, gap="small")
    latest_only = bool(top_cols[0].button("最新だけ更新", key="easy_latest_only", disabled=not auto_ready, width="stretch"))
    weekly_only = bool(top_cols[1].button("今週AI予想だけ更新", key="easy_weekly_only", width="stretch"))
    results_only = bool(bottom_cols[0].button("結果取得だけ", key="easy_results_only", disabled=not auto_ready, width="stretch"))
    reflection_only = bool(
        bottom_cols[1].button(
            "反省再学習だけ",
            key="easy_reflection_only",
            disabled=not history_exists,
            width="stretch",
        )
    )
    st.caption("細かい操作はこの下の通常ボタンからも使えます。")
    return EasyActionClicks(
        latest_only=latest_only,
        weekly_only=weekly_only,
        results_only=results_only,
        reflection_only=reflection_only,
    )


def render_standard_update_buttons(*, auto_ready: bool) -> StandardUpdateClicks:
    cols = st.columns(3)
    weekly_fast = bool(
        cols[0].button(
            "今週だけ高速更新",
            disabled=not auto_ready,
            help="履歴更新をスキップして今週出走表だけ更新",
        )
    )
    latest_only = bool(cols[1].button("最新だけ更新", disabled=not auto_ready))
    selected_mode_update = bool(cols[2].button("選択モード更新", disabled=not auto_ready))
    return StandardUpdateClicks(
        weekly_fast=weekly_fast,
        latest_only=latest_only,
        selected_mode_update=selected_mode_update,
    )


def render_post_race_action_buttons(
    *,
    auto_ready: bool,
    history_exists: bool,
) -> PostRaceActionClicks:
    st.caption("レース後操作パネル")
    cols = st.columns([1.05, 1.1, 1.4, 1.0], gap="small")
    results_only = bool(
        cols[0].button(
            "結果取得だけ",
            disabled=not auto_ready,
            help="結果だけ取り込みます。今週出走表更新と再学習は行いません。",
        )
    )
    reflection_only = bool(
        cols[1].button(
            "反省再学習だけ",
            disabled=not history_exists,
            help="本命を外した保存済みレースを優先して、反省寄りに軽量再学習します。",
        )
    )
    results_train = bool(
        cols[2].button(
            "結果取得→履歴更新→再学習",
            disabled=not auto_ready,
            help="レース後の結果取り込み向けです。出走表更新はスキップして履歴更新と再学習を行います。",
        )
    )
    weekly_only = bool(cols[3].button("今週AI予想だけ更新"))
    return PostRaceActionClicks(
        results_only=results_only,
        reflection_only=reflection_only,
        results_train=results_train,
        weekly_only=weekly_only,
    )


def render_latest_update_caption(report: Dict[str, Any] | None) -> None:
    if not isinstance(report, dict):
        return
    st.caption(
        "最新更新: "
        f"history {_safe_int(report.get('history_rows')):,}行 / "
        f"entries {_safe_int(report.get('entries_rows')):,}行 / "
        f"週レース {_safe_int(report.get('weekly_races')):,}"
    )


def render_latest_update_metrics(report: Dict[str, Any] | None) -> None:
    if not isinstance(report, dict):
        return
    cols = st.columns(4)
    cols[0].metric("履歴行数", f"{_safe_int(report.get('history_rows')):,}")
    cols[1].metric("出走行数", f"{_safe_int(report.get('entries_rows')):,}")
    cols[2].metric("履歴レース数", f"{_safe_int(report.get('history_races')):,}")
    cols[3].metric("今週レース数", f"{_safe_int(report.get('weekly_races')):,}")
