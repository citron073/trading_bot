from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict

import pandas as pd
import streamlit as st


FrameDecorator = Callable[[pd.DataFrame], pd.DataFrame]
TextFormatter = Callable[[Any], str]


WEEKLY_MAIN_COLUMNS = [
    "レース",
    "開催",
    "格付",
    "日付",
    "レース名",
    "◎",
    "○",
    "▲",
    "△",
    "本命馬",
    "本命人気",
    "本命単勝オッズ",
    "大穴候補",
    "大穴人気",
    "危険人気馬",
    "危険人気",
    "勝率",
    "複勝率",
    "単勝候補",
    "複勝候補",
    "馬連候補",
    "ワイド候補",
    "三連複候補",
    "三連単候補",
    "天気予報",
    "馬場",
    "距離",
]

WEEKLY_DETAIL_COLUMNS = [
    "レース",
    "◎",
    "○",
    "▲",
    "△",
    "開催",
    "格付",
    "データ状態",
    "日付",
    "レース名",
    "本命馬",
    "本命人気",
    "本命単勝オッズ",
    "大穴候補",
    "大穴人気",
    "危険人気馬",
    "危険人気",
    "スピ候補",
    "LLM本命",
    "LLM本命比較",
    "LLM警戒区分",
    "LLM別軸理由",
    "LLM穴",
    "LLM危険人気",
    "LLM危険連動",
    "LLMソース",
    "型要約",
    "買い方方針",
    "券種期待度",
    "人気急変",
    "本命騎手",
    "補正本数",
    "条件補正",
    "勝率",
    "複勝率",
    "単勝候補",
    "複勝候補",
    "馬連候補",
    "ワイド候補",
    "三連複候補",
    "三連単候補",
    "天気予報",
    "馬場",
    "距離",
    "頭数",
    "レースID",
]

WEEKLY_OVERVIEW_COLUMNS = [
    "レース",
    "データ状態",
    "日付",
    "開催",
    "格付",
    "レース名",
    "頭数",
    "注目馬",
    "注目騎手",
    "天気予報",
    "馬場",
    "距離",
    "レースID",
]

PROGRAM_ORDER_COLUMNS = [
    "レース順",
    "レース",
    "格付",
    "頭数",
    "本命馬",
    "大穴候補",
    "三連単候補",
    "買い方方針",
    "LLM警戒区分",
    "券種期待度",
    "補正本数",
    "人気急変",
    "レースID",
]

GRADED_FOCUS_COLUMNS = [
    "レース",
    "開催",
    "本命馬",
    "本命人気",
    "大穴候補",
    "危険人気馬",
    "単勝候補",
    "複勝候補",
    "馬連候補",
    "ワイド候補",
    "三連複候補",
    "三連単候補",
    "注目馬",
    "注目騎手",
    "天気予報",
    "馬場",
    "距離",
    "頭数",
    "レースID",
]


@dataclass(frozen=True)
class WeeklyScopeSelection:
    selected_scope: str
    display_label: str
    caption: str


@dataclass(frozen=True)
class WeeklyFilterSelection:
    venues: list[str]
    grades: list[str]
    llm_alignment: str


@dataclass(frozen=True)
class ProgramOrderSelection:
    action: str
    current_row: pd.Series
    current_race_id: str
    current_index: int
    race_ids: list[str]


@dataclass(frozen=True)
class VenueReaderSelection:
    action: str
    current_row: pd.Series
    next_row: pd.Series
    current_race_id: str
    current_index: int
    race_ids: list[str]


@dataclass(frozen=True)
class WeeklyDetailSelectorSelection:
    action: str
    selected_race_id: str
    selected_label: str
    selected_row: pd.Series


def normalize_weekly_alignment(value: object, options: tuple[str, ...]) -> str:
    text = "" if value is None else str(value).strip()
    if text in options:
        return text
    return options[0] if options else ""


def existing_columns(frame: pd.DataFrame, candidates: list[str]) -> list[str]:
    return [col for col in candidates if col in frame.columns]


def weekly_main_columns(frame: pd.DataFrame) -> list[str]:
    return existing_columns(frame, WEEKLY_MAIN_COLUMNS)


