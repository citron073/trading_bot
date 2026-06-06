# /status — モーニングブリーフィング

**役割**: リスク・ログ・チャート・フィルターを1コマンドで一括確認する朝イチ総合レポート。

## 一括取得コマンド

```bash
TODAY=$(date +%Y%m%d)
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, json, pathlib, re, collections, sys
from datetime import datetime, timedelta

ROOT = pathlib.Path('/home/ubuntu/trading_bot/MAIN')
sys.path.insert(0, str(ROOT / 'tools'))
try:
    from state_schema_check import check_state as _check_state
    _schema_ok, _schema_items = _check_state(ROOT / 'state.json')
except Exception as _schema_e:
    _schema_ok, _schema_items = True, []
LOGS = pathlib.Path('/home/ubuntu/trading_bot/logs')
state = json.loads((ROOT / 'state.json').read_text())
ctrl = {}
for row in csv.reader((ROOT / 'CONTROL.csv').open()):
    if len(row) >= 2: ctrl[row[0].strip()] = row[1].strip()

now_str = datetime.now().strftime('%Y-%m-%d %H:%M JST')
print(f'【モーニングブリーフィング】{now_str}')
print('=' * 50)

# ── 1. リスク ──────────────────────────────────
collateral = state.get('_risk_day_start_jpy', 0) or 0
ltp = state.get('_last_ltp', 0) or 0
lot = 0.001
ratio = float(ctrl.get('fx_collateral_use_ratio', '0.90'))
required = lot * ltp / ratio if ltp > 0 else 0
margin = collateral - required
margin_pct = margin / required * 100 if required > 0 else 0
col_icon = '🟢' if margin >= 500 else '🟡' if margin >= 0 else '🔴'

daily_loss = state.get('_risk_daily_loss_jpy', 0) or 0
streak = state.get('_streak_losses', 0) or 0
streak_stop = bool(state.get('_streak_stop'))
daily_stop = bool(state.get('_daily_loss_stop'))
pos = state.get('position', 'none')
loss_icon = '🟢' if abs(daily_loss) < collateral * 0.01 else '🟡' if abs(daily_loss) < collateral * 0.015 else '🔴'
streak_icon = '🟢' if streak <= 1 else '🟡' if streak == 2 else '🔴'

print()
print('📊 リスク状態')
print(f'  {col_icon} 証拠金: {collateral:,.0f} JPY  必要: {required:,.0f} JPY  余裕: {margin:+,.0f} JPY ({margin_pct:+.1f}%)')
print(f'  {loss_icon} 日次損失: {daily_loss:+,.0f} JPY  streak_stop={streak_stop}  daily_stop={daily_stop}')
print(f'  {streak_icon} 連敗: {streak}回  ポジション: {pos}  LTP: {ltp:,.0f} JPY')

# ── 2. 今日のログ ──────────────────────────────
today_f = LOGS / f'trade_log_${TODAY}.csv'
results = {}
entries = []
filter_counts = collections.Counter()
if today_f.exists():
    for r in csv.reader(today_f.open()):
        if len(r) < 2: continue
        res = r[1]; note = r[-1] if r else ''
        results[res] = results.get(res, 0) + 1
        if res in ('CLOSE_BUY','CLOSE_SELL','PAPER_EXIT_TP','PAPER_EXIT_SL'): entries.append(r)
        if res == 'OBSERVE_BUY_FAST_MA_NEAR': filter_counts['ma_near'] += 1
        if res == 'OBSERVE_SELL_FAST_MA_NEAR': filter_counts['ma_near'] += 1
        if res == 'OBSERVE_TREND_STRENGTH_WEAK': filter_counts['trend_weak'] += 1
        if res == 'OBSERVE_AI_BLOCK': filter_counts['ai_block'] += 1

tp = sum(1 for r in entries if 'TP' in r[1])
sl = sum(1 for r in entries if 'SL' in r[1])
total = tp + sl
wr_str = f'{tp/total*100:.0f}%' if total > 0 else 'N/A'
obs_ok = results.get('OBSERVE_OK', 0)
unfilled = sum(1 for r in csv.reader(today_f.open()) if len(r) > 1 and r[1] == 'OBSERVE_OK' and 'entry_unfilled' in (r[-1] if r else '')) if today_f.exists() else 0

print()
print('📈 本日の取引')
print(f'  TP={tp} SL={sl} WR={wr_str}  OBSERVE_OK={obs_ok} (unfilled={unfilled})')
print(f'  ブロック: MA近={filter_counts[\"ma_near\"]} TW={filter_counts[\"trend_weak\"]} AI={filter_counts[\"ai_block\"]}')

# 7日間の勝率推移
print()
print('📅 直近7日 WR推移')
today_dt = datetime.now()
obs_ok_days_7 = 0
for i in range(7):
    d = today_dt - timedelta(days=i)
    f = LOGS / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    rows = list(csv.reader(f.open()))
    tp_d = sum(1 for r in rows if len(r)>1 and 'TP' in r[1])
    sl_d = sum(1 for r in rows if len(r)>1 and 'SL' in r[1])
    obs_ok_d = sum(1 for r in rows if len(r)>1 and r[1] == 'OBSERVE_OK')
    if obs_ok_d > 0: obs_ok_days_7 += 1
    tot = tp_d + sl_d
    wr_d = f'{tp_d/tot*100:.0f}%' if tot > 0 else 'N/A '
    icon = '🟢' if tot > 0 and tp_d/tot >= 0.44 else '🟡' if tot > 0 else '⚪'
    ok_str = f' OK={obs_ok_d}' if obs_ok_d > 0 else ''
    print(f'  {d.strftime(\"%m/%d\")} {icon} TP={tp_d} SL={sl_d} WR={wr_d}{ok_str}')

# ── 3. MR PAPER (7日) ─────────────────────────
print()
print('🎯 MR PAPER (7日)')
try:
    import csv as _csv
    from mr_observe_summary import build_summary as _mr_build, build_multi_day_summary as _mr_multi_fn, resolve_log_paths as _mr_paths_fn
    _MR_LOGS = ROOT.parent / 'logs' / 'instances' / 'mr_observe'
    _mr_day_sums = []
    for _p in _mr_paths_fn(_MR_LOGS, None, 7):
        if not _p.exists(): continue
        _rows = list(_csv.DictReader(_p.open(newline='', encoding='utf-8-sig')))
        _mr_day_sums.append(_mr_build(_rows, day8=_p.stem.replace('trade_log_', '')))
    _mr_tot = _mr_multi_fn(_mr_day_sums)
    _bd = _mr_tot.get('mr_paper_exit_breakdown', {})
    _entries = _mr_tot.get('mr_paper_entries_total', 0)
    _tp = _bd.get('tp_n', 0); _sl = _bd.get('sl_n', 0); _to = _bd.get('timeout_n', 0)
    _wr = _bd.get('wr_pct', 0.0)
    _rank_a = _mr_tot.get('mr_rank_counts', {}).get('A', 0)
    _mr_icon = '🟢' if _entries > 0 and _wr >= 50 else '🟡' if _entries > 0 else '⚪'
    print(f'  {_mr_icon} entries={_entries}  TP={_tp} SL={_sl} TIMEOUT={_to}  WR={_wr:.0f}%')
    print(f'  rank_A={_rank_a}  trigger_n={_mr_tot.get(\"mr_rank_a_trigger_n\", 0)}  reclaim_n={_mr_tot.get(\"mr_rank_a_reclaim_n\", 0)}')
except Exception as _mr_e:
    print(f'  ⚪ MR PAPER取得エラー: {_mr_e}')

# ── 4. チャート（市場文脈）────────────────────
ltp_hist = state.get('ltp_history', []) or []
def htf_bias(hist, n):
    if len(hist) < n: return 'N/A'
    tail = hist[-n:]
    gc = [tail[i*3:(i+1)*3][-1] for i in range(n//3) if tail[i*3:(i+1)*3]]
    if len(gc) < 3: return 'N/A'
    r = sum(1 for i in range(1,len(gc)) if gc[i]>gc[i-1]); f_ = len(gc)-1-r
    return 'UP' if r>f_ else 'DOWN' if f_>r else 'NEUTRAL'

lookback = int(ctrl.get('trend_strength_lookback_n', '20'))
er = None
if len(ltp_hist) >= lookback:
    tail = [float(x) for x in ltp_hist[-lookback:]]
    gross = sum(abs(tail[i]-tail[i-1]) for i in range(1,len(tail)))
    net = abs(tail[-1]-tail[0])
    er = round(net/gross, 3) if gross > 0 else 0.0

min_er = float(ctrl.get('trend_strength_min_er', '0.28'))
htf15 = htf_bias(ltp_hist, 9)
htf60 = htf_bias(ltp_hist, 36)
conflict = htf15 != htf60 and 'N/A' not in (htf15, htf60)
mp = state.get('_market_phase', {}) or {}

print()
print('🌐 市場文脈')
print(f'  HTF15={htf15}  HTF60={htf60}  競合={\"あり\" if conflict else \"なし\"}')
er_icon = '🟢' if er is not None and er >= min_er else '🟡' if er is not None else '⚪'
print(f'  {er_icon} ER={er} (閾値{min_er})  フェーズ={mp.get(\"phase\",\"N/A\")}  モメンタム={mp.get(\"momentum\",\"N/A\")}')
print(f'  トレンド={state.get(\"_trend_last\",\"N/A\")}  反転={state.get(\"_trend_flip_time_jst\",\"N/A\")}')

# ── 5. ops_checks ──────────────────────────────
ops = {}
ops_f = ROOT / '.ops_checks.json'
if ops_f.exists():
    try: ops = json.loads(ops_f.read_text())
    except: pass

print()
print('🔧 ops_checks')
for key in ['live_preflight', 'run_check.sh', 'fx_collateral']:
    v = ops.get(key, {})
    if not isinstance(v, dict): continue
    ok = v.get('ok', '?')
    at = v.get('updated_at', '?')
    icon = '🟢' if ok else '🔴'
    print(f'  {icon} {key}: ok={ok} at={at}')
_schema_icon = '🟢' if _schema_ok else '🔴'
_schema_errs = [m for lvl, m in _schema_items if lvl == 'ERROR']
_schema_warn = [m for lvl, m in _schema_items if lvl == 'WARN']
_schema_line = (_schema_errs or _schema_warn or ['valid'])[0][:60]
print(f'  {_schema_icon} state_schema: {_schema_line}')

# ── 6. 総合判定 ────────────────────────────────
print()
issues = []
if margin < 0: issues.append('証拠金不足')
if streak_stop: issues.append('連敗ストップ発動中')
if daily_stop: issues.append('日次損失ストップ中')
if conflict: issues.append('HTF競合あり(ペナルティ)')
if er is not None and er < min_er: issues.append(f'ER={er} チョッピー')
if filter_counts['ma_near'] > 10: issues.append(f'MA近接ブロック多発({filter_counts[\"ma_near\"]}件)')
if not today_f.exists(): issues.append('本日ログなし')
if not _schema_ok: issues.append('state.json schema ERROR')
if obs_ok_days_7 == 0: issues.append('7日連続OBSERVE_OK=0(EM休止中)')

status_str = '⚠️ 要注目: ' + ' / '.join(issues) if issues else '✅ 正常運転中'
print(f'【総合判定】{status_str}')
PYEOF"

# ── KEIBA ローカル状態（Mac上で実行） ──────────────────────────
python3 << 'LOCALEOF'
import json, csv, pathlib
from datetime import datetime

BASE = pathlib.Path('/Users/tani/trading_bot/trading_bot/KEIBA/data')
print()
print('🐎 KEIBA ローカル状態')

cyc = {}
if (BASE / 'auto_cycle_status.json').exists():
    try: cyc = json.loads((BASE / 'auto_cycle_status.json').read_text())
    except: pass

running = cyc.get('running', False)
last_ok = cyc.get('last_success')
last_at = cyc.get('last_completed_at', '-')
icon = '🟢' if not running and last_ok else '🔴' if last_ok is False else '🟡'
print(f'  {icon} 稼働: {"実行中" if running else "停止中"}  最終完了: {last_at}  成功: {last_ok}')

fb = BASE / 'prediction_feedback.csv'
if fb.exists():
    try:
        rows = list(csv.DictReader(open(fb)))
        done = [r for r in rows if r.get('result_available','').lower()=='true']
        hits = [r for r in done if r.get('top_horse_hit','').lower()=='true']
        wr = len(hits)/len(done)*100 if done else 0
        wr_icon = '🟢' if wr >= 50 else '🟡' if wr >= 35 else '🔴'
        print(f'  {wr_icon} 予測: {len(rows)}件  結果確認: {len(done)}件  1着的中: {wr:.1f}%')
    except: pass
else:
    print('  ⚪ prediction_feedback.csv なし')

summary = cyc.get('last_summary', '')
if summary:
    print(f'  📋 {summary[:120]}')
LOCALEOF
```

