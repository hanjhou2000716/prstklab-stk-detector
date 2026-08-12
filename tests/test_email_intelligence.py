import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from src.email_intelligence import (
    creator_episode_key,
    normalize_creator_insight,
    normalize_email_observation,
    route_email_source,
)


def test_router_separates_transport_from_content_origin() -> None:
    result = route_email_source(sender="jetmaie.fintech@gmail.com", subject="FinancialJuice breaking news")
    assert result == {"source": "financialjuice", "content_type": "breaking_news", "parse_status": "identified"}


def test_unknown_email_is_explicit_invalid_source() -> None:
    result = normalize_email_observation({"message_id": "m-1", "sender": "unknown@example.com", "body": "hello"})
    assert result["content_origin"] == "unknown"
    assert result["parse_status"] == "invalid_source"
    assert "body" not in result
    assert len(result["body_hash"]) == 64


def test_email_schema_is_valid_and_public_safe() -> None:
    result = normalize_email_observation({
        "message_id": "gmail-1", "thread_id": "thread-1", "sender": "news@financialjuice.com",
        "subject": "FinancialJuice alert", "body": "private content", "received_at": "2026-08-12T01:00:00Z",
    })
    schema = json.loads(Path("schemas/email-observation.schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(result))


def test_creator_claims_and_opinions_are_attributed_separately() -> None:
    result = normalize_creator_insight({
        "creator_id": "gooaye", "episode_key": "gooaye:ep-1", "content_origin": "gooaye",
        "claims": ["EPS was disclosed"], "opinions": ["valuation looks attractive"],
        "verification_state": "unverified", "evidence_alignment": "not_verifiable",
    })
    assert result["claims"] == ["EPS was disclosed"]
    assert result["opinions"] == ["valuation looks attractive"]
    assert result["verification_state"] == "unverified"
    assert result["public_safe"] is True


def test_creator_schema_accepts_explicit_unverified_state() -> None:
    result = normalize_creator_insight({"episode_key": "haojiao:ep-1", "content_origin": "haojiao"})
    schema = json.loads(Path("schemas/creator-insight.schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(result))


def test_creator_episode_key_is_stable_without_raw_body() -> None:
    record = {"content_origin": "gooaye", "episode_id": "EP-7", "episode_title": "市場觀察", "published_at": "2026-08-12T02:03:00Z", "body": "private"}
    assert creator_episode_key(record) == creator_episode_key(dict(record))
    assert normalize_creator_insight(record)["episode_key"].startswith("gooaye:")
