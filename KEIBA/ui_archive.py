from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

import pandas as pd
import streamlit as st


MetricFormatter = Callable[[Any], str]
DetailFrameBuilder = Callable[[pd.DataFrame], pd.DataFrame]
FrameDecorator = Callable[[pd.DataFrame], pd.DataFrame]
RaceLabelFormatter = Callable[[Any, Any, Any, Any], str]
ResultStatusFormatter = Callable[[Any, Any, Any], str]
BudgetBasisCommentBuilder = Callable[[pd.Series, Dict[str, Any]], str]
WeightChangeFocusBuilder = Callable[..., tuple[pd.DataFrame, pd.DataFrame]]


@dataclass(frozen=True)
class ArchiveDetailFrames:
    bet_type_performance: pd.DataFrame
    bet_type_feedback_rows: pd.DataFrame
    condition_adjustment_performance: pd.DataFrame
    condition_segment_performance: pd.DataFrame


def _empty_detail_frames() -> ArchiveDetailFrames:
    return ArchiveDetailFrames(
        bet_type_performance=pd.DataFrame(),
        bet_type_feedback_rows=pd.DataFrame(),
        condition_adjustment_performance=pd.DataFrame(),
        condition_segment_performance=pd.DataFrame(),
    )


def _safe_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        try:
            if bool(pd.isna(value)):
                return 0
        except Exception:
            pass
        return int(value)
    except Exception:
        return 0


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _yen_text(value: Any) -> str:
    try:
        number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except Exception:
        number = pd.NA
    if pd.isna(number):
        return "-"
    return f"{int(round(float(number))):,}円"


def render_feedback_summary_metrics(
    summary: Dict[str, Any],
    *,
    format_rate_metric: MetricFormatter,
    format_roi_metric: MetricFormatter,
    include_hit_rates: bool = True,
) -> None:
    summary = summary if isinstance(summary, dict) else {}

    top_cols = st.columns(6)
    top_cols[0].metric("保存予想数", f"{_safe_int(summary.get('stored_predictions')):,}")
    top_cols[1].metric("評価済み", f"{_safe_int(summary.get('evaluated_races')):,}")
    top_cols[2].metric("結果待ち", f"{_safe_int(summary.get('pending_races')):,}")
    top_cols[3].metric("本命勝率", format_rate_metric(summary.get("top_horse_hit_rate")))
    top_cols[4].metric("単勝回収率(暫定)", format_roi_metric(summary.get("single_roi")))
    top_cols[5].metric("複勝回収率(暫定)", format_roi_metric(summary.get("place_roi")))

    if not include_hit_rates:
        return

    hit_cols = st.columns(5)
    hit_cols[0].metric("単勝的中率", format_rate_metric(summary.get("single_hit_rate")))
    hit_cols[1].metric("複勝的中率", format_rate_metric(summary.get("place_hit_rate")))
    hit_cols[2].metric("三連複的中率", format_rate_metric(summary.get("trio_hit_rate")))
    hit_cols[3].metric("三連単的中率", format_rate_metric(summary.get("trifecta_hit_rate")))
    hit_cols[4].metric("未来予想", f"{_safe_int(summary.get('upcoming_races')):,}")


def render_archive_detail_toggle(*, key: str = "archive_detail_loaded") -> bool:
    return bool(
        st.toggle(
            "アーカイブ詳細集計を読み込む",
            key=key,
            help=(
                "券種別成績、条件補正、予想差分一覧を開く時だけ計算します。"
                "通常表示を軽くするため、必要な時だけONにしてください。"
            ),
        )
    )


def build_archive_detail_frames(
    prediction_feedback_df: pd.DataFrame,
    *,
    build_bet_type_performance_table: DetailFrameBuilder,
    build_bet_type_feedback_rows: DetailFrameBuilder,
    build_condition_adjustment_performance_table: DetailFrameBuilder,
    build_condition_segment_performance_table: DetailFrameBuilder,
) -> ArchiveDetailFrames:
    if prediction_feedback_df.empty:
        return _empty_detail_frames()

    with st.spinner("アーカイブ詳細を集計中..."):
        return ArchiveDetailFrames(
            bet_type_performance=build_bet_type_performance_table(prediction_feedback_df),
            bet_type_feedback_rows=build_bet_type_feedback_rows(prediction_feedback_df),
            condition_adjustment_performance=build_condition_adjustment_performance_table(prediction_feedback_df),
            condition_segment_performance=build_condition_segment_performance_table(prediction_feedback_df),
        )


