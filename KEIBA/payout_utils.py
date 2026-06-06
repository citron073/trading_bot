from __future__ import annotations

import re
from typing import Any, Dict, List

BET_TYPE_ALIASES: Dict[str, str] = {
    "単勝": "単勝",
    "win": "単勝",
    "複勝": "複勝",
    "place": "複勝",
    "馬連": "馬連",
    "quinella": "馬連",
    "ワイド": "ワイド",
    "wide": "ワイド",
    "馬単": "馬単",
    "exacta": "馬単",
    "三連複": "三連複",
    "trio": "三連複",
    "trifecta_box": "三連複",
    "三連単": "三連単",
    "trifecta": "三連単",
}

BET_TYPE_ORDER: List[str] = ["単勝", "複勝", "馬連", "ワイド", "馬単", "三連複", "三連単"]
ORDERED_BET_TYPES = {"単勝", "複勝", "馬単", "三連単"}
UNORDERED_BET_TYPES = {"馬連", "ワイド", "三連複"}


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none"} else text


def normalize_bet_type(value: Any) -> str:
    text = _to_text(value)
    if not text:
        return ""
    compact = text.lower().replace(" ", "").replace("_", "")
    if compact in BET_TYPE_ALIASES:
        return BET_TYPE_ALIASES[compact]
    if text in BET_TYPE_ALIASES:
        return BET_TYPE_ALIASES[text]
    for alias, canonical in BET_TYPE_ALIASES.items():
        if alias and alias in compact:
            return canonical
    return ""


def normalize_ticket_text(ticket: Any, bet_type: str) -> str:
    bet = normalize_bet_type(bet_type)
    text = _to_text(ticket)
    if not bet or not text:
        return ""
    numbers = [str(int(token)) for token in re.findall(r"\d+", text)]
    if not numbers:
        numbers = [part.strip() for part in re.split(r"[-/→>\s]+", text) if part.strip()]
    if not numbers:
        return ""
    if bet in UNORDERED_BET_TYPES:
        numbers = sorted(numbers, key=lambda value: int(value) if value.isdigit() else value)
    return "-".join(numbers)


def prediction_pick_to_ticket(pick_text: Any, bet_type: str, horse_to_gate: Dict[str, str]) -> str:
    bet = normalize_bet_type(bet_type)
    text = _to_text(pick_text)
    if not bet or not text:
        return ""
    horse_parts = [part.strip() for part in text.split("-") if part.strip() and part.strip() != "-"]
    if not horse_parts:
        horse_parts = [text]
    gate_parts: List[str] = []
    for horse in horse_parts:
        gate = _to_text(horse_to_gate.get(horse, ""))
        if not gate:
            return ""
        gate_parts.append(gate)
    if bet in UNORDERED_BET_TYPES:
        gate_parts = sorted(gate_parts, key=lambda value: int(value) if value.isdigit() else value)
    return "-".join(gate_parts)
