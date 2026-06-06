from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from note_cms.agent_store import AgentConfigStore
from note_cms.checker import ConsistencyChecker
from note_cms.generator import ArticleGenerator
from note_cms.linker import (
    apply_internal_links_to_text,
    build_internal_link_preview,
    extract_note_url,
    find_internal_link_matches,
    suggest_related_links,
)
from note_cms.marketing_store import MarketingDataStore
from note_cms.models import ArticleRecord, STATUS_DRAFT
from note_cms.settings_store import SettingsStore
from note_cms.source_importer import expand_batch_sources, import_text, source_ref_for_preview, _extract_html_text
from note_cms.storage import CSVArticleStore, normalize_google_csv_url
from note_cms.sync_log_store import SyncLogStore
from note_cms.template_store import TemplateConfigStore
from note_cms.web import (
    _apply_agent_defaults,
    _auto_assist_record_links,
    _article_from_atom,
    _import_marketing_source_item,
    _preview_marketing_source_item,
    _retry_marketing_import_history,
)
from note_cms.x_client import XClient


def _load_central_skill_module():
    path = Path(__file__).resolve().parents[1] / "MAIN" / "tools" / "note_cms_central_skill.py"
    spec = importlib.util.spec_from_file_location("note_cms_central_skill_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load note_cms_central_skill.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NoteCMSTest(unittest.TestCase):
    def test_store_upsert_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVArticleStore(Path(tmp) / "articles.csv")
            record = ArticleRecord(
                verification_id="N-20260416-001",
                title="テスト記事",
                topic="CMS検証",
                writer_agent="writer_main",
            )

            store.upsert(record)
            records = store.list_records()

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].verification_id, "N-20260416-001")
            self.assertEqual(records[0].title, "テスト記事")
            self.assertEqual(records[0].writer_agent, "writer_main")

    def test_generator_keeps_unknowns_visible(self) -> None:
        record = ArticleRecord(
            verification_id="N-20260416-001",
            title="検証記事",
            topic="note運用",
            source_numbers="10分; 15分",
            facts="note投稿は手動",
            unknowns="X APIの権限",
            angle="完全自動にしない",
            cta="コメントで教えてください。",
        )

        draft = ArticleGenerator().generate_draft(record)

        self.assertEqual(record.status, STATUS_DRAFT)
        self.assertIn("まだ不明なこと", draft)
        self.assertIn("X APIの権限", draft)

    def test_checker_flags_unsourced_number(self) -> None:
        record = ArticleRecord(
            verification_id="N-20260416-001",
            source_numbers="10分",
            facts="検証済み",
            unknowns="出典日",
            cta="コメントで教えてください。",
            final="10分で作れます。20分かかる可能性もあります。コメントで教えてください。",
        )

        report = ConsistencyChecker().report(record)

        self.assertIn("数値矛盾", report)
        self.assertIn("20", report)

    def test_x_post_is_short(self) -> None:
        record = ArticleRecord(
            verification_id="N-20260416-001",
            title="長いタイトル" * 40,
            angle="事実と推測を分ける",
            note_url="https://note.com/example/n/test",
        )

        text = ArticleGenerator().generate_x_post(record, max_chars=140)

        self.assertLessEqual(len(text), 140)
        self.assertIn("https://note.com/example/n/test", text)

    def test_x_post_uses_reuse_tag_hint(self) -> None:
        record = ArticleRecord(
            verification_id="N-20260416-001",
            title="再掲記事",
            reuse_tag="再利用候補",
            note_url="https://note.com/example/n/reuse",
        )

        text = ArticleGenerator().generate_x_post(record, max_chars=160)

        self.assertIn("過去記事", text)
        self.assertIn("https://note.com/example/n/reuse", text)

    def test_internal_linker_extracts_url_and_links_matching_titles(self) -> None:
        past = ArticleRecord(
            verification_id="N-20260420-001",
            title="AI記事の作り方",
            note_url="https://note.com/tani/n/ai_article",
        )
        text = "詳しくはAI記事の作り方で整理しました。公開URL https://note.com/tani/n/new_article"

        matches = find_internal_link_matches(text, [past], current_id="N-20260421-001")
        linked, count = apply_internal_links_to_text(text, matches)

        self.assertEqual(extract_note_url(text), "https://note.com/tani/n/new_article")
        self.assertEqual(count, 1)
        self.assertIn("[AI記事の作り方](https://note.com/tani/n/ai_article)", linked)

    def test_auto_assist_record_links_adds_note_url_and_related_cta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVArticleStore(Path(tmp) / "articles.csv")
            store.upsert(
                ArticleRecord(
                    verification_id="N-20260420-001",
                    title="過去記事タイトル",
                    note_url="https://note.com/tani/n/past",
                    status="投稿済み",
                )
            )
            record = ArticleRecord(
                verification_id="N-20260421-001",
                title="新しい記事",
                final="今回は過去記事タイトルを前提に整理します。\nhttps://note.com/tani/n/new",
                cta="",
            )

            summary = _auto_assist_record_links(record, store)

            self.assertTrue(summary["note_url_filled"])
            self.assertEqual(record.note_url, "https://note.com/tani/n/new")
            self.assertIn("[過去記事タイトル](https://note.com/tani/n/past)", record.final)
            self.assertIn("[過去記事タイトル](https://note.com/tani/n/past)", record.cta)

    def test_auto_assist_record_links_uses_same_title_as_related_article(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVArticleStore(Path(tmp) / "articles.csv")
            store.upsert(
                ArticleRecord(
                    verification_id="N-20260420-001",
                    title="同じタイトル",
                    note_url="https://note.com/tani/n/same_title",
                    status="投稿済み",
                )
            )
            record = ArticleRecord(
                verification_id="N-20260421-001",
                title="同じタイトル",
                final="新しく公開する本文です。",
            )

            summary = _auto_assist_record_links(record, store)

            self.assertEqual(summary["cta_links_appended"], 1)
            self.assertIn("[同じタイトル](https://note.com/tani/n/same_title)", record.cta)

    def test_internal_link_preview_suggests_related_articles(self) -> None:
        current = ArticleRecord(
            verification_id="N-20260422-001",
            title="note運用を半自動化する方法",
            topic="note CMS",
            facts="URL管理と内部リンクを自動化する",
            angle="人がやらなくていい作業を減らす",
        )
        related = ArticleRecord(
            verification_id="N-20260420-001",
            title="note CMSでURL管理を楽にする",
            topic="note CMS",
            facts="URL管理と記事導線の整備",
            note_url="https://note.com/tani/n/url_manage",
        )

        suggestions = suggest_related_links(current, [related], current_id=current.verification_id)
        preview = build_internal_link_preview(current, [related])

        self.assertEqual(suggestions[0].verification_id, "N-20260420-001")
        self.assertFalse(preview["suggestions"][0]["exact"])
        self.assertIn("共通キーワード", preview["suggestions"][0]["reason"])

    def test_auto_assist_record_links_appends_related_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVArticleStore(Path(tmp) / "articles.csv")
            store.upsert(
                ArticleRecord(
                    verification_id="N-20260420-001",
                    title="note CMSでURL管理を楽にする",
                    topic="note CMS",
                    facts="URL管理と記事導線の整備",
                    note_url="https://note.com/tani/n/url_manage",
                )
            )
            record = ArticleRecord(
                verification_id="N-20260422-001",
                title="note運用を半自動化する方法",
                topic="note CMS",
                facts="URL管理と内部リンクを自動化する",
                angle="人がやらなくていい作業を減らす",
            )

            summary = _auto_assist_record_links(record, store)

            self.assertEqual(summary["related_links_appended"], 1)
            self.assertIn("関連して読める記事", record.cta)
            self.assertIn("[note CMSでURL管理を楽にする](https://note.com/tani/n/url_manage)", record.cta)

    def test_google_edit_url_converts_to_csv_url(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/abc123/edit#gid=456"

        normalized = normalize_google_csv_url(url)

        self.assertEqual(
            normalized,
            "https://docs.google.com/spreadsheets/d/abc123/gviz/tq?tqx=out%3Acsv&gid=456",
        )

    def test_x_client_dry_run(self) -> None:
        result = XClient().post_text("テスト投稿", dry_run=True)

        self.assertTrue(result.dry_run)
        self.assertEqual(result.post_id, "DRY_RUN")
        self.assertEqual(result.text, "テスト投稿")

    def test_template_store_merges_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TemplateConfigStore(Path(tmp) / "templates.json")

            saved = store.save(
                {
                    "active_set": "verification",
                    "sets": {
                        "verification": {
                            "cta": "コメント歓迎",
                        }
                    },
                }
            )
            loaded = store.load()

            self.assertEqual(saved["active_set"], "verification")
            self.assertEqual(loaded["sets"]["verification"]["cta"], "コメント歓迎")
            self.assertIn("conclusion", loaded["sets"]["standard"])
            self.assertIn("x_post", loaded["sets"]["quick"])

    def test_csv_store_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVArticleStore(Path(tmp) / "articles.csv")
            store.upsert(ArticleRecord(verification_id="N-20260425-001", title="バックアップ"))

            backup = store.create_backup(label="test")

            self.assertTrue(backup.exists())
            self.assertEqual(backup.parent.name, "backups")
            self.assertIn("test", backup.name)

    def test_import_rows_with_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVArticleStore(Path(tmp) / "articles.csv")
            store.upsert(ArticleRecord(verification_id="N-20260425-001", title="旧タイトル"))

            stats = store.import_rows_with_stats(
                [
                    {"verification_id": "N-20260425-001", "title": "新タイトル"},
                    {"verification_id": "N-20260425-002", "title": "新規"},
                ]
            )

            self.assertEqual(stats["total"], 2)
            self.assertEqual(stats["updated"], 1)
            self.assertEqual(stats["new"], 1)
            self.assertEqual(stats["changed"], 2)

    def test_preview_import_rows_does_not_mutate_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVArticleStore(Path(tmp) / "articles.csv")
            store.upsert(ArticleRecord(verification_id="N-20260425-001", title="旧タイトル"))
            store.upsert(ArticleRecord(verification_id="N-20260425-002", title="削除候補"))

            preview = store.preview_import_rows(
                [
                    {"verification_id": "N-20260425-001", "title": "新タイトル"},
                    {"verification_id": "N-20260425-003", "title": "新規"},
                ]
            )
            records = {record.verification_id: record for record in store.list_records()}

            self.assertEqual(preview["total"], 2)
            self.assertEqual(preview["new"], 1)
            self.assertEqual(preview["updated"], 1)
            self.assertEqual(preview["removed"], 1)
            self.assertEqual(records["N-20260425-001"].title, "旧タイトル")
            self.assertIn("N-20260425-002 | 削除候補", preview["samples"]["removed"])

    def test_restore_backup_restores_previous_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVArticleStore(Path(tmp) / "articles.csv")
            store.upsert(ArticleRecord(verification_id="N-20260425-001", title="最初"))
            backup = store.create_backup(label="restoretest")

            store.upsert(ArticleRecord(verification_id="N-20260425-001", title="更新後"))

            restored, pre_restore = store.restore_backup(backup.name)
            record = store.get("N-20260425-001")

            self.assertEqual(restored.name, backup.name)
            self.assertTrue(pre_restore.exists())
            self.assertEqual(record.title, "最初")

    def test_preview_backup_diff_reports_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVArticleStore(Path(tmp) / "articles.csv")
            store.upsert(ArticleRecord(verification_id="N-20260425-001", title="最初"))
            backup = store.create_backup(label="preview")

            store.upsert(ArticleRecord(verification_id="N-20260425-001", title="更新後"))
            store.upsert(ArticleRecord(verification_id="N-20260425-002", title="追加"))

            preview = store.preview_backup_diff(backup.name)

            self.assertEqual(preview["current_only_count"], 1)
            self.assertEqual(preview["changed_count"], 1)
            self.assertEqual(preview["backup_only_count"], 0)
            self.assertIn("N-20260425-002 | 追加", preview["samples"]["current_only"])
            self.assertIn("N-20260425-001 | 更新後", preview["samples"]["changed"])

    def test_settings_store_persists_google_sheet_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SettingsStore(Path(tmp) / "settings.json")

            saved = store.save(
                {
                    "google_sheet_url": " https://docs.google.com/spreadsheets/d/demo/edit#gid=0 ",
                    "last_google_sync_at": " 2026-04-25T18:40:00 ",
                    "last_google_sync_summary": " 新規1 / 更新2 ",
                }
            )
            loaded = store.load()

            self.assertEqual(
                saved["google_sheet_url"],
                "https://docs.google.com/spreadsheets/d/demo/edit#gid=0",
            )
            self.assertEqual(loaded["google_sheet_url"], saved["google_sheet_url"])
            self.assertEqual(loaded["last_google_sync_at"], "2026-04-25T18:40:00")
            self.assertEqual(loaded["last_google_sync_summary"], "新規1 / 更新2")

    def test_sync_log_store_keeps_latest_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SyncLogStore(Path(tmp) / "sync_history.json")

            store.append(
                {
                    "occurred_at": "2026-04-25T19:00:00",
                    "source_label": "保存URL同期",
                    "status": "success",
                    "summary": "新規1",
                    "backup_path": "",
                    "error_message": "",
                }
            )
            store.append(
                {
                    "occurred_at": "2026-04-25T20:00:00",
                    "source_label": "差分取込",
                    "status": "error",
                    "summary": "更新2",
                    "backup_path": "note_cms_data/backups/sample.csv",
                    "error_message": "timeout",
                }
            )

            items = store.load()

            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["occurred_at"], "2026-04-25T20:00:00")
            self.assertEqual(items[0]["backup_path"], "note_cms_data/backups/sample.csv")
            self.assertEqual(items[0]["status"], "error")
            self.assertEqual(items[0]["error_message"], "timeout")

    def test_agent_store_normalizes_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AgentConfigStore(Path(tmp) / "agents.json")

            saved = store.save(
                {
                    "agents": [
                        {
                            "id": "writer_alt",
                            "label": "別の生成担当",
                            "role": "writer",
                            "enabled": True,
                            "default_template_set": "standard",
                            "command_key": "generate",
                        },
                        {
                            "id": "checker_off",
                            "label": "停止中",
                            "role": "checker",
                            "enabled": False,
                            "default_template_set": "verification",
                            "command_key": "check",
                        },
                    ],
                    "default_assignments": {
                        "writer": "writer_alt",
                        "checker": "checker_off",
                    },
                }
            )

            self.assertEqual(saved["default_assignments"]["writer"], "writer_alt")
            self.assertEqual(saved["default_assignments"]["checker"], "checker_main")
            self.assertTrue(any(agent["id"] == "publisher_main" for agent in saved["agents"]))

    def test_apply_agent_defaults_sets_article_assignments(self) -> None:
        record = ArticleRecord(verification_id="N-20260426-001")

        _apply_agent_defaults(
            record,
            {
                "default_assignments": {
                    "writer": "writer_main",
                    "checker": "checker_main",
                    "publisher": "publisher_main",
                    "x": "x_main",
                }
            },
        )

        self.assertEqual(record.writer_agent, "writer_main")
        self.assertEqual(record.checker_agent, "checker_main")
        self.assertEqual(record.publisher_agent, "publisher_main")
        self.assertEqual(record.x_agent, "x_main")

    def test_marketing_store_initializes_shared_csv_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketingDataStore(Path(tmp) / "marketing")

            store.ensure()
            context = store.context()

            self.assertTrue(store.atoms_path.exists())
            self.assertTrue(store.pipeline_path.exists())
            self.assertTrue(store.outputs_path.exists())
            self.assertTrue(store.import_history_path.exists())
            self.assertEqual(context["stats"]["atoms_total"], 0)
            self.assertIn("atoms.csv", context["data_layer"]["atoms_csv"])
            self.assertIn("import_history.json", context["data_layer"]["import_history_json"])
            self.assertTrue(any(layer["id"] == "quality" for layer in context["layers"]))

    def test_marketing_store_creates_atom_output_and_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketingDataStore(Path(tmp) / "marketing")

            atom = store.create_atom(
                {
                    "title": "AI活用メモ",
                    "summary": "1人マーケ部門の運用メモ",
                    "evidence": "PDFから抽出",
                    "suggested_channels": "note,x",
                }
            )
            output = store.create_output(
                {
                    "atom_id": atom["atom_id"],
                    "channel": "note",
                    "title": "AI活用メモ",
                    "url": "https://note.com/example",
                    "impressions": "100",
                    "engagements": "12",
                }
            )
            review = store.week_review()

            self.assertTrue(atom["atom_id"].startswith("A-"))
            self.assertTrue(output["output_id"].startswith("O-"))
            self.assertEqual(review["total_engagements"], 12)
            self.assertEqual(store.stats()["outputs_total"], 1)

    def test_marketing_store_records_import_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketingDataStore(Path(tmp) / "marketing")

            row = store.append_import_history(
                {
                    "kind": "text",
                    "source_label": "pasted",
                    "create_article": True,
                    "items": [
                        {"status": "created", "source": "A", "atom_id": "A-1", "record_id": "N-1", "error": ""},
                        {"status": "duplicate", "source": "B", "atom_id": "A-2", "record_id": "", "error": ""},
                        {"status": "error", "source": "C", "atom_id": "", "record_id": "", "error": "failed"},
                    ],
                }
            )
            history = store.list_import_history()

            self.assertEqual(row["summary"]["total"], 3)
            self.assertEqual(row["summary"]["created"], 1)
            self.assertEqual(row["summary"]["duplicate"], 1)
            self.assertEqual(row["summary"]["error"], 1)
            self.assertEqual(history[0]["kind"], "text")

    def test_marketing_store_skips_duplicate_source_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MarketingDataStore(Path(tmp) / "marketing")

            first, first_created = store.create_atom_once(
                {
                    "title": "同じURL",
                    "summary": "最初",
                    "source_url": "https://example.com/a",
                }
            )
            second, second_created = store.create_atom_once(
                {
                    "title": "同じURLの再読込",
                    "summary": "二回目",
                    "source_url": "https://example.com/a",
                }
            )

            self.assertTrue(first_created)
            self.assertFalse(second_created)
            self.assertEqual(first["atom_id"], second["atom_id"])
            self.assertEqual(store.stats()["atoms_total"], 1)

    def test_article_from_atom_keeps_source_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_store = CSVArticleStore(Path(tmp) / "articles.csv")
            atom = {
                "atom_id": "A-20260427-001",
                "source_type": "manual",
                "title": "検証テーマ",
                "summary": "読者の判断材料を整理する",
                "evidence": "確認済みメモ",
                "source_url": "https://example.com/source",
            }

            record = _article_from_atom(article_store, atom)

            self.assertEqual(record.title, "検証テーマ")
            self.assertEqual(record.template_set, "verification")
            self.assertIn("A-20260427-001", record.memo)
            self.assertIn("確認済みメモ", record.facts)

    def test_import_text_creates_atom_payload(self) -> None:
        imported = import_text(
            """
            過去記事の見出し

            確認できている事実を整理します。数値はあとで確認します。
            不明点は公開前に残します。
            """
        )
        payload = imported.to_atom_payload()

        self.assertEqual(payload["source_type"], "text")
        self.assertEqual(payload["title"], "過去記事の見出し")
        self.assertIn("確認できている事実", payload["summary"])
        self.assertEqual(payload["status"], "imported")

    def test_expand_batch_sources_supports_url_list_and_pdf_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "a.pdf").write_bytes(b"%PDF-1.4\n")
            (folder / "b.txt").write_text("ignore", encoding="utf-8")

            urls = expand_batch_sources("url_list", "1. https://example.com/a\n- https://example.com/b\n")
            pdfs = expand_batch_sources("pdf_folder", str(folder))

            self.assertEqual(urls, [("url", "https://example.com/a"), ("url", "https://example.com/b")])
            self.assertEqual(len(pdfs), 1)
            self.assertEqual(pdfs[0][0], "pdf")
            self.assertTrue(pdfs[0][1].endswith("a.pdf"))

    def test_source_ref_for_preview_does_not_fetch_url(self) -> None:
        ref = source_ref_for_preview("url", "https://example.com/article")

        self.assertEqual(ref, "https://example.com/article")

    def test_preview_marketing_source_item_reports_new_and_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_store = CSVArticleStore(Path(tmp) / "articles.csv")
            marketing_store = MarketingDataStore(Path(tmp) / "marketing")

            first = _preview_marketing_source_item(
                article_store,
                marketing_store,
                "text",
                "過去記事タイトル\n\n本文です。",
            )
            marketing_store.create_atom(
                {
                    "title": "過去記事タイトル",
                    "summary": "本文です。",
                    "source_url": first["source_ref"],
                }
            )
            second = _preview_marketing_source_item(
                article_store,
                marketing_store,
                "text",
                "過去記事タイトル\n\n本文です。",
            )

            self.assertEqual(first["status"], "new")
            self.assertEqual(second["status"], "duplicate")
            self.assertTrue(second["atom_id"].startswith("A-"))

    def test_import_marketing_source_item_deduplicates_text_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_store = CSVArticleStore(Path(tmp) / "articles.csv")
            marketing_store = MarketingDataStore(Path(tmp) / "marketing")
            agent_store = AgentConfigStore(Path(tmp) / "agents.json")
            agent_store.save({})

            first = _import_marketing_source_item(
                article_store,
                agent_store,
                marketing_store,
                "text",
                "過去記事タイトル\n\n本文です。",
                True,
            )
            second = _import_marketing_source_item(
                article_store,
                agent_store,
                marketing_store,
                "text",
                "過去記事タイトル\n\n本文です。",
                True,
            )

            self.assertEqual(first["status"], "created")
            self.assertEqual(second["status"], "duplicate")
            self.assertEqual(marketing_store.stats()["atoms_total"], 1)
            self.assertEqual(len(article_store.list_records()), 1)

    def test_retry_marketing_import_history_replays_failed_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article_store = CSVArticleStore(Path(tmp) / "articles.csv")
            marketing_store = MarketingDataStore(Path(tmp) / "marketing")
            agent_store = AgentConfigStore(Path(tmp) / "agents.json")
            agent_store.save({})

            history_row = marketing_store.append_import_history(
                {
                    "kind": "text",
                    "source_label": "manual batch",
                    "create_article": True,
                    "items": [
                        {
                            "status": "error",
                            "source": "再実行タイトル\n\n本文です。",
                            "source_ref": "pasted_text:retry",
                            "atom_id": "",
                            "record_id": "",
                            "error": "temporary failure",
                        },
                        {
                            "status": "duplicate",
                            "source": "重複タイトル\n\n本文です。",
                            "source_ref": "pasted_text:duplicate",
                            "atom_id": "A-OLD",
                            "record_id": "",
                            "error": "",
                        },
                    ],
                }
            )

            items, retry_history = _retry_marketing_import_history(
                article_store,
                agent_store,
                marketing_store,
                history_row,
                "failed",
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["status"], "created")
            self.assertEqual(marketing_store.stats()["atoms_total"], 1)
            self.assertEqual(len(article_store.list_records()), 1)
            self.assertIsNotNone(retry_history)
            self.assertEqual(marketing_store.list_import_history()[0]["kind"], "text:retry_failed")

    def test_html_import_extracts_title_and_readable_text(self) -> None:
        title, text = _extract_html_text(
            """
            <html>
              <head><title>過去記事タイトル</title><script>ignore()</script></head>
              <body>
                <h1>本文見出し</h1>
                <p>本文の一段落目です。</p>
                <p>本文の二段落目です。</p>
              </body>
            </html>
            """
        )

        self.assertEqual(title, "過去記事タイトル")
        self.assertIn("本文の一段落目です。", text)
        self.assertNotIn("ignore", text)

    def test_central_context_includes_workload_and_health(self) -> None:
        module = _load_central_skill_module()
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "articles.csv"
            store = CSVArticleStore(csv_path)
            store.upsert(
                ArticleRecord(
                    verification_id="N-20260426-001",
                    title="担当確認",
                    writer_agent="writer_main",
                    checker_agent="checker_main",
                    publisher_agent="publisher_main",
                    x_agent="x_main",
                    draft="下書きあり",
                    check_report="OK: fixed checks passed",
                    final="最終稿あり",
                    signoff_at="2026-04-26T10:00:00",
                    x_post="X文あり",
                )
            )
            AgentConfigStore(Path(tmp) / "agents.json").save({})

            context = module.build_context(csv_path)

            self.assertIn("health", context)
            self.assertEqual(context["health"]["status"], "ok")
            self.assertIn("workload", context["assignments"])
            self.assertIn("marketing_department", context)
            self.assertIn("atoms_csv", context["marketing_department"]["data_layer"])
            writer_row = next(item for item in context["assignments"]["workload"] if item["role"] == "writer")
            self.assertEqual(writer_row["assigned_count"], 1)
            self.assertEqual(writer_row["completed_count"], 1)
            self.assertTrue(context["recent_records"][0]["role_progress"]["publisher"]["done"])

    def test_central_context_health_detects_missing_assignment(self) -> None:
        module = _load_central_skill_module()
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "articles.csv"
            store = CSVArticleStore(csv_path)
            store.upsert(
                ArticleRecord(
                    verification_id="N-20260426-002",
                    title="未割当確認",
                    writer_agent="writer_main",
                    checker_agent="checker_main",
                    publisher_agent="publisher_main",
                    x_agent="",
                    draft="下書きあり",
                )
            )
            AgentConfigStore(Path(tmp) / "agents.json").save({})

            context = module.build_context(csv_path)

            self.assertEqual(context["health"]["status"], "error")
            self.assertTrue(any(check["id"] == "record_assignments" and not check["ok"] for check in context["health"]["checks"]))

    def test_central_context_includes_latest_sync_age(self) -> None:
        module = _load_central_skill_module()
        original_minutes_since = module._minutes_since
        module._minutes_since = lambda _value: 30
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "articles.csv"
            CSVArticleStore(csv_path).ensure()
            AgentConfigStore(Path(tmp) / "agents.json").save({})
            SettingsStore(Path(tmp) / "settings.json").save(
                {
                    "google_sheet_url": "https://docs.google.com/spreadsheets/d/demo/edit#gid=0",
                    "last_google_sync_at": "2026-04-26T09:30:00",
                    "last_google_sync_summary": "保存URL同期: 新規1",
                }
            )
            SyncLogStore(Path(tmp) / "sync_history.json").append(
                {
                    "occurred_at": "2026-04-26T09:30:00",
                    "source_label": "保存URL同期",
                    "status": "success",
                    "summary": "新規1",
                    "backup_path": "",
                    "error_message": "",
                }
            )

            context = module.build_context(csv_path)

            self.assertIn("latest_sync_age_minutes", context["health"])
            self.assertIsInstance(context["health"]["latest_sync_age_minutes"], int)
            self.assertGreaterEqual(context["health"]["latest_sync_age_minutes"], 0)
            self.assertEqual(context["health"]["summary_line"], "問題は見つかっていません。")
        module._minutes_since = original_minutes_since

    def test_central_context_warns_when_sync_is_stale(self) -> None:
        module = _load_central_skill_module()
        original_minutes_since = module._minutes_since
        module._minutes_since = lambda _value: 1500
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "articles.csv"
            CSVArticleStore(csv_path).ensure()
            AgentConfigStore(Path(tmp) / "agents.json").save({})
            SettingsStore(Path(tmp) / "settings.json").save(
                {
                    "google_sheet_url": "https://docs.google.com/spreadsheets/d/demo/edit#gid=0",
                    "last_google_sync_at": "2026-04-20T09:30:00",
                    "last_google_sync_summary": "保存URL同期: 新規1",
                }
            )
            SyncLogStore(Path(tmp) / "sync_history.json").append(
                {
                    "occurred_at": "2026-04-20T09:30:00",
                    "source_label": "保存URL同期",
                    "status": "success",
                    "summary": "新規1",
                    "backup_path": "",
                    "error_message": "",
                }
            )

            context = module.build_context(csv_path)

            self.assertEqual(context["health"]["status"], "warn")
            self.assertTrue(any(check["id"] == "saved_google_sync" and not check["ok"] for check in context["health"]["checks"]))
            self.assertIn("古くなっています", context["health"]["summary_line"])
        module._minutes_since = original_minutes_since

    def test_central_context_errors_when_sync_is_too_old(self) -> None:
        module = _load_central_skill_module()
        original_minutes_since = module._minutes_since
        module._minutes_since = lambda _value: 5000
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "articles.csv"
            CSVArticleStore(csv_path).ensure()
            AgentConfigStore(Path(tmp) / "agents.json").save({})
            SettingsStore(Path(tmp) / "settings.json").save(
                {
                    "google_sheet_url": "https://docs.google.com/spreadsheets/d/demo/edit#gid=0",
                    "last_google_sync_at": "2026-04-20T09:30:00",
                    "last_google_sync_summary": "保存URL同期: 新規1",
                }
            )
            SyncLogStore(Path(tmp) / "sync_history.json").append(
                {
                    "occurred_at": "2026-04-20T09:30:00",
                    "source_label": "保存URL同期",
                    "status": "success",
                    "summary": "新規1",
                    "backup_path": "",
                    "error_message": "",
                }
            )

            context = module.build_context(csv_path)

            self.assertEqual(context["health"]["status"], "error")
            self.assertTrue(any(check["id"] == "saved_google_sync" and check.get("severity") == "error" for check in context["health"]["checks"]))
        module._minutes_since = original_minutes_since

    def test_central_context_uses_latest_sync_error_for_summary(self) -> None:
        module = _load_central_skill_module()
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "articles.csv"
            CSVArticleStore(csv_path).ensure()
            AgentConfigStore(Path(tmp) / "agents.json").save({})
            SettingsStore(Path(tmp) / "settings.json").save(
                {
                    "google_sheet_url": "https://docs.google.com/spreadsheets/d/demo/edit#gid=0",
                }
            )
            SyncLogStore(Path(tmp) / "sync_history.json").append(
                {
                    "occurred_at": "2026-04-26T09:30:00",
                    "source_label": "保存URL同期",
                    "status": "error",
                    "summary": "更新2",
                    "backup_path": "",
                    "error_message": "timeout",
                }
            )

            context = module.build_context(csv_path)

            self.assertEqual(context["health"]["status"], "warn")
            self.assertEqual(context["health"]["summary_line"], "直近失敗: timeout")


if __name__ == "__main__":
    unittest.main()