def render_bet_type_performance_table(
    bet_type_performance_df: pd.DataFrame,
    *,
    format_rate_metric: MetricFormatter,
    format_roi_metric: MetricFormatter,
    with_one_based_index: FrameDecorator,
) -> None:
    if bet_type_performance_df.empty:
        return

    view = bet_type_performance_df.copy()
    for col in ["的中率", "払戻既知率"]:
        if col in view.columns:
            view[col] = view[col].map(format_rate_metric)
    if "回収率" in view.columns:
        view["回収率"] = view["回収率"].map(format_roi_metric)
    st.caption("券種別成績一覧")
    st.dataframe(with_one_based_index(view), width="stretch", height=245)


def render_budget_basis_performance_table(
    budget_basis_performance_df: pd.DataFrame,
    *,
    trend_summary: Dict[str, Any],
    build_winning_comment: BudgetBasisCommentBuilder,
    format_rate_metric: MetricFormatter,
    format_roi_metric: MetricFormatter,
    with_one_based_index: FrameDecorator,
) -> None:
    if budget_basis_performance_df.empty:
        return

    chart_source = budget_basis_performance_df.copy()
    chart_source["配分基準表示"] = chart_source.apply(
        lambda row: " / ".join(
            part for part in [_text(row.get("配分基準", "")), _text(row.get("採用モード", ""))] if part
        )
        or "-",
        axis=1,
    )
    roi_chart_cols = [col for col in ["単勝回収率", "複勝回収率"] if col in chart_source.columns]
    hit_chart_cols = [col for col in ["本命的中率", "単勝的中率", "複勝的中率"] if col in chart_source.columns]
    chart_cols = st.columns(2, gap="large")
    if roi_chart_cols:
        with chart_cols[0]:
            st.caption("配分基準別 回収率")
            st.bar_chart(chart_source.set_index("配分基準表示")[roi_chart_cols])
    if hit_chart_cols:
        with chart_cols[1]:
            st.caption("配分基準別 的中率")
            st.bar_chart(chart_source.set_index("配分基準表示")[hit_chart_cols])

    view = budget_basis_performance_df.copy()
    for col in ["本命的中率", "単勝的中率", "複勝的中率"]:
        if col in view.columns:
            view[col] = view[col].map(format_rate_metric)
    for col in ["単勝回収率", "複勝回収率"]:
        if col in view.columns:
            view[col] = view[col].map(format_roi_metric)
    view["勝ち筋コメント"] = budget_basis_performance_df.apply(
        lambda row: build_winning_comment(row, trend_summary),
        axis=1,
    )
    st.caption("配分基準別成績")
    st.dataframe(with_one_based_index(view), width="stretch", height=220)


def render_condition_performance_tables(
    condition_adjustment_performance_df: pd.DataFrame,
    condition_segment_performance_df: pd.DataFrame,
    *,
    format_rate_metric: MetricFormatter,
    format_roi_metric: MetricFormatter,
    with_one_based_index: FrameDecorator,
) -> None:
    if not condition_adjustment_performance_df.empty:
        view = condition_adjustment_performance_df.copy()
        for col in ["本命的中率", "単勝的中率", "複勝的中率", "単勝回収率", "複勝回収率"]:
            if col in view.columns:
                formatter = format_roi_metric if "回収率" in col else format_rate_metric
                view[col] = view[col].map(formatter)
        st.caption("条件補正 本数別成績")
        st.dataframe(with_one_based_index(view), width="stretch", height=220)

    if not condition_segment_performance_df.empty:
        segment_view = condition_segment_performance_df.copy().head(12)
        for col in ["本命的中率", "単勝的中率", "単勝回収率"]:
            if col in segment_view.columns:
                formatter = format_roi_metric if "回収率" in col else format_rate_metric
                segment_view[col] = segment_view[col].map(formatter)
        st.caption("条件補正 セグメント別成績")
        st.dataframe(with_one_based_index(segment_view), width="stretch", height=260)


