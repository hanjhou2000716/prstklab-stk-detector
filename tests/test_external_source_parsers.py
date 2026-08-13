import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.external_source_parsers import parse_creator_email, parse_external_email, parse_financialjuice_email


def test_financialjuice_parser_keeps_vendor_importance_separate() -> None:
    result = parse_financialjuice_email(
        sender="alerts@financialjuice.com", subject="FinancialJuice alert",
        body="Importance: 10/10\nOriginal headline: Oil supply update\nAI commentary: Watch supply.\nPossible impact: Energy volatility.",
        message_id="m-1",
    )
    assert result["parse_status"] == "parsed"
    assert result["vendor_importance"] == 10
    assert result["attribution"] == "FinancialJuice"
    assert "body" not in result


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