def weekly_detail_columns(frame: pd.DataFrame) -> list[str]:
    return existing_columns(frame, WEEKLY_DETAIL_COLUMNS)


def weekly_overview_columns(frame: pd.DataFrame) -> list[str]:
    return existing_columns(frame, WEEKLY_OVERVIEW_COLUMNS)


def program_order_columns(frame: pd.DataFrame) -> list[str]:
    return existing_columns(frame, PROGRAM_ORDER_COLUMNS)


def graded_focus_columns(frame: pd.DataFrame) -> list[str]:
    return existing_columns(frame, GRADED_FOCUS_COLUMNS)


def detail_selector_options(
    selector_frame: pd.DataFrame,
    *,
    to_text: TextFormatter,
) -> tuple[list[str], dict[str, str]]:
    if selector_frame.empty or "race_id" not in selector_frame.columns:
        return [], {}
    race_ids = [to_text(value) for value in selector_frame["race_id"].tolist()]
    if "label" in selector_frame.columns:
        labels = [to_text(value) or race_id for value, race_id in zip(selector_frame["label"].tolist(), race_ids)]
    else:
        labels = race_ids.copy()
    return race_ids, dict(zip(race_ids, labels))


def resolve_detail_selector_race_id(selector_ids: list[str], current_race_id: object, *, to_text: TextFormatter) -> str:
    current = to_text(current_race_id)
    if current in selector_ids:
        return current
    return selector_ids[0] if selector_ids else ""


def render_weekly_scope_selector(
    *,
    has_today_scope: bool,
    today_value: date,
    week_start_value: date,
    week_end_value: date,
) -> WeeklyScopeSelection:
    scope_col1, scope_col2 = st.columns([1.2, 3.0], gap="small")
    with scope_col1:
        selected_scope = st.radio(
            "表示範囲",
            options=("今日", "今週"),
            index=0 if has_today_scope else 1,
            horizontal=True,
            key="weekly_display_scope",
        )
    display_label = "今日" if selected_scope == "今日" else "今週"
    if selected_scope == "今日":
        caption = f"今日の表示日付: {today_value.strftime('%Y/%m/%d')}"
    else:
        caption = (
            f"今週表示範囲: {week_start_value.strftime('%Y/%m/%d')} - "
            f"{week_end_value.strftime('%Y/%m/%d')}（月-日）"
        )
    with scope_col2:
        st.caption(caption)
    return WeeklyScopeSelection(
        selected_scope=selected_scope,
        display_label=display_label,
        caption=caption,
    )


def render_weekly_filter_controls(
    *,
    venue_options: list[str],
    grade_options: list[str],
    llm_alignment_options: tuple[str, ...],
    current_llm_alignment: object,
    display_scope_label: str,
) -> WeeklyFilterSelection:
    selected_venues = venue_options.copy()
    selected_grades = grade_options.copy()
    selected_llm_alignment = normalize_weekly_alignment(current_llm_alignment, llm_alignment_options)
    if venue_options or grade_options:
        filter_col1, filter_col2, filter_col3, filter_col4, filter_col5 = st.columns(
            [2.0, 1.6, 1.5, 0.7, 0.7],
            gap="small",
        )
        with filter_col1:
            selected_venues = st.multiselect(
                "今週の開催場所で絞る",
                venue_options,
                default=venue_options,
                key="weekly_venue_filter",
                help="未選択は全開催として扱います。",
            )
        with filter_col2:
            selected_grades = st.multiselect(
                "格付けで絞る",
                grade_options,
                default=grade_options,
                key="weekly_grade_filter",
                help="G1 / G2 / G3 / 未判定 などで絞れます。未選択は全格付けです。",
            )
        with filter_col3:
            selected_llm_alignment = st.selectbox(
                "LLM比較",
                options=llm_alignment_options,
                index=llm_alignment_options.index(selected_llm_alignment),
                key="weekly_llm_alignment_filter",
                help="LLM本命とデータ本命がズレたレースを見つけやすくします。",
            )
        active_venues = selected_venues or venue_options
        active_grades = selected_grades or grade_options
        filter_col4.metric("選択開催", f"{len(active_venues):,}")
        filter_col5.metric("選択格付", f"{len(active_grades):,}")
        st.caption(
            f"{display_scope_label}AI自動予想と{display_scope_label}のレース情報は、"
            "開催場所フィルタと格付けフィルタに連動します。"
        )
    return WeeklyFilterSelection(
        venues=selected_venues,
        grades=selected_grades,
        llm_alignment=selected_llm_alignment,
    )


