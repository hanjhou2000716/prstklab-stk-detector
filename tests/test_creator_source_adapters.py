from src.creator_provider_registry import CreatorProvider, creator_ids
from src.creator_source_adapters import parse_creator_template


def test_known_template_splits_fact_and_opinion_without_guessing() -> None:
    result = parse_creator_template(
        source="haojiao",
        sender="digest@example.invalid",
        subject="Episode 42",
        body="""Title: Semiconductor cycle\nFact: Issuer filing reports flat revenue.\nOpinion: Market may remain volatile.\nRisk: Wait for official guidance.""",
        message_id="msg-42",
    )
    assert result["parse_status"] == "parsed"
    assert result["claims"] == ["Issuer filing reports flat revenue."]
    assert result["opinions"] == ["Market may remain volatile.", "Wait for official guidance."]
    assert result["verification_state"] == "unverified"
    assert result["public_safe"] is True
    assert "body" not in result


def test_unknown_template_is_explicit_and_not_guessed() -> None:
    result = parse_creator_template(
        source="gooaye",
        sender="digest@example.invalid",
        subject="Episode 43",
        body="A free-form paragraph without labelled sections.",
        message_id="msg-43",
    )
    assert result["parse_status"] == "unsupported_template"
    assert result["failure_reason"] == "missing_fact_or_opinion_sections"
    assert result["template_fingerprint"]


def test_wrong_source_fails_closed() -> None:
    result = parse_creator_template(
        source="unknown",
        sender="digest@example.invalid",
        subject="Episode 44",
        body="Title: x\nFact: y",
    )
    assert result["parse_status"] == "invalid_source"


def test_all_registry_providers_use_shared_template_adapter() -> None:
    """Registry additions must not require a second adapter allowlist."""
    for provider_id in creator_ids():
        result = parse_creator_template(
            source=provider_id,
            sender="digest@example.invalid",
            subject="Episode 45",
            body="Title: Shared template\nFact: Public filing is available.",
            message_id=f"msg-{provider_id}",
        )
        assert result["parse_status"] == "parsed"
        assert result["creator_id"] == provider_id


def test_registry_parser_mismatch_fails_closed(monkeypatch) -> None:
    configured = CreatorProvider(
        creator_id="haojiao",
        display_name="Haojiao",
        source_type="editorial",
        email_identity_rules={"markers": ("haojiao",), "domains": ()},
        gmail_label="PRStK/Creator/Haojiao",
        parser="future-template-v3",
        consensus_eligible=True,
        notification_policy="optional_reviewed_only",
        media_policy="summary_image_if_reviewed",
        display_order=1,
        enabled=True,
    )
    monkeypatch.setattr("src.creator_source_adapters.get_creator_provider", lambda _source: configured)
    result = parse_creator_template(
        source="haojiao",
        sender="digest@example.invalid",
        subject="Episode 46",
        body="Title: Future template\nFact: Public filing is available.",
    )
    assert result["parse_status"] == "unsupported_parser"
    assert result["failure_reason"] == "creator_parser_not_supported"
