from jsonschema import Draft202012Validator, FormatChecker

from src.external_event_pipeline import build_external_event


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
