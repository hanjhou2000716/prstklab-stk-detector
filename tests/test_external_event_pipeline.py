from jsonschema import Draft202012Validator, FormatChecker

from src.external_event_pipeline import build_external_event, build_external_events


def test_discovery_event_stays_pending_without_two_evidence_types():
    result = build_external_event({
        "source": "financialjuice",
        "original_headline": "Iran oil supply risk",
        "event_type": "energy",
        "importance": 10,
    })
    assert result["lifecycle_state"] == "pending_confirmation"
    assert result["notification"]["allowed"] is False
    assert result["risk"]["prstk_risk_level"] == "R2"


def test_financialjuice_priority_is_exposed_without_overriding_risk() -> None:
    result = build_external_event({
        "source": "financialjuice",
        "original_headline": "Oil supply risk",
        "event_type": "energy",
        "importance": 8,
    })
    assert result["vendor_priority"]["vendor_priority_notification"] is True
    assert result["risk"]["prstk_risk_level"] == "R2"
    assert result["notification"]["allowed"] is False


def test_event_becomes_eligible_only_with_official_and_market_evidence():
    result = build_external_event(
        {
            "source": "financialjuice",
            "original_headline": "Confirmed supply disruption",
            "event_type": "energy",
            "importance": 10,
            "market_evidence": [{"symbol": "CL=F", "change_pct": 5.4}],
        },
        official_confirmed=True,
        market_sync_confirmed=True,
    )
    assert result["lifecycle_state"] == "confirmed"
    assert result["notification"]["allowed"] is True
    assert result["risk"]["prstk_risk_level"] == "R4"


def test_external_event_contract_is_schema_valid():
    import json
    from pathlib import Path

    schema = json.loads((Path("schemas") / "external-event.schema.json").read_text(encoding="utf-8"))
    result = build_external_event({"source": "reuters", "headline": "Central bank statement", "event_type": "macro"})
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(result))
    assert errors == []


def test_compound_financialjuice_envelope_fans_out_into_shared_pipeline() -> None:
    envelope = {
        "parse_status": "parsed",
        "message_id": "compound-pipeline-1",
        "items": [
            {"item_id": "item-1", "event_cluster_key": "fj-cluster-1", "candidate_event_type": "energy", "original_headline": "Oil supply"},
            {"item_id": "item-2", "event_cluster_key": "fj-cluster-2", "candidate_event_type": "policy", "original_headline": "Export controls"},
        ],
    }
    results = build_external_events(envelope)
    assert len(results) == 2
    assert len({result["observation_id"] for result in results}) == 2
    assert all(result["lifecycle_state"] == "pending_confirmation" for result in results)


def test_unresolved_compound_envelope_never_emits_partial_event() -> None:
    result = build_external_events({
        "parse_status": "compound_unresolved",
        "message_id": "compound-pipeline-2",
    })
    assert len(result) == 1
    assert result[0]["parse_status"] == "compound_unresolved"
    assert result[0]["notification"]["allowed"] is False
