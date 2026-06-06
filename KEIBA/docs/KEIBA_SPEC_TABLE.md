# KEIBA Spec Table

最終更新: 2026-05-31 JST

この表は、統合ダッシュボード `MAIN/tools/unified_dashboard.html` に表示する KEIBA 独立版の運用SPECです。
トレードBOT用の `MAIN/docs/OUROBOROS_TRADING_SPEC_TABLE.md` とは分離して管理します。

## 正とする表示経路

| 領域 | 現状 | 正の接続先 |
|---|---|---|
| 統合ダッシュボード | 実装済み | `MAIN/tools/unified_dashboard.html` |
| KEIBAステータスAPI | 実装済み | `http://127.0.0.1:8789/keiba-status.json` |
| KEIBAステータスサーバー | 実装済み | `KEIBA/keiba_status_server.py` |
| KEIBA本体UI | 実装済み | `KEIBA/app.py` / Streamlit |
| React化テンプレ | 足場のみ | `KEIBA/react_harness_template/` |

## 実装状況

| 領域 | 状態 | 主なファイル | ダッシュボード表示 |
|---|---|---|---|
| 競馬予想本体 | 実装済み | `app.py`, `predictor.py`, `auto_agent.py` | Streamlit側 |
| 今週予想UI | 分割済み | `ui_weekly.py` | Streamlit側 |
| サイドバーUI | 分割済み | `ui_sidebar.py` | Streamlit側 |
| アーカイブUI | 分割済み | `ui_archive.py` | Streamlit側 |
| 買い目UI | 分割済み | `ui_prediction.py` | Streamlit側 |
| 状態/CSV読込共通化 | 部分実装 | `state_store.py` | 間接反映 |
| 予想パイプライン共通化 | 部分実装 | `prediction_pipeline.py` | 間接反映 |
| LLMメモ軽量化 | 部分実装 | `llm_memory.py`, `data/archive/` | 間接反映 |
| 自動サイクル | 実装済み | `keiba_auto_cycle.py`, `data/auto_cycle_status.json` | KEIBAタブ |
| ステータスAPI | 実装済み | `keiba_status_server.py` | KEIBAタブ |
| 公開トンネル監視 | 実装済み | `keiba_public_healthcheck.sh`, `data/public_*.json` | Streamlit側中心 |
| Reactハーネステンプレ | 実装済み | `react_harness_template/` | まだ本番表示ではない |
| 無料ハーネス診断 | 実装済み | `auto_agent.py`, `data/prediction_harness_status.json` | KEIBAタブ |
| 手動結果CSV取り込み | 実装済み | `result_import.py`, `tools/import_manual_results.py`, `data/manual_results_template.csv` | KEIBAタブ |

## 現状との差分・注意点

| 項目 | 現状 | 対応方針 |
|---|---|---|
| `app.py` が大きい | まだ1万行超 | 壊さないため段階分割を継続 |
| データ配置 | `data/runtime`, `archive`, `cache`, `models` は存在。ただしCSVは直下にも残る | 互換維持のため即移動しない |
| Parquet高速化 | `data/cache/*.parquet` は存在 | CSV正本 + Parquetキャッシュ併用 |
| LLM運用 | 遅い時は自動で軽量化 | 全レースLLMコメントを必須にしない |
| Quick Tunnel | 起動ごとにURLが変わる | 固定URLはNamed Tunnel設定が必要 |
| 統合ダッシュボード | KEIBAタブはステータスAPI依存 | API未起動時はN/A表示 |
| 公開URL同期 | health結果が古い場合がある | 最新URLは `public_tunnel_status.json` を優先 |
| 無料ハーネス診断 | 予想票の不足は業務注意 | 例外ではなく次アクションとして表示 |
| netkeiba結果取得 | 回線によってブロックされる場合あり | ブロック検出 + 結果HTMLフォールバック + 手動CSV取り込みで回避 |

## 統合ダッシュボードに出すべき最小項目

