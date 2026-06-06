# /version — バージョン確認・記録エージェント

**役割**: システム変更の前後にバージョンを確認し、スペック表（`MAIN/docs/OUROBOROS_TRADING_SPEC_TABLE.md`）と `HANDOVER.md` に記録する。  
**必須ルール**: `bot.py` / `dashboard.py` / `widget_status.py` / `bot.py`（feature schema）に変更を加える場合は、このコマンドを **変更前** と **変更後** に実行する。

---

## Step 1: 変更前の現バージョン確認（VM + ローカル）

```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import re, pathlib

def extract(path, pattern, default='N/A'):
    try:
        text = pathlib.Path(path).read_text()
        m = re.search(pattern, text)
        return m.group(1) if m else default
    except:
        return default

ROOT = pathlib.Path('/home/ubuntu/trading_bot/MAIN')
bot_ver    = extract(ROOT/'bot.py', r'OUROBOROS_BOT_VERSION\s*=\s*\"([^\"]+)\"')
schema_ver = extract(ROOT/'bot.py', r'OUROBOROS_FEATURE_SCHEMA_VERSION\s*=\s*\"([^\"]+)\"')
dash_ver   = extract(ROOT/'dashboard.py', r'APP_VERSION\s*=\s*\"([^\"]+)\"')
widget_ver = extract(ROOT/'tools/widget_status.py', r'WIDGET_SERVER_VERSION\s*=\s*\"([^\"]+)\"')

print('=== 現在のバージョン ===')
print(f'bot_logic:      {bot_ver}')
print(f'feature_schema: {schema_ver}')
print(f'dashboard:      {dash_ver}')
print(f'widget_server:  {widget_ver}')

# スペック表の最終更新日
spec = pathlib.Path(ROOT/'docs/OUROBOROS_TRADING_SPEC_TABLE.md')
if spec.exists():
    m = re.search(r'最終更新:\s*(.+)', spec.read_text())
    print(f'spec_table_updated: {m.group(1).strip() if m else \"N/A\"}')
print()
print('--- 変更前バージョンをメモしてください ---')
PYEOF"
```

---

## Step 2: 変更後の新バージョン記録

変更が完了したら以下を実行してスペック表を更新する。

### 2a. スペック表ヘッダー更新（ローカル）

スペック表ファイル: `MAIN/docs/OUROBOROS_TRADING_SPEC_TABLE.md`

更新箇所（ファイル先頭3行）:
```
最終更新: YYYY-MM-DD JST
実装バージョン: `OUROBOROS_BOT_VERSION=X.X.X`（変更内容の要約）/ ...
ダッシュボードバージョン: `APP_VERSION=vX.X.X`
特徴量スキーマ: `OUROBOROS_FEATURE_SCHEMA_VERSION=...`
```

### 2b. 実装状況テーブルに行を追加（ローカル）

`MAIN/docs/OUROBOROS_TRADING_SPEC_TABLE.md` の「実装状況」テーブルに変更した機能を追記:
```
| 機能名 | 実装済み（YYYY-MM-DD追加） | 関連設定キー | note/state | 安全ゲート |
```

### 2c. HANDOVER.md に新セクション追加

`MAIN/HANDOVER.md` の最新 `3-0X` セクションに実装内容を記録する（`/version` 自体のコマンドではなく、次の実装セッションで行う）。

---

## Step 3: バージョン整合性チェック

