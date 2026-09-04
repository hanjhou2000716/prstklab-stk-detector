import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.external_source_parsers import parse_creator_email, parse_external_email, parse_financialjuice_email
from src.financialjuice_contract import financialjuice_item_id


def test_financialjuice_parser_keeps_vendor_importance_separate() -> None:
    result = parse_financialjuice_email(
        sender="alerts@financialjuice.com", subject="FinancialJuice alert",
        body="Importance: 10/10\nOriginal headline: Oil supply update\nAI commentary: Watch supply.\nPossible impact: Energy volatility.",
        message_id="m-1",
    )
    assert result["parse_status"] == "parsed"
    assert result["vendor_importance"] == 10
    assert result["attribution"] == "FinancialJuice"
    assert result["source_url"] == "https://www.financialjuice.com/"
    assert result["source_domain"] == "financialjuice.com"
    assert "body" not in result


def test_financialjuice_single_item_has_stable_independent_identity() -> None:
    first = parse_financialjuice_email(
        sender="alerts@financialjuice.com", subject="FinancialJuice alert",
        body="Importance: 10/10\nOriginal headline: Iran telecom attack",
        message_id="message-a",
    )
    second = parse_financialjuice_email(
        sender="alerts@financialjuice.com", subject="FinancialJuice alert",
        body="Importance: 9/10\nOriginal headline: Nscale Anthropic contract",
        message_id="message-b",
    )
    assert first["item_id"] != second["item_id"]
    assert first["event_cluster_key"] != second["event_cluster_key"]
    assert len(first["content_hash"]) == 64


def test_financialjuice_parser_uses_substantive_subject_when_body_is_stub() -> None:
    result = parse_financialjuice_email(
        sender="alerts@financialjuice.com",
        subject="FJ: Company evaluates strategic partnership",
        body="Importance: 8/10\n📝 繁體中文翻譯:",
        message_id="subject-headline-1",
    )
    assert result["parse_status"] == "parsed"
    assert result["vendor_original_headline"] == "FJ: Company evaluates strategic partnership"


def test_financialjuice_parser_rejects_generic_subject_and_metadata_as_headline() -> None:
    result = parse_financialjuice_email(
        sender="alerts@financialjuice.com",
        subject="FinancialJuice breaking news",
        body="Importance: 8/10\n📝 繁體中文翻譯:",
        message_id="subject-headline-2",
    )
    assert result["parse_status"] == "parse_failed"
    assert result["failure_reason"] == "missing_headline"


def test_financialjuice_html_relay_extracts_public_fields_without_markup() -> None:
    """The live Gmail relay is HTML-only; tags must never become an event title."""
    result = parse_financialjuice_email(
        sender="jetmaie.fintech@gmail.com",
        subject="📰 FinancialJuice 新聞 (08-20 07:08)",
        body="""
        <!DOCTYPE html><html><head><style>.x { color: red; }</style></head><body>
        <h1>📰 FinancialJuice 新聞通知</h1>
        <span>即時新聞</span><span>財經資訊</span><span>⚠️ 高重要性</span>
        <div><strong>重要性評分:</strong><span>8/10</span></div>
        <div><strong>📝 繁體中文翻譯:</strong><p>川普：這將是前所未有的經濟衝突與孤立。</p></div>
        <div><strong>💡 AI 評論:</strong><p>言論升高中東緊張，但尚未成為具體行動。</p></div>
        <div><strong>⚠️ 可能影響:</strong><p>留意是否轉為實際制裁或封鎖。</p></div>
        </body></html>
        """,
        message_id="sanitized-fj-html-1",
    )
    assert result["parse_status"] == "parsed"
    assert result["vendor_importance"] == 8
    assert result["vendor_translation"].startswith("川普：")
    assert result["vendor_original_headline"].startswith("川普：")
    assert "<" not in result["vendor_original_headline"]
    assert "AI 評論" not in result["vendor_analysis"]
    assert result["public_safe"] is True


