from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parents[1] / "railway-monitor"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema = _load("railway_state_schema_for_classification_test", "state_store_schema.py")
classification = _load("railway_classification_store_test", "classification_store.py")


def test_classification_state_transitions_are_retryable_and_diagnostic():
    connection = sqlite3.connect(":memory:")
    schema.initialize_state_schema(connection)

    classification.record_incoming_flash(
        connection,
        event_id="evt-1",
        title="Talks resume",
        content="Officials opened dialogue.",
        occurred_at="2026-08-14T00:00:00+00:00",
        classification_reason="pending_second_source",
    )
    assert classification.add_if_new(connection, "evt-1") is True
    assert classification.claim_classification(connection, "evt-1", "unclassified") is False
    assert classification.claim_classification(connection, "evt-1", "in_scope") is True
    assert classification.claim_classification(connection, "evt-1", "out_of_scope") is False
    assert classification.classification_for(connection, "evt-1") == "in_scope"
    assert classification.classification_diagnostics(connection)["unclassified_count"] == 0


def test_classification_failure_reopens_event_without_erasing_evidence():
    connection = sqlite3.connect(":memory:")
    schema.initialize_state_schema(connection)
    classification.record_incoming_flash(
        connection,
        event_id="evt-2",
        title="Iran update",
        content="Awaiting official confirmation.",
        occurred_at="2026-08-14T00:00:00+00:00",
        classification_reason="pending_official_source",
    )
    assert classification.claim_classification(connection, "evt-2", "in_scope") is True
    classification.release_classification(connection, "evt-2", "dispatch timeout")

    assert classification.classification_for(connection, "evt-2") == "unclassified"
    row = connection.execute(
        "SELECT classification_reason, last_error FROM incoming_events WHERE event_id='evt-2'"
    ).fetchone()
    assert row == ("dispatch_failed:dispatch timeout", "dispatch timeout")
    assert classification.claim_classification(connection, "evt-2", "in_scope") is True


def test_invalid_classification_is_rejected_without_writing_state():
    connection = sqlite3.connect(":memory:")
    schema.initialize_state_schema(connection)

    try:
        classification.claim_classification(connection, "evt-3", "confirmed")
    except ValueError as error:
        assert "unsupported event classification" in str(error)
    else:
        raise AssertionError("invalid classification was accepted")
