# /manage — エージェントマネージャー

**役割**: 全エージェント（スキル）の担当範囲を一覧管理し、重複・抜けを検出して統括する。
新スキル追加・既存スキル変更・統合・廃止の際は必ずこのコマンドで登録台帳を更新する。

---

## エージェント台帳（完全版）

| スキル | ファイル | 担当領域 | 入力データ | 出力 |
|--------|---------|---------|-----------|------|
| `/risk` | `.claude/commands/risk.md` | 証拠金・日次損益・連敗・安全フロア | VM: `state.json`, `CONTROL.csv` | リスク状態レポート |
| `/log` | `.claude/commands/log.md` | 取引ログ分析・異常検知・パターン抽出 | VM: `logs/trade_log_*.csv` | ログ分析レポート |
| `/chart` | `.claude/commands/chart.md` | 市場文脈・HTFバイアス・トレンド強度 | VM: `state.json` | チャート分析レポート |
| `/filter` | `.claude/commands/filter.md` | フィルター効率・Shadow A/Bテスト比較 | VM: `logs/trade_log_*.csv`, `CONTROL.csv` | ブロック件数・機会コスト |
| `/ai` | `.claude/commands/ai.md` | AIモデル鮮度・訓練WR・自動学習・週次WR推移 | VM: `ai_model.json`, `logs/*.csv`, `CONTROL.csv` | AIモデル監視レポート |
| `/fill` | `.claude/commands/fill.md` | 約定率・OBSERVE_OK vs unfilled・offset調整 | VM: `logs/trade_log_*.csv` | fill rateレポート |
| `/backtest` | `.claude/commands/backtest.md` | 過去OHLCfetch・バックテスト実行・学習サンプル生成 | VM: `data/historical_ohlc.csv` | バックテスト結果 |
| `/data` | `.claude/commands/data.md` | OHLCデータ状況・バックテストサンプル管理 | VM: `data/historical_ohlc.csv`, `logs/backtest/` | データ状況レポート |
| `/status` | `.claude/commands/status.md` | 朝次ブリーフィング（全MAIN項目一括）+ KEIBA状態 | VM: `state.json`, `logs/`, `.ops_checks.json` + Local: KEIBA `data/` | 総合モーニングレポート |
| `/keiba` | `.claude/commands/keiba.md` | KEIBA予測システム状態確認 | Local: `KEIBA/data/` | KEIBA状態レポート |
| `/manage` | `.claude/commands/manage.md` | 全エージェント台帳管理・重複検出 | Local: このファイル | 台帳・重複レポート |
| `/version` | `.claude/commands/version.md` | バージョン確認・スペック表記録 | VM: bot.py等 + Local: docs/ | バージョン状態・更新指示 |

---

## 担当範囲マトリクス（重複検出）

| データソース | 担当エージェント | 重複状態 |
|------------|----------------|---------|
| `state.json` | `/risk`, `/chart`, `/status` | ✅ 意図的（各エージェントが異なる切り口で分析） |
| `logs/trade_log_*.csv` | `/log`, `/filter`, `/fill`, `/ai`, `/status` | ✅ 意図的（ログから異なる指標を抽出） |
| `CONTROL.csv` | `/ai`, `/filter`, `/status` | ✅ 意図的（設定確認は共通） |
| `ai_model.json` | `/ai` のみ | ✅ 専任 |
| `data/historical_ohlc.csv` | `/data`, `/backtest` | ✅ 意図的（管理 vs 実行で分担） |
| KEIBA `data/` | `/keiba`, `/status` | ✅ `/keiba` は詳細、`/status` は一行サマリー |

> **重複がない状態**: 現時点で不正な重複（同じ出力を生成する複数エージェント）はなし。

---

## 統合・廃止ルール

### 統合を検討するケース
- 同じ SSH コマンド + 同じ出力形式が2つ以上のスキルに存在する場合
- 一方のスキルが他方のサブセット（1セクション分）しか持たない場合

### 廃止を検討するケース
- 6ヶ月以上使用実績がないスキル（`/status` の利用で代替できる場合）

### 新スキル追加手順
1. このファイルの台帳に追加（担当領域が既存と被らないことを確認）
2. `.claude/commands/<name>.md` を作成
3. `CLAUDE.md` のスキルマップを更新
4. `/version` で変更を記録

---

## 重複スキャン（実行コマンド）

```python
python3 << 'PYEOF'
import pathlib, re

cmd_dir = pathlib.Path('.claude/commands')
agents = {}
for f in sorted(cmd_dir.glob('*.md')):
    text = f.read_text()
    ssh_lines = [l.strip() for l in text.splitlines() if 'ssh' in l.lower() and 'trade_log' in l.lower()]
    agents[f.stem] = len(ssh_lines)

print('=== SSH接続先別エージェント一覧 ===')
for name, cnt in agents.items():
    label = f'{cnt}件のログアクセス' if cnt > 0 else 'VMログアクセスなし'
    print(f'  /{name}: {label}')

# ファイル別重複チェック
files = {
    'state.json': [],
    'trade_log': [],
    'CONTROL.csv': [],
    'ai_model.json': [],
    'historical_ohlc': [],
    'KEIBA': [],
}
for f in sorted(cmd_dir.glob('*.md')):
    text = f.read_text()
    for key in files:
        if key in text:
            files[key].append(f.stem)

print()
print('=== データソース別担当エージェント ===')
for src, agents_list in files.items():
    status = '✅ 問題なし' if len(agents_list) <= 3 else '⚠️ 要確認' if len(agents_list) > 4 else '✅ 意図的共有'
    print(f'  {src}: {", ".join("/"+a for a in agents_list)} — {status}')
PYEOF
```

---

## スキルマップ更新履歴

| 日付 | 変更 | 担当セッション |
|------|------|-------------|
| 2026-04-26 | `/manage`, `/version` 新設 | session 14 |
| 2026-04-26 | `/keiba` 新設、`/status` に KEIBA 組み込み | session 12-13 |
| 2026-04-25 | `/backtest`, `/data`, `/filter` にA/Bテスト追加 | session 10 |
| 2026-04-22 | 全スキル初期整備 | session 1-4 |