def render_llm_disagreement_performance_table(
    llm_disagreement_performance_df: pd.DataFrame,
    *,
    format_rate_metric: MetricFormatter,
    format_signed_rate_metric: MetricFormatter,
    with_one_based_index: FrameDecorator,
) -> None:
    if llm_disagreement_performance_df.empty:
        return

    view = llm_disagreement_performance_df.copy()
    for col in ["データ本命勝率", "LLM本命勝率"]:
        if col in view.columns:
            view[col] = view[col].map(format_rate_metric)
    if "LLM優勢差" in view.columns:
        view["LLM優勢差"] = view["LLM優勢差"].map(format_signed_rate_metric)
    st.caption("LLM別軸レース成績")
    st.dataframe(with_one_based_index(view), width="stretch", height=220)


def _weight_value_text(value: Any, *, signed: bool = False) -> str:
    try:
        number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except Exception:
        number = pd.NA
    if pd.isna(number):
        return "-"
    return f"{float(number):+.3f}" if signed else f"{float(number):.3f}"


def _weight_ratio_text(value: Any) -> str:
    try:
        number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except Exception:
        number = pd.NA
    if pd.isna(number):
        return "-"
    return f"{float(number):.2f}x"


def render_weight_change_table(
    latest_weight_change_df: pd.DataFrame,
    *,
    latest_weight_meta: Dict[str, Any],
    build_weight_change_focus_tables: WeightChangeFocusBuilder,
    format_timestamp_text: MetricFormatter,
    with_one_based_index: FrameDecorator,
) -> None:
    if latest_weight_change_df.empty:
        return

    view = latest_weight_change_df.copy()
    for col in ["前", "後", "差分"]:
        if col in view.columns:
            view[col] = view[col].map(lambda value, col=col: _weight_value_text(value, signed=(col == "差分")))
    if "倍率" in view.columns:
        view["倍率"] = view["倍率"].map(_weight_ratio_text)

    strong_table, weak_table = build_weight_change_focus_tables(latest_weight_change_df, limit=4)
    focus_cols = st.columns(2, gap="large")
    with focus_cols[0]:
        st.caption("強化された要素")
        if strong_table.empty:
            st.caption("強化なし")
        else:
            strong_view = strong_table.copy()
            if "差分" in strong_view.columns:
                strong_view["差分"] = strong_view["差分"].map(lambda value: _weight_value_text(value, signed=True))
            if "倍率" in strong_view.columns:
                strong_view["倍率"] = strong_view["倍率"].map(_weight_ratio_text)
            st.dataframe(strong_view, width="stretch", height=180, hide_index=True)

    with focus_cols[1]:
        st.caption("抑えた要素")
        if weak_table.empty:
            st.caption("抑制なし")
        else:
            weak_view = weak_table.copy()
            if "差分" in weak_view.columns:
                weak_view["差分"] = weak_view["差分"].map(lambda value: _weight_value_text(value, signed=True))
            if "倍率" in weak_view.columns:
                weak_view["倍率"] = weak_view["倍率"].map(_weight_ratio_text)
            st.dataframe(weak_view, width="stretch", height=180, hide_index=True)

    st.caption("反省再学習後の重み変化")
    st.dataframe(with_one_based_index(view), width="stretch", height=270)
    if isinstance(latest_weight_meta, dict):
        st.caption(
            f"条件補正セグメント: {_safe_int(latest_weight_meta.get('before_segments'))} -> "
            f"{_safe_int(latest_weight_meta.get('after_segments'))} / "
            f"保存時刻 {format_timestamp_text(latest_weight_meta.get('recorded_at', ''))}"
        )