def render_weekly_prediction_tables(
    view_weekly: pd.DataFrame,
    *,
    display_scope_label: str,
    selected_llm_alignment: object,
    with_one_based_index: FrameDecorator,
    to_text: TextFormatter,
) -> pd.DataFrame:
    if view_weekly.empty:
        st.info("選択した開催場所/格付けに一致する今週AI予想はありません。")
        return pd.DataFrame()

    st.caption(f"{display_scope_label}の表示レース数: {len(view_weekly):,}")
    if to_text(selected_llm_alignment) != "すべて":
        st.caption(f"LLM比較モード: {to_text(selected_llm_alignment)}")

    main_cols = weekly_main_columns(view_weekly)
    detail_cols = weekly_detail_columns(view_weekly)
    if main_cols:
        st.dataframe(with_one_based_index(view_weekly[main_cols]), width="stretch", height=260)
    if detail_cols:
        with st.expander("詳細列を開く（LLM理由・補正・内部データ）", expanded=False):
            st.dataframe(with_one_based_index(view_weekly[detail_cols]), width="stretch", height=360)
    return view_weekly.copy()


def render_weekly_race_overview_table(
    view_overview: pd.DataFrame,
    *,
    with_one_based_index: FrameDecorator,
) -> pd.DataFrame:
    if view_overview.empty:
        st.caption("今週レース情報を集計できませんでした。")
        return pd.DataFrame()

    overview_cols = weekly_overview_columns(view_overview)
    st.caption(f"表示レース数: {len(view_overview):,}")
    if overview_cols:
        st.dataframe(with_one_based_index(view_overview[overview_cols]), width="stretch", height=240)
    return view_overview.copy()


def render_program_order_panel(
    program_display: pd.DataFrame,
    *,
    selected_program_venue: str,
    current_race_id: object,
    with_one_based_index: FrameDecorator,
    to_text: TextFormatter,
) -> ProgramOrderSelection:
    if program_display.empty or "レースID" not in program_display.columns:
        return ProgramOrderSelection(
            action="",
            current_row=pd.Series(dtype=object),
            current_race_id="",
            current_index=-1,
            race_ids=[],
        )

    program_ids = [to_text(value) for value in program_display["レースID"].tolist()]
    current_program_race_id = to_text(current_race_id)
    if current_program_race_id not in program_ids:
        current_program_race_id = program_ids[0]
    st.session_state["program_selected_race_id"] = current_program_race_id
    current_program_index = program_ids.index(current_program_race_id)

    st.caption(f"{selected_program_venue} をレース順で確認できます。")
    display_cols = program_order_columns(program_display)
    if display_cols:
        st.dataframe(with_one_based_index(program_display[display_cols]), width="stretch", height=260)

    action = ""
    program_nav_cols = st.columns([1.0, 1.0, 1.2, 1.2], gap="small")
    with program_nav_cols[0]:
        if st.button("前のレース", key="program_prev_race", disabled=(current_program_index <= 0)):
            st.session_state["program_selected_race_id"] = program_ids[current_program_index - 1]
            st.rerun()
    with program_nav_cols[1]:
        if st.button("次のレース", key="program_next_race", disabled=(current_program_index >= len(program_ids) - 1)):
            st.session_state["program_selected_race_id"] = program_ids[current_program_index + 1]
            st.rerun()

    current_program_row = program_display[program_display["レースID"].map(to_text) == current_program_race_id].iloc[0]
    with program_nav_cols[2]:
        if st.button("このレースを詳細表示", key="program_show_race"):
            action = "show"
    with program_nav_cols[3]:
        if st.button("このレースだけ再計算", key="program_refresh_race"):
            action = "refresh"

    st.caption(
        "現在: "
        f"{to_text(current_program_row.get('レース順', '-'))} / "
        f"{to_text(current_program_row.get('レース', '-'))} / "
        f"本命 {to_text(current_program_row.get('本命馬', '-'))} / "
        f"大穴 {to_text(current_program_row.get('大穴候補', '-'))} / "
        f"方針 {to_text(current_program_row.get('買い方方針', '-'))} / "
        f"条件補正 {to_text(current_program_row.get('補正本数', '-'))}"
    )
    return ProgramOrderSelection(
        action=action,
        current_row=current_program_row,
        current_race_id=current_program_race_id,
        current_index=current_program_index,
        race_ids=program_ids,
    )


