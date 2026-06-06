from __future__ import annotations

from typing import Any, Callable, Dict

import pandas as pd
import streamlit as st


FrameDecorator = Callable[[pd.DataFrame], pd.DataFrame]
TableStyler = Callable[[pd.DataFrame, str, str], Any]
TextFormatter = Callable[[Any], str]
AnchorBuilder = Callable[[str], str]


def render_prediction_ticket_table(
    standard_ticket_df: pd.DataFrame,
    bet_view_ticket_df: pd.DataFrame,
    *,
    highlighted_bet_type: str,
    highlighted_bet_source: str,
    with_one_based_index: FrameDecorator,
    style_prediction_ticket_table: TableStyler,
) -> None:
    buy_list_cols = [
        "券種",
        "狙い",
        "本線",
        "押さえ",
        "期待度",
        "的中確率",
        "参考オッズ",
        "理論オッズ",
        "目安配分",
        "配分基準",
        "買い方メモ",
    ]
    buy_list_cols = [col for col in buy_list_cols if col in standard_ticket_df.columns]
    source = bet_view_ticket_df if not bet_view_ticket_df.empty else standard_ticket_df
    buy_list_cols = [col for col in buy_list_cols if col in source.columns]
    ticket_table_view = with_one_based_index(source[buy_list_cols])
    if highlighted_bet_type and highlighted_bet_source == "history":
        st.caption(f"履歴から開いた `{highlighted_bet_type}` の行を濃い背景色で表示しています。")
    st.dataframe(
        style_prediction_ticket_table(
            ticket_table_view,
            highlighted_bet_type,
            highlighted_bet_source,
        ),
        width="stretch",
        height=320,
    )
    st.download_button(
        "予想票をCSVで保存",
        data=standard_ticket_df.to_csv(index=False, encoding="utf-8-sig"),
        file_name="keiba_prediction_ticket.csv",
        mime="text/csv",
        key="download_prediction_ticket",
    )


def render_bet_candidate_tables(
    bet_view_tables: Dict[str, pd.DataFrame],
    *,
    highlighted_bet_type: str,
    highlighted_bet_source: str,
    bet_type_anchor_id: AnchorBuilder,
    to_text: TextFormatter,
) -> None:
    for bet_type, table in bet_view_tables.items():
        bet_type_text = to_text(bet_type)
        st.markdown(f"<div id='{bet_type_anchor_id(bet_type_text)}'></div>", unsafe_allow_html=True)
        if bet_type_text == highlighted_bet_type:
            if highlighted_bet_source == "llm_auto":
                highlight_badge_text = "LLM別軸で先頭表示"
            elif highlighted_bet_source == "history":
                highlight_badge_text = "履歴から確認中"
            else:
                highlight_badge_text = "おすすめから移動"
            st.markdown(
                f"### {bet_type_text} <span style='font-size:0.72rem;color:#1f5d37;background:rgba(225,246,231,0.96);padding:2px 8px;border-radius:999px;'>{highlight_badge_text}</span>",
                unsafe_allow_html=True,
            )
            if highlighted_bet_source == "llm_auto":
                st.info(f"`{bet_type_text}` は LLM別軸モードのおすすめ券種なので、先頭で確認しやすくしています。")
            elif highlighted_bet_source == "history":
                st.info(f"`{bet_type_text}` は LLMおまかせ履歴のおすすめ券種なので、色を強めて目立たせています。")
            else:
                st.info(f"`{bet_type_text}` の買い目候補を確認しやすいように、この券種を先頭で目立たせています。")
        else:
            st.markdown(f"### {bet_type_text}")
        if table.empty:
            st.caption("出走頭数が少ないため、この券種は算出対象外です。")
            continue
        st.dataframe(table, width="stretch")