def render_bet_type_feedback_rows(
    bet_type_feedback_rows_df: pd.DataFrame,
    bet_type_performance_df: pd.DataFrame,
    *,
    result_status_text: ResultStatusFormatter,
    format_race_label: RaceLabelFormatter,
    format_date_text: MetricFormatter,
    format_timestamp_text: MetricFormatter,
    format_hit_mark: MetricFormatter,
    with_one_based_index: FrameDecorator,
) -> None:
    if bet_type_feedback_rows_df.empty:
        return

    view = bet_type_feedback_rows_df.copy()
    view["結果状態"] = view.apply(
        lambda row: result_status_text(
            row.get("result_available", ""),
            row.get("race_date", ""),
            row.get("race_id", ""),
        ),
        axis=1,
    )
    if "hit" in view.columns:
        view["的中"] = view["hit"].map(format_hit_mark)
    if "payout_known" in view.columns:
        view["払戻状態"] = view["payout_known"].map(
            lambda value: "既知" if str(value).lower() in {"true", "1"} else "未取得"
        )
    view["レース"] = view.apply(
        lambda row: format_race_label(
            row.get("race_id", ""),
            row.get("venue", ""),
            row.get("race_date", ""),
            row.get("race_name", ""),
        ),
        axis=1,
    )
    if "race_date" in view.columns:
        view["race_date"] = view["race_date"].map(format_date_text)
    if "predicted_at" in view.columns:
        view["predicted_at"] = view["predicted_at"].map(format_timestamp_text)
    if "payout_100" in view.columns:
        view["payout_100"] = view["payout_100"].map(_yen_text)

    options = [
        item
        for item in bet_type_performance_df.get("券種", pd.Series(dtype=str)).tolist()
        if _text(item)
    ]
    if not options and "bet_type" in view.columns:
        options = sorted({_text(item) for item in view["bet_type"].tolist() if _text(item)})
    active_bet_types = st.multiselect(
        "券種ごとの予想履歴",
        options=options,
        default=options,
        key="archive_bet_type_feedback_filter",
        help="単勝から三連単まで、各券種の予想・的中・払戻を一覧で確認できます。",
    )
    if active_bet_types and "bet_type" in view.columns:
        view = view[view["bet_type"].isin(active_bet_types)].copy()

    view = view.rename(
        columns={
            "bet_type": "券種",
            "pick": "予想",
            "actual_top3": "実着順",
            "payout_100": "払戻(100円)",
            "predicted_at": "予想保存時刻",
            "race_date": "日付",
            "race_grade": "格付",
            "budget_basis_label": "配分基準",
            "budget_basis_mode": "採用モード",
            "race_id": "レースID",
        }
    )
    history_cols = [
        "結果状態",
        "券種",
        "レース",
        "格付",
        "配分基準",
        "採用モード",
        "予想",
        "実着順",
        "的中",
        "払戻(100円)",
        "払戻状態",
        "予想保存時刻",
        "レースID",
    ]
    history_cols = [col for col in history_cols if col in view.columns]
    st.caption("券種ごとの予想一覧")
    st.dataframe(with_one_based_index(view[history_cols]), width="stretch", height=300)