def build_reader_ticket_frame(row: pd.Series, *, to_text: TextFormatter) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"券種": "単勝", "候補": to_text(row.get("単勝候補", row.get("本命馬", "-")))},
            {"券種": "複勝", "候補": to_text(row.get("複勝候補", row.get("本命馬", "-")))},
            {"券種": "馬連", "候補": to_text(row.get("馬連候補", "-"))},
            {"券種": "ワイド", "候補": to_text(row.get("ワイド候補", "-"))},
            {"券種": "三連複", "候補": to_text(row.get("三連複候補", "-"))},
            {"券種": "三連単", "候補": to_text(row.get("三連単候補", "-"))},
        ]
    )


def render_venue_reader_panel(
    venue_reader_frame: pd.DataFrame,
    *,
    selected_reader_venue: str,
    current_race_id: object,
    autoplay_active: bool,
    jump_targets: Dict[str, str],
    to_text: TextFormatter,
    render_name_text: TextFormatter,
) -> VenueReaderSelection:
    if venue_reader_frame.empty or "レースID" not in venue_reader_frame.columns:
        return VenueReaderSelection(
            action="",
            current_row=pd.Series(dtype=object),
            next_row=pd.Series(dtype=object),
            current_race_id="",
            current_index=-1,
            race_ids=[],
        )

    reader_ids = [to_text(value) for value in venue_reader_frame["レースID"].tolist()]
    current_reader_race_id = to_text(current_race_id)
    if current_reader_race_id not in reader_ids:
        current_reader_race_id = reader_ids[0]
    st.session_state["venue_reader_race_id"] = current_reader_race_id
    current_reader_index = reader_ids.index(current_reader_race_id)
    current_reader_row = venue_reader_frame[venue_reader_frame["レースID"].map(to_text) == current_reader_race_id].iloc[0]
    next_reader_row = (
        venue_reader_frame.iloc[current_reader_index + 1]
        if current_reader_index < len(reader_ids) - 1
        else pd.Series(dtype=object)
    )

    info_cols = st.columns(3)
    info_cols[0].metric("読むレース数", f"{len(venue_reader_frame):,}")
    info_cols[1].metric("現在", to_text(current_reader_row.get("レース順", "-")))
    info_cols[2].metric("残り", f"{max(0, len(reader_ids) - current_reader_index - 1):,}")
    st.progress(
        max(0.0, min(1.0, float(current_reader_index + 1) / max(1, len(reader_ids)))),
        text=(
            f"{selected_reader_venue} {current_reader_index + 1}/{len(reader_ids)} "
            f"({to_text(current_reader_row.get('レース順', '-'))})"
        ),
    )

    jump_cols = st.columns(4, gap="small")
    for idx, (label, target_race_id) in enumerate(jump_targets.items()):
        target_text = to_text(target_race_id)
        with jump_cols[idx]:
            if st.button(
                label,
                key=f"venue_reader_jump_{label}",
                disabled=(not target_text or target_text == current_reader_race_id),
            ):
                st.session_state["venue_reader_race_id"] = target_text
                st.rerun()

    action = ""
    reader_nav_cols = st.columns([0.95, 0.95, 1.0, 1.2, 1.25, 1.35], gap="small")
    with reader_nav_cols[0]:
        if st.button("前のレース", key="venue_reader_prev", disabled=(current_reader_index <= 0)):
            st.session_state["venue_reader_autoplay"] = False
            st.session_state["venue_reader_autoplay_venue"] = ""
            st.session_state["venue_reader_race_id"] = reader_ids[current_reader_index - 1]
            st.rerun()
    with reader_nav_cols[1]:
        if st.button("次のレース", key="venue_reader_next", disabled=(current_reader_index >= len(reader_ids) - 1)):
            st.session_state["venue_reader_autoplay"] = False
            st.session_state["venue_reader_autoplay_venue"] = ""
            st.session_state["venue_reader_race_id"] = reader_ids[current_reader_index + 1]
            st.rerun()
    with reader_nav_cols[2]:
        if st.button("詳細表示", key="venue_reader_show"):
            st.session_state["venue_reader_autoplay"] = False
            st.session_state["venue_reader_autoplay_venue"] = ""
            action = "show"
    with reader_nav_cols[3]:
        if st.button("このレースだけ再計算", key="venue_reader_refresh"):
            st.session_state["venue_reader_autoplay"] = False
            st.session_state["venue_reader_autoplay_venue"] = ""
            action = "refresh"
    with reader_nav_cols[4]:
        if st.button("次を自動で開く", key="venue_reader_open_next", disabled=(current_reader_index >= len(reader_ids) - 1)):
            st.session_state["venue_reader_autoplay"] = False
            st.session_state["venue_reader_autoplay_venue"] = ""
            if not next_reader_row.empty:
                st.session_state["venue_reader_race_id"] = to_text(next_reader_row.get("レースID", ""))
            action = "open_next"
    with reader_nav_cols[5]:
        if autoplay_active:
            if st.button("自動送り停止", key="venue_reader_autoplay_stop"):
                st.session_state["venue_reader_autoplay"] = False
                st.session_state["venue_reader_autoplay_venue"] = ""
                st.rerun()
        else:
            if st.button("最終まで自動送り", key="venue_reader_autoplay_start", disabled=(current_reader_index >= len(reader_ids) - 1)):
                action = "autoplay_start"

    read_m1, read_m2, read_m3, read_m4 = st.columns(4)
    read_m1.metric("レース順", to_text(current_reader_row.get("レース順", "-")))
    read_m2.metric("本命", to_text(current_reader_row.get("本命馬", "-")))
    read_m3.metric("大穴", to_text(current_reader_row.get("大穴候補", "-")))
    read_m4.metric("三連単", to_text(current_reader_row.get("三連単候補", "-")))
    st.caption(
        f"{to_text(current_reader_row.get('レース', '-'))} / "
        f"天気 {to_text(current_reader_row.get('天気予報', '-'))} / "
        f"馬場 {to_text(current_reader_row.get('馬場', '-'))} / "
        f"距離 {to_text(current_reader_row.get('距離', '-'))}"
    )
    read_ticket_df = build_reader_ticket_frame(current_reader_row, to_text=to_text)
    read_ticket_df["候補"] = read_ticket_df["候補"].map(render_name_text)
    st.dataframe(read_ticket_df, width="stretch", height=245, hide_index=True)
    return VenueReaderSelection(
        action=action,
        current_row=current_reader_row,
        next_row=next_reader_row,
        current_race_id=current_reader_race_id,
        current_index=current_reader_index,
        race_ids=reader_ids,
    )


