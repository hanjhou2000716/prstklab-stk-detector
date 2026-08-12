import json
from pathlib import Path


def test_intelligence_schema_declares_external_event_risk():
    schema = json.loads(Path("schemas/intelligence.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["external_event_risk"]["type"] == "object"