def test_financialjuice_table_fragment_extracts_fields_without_html_wrapper() -> None:
    """Gmail may return only a table fragment rather than html/body tags."""
    result = parse_financialjuice_email(
        sender="jetmaie.fintech@gmail.com",
        subject="📰 FinancialJuice 新聞 (09-02 14:20)",
        body="""
        <table><tr><td>即時新聞</td><td>財經資訊</td><td>⚠️ 高重要性</td></tr>
        <tr><td><strong>重要性評分:</strong></td><td>10/10</td></tr>
        <tr><td><strong>📝 繁體中文翻譯:</strong></td><td>沙烏地阿拉伯外交部表示，伊朗在荷莫茲海峽襲擊了一艘沙烏地船隻。</td></tr>
        <tr><td><strong>💡 AI評論:</strong></td><td>此為荷莫茲海峽油運要道的突發軍事攻擊。</td></tr>
        <tr><td><strong>⚠️ 可能影響:</strong></td><td>油價恐急漲並加劇通膨預期。</td></tr></table>
        """,
        message_id="table-fragment-fj-1",
    )
    assert result["parse_status"] == "parsed"
    assert result["vendor_importance"] == 10
    assert result["vendor_original_headline"].startswith("沙烏地阿拉伯外交部")
    assert result["vendor_analysis"].startswith("此為荷莫茲海峽")
    assert result["vendor_possible_impact"].startswith("油價恐急漲")


def test_financialjuice_inline_html_labels_do_not_cross_assign_values() -> None:
    result = parse_financialjuice_email(
        sender="jetmaie.fintech@gmail.com",
        subject="FinancialJuice breaking news",
        body=(
            "重要性評分: 10/10 📝 繁體中文翻譯: 某公司據報正在評估合作 "
            "💡 AI 評論: 若合作成真，仍未正式確認 "
            "⚠️ 可能影響: 可能影響 AI 伺服器供應鏈。"
        ),
        message_id="inline-labels-1",
    )
    assert result["parse_status"] == "parsed"
    assert result["vendor_translation"] == "某公司據報正在評估合作"
    assert result["vendor_analysis"] == "若合作成真，仍未正式確認"
    assert result["vendor_possible_impact"] == "可能影響 AI 伺服器供應鏈。"
    assert result["vendor_original_headline"] == "某公司據報正在評估合作"


def test_financialjuice_compact_live_labels_preserve_original_translation_analysis_and_impact() -> None:
    """Live relays may omit spaces/newlines around icon-labelled sections."""
    result = parse_financialjuice_email(
        sender="jetmaie.fintech@gmail.com",
        subject="📰 FinancialJuice 新聞 (09-02 13:58)",
        body=(
            "重要性評分: 8/10 📝 繁體中文翻譯: 美伊衝突再度升級，油價突破90美元。"
            " 💡 AI評論: 市場風險偏好受壓，但後續仍需核對。"
            " 📄 原文內容: Iran says there are no nuclear activities."
            " ⚠️ 可能影響: 油價與高估值科技股波動可能升高。"
        ),
        message_id="compact-live-labels-1",
    )
    assert result["parse_status"] == "parsed"
    assert result["vendor_original_headline"] == "Iran says there are no nuclear activities."
    assert result["vendor_translation"] == "美伊衝突再度升級，油價突破90美元。"
    assert result["vendor_analysis"] == "市場風險偏好受壓，但後續仍需核對。"
    assert result["vendor_possible_impact"] == "油價與高估值科技股波動可能升高。"


def test_financialjuice_parser_keeps_explicit_source_url_domain_aligned() -> None:
    result = parse_financialjuice_email(
        sender="alerts@financialjuice.com", subject="FinancialJuice alert",
        body="Importance: 8/10\nOriginal headline: Headline\nSource URL: https://www.financialjuice.com/story/1",
        message_id="m-source-url",
    )

    assert result["source_url"] == "https://www.financialjuice.com/story/1"
    assert result["source_domain"] == "financialjuice.com"