```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import re, pathlib, json

ROOT = pathlib.Path('/home/ubuntu/trading_bot/MAIN')

def extract(path, pattern, default='N/A'):
    try:
        text = pathlib.Path(path).read_text()
        m = re.search(pattern, text)
        return m.group(1) if m else default
    except:
        return default

# VM実体
bot_ver    = extract(ROOT/'bot.py', r'OUROBOROS_BOT_VERSION\s*=\s*\"([^\"]+)\"')
schema_ver = extract(ROOT/'bot.py', r'OUROBOROS_FEATURE_SCHEMA_VERSION\s*=\s*\"([^\"]+)\"')
dash_ver   = extract(ROOT/'dashboard.py', r'APP_VERSION\s*=\s*\"([^\"]+)\"')
widget_ver = extract(ROOT/'tools/widget_status.py', r'WIDGET_SERVER_VERSION\s*=\s*\"([^\"]+)\"')

# HANDOVER.json (widget_status がサーブするバージョン群)
handover_f = ROOT / 'HANDOVER.json'
handover = {}
if handover_f.exists():
    try: handover = json.loads(handover_f.read_text()).get('versions', {})
    except: pass

h_bot    = handover.get('bot_logic', 'N/A')
h_schema = handover.get('feature_schema', 'N/A')
h_dash   = handover.get('dashboard', 'N/A')

print('=== バージョン整合性チェック ===')
def check(label, actual, recorded):
    ok = '✅' if actual == recorded or recorded == 'N/A' else '⚠️ 不一致'
    print(f'  {ok} {label}: 実体={actual}  HANDOVER.json={recorded}')

check('bot_logic',      bot_ver,    h_bot)
check('feature_schema', schema_ver, h_schema)
check('dashboard',      dash_ver,   h_dash)
print(f'  ℹ️  widget_server: {widget_ver}  (HANDOVER.jsonに含まれない場合もあり)')

# スペック表バージョン vs 実体
spec = ROOT / 'docs/OUROBOROS_TRADING_SPEC_TABLE.md'
if spec.exists():
    spec_text = spec.read_text()
    s_bot = re.search(r'OUROBOROS_BOT_VERSION=([^\`\"]+)', spec_text)
    s_dash = re.search(r'APP_VERSION=([^\`\"]+)', spec_text)
    spec_bot = s_bot.group(1).strip() if s_bot else 'N/A'
    spec_dash = s_dash.group(1).strip() if s_dash else 'N/A'
    print()
    print('=== スペック表との照合 ===')
    check_s = lambda lbl, act, rec: print(f'  {\"✅\" if act==rec else \"⚠️ 不一致\"} {lbl}: 実体={act}  spec_table={rec}')
    check_s('bot_logic',  bot_ver,  spec_bot)
    check_s('dashboard',  dash_ver, spec_dash)
PYEOF"
```

---

## バージョン管理ルール

| コンポーネント | バージョン変数 | バージョンアップのタイミング |
|-------------|-------------|--------------------------|
| `bot.py` 売買ロジック | `OUROBOROS_BOT_VERSION` | エントリー/エグジット判定ロジック変更時 |
| `bot.py` 特徴量スキーマ | `OUROBOROS_FEATURE_SCHEMA_VERSION` | note/state に新フィールドを追加した時 |
| `dashboard.py` | `APP_VERSION` | 表示・UI・API の変更時 |
| `widget_status.py` | `WIDGET_SERVER_VERSION` | API レスポンス形式変更時 |

### バージョン番号の形式

- `bot.py`: `YYYY.MM.DD.N`（例: `2026.04.26.1`）— 同日複数変更は `.N` でインクリメント
- `dashboard.py`: `vX.Y.Z` セマンティックバージョニング（例: `v1.2.0`）
- `widget_status.py`: `OuroborosWidget/X.Y`（例: `OuroborosWidget/1.1`）

### 変更が不要なケース
- CONTROL.csv パラメータの数値変更のみ（コードは変わらない）
- `HANDOVER.md` / ドキュメントのみの更新
- スキルファイル（`.claude/commands/*.md`）のみの更新

---

## 出力フォーマット例

```
=== 現在のバージョン ===
bot_logic:      2026.04.18.3
feature_schema: ohlc-chart-pattern-quality-...-v1
dashboard:      v1.1.9
widget_server:  OuroborosWidget/1.0

=== バージョン整合性チェック ===
  ✅ bot_logic:      実体=2026.04.18.3  HANDOVER.json=2026.04.18.3
  ✅ feature_schema: 実体=ohlc-...      HANDOVER.json=ohlc-...
  ✅ dashboard:      実体=v1.1.9        HANDOVER.json=v1.1.9

=== スペック表との照合 ===
  ✅ bot_logic:  実体=2026.04.18.3  spec_table=2026.04.18.3
  ✅ dashboard:  実体=v1.1.9        spec_table=v1.1.9
```