def render_weekly_detail_selector_panel(
    selector_frame: pd.DataFrame,
    *,
    current_race_id: object,
    to_text: TextFormatter,
) -> WeeklyDetailSelectorSelection:
    st.subheader("今週一覧から詳細予想へ")
    selector_ids, selector_label_map = detail_selector_options(selector_frame, to_text=to_text)
    if not selector_ids:
        return WeeklyDetailSelectorSelection(
            action="",
            selected_race_id="",
            selected_label="",
            selected_row=pd.Series(dtype=object),
        )

    selected_race_id = resolve_detail_selector_race_id(selector_ids, current_race_id, to_text=to_text)
    selector_index = selector_ids.index(selected_race_id)
    select_col, action_col, refresh_col = st.columns([3.0, 1.0, 1.15], gap="small")
    with select_col:
        selected_race_id = st.selectbox(
            "今週AI自動予想から詳細表示するレース",
            options=selector_ids,
            index=selector_index,
            format_func=lambda rid: selector_label_map.get(rid, rid),
            key="weekly_detail_selector_race_id",
        )

    action = ""
    with action_col:
        st.markdown("<div style='height: 1.85rem;'></div>", unsafe_allow_html=True)
        if st.button("詳細予想を表示", type="primary", key="apply_weekly_detail_selector"):
            action = "show"
    with refresh_col:
        st.markdown("<div style='height: 1.85rem;'></div>", unsafe_allow_html=True)
        if st.button("選択レースだけ再計算", key="refresh_single_weekly_prediction"):
            action = "refresh"

    row_match = selector_frame[selector_frame["race_id"].map(to_text) == selected_race_id]
    selected_row = row_match.iloc[0] if not row_match.empty else pd.Series(dtype=object)
    selected_label = selector_label_map.get(selected_race_id, selected_race_id)
    st.caption(
        "現在の詳細予想候補: "
        f"{selected_label} / "
        f"開催 {to_text(selected_row.get('venue', '-')) or '-'} / "
        f"格付 {to_text(selected_row.get('grade', '-')) or '-'} / "
        f"頭数 {to_text(selected_row.get('field_size', '-')) or '-'}"
    )
    st.caption("`選択レースだけ再計算` は今週一覧と詳細予想の対象1レースだけ更新します。全レース再計算より速いです。")
    return WeeklyDetailSelectorSelection(
        action=action,
        selected_race_id=selected_race_id,
        selected_label=selected_label,
        selected_row=selected_row,
    )


