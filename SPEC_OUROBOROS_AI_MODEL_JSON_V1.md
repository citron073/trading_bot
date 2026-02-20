# Project Ouroboros v1 — AI_MODEL.JSON SPEC v1（実装完全準拠）

============================================================
対象：MAIN/ai_model.json（Dashboardが編集、botが読む）
============================================================

------------------------------------------------------------
A. 読み取り契約
------------------------------------------------------------

| 項目 | 契約 |
|---|---|
| 無い場合 | AI_DEFAULT を使用 |
| 形式 | JSON object |
| deep merge | default と再帰マージ（unknown keys保持） |
| ai_mode正規化 | OFF/ADVISORY/FILTER/DECISION → bot内部 OFF/SCORE_ONLY/VETO/GATE |

------------------------------------------------------------
B. トップキー（AI_DEFAULT準拠）
------------------------------------------------------------

| key | 型 | 必須 | 説明 |
|---|---|---:|---|
| ai_enabled | bool | ✅ | AI全体ON/OFF |
| ai_mode | string | ✅ | OFF/ADVISORY/FILTER/DECISION |
| ai_weight | number | ✅ | 0.0〜1.0（botはclamp） |
| decision_points | object | ✅ | entry/exit/extend/skip |
| confidence_threshold | object | ✅ | entry/extend |
| ai_veto | object | ✅ | enabled/min_confidence |
| features | object | ✅ | use_ma/use_trend/use_spread/use_time/use_recent_winrate |
| model_info | object | ✅ | type/version/trained_on/last_updated |
| logging | object | ✅ | log_ai_decision/log_ai_score/log_ai_reason |

------------------------------------------------------------
C. 変更ルール
------------------------------------------------------------

- キー名変更は bot + Dashboard + SPEC 同時更新必須
- unknown keys は保持（破壊的変更禁止）

============================================================
END OF SPEC
============================================================
