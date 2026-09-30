from __future__ import annotations

import json
from datetime import datetime

import pytest

from src import scheduled_recipient_manifest as manifest


def test_manifest_is_sanitized_versioned_and_round_trips():
    created = manifest.build_recipient_manifest(
        ["123456789", "-99887766", "123456789"],
        datetime.fromisoformat("2026-09-30T12:00:00+08:00"),
    )
    assert created["schema_version"] == manifest.SCHEMA_VERSION
    latest = created["versions"][-1]
    assert latest["effective_at"] == "2026-09-30T04:00:00Z"
    assert latest["recipient_hashes"] == sorted(latest["recipient_hashes"])
    assert len(latest["recipient_hashes"]) == 2
    assert all(len(value) == 12 for value in latest["recipient_hashes"])
    assert "123456789" not in json.dumps(created)
    parsed = manifest.parse_recipient_manifest(json.dumps(created))
    assert parsed.version == latest["version"]
    assert set(parsed.recipient_hashes) == set(latest["recipient_hashes"])


def test_manifest_requires_a_nonempty_active_recipient_set():
    with pytest.raises(ValueError, match="expected_recipient_set_hashes_unavailable"):
        manifest.build_recipient_manifest([])


def test_manifest_rejects_naive_effective_timestamp():
    with pytest.raises(ValueError, match="expected_recipient_set_effective_at_invalid"):
        manifest.build_recipient_manifest(["123456789"], "2026-09-30T04:00:00")


def test_manifest_rejects_duplicate_or_malformed_hashes():
    payload = {
        "schema_version": manifest.SCHEMA_VERSION,
        "versions": [{
            "version": "recipients-0000000000000000",
            "effective_at": "2026-09-30T04:00:00Z",
            "recipient_hashes": ["aaaaaaaaaaaa", "aaaaaaaaaaaa"],
        }],
    }
    with pytest.raises(ValueError, match="expected_recipient_set_manifest_invalid"):
        manifest.parse_recipient_manifest(json.dumps(payload))


def test_manifest_rejects_fingerprint_mismatch():
    payload = manifest.build_recipient_manifest(["123456789"], "2026-09-30T04:00:00Z")
    payload["versions"][0]["recipient_hashes"] = ["aaaaaaaaaaaa"]
    with pytest.raises(ValueError, match="expected_recipient_set_fingerprint_mismatch"):
        manifest.parse_recipient_manifest(json.dumps(payload))


def test_manifest_history_selects_version_effective_at_original_slot():
    first = manifest.build_recipient_manifest(["123456789"], "2026-09-29T04:00:00Z")
    second = manifest.build_recipient_manifest(
        ["987654321"], "2026-09-30T04:00:00Z", json.dumps(first),
    )
    parsed = manifest.parse_recipient_manifest(json.dumps(second))
    old_anchor = datetime.fromisoformat("2026-09-29T12:00:00+08:00")
    new_anchor = datetime.fromisoformat("2026-09-30T12:00:00+08:00")
    assert parsed.for_anchor(old_anchor).version == first["versions"][0]["version"]
    assert parsed.for_anchor(new_anchor).version == second["versions"][1]["version"]
    assert parsed.for_anchor(datetime.fromisoformat("2026-09-28T12:00:00+08:00")) is None


def test_manifest_initializer_and_drift_workflows_are_read_only():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    initializer = (root / "initialize-scheduled-recipient-manifest.yml").read_text(encoding="utf-8")
    drift = (root / "scheduled-recipient-manifest-drift.yml").read_text(encoding="utf-8")
    audit = (root / "scheduled-brief-slot-audit.yml").read_text(encoding="utf-8")
    initializer_script = (Path(__file__).resolve().parents[1] / "scripts" / "initialize_scheduled_recipient_manifest.py").read_text(encoding="utf-8")
    for workflow in (initializer, drift):
        assert "contents: read" in workflow
        assert "TELEGRAM_BOT_TOKEN" not in workflow
    assert "SCHEDULED_RECIPIENT_SET_MANIFEST" in initializer_script
    assert "SCHEDULED_RECIPIENT_SET_MANIFEST" in drift
    assert "vars.SCHEDULED_RECIPIENT_SET_MANIFEST" in audit
    assert "SUPABASE_SERVICE_ROLE_KEY" not in audit


def test_manifest_history_is_append_only_and_preserves_prior_audit_sets():
    first = manifest.build_recipient_manifest(["123456789"], "2026-09-29T04:00:00Z")
    unchanged = manifest.build_recipient_manifest(
        ["123456789"], "2026-09-30T04:00:00Z", json.dumps(first),
    )
    assert unchanged == first
    with pytest.raises(ValueError, match="expected_recipient_set_effective_at_precedes_latest_version"):
        manifest.build_recipient_manifest(
            ["987654321"], "2026-09-28T04:00:00Z", json.dumps(first),
        )
    with pytest.raises(ValueError, match="expected_recipient_set_effective_at_not_monotonic"):
        manifest.build_recipient_manifest(
            ["987654321"], "2026-09-29T04:00:00Z", json.dumps(first),
        )


def test_manifest_rejects_wrong_field_types_and_extra_partial_fields():
    payload = manifest.build_recipient_manifest(["123456789"], "2026-09-30T04:00:00Z")
    payload["versions"][0]["recipient_hashes"] = [123456789012]
    with pytest.raises(ValueError, match="expected_recipient_set_manifest_invalid"):
        manifest.parse_recipient_manifest(json.dumps(payload))
    payload["versions"][0]["recipient_hashes"] = ["aaaaaaaaaaaa"]
    payload["unexpected"] = "mixed-update"
    with pytest.raises(ValueError, match="expected_recipient_set_manifest_invalid"):
        manifest.parse_recipient_manifest(json.dumps(payload))