def render_graded_focus_section(
    view_weekly_display: pd.DataFrame,
    view_overview_display: pd.DataFrame,
    *,
    with_one_based_index: FrameDecorator,
    render_grade_bet_memo_cards: Callable[..., None],
) -> None:
    if view_weekly_display.empty or "格付" not in view_weekly_display.columns:
        return

    graded_df = view_weekly_display[view_weekly_display["格付"].isin(["G1", "G2", "G3"])].copy()
    if graded_df.empty:
        return

    st.subheader("重賞フォーカス")
    graded_memo_mode = st.radio(
        "重賞メモモード",
        ("堅め", "標準", "穴狙い"),
        horizontal=True,
        key="graded_memo_mode",
    )
    focus_tabs = st.tabs(["G1", "G2", "G3"])
    for idx, grade_name in enumerate(["G1", "G2", "G3"]):
        with focus_tabs[idx]:
            grade_df = graded_df[graded_df["格付"] == grade_name].copy()
            if grade_df.empty:
                st.caption(f"{grade_name} は今週表示対象にありません。")
                continue

            gm1, gm2, gm3 = st.columns(3)
            race_count = grade_df["レースID"].nunique() if "レースID" in grade_df.columns else len(grade_df)
            gm1.metric(f"{grade_name}レース数", f"{race_count:,}")
            venues = " / ".join(
                sorted(
                    {
                        str(value)
                        for value in grade_df.get("開催", pd.Series(dtype=str)).dropna().astype(str)
                        if str(value).strip() and str(value) != "-"
                    }
                )
            )
            gm2.metric("開催", venues or "-")
            win_rate_series = pd.to_numeric(
                grade_df.get("勝率", pd.Series(dtype=str)).astype(str).str.rstrip("%"),
                errors="coerce",
            )
            gm3.metric("本命平均勝率", f"{win_rate_series.mean() / 100:.2%}" if win_rate_series.notna().any() else "-")

            grade_merge = grade_df.copy()
            if not view_overview_display.empty and {"レースID", "注目馬", "注目騎手"}.intersection(view_overview_display.columns):
                merge_cols = [col for col in ["レースID", "注目馬", "注目騎手", "頭数"] if col in view_overview_display.columns]
                grade_merge = grade_merge.merge(
                    view_overview_display[merge_cols],
                    on="レースID",
                    how="left",
                    suffixes=("", "_overview"),
                )
            st.caption(f"{grade_name} 買い目メモ")
            render_grade_bet_memo_cards(grade_merge, grade_name, graded_memo_mode, limit=4)
            focus_cols = graded_focus_columns(grade_merge)
            st.caption(f"{grade_name} だけを抜き出して確認できます。開催・格付けフィルタ後の内容に連動します。")
            if focus_cols:
                st.dataframe(with_one_based_index(grade_merge[focus_cols]), width="stretch", height=220)