def test_creator_parser_defaults_claims_to_unverified() -> None:
    result = parse_creator_email(
        sender="news@gooaye.example", subject="EP 1",
        body="標題：AI 產業觀察\n重點：供應鏈仍需核對\n看法：保持中立\n事實：公司公告待確認",
        source="gooaye", message_id="m-2",
    )
    assert result["parse_status"] == "parsed"
    assert result["verification_state"] == "unverified"
    assert result["claims"] and result["opinions"]


def test_unknown_template_is_dlq_safe() -> None:
    result = parse_external_email(sender="unknown@example.com", subject="hello", body="text", message_id="m-3")
    assert result["parse_status"] == "invalid_source"
    assert result["failure_reason"] == "unknown_template"


def test_retired_creator_external_parser_fails_closed() -> None:
    result = parse_external_email(
        sender="newsletter@example.com",
        subject="財經皓角市場觀察",
        body="Title: legacy\nFact: historical fixture",
        message_id="retired-parser-1",
    )
    assert result["parse_status"] == "retired_source_suppressed"
    assert result["failure_reason"] == "creator_source_retired"
    assert result["content_origin"] == "haojiao"


def test_financialjuice_result_matches_schema() -> None:
    result = parse_financialjuice_email(sender="financialjuice", subject="alert", body="headline only", message_id="m-4")
    schema = json.loads(Path("schemas/external-parse-result.schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema).iter_errors(result))


def test_financialjuice_compound_email_fans_out_items() -> None:
    result = parse_financialjuice_email(
        sender="alerts@financialjuice.com", subject="compound alert",
        body=(
            "Item 1\nImportance: 9/10\nOriginal headline: Oil supply disruption\n"
            "Translation: 原油供應中斷\nEntities: Iran, oil\n"
            "AI commentary: Supply risk.\nPossible impact: Oil volatility.\n"
            "Item 2\nImportance: 8/10\nOriginal headline: Semiconductor export control\n"
            "Translation: 半導體出口管制\nEntities: China, semiconductor\n"
            "AI commentary: Chip access changes.\nPossible impact: Technology volatility."
        ),
        message_id="compound-1",
    )
    assert result["parse_status"] == "parsed"
    assert result["compound"] is True
    assert result["item_count"] == 2
    assert len(result["items"]) == 2
    assert len({item["item_id"] for item in result["items"]}) == 2
    assert len({item["content_hash"] for item in result["items"]}) == 2
    assert len({item["event_cluster_key"] for item in result["items"]}) == 2
    assert all(item["candidate_event_type"] for item in result["items"])


def test_financialjuice_compound_item_identity_survives_semantic_replay() -> None:
    first = financialjuice_item_id("message-1", 0, "hash-a")
    replay = financialjuice_item_id("message-1", 0, "hash-b")
    assert first == replay


def test_financialjuice_compound_missing_item_is_fail_closed() -> None:
    result = parse_financialjuice_email(
        sender="alerts@financialjuice.com", subject="compound alert",
        body="Item 1\nImportance: 9/10\nOriginal headline: First event\n"
        "Item 2\nImportance: 8/10\nTranslation: missing headline",
        message_id="compound-2",
    )
    assert result["parse_status"] == "compound_unresolved"
    assert result["items"] == []
    assert result["failure_reason"] == "compound_item_missing_headline"


def test_financialjuice_compound_result_matches_schema() -> None:
    result = parse_financialjuice_email(
        sender="financialjuice", subject="compound",
        body="Item 1\nOriginal headline: First\nItem 2\nOriginal headline: Second",
        message_id="compound-3",
    )
    schema = json.loads(Path("schemas/financialjuice-envelope.schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema).iter_errors(result))
