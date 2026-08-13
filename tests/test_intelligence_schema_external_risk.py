import json
from pathlib import Path
from jsonschema import Draft202012Validator


def test_intelligence_schema_declares_external_event_risk():
    schema = json.loads(Path("schemas/intelligence.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["external_event_risk"]["type"] == "object"


def test_intelligence_schema_requires_identity_for_unsuppressed_events():
    schema = json.loads(Path("schemas/intelligence.schema.json").read_text(encoding="utf-8"))
    payload = {"external_event_risk": {"unified_events": [{"lifecycle_state": "pending_confirmation"}]}}
    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert errors
    assert "notification_id" in errors[0].message


def test_intelligence_schema_allows_identity_free_suppressed_events():
    schema = json.loads(Path("schemas/intelligence.schema.json").read_text(encoding="utf-8"))
    payload = {"external_event_risk": {"unified_events": [{"lifecycle_state": "suppressed"}]}}
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []
