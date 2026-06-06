# KEIBA — 競馬予想システム コンテキスト

このファイルは KEIBA システム専用のエージェント文脈です。
トレードボット（MAIN）のコンテキストは `../CLAUDE.md` を参照してください。

---

## システム概要

| 項目 | 値 |
|------|-----|
| 用途 | JRA 競馬予測・採点・学習 |
| 起動 | `./run_keiba.sh`（Streamlit: localhost:8511） |
| 自動サイクル | `keiba_auto_cycle.py`（launchd: 30分間隔） |
| LLM | Ollama ローカル（qwen2.5:1.5b） |

## 重要ファイルマップ

| 用途 | ファイル |
|------|---------|
| 設定 | `data/auto_cycle_config.json` |
| サイクル状態 | `data/auto_cycle_status.json` |
| 予測実績 | `data/prediction_feedback.csv` |
| 今週予測 | `data/weekly_predictions_auto.csv` |
| 特徴量重み | `data/keiba_best_weights.json` |

## エージェント役割定義

```
KEIBA/.claude/CLAUDE.md（この文書）
  └── /keiba-status  — 状態確認（自動サイクル・予測精度・データ量）
```

## 連携システム

- トレードボット通知 → `../MAIN/tools/trade_event_notifier.py`
- 共通設定管理 → `../CLAUDE.md`（ルート CLAUDE.md）
- ルート CLI スキル → `../.claude/commands/keiba.md`（`/keiba` コマンド）

## 判断ルール

### 自動実行してよいもの
- `data/` 以下のファイル読み取り・分析
- `run_keiba.sh` の状態確認
- launchd タイマー確認（`launchctl list | grep keiba`）

### 必ず確認を取るもの
- `keiba_auto_cycle.py` や `auto_agent.py` のコード変更
- `data/auto_cycle_config.json` の設定変更
- launchd plist のインストール・削除
