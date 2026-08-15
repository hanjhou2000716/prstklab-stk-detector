from src.creator_intelligence_pipeline import build_creator_intelligence_release

PARENT = {"release_id": "release-1", "market_snapshot_id": "market-1", "event_snapshot_id": "event-1"}


def test_pipeline_accepts_sanitized_creator_insight_and_dedupes_episode():
    result = build_creator_intelligence_release(
        [
            {"content_origin": "haojiao", "episode_key": "ep-1", "public_safe": True, "verification_state": "unverified"},
            {"content_origin": "haojiao", "episode_key": "ep-1", "public_safe": True, "verification_state": "unverified"},
        ],
        parent_manifest=PARENT,
    )
    assert result["accepted_count"] == 1
    assert result["dropped_reasons"] == ["1:duplicate_episode"]
    assert result["artifact"]["status"] == "ready"
    assert result["artifact"]["creator_consensus"]["consensus_state"] == "insufficient_sources"
    assert result["public_artifact"]["creator_consensus"]["consensus_state"] == "insufficient_sources"


def test_pipeline_drops_private_or_unknown_records_fail_closed():
    result = build_creator_intelligence_release(
        [
            {"content_origin": "gooaye", "episode_key": "ep-1", "raw_body": "secret"},
            {"content_origin": "unknown", "episode_key": "ep-2"},
        ],
        parent_manifest=PARENT,
    )
    assert result["accepted_count"] == 0
    assert result["source_state"] == "no_creator_insights"
    assert result["artifact"]["status"] == "ready"


def test_pipeline_drops_parser_failures_before_public_release():
    result = build_creator_intelligence_release(
        [
            {
                "content_origin": "haojiao",
                "episode_key": "ep-bad",
                "episode_title": "Unparsed",
                "parse_status": "unsupported_template",
                "failure_reason": "missing_fact_or_opinion_sections",
            },
            {
                "content_origin": "gooaye",
                "episode_key": "ep-incomplete",
                "episode_title": "Incomplete",
                "parse_status": "parsed",
                "source_adapter": "creator-template-v2",
                "required_fields_present": False,
            },
        ],
        parent_manifest=PARENT,
    )
    assert result["accepted_count"] == 0
    assert result["dropped_reasons"] == [
        "0:unsupported_template",
        "1:adapter_required_fields_missing",
    ]


def test_creator_release_rejects_parser_failure_even_if_called_directly():
    result = build_creator_intelligence_release(
        [
            {
                "content_origin": "haojiao",
                "episode_key": "ep-direct",
                "episode_title": "Direct failure",
                "parse_status": "parse_failed",
            }
        ],
        parent_manifest=PARENT,
    )
    assert result["accepted_count"] == 0
    assert result["artifact"]["status"] == "ready"
