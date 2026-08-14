from __future__ import annotations

import hashlib
import hmac
import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "railway-monitor" / "dispatch_payload.py"
SPEC = importlib.util.spec_from_file_location("railway_dispatch_payload_test", MODULE)
assert SPEC and SPEC.loader
payload = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(payload)


class Alert:
    canonical = "event|summary|2026-08-14T00:00:00Z"
    source = "test"
    event_id = "evt-1"
    category = "geopolitical_event"
    summary = "Official confirmation"
    risk_level = "observation"
    official_confirmed = True
    market_sync_confirmed = False
    market_sync = ("oil",)
    occurred_at = "2026-08-14T00:00:00Z"
    evidence_payload = [{"url": "https://example.test/a"}]


def test_payload_contains_stable_trace_and_normalized_sources():
    result = payload.build_dispatch_payload(
        Alert(),
        None,
        alert_trace_id=lambda _: "trace-1",
        alert_canonical_key=lambda _: "key-1",
        normalize_source_url=lambda value: value.rstrip("/"),
    )
    client = result["client_payload"]
    assert client["trace_id"] == "trace-1"
    assert client["canonical_key"] == "key-1"
    assert client["source_url"] == "https://example.test/a"
    assert client["event_ledger_retention_days"] == 30


def test_signature_is_hmac_and_is_added_to_payload():
    expected = hmac.new(b"secret", Alert.canonical.encode(), hashlib.sha256).hexdigest()
    assert payload.sign(Alert(), "secret") == f"sha256={expected}"
    signed = payload.sign_dispatch_payload({"client_payload": {}}, Alert(), "secret")
    assert signed["client_payload"]["signature"] == f"sha256={expected}"