def render_prediction_feedback_table(
    prediction_feedback_df: pd.DataFrame,
    *,
    archive_detail_loaded: bool,
    result_status_text: ResultStatusFormatter,
    format_race_label: RaceLabelFormatter,
    format_date_text: MetricFormatter,
    format_timestamp_text: MetricFormatter,
    format_hit_mark: MetricFormatter,
    format_condition_adjustment_count: MetricFormatter,
    with_one_based_index: FrameDecorator,
) -> None:
    if not archive_detail_loaded:
        st.info("予想差分の全一覧は詳細集計ONで表示します。まずは上の要約だけ確認できます。")
        return
    if prediction_feedback_df.empty:
        st.caption("まだ保存済み予想または結果差分がありません。")
        return

    view = prediction_feedback_df.copy()
    view["結果状態"] = view.apply(
        lambda row: result_status_text(
            row.get("result_available", ""),
            row.get("race_date", ""),
            row.get("race_id", ""),
        ),
        axis=1,
    )
    view["race_label"] = view.apply(
        lambda row: format_race_label(
            row.get("race_id", ""),
            row.get("venue", ""),
            row.get("race_date", ""),
            row.get("race_name", ""),
        ),
        axis=1,
    )
    if "race_date" in view.columns:
        view["race_date"] = view["race_date"].map(format_date_text)
    if "predicted_at" in view.columns:
        view["predicted_at"] = view["predicted_at"].map(format_timestamp_text)
    for col in [
        "top_horse_hit",
        "llm_top_hit",
        "llm_disagreement",
        "single_hit",
        "place_hit",
        "quinella_hit",
        "wide_hit",
        "exacta_hit",
        "trio_hit",
        "trifecta_hit",
    ]:
        if col in view.columns:
            view[col] = view[col].map(format_hit_mark)
    for col in [
        "single_payout_100",
        "place_payout_100",
        "quinella_payout_100",
        "wide_payout_100",
        "exacta_payout_100",
        "trio_payout_100",
        "trifecta_payout_100",
    ]:
        if col in view.columns:
            view[col] = view[col].map(_yen_text)

    view = view.rename(
        columns={
            "race_label": "レース",
            "predicted_at": "予想保存時刻",
            "condition_adjustment_count": "補正本数",
            "condition_adjustments": "条件補正",
            "top_horse": "本命",
            "llm_top_horse": "LLM本命",
            "llm_dark_horse": "LLM穴",
            "llm_danger_favorite": "LLM危険人気",
            "llm_disagreement_reason": "LLM別軸理由",
            "single_pick": "単勝予想",
            "place_pick": "複勝予想",
            "quinella_pick": "馬連予想",
            "wide_pick": "ワイド予想",
            "exacta_pick": "馬単予想",
            "trio_pick": "三連複予想",
            "trifecta_pick": "三連単予想",
            "actual_winner": "1着",
            "actual_second": "2着",
            "actual_third": "3着",
            "actual_top3": "実着順",
            "top_horse_hit": "本命的中",
            "llm_top_hit": "LLM本命的中",
            "llm_disagreement": "LLM別軸",
            "single_hit": "単勝的中",
            "place_hit": "複勝的中",
            "quinella_hit": "馬連的中",
            "wide_hit": "ワイド的中",
            "exacta_hit": "馬単的中",
            "trio_hit": "三連複的中",
            "trifecta_hit": "三連単的中",
            "single_payout_100": "単勝払戻(100円)",
            "place_payout_100": "複勝払戻(100円)",
            "quinella_payout_100": "馬連払戻(100円)",
            "wide_payout_100": "ワイド払戻(100円)",
            "exacta_payout_100": "馬単払戻(100円)",
            "trio_payout_100": "三連複払戻(100円)",
            "trifecta_payout_100": "三連単払戻(100円)",
            "race_date": "日付",
            "race_grade": "格付",
            "venue": "開催",
            "budget_basis_label": "配分基準",
            "budget_basis_mode": "採用モード",
            "race_id": "レースID",
        }
    )
    sort_cols = [col for col in ["結果状態", "日付", "レースID"] if col in view.columns]
    if sort_cols:
        ascending_lookup = {"結果状態": True, "日付": False, "レースID": False}
        view = view.sort_values(
            sort_cols,
            ascending=[ascending_lookup.get(col, True) for col in sort_cols],
            na_position="last",
        )
    if "補正本数" in view.columns:
        view["補正本数"] = view["補正本数"].map(format_condition_adjustment_count)
    feedback_cols = [
        "結果状態",
        "レース",
        "格付",
        "配分基準",
        "採用モード",
        "補正本数",
        "条件補正",
        "本命",
        "LLM本命",
        "LLM穴",
        "LLM危険人気",
        "LLM別軸",
        "LLM別軸理由",
        "1着",
        "2着",
        "3着",
        "本命的中",
        "LLM本命的中",
        "単勝的中",
        "複勝的中",
        "馬連的中",
        "ワイド的中",
        "三連複的中",
        "三連単的中",
        "単勝払戻(100円)",
        "複勝払戻(100円)",
        "馬連払戻(100円)",
        "ワイド払戻(100円)",
        "馬単払戻(100円)",
        "三連複払戻(100円)",
        "三連単払戻(100円)",
        "予想保存時刻",
        "レースID",
    ]
    feedback_cols = [col for col in feedback_cols if col in view.columns]
    st.dataframe(with_one_based_index(view[feedback_cols]), width="stretch", height=320)
    st.download_button(
        "予想差分CSVを保存",
        data=prediction_feedback_df.to_csv(index=False, encoding="utf-8-sig"),
        file_name="keiba_prediction_feedback.csv",
        mime="text/csv",
        key="download_prediction_feedback",
    )