## 出力フォーマット例

```
【モーニングブリーフィング】2026-04-25 10:00 JST
==================================================

📊 リスク状態
  🟢 証拠金: 18,750 JPY  必要: 13,843 JPY  余裕: +4,907 JPY (+35.4%)
  🟢 日次損失: 0 JPY  streak_stop=False  daily_stop=False
  🟢 連敗: 0回  ポジション: none  LTP: 12,391,849 JPY

📈 本日の取引
  TP=0 SL=1 WR=N/A  OBSERVE_OK=0 (unfilled=0)
  ブロック: MA近=18 TW=0 AI=0

📅 直近7日 WR推移
  04/25 ⚪ TP=0 SL=1 WR=N/A
  04/24 🟢 TP=2 SL=2 WR=50%
  ...

🌐 市場文脈
  HTF15=NEUTRAL  HTF60=UP  競合=あり
  🟢 ER=0.473 (閾値0.28)  フェーズ=C  モメンタム=UP_BREAK
  トレンド=UP  反転=2026-04-25 16:47:42

🔧 ops_checks
  🟢 live_preflight: ok=True at=2026-04-25 09:45:00
  🟢 run_check.sh:   ok=True at=2026-04-25 17:30:01
  🟢 fx_collateral:  ok=True at=2026-04-25 09:45:00

【総合判定】⚠️ 要注目: HTF競合あり(ペナルティ) / MA近接ブロック多発(18件)

🐎 KEIBA ローカル状態
  🟢 稼働: 停止中  最終完了: 2026-04-26T06:49:03  成功: True
  🟢 予測: 52件  結果確認: 18件  1着的中: 55.6%
  📋 history 12,345行 / entries 234行 / 履歴 1,234R / 今週 52R / 学習 OFF
```