| 表示項目 | データ元 | 目的 |
|---|---|---|
| 自動サイクル状態 | `auto_cycle_status.json` | 進行中/正常/エラーの判断 |
| 進捗率・フェーズ | `auto_cycle_status.json` | 止まっているかの判断 |
| 履歴レース数/行数 | `auto_cycle_status.json.report` | データ量の確認 |
| 今週予想数 | `auto_cycle_status.json.report` | 予想生成状況の確認 |
| 的中率/直近WR | `prediction_feedback.csv` | 学習・予想品質の確認 |
| 今週トップ予想 | `weekly_predictions_auto.csv` | すぐ見る予想 |
| スペック整合 | `keiba_status_server.py` の自己診断 | 仕様と現状のズレ確認 |
| 次にやること | `prediction_harness_status.json.planner` | 人が迷わない操作導線 |
| 不足データ | `prediction_harness_status.json.contract.issues` | 人気/オッズ/格付けなどの不足確認 |
| 今週範囲チェック | `weekly_predictions_auto.csv` | 今週外データを削除せず可視化 |
| ダッシュボード実行ボタン | `POST /actions/weekly-predictions` | 許可済みの今週AI予想更新だけ実行 |
| 実行中自動更新 | `action_status.running` | 実行中だけ5秒ごとに状態更新 |
| 今週0件注意 | `weekly_scope.current_week_races` | 今週予想が0件なら大きく更新誘導 |
| 更新完了通知 | `action_status.completed_at` + `top_weekly_predictions` | 本命/大穴/三連単候補を即確認 |
| 最優先不足 | `data_quality.shortage_items` | error優先、なければwarnを強調 |
| トップバー要更新 | `weekly_scope.current_week_races=0` | KEIBA要更新を常時表示 |
| 自動サイクル健全性 | `cycle_health` | 実行中/停止疑い/エラーを表示 |
| 取得失敗分類 | `action_status.failure` | 取得元未更新/通信失敗/解析失敗を表示 |
| 固定操作バー | `weekly_scope` + `entry_scope` | 今週0件時に更新ボタンを上部固定 |
| 自動サイクル再起動要求 | `POST /actions/restart-local-auto` | 停止疑い時のみLaunchAgentへ再起動要求 |
| 実行ログ | `action_status.logs` | 更新中の段階をダッシュボード表示 |
| レース一覧代替URL | `auto_data_ingest.py` | netkeiba race_list_sub に加え race_list も試す |
| 手動更新の進捗 | `action_status.progress_pct/logs` | 今週データ更新中の待ち状態を可視化 |
| 手動更新タイムアウト | `dashboard_action_status.json` | 長時間進捗なしなら停止疑いに読み替える |
| 今週出走表優先更新 | `keiba_auto_cycle.py` | 今週0R時は履歴取得より先に出走表を更新 |
| 結果待ち理由 | `prediction_harness_status.json.evaluator` | history_auto未反映のpending_dueをレース例つきで表示 |
| 手動結果CSV反映 | `POST /actions/import-manual-results` | `data/manual_results.csv` を履歴/採点/ハーネスへ反映 |

## 変更時ルール

- 統合ダッシュボードに出す項目を増やす場合は、まず `keiba_status_server.py` のJSONに後方互換で追加する。
- `unified_dashboard.html` は追加フィールドが無い場合でも落ちないようにする。
- `MAIN/docs/OUROBOROS_TRADING_SPEC_TABLE.md` はトレード用なので、KEIBA変更では原則更新しない。
- KEIBA側の構成・運用・表示経路を変えたら、このファイルを更新する。
- CSVの列名削除・改名は禁止。必要な場合は新列追加で互換を保つ。
- スペック整合は「システムが壊れているか」を見る。予想票の不足やオッズ未取得は `WARN` ではなく次アクションで扱う。
- 今週外の予想データは勝手に削除しない。統合ダッシュボードでは範囲外件数として表示し、必要時だけ再生成へ誘導する。
- 今週出走表が0件の場合、`POST /actions/weekly-predictions` は先に出走表を軽量更新してから予想生成する。
- 予想の最新判定はファイル更新時刻だけでなく、今週範囲のレースが含まれるかも見る。
- 自動サイクルは状態ファイルを直接修正せず、`cycle_health` として読み替えて表示する。
- 取得失敗は可能な範囲で `取得元未更新` / `通信失敗` / `解析失敗` に分類し、次に待つべきか再実行すべきか判断しやすくする。
- 自動サイクル再起動は `cycle_health.state=stale` の時だけ許可する。通常実行中や正常時は何もしない。
- レース一覧取得は既存取得元を優先し、失敗時だけ代替URLを試す。取得済みCSVの削除や改名はしない。
- 統合ダッシュボードから実行できる処理は許可済みアクションだけに限定する。任意コマンド実行は禁止。
- 実行ボタンはバックグラウンド開始に留め、結果は `dashboard_action_status.json` と `keiba-status.json` で確認する。
- `KEIBA_DASHBOARD_ACTION_TOKEN` が設定されている場合、POST実行には同じBearer tokenまたは `X-KEIBA-Action-Token` が必要。
- ダッシュボード設定の `KEIBA Action Token` は任意。未設定ならローカル運用を優先して従来通り動作する。
- 手動更新アクションは進捗ログを `dashboard_action_status.json` に残す。20分以上進捗更新がない場合は停止疑いとして扱う。
- 自動サイクルは今週範囲の出走表が0Rの場合、`--skip-entries` 指定中でも出走表更新を優先し、重い履歴取得は後回しにする。
- 結果取得元がブロックされる場合、`data/manual_results.csv` を使って結果を反映する。テンプレートは `data/manual_results_template.csv`。
- 手動結果CSVの必須列は `race_id,winner,second,third`。任意列として `race_date,venue,race_name,weather,track_condition,distance,*_jockey,*_gate,*_odds` を受け付ける。
