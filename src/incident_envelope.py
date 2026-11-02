"""Strict, versioned incident evidence envelope shared across producers."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

SCHEMA = "incident-envelope-v2"
MAX_ENVELOPE_BYTES = 64_000
LIFECYCLES = {"active", "recovery_pending", "recovered", "historical_diagnosed", "historical_pending_verification"}
SEVERITIES = {"critical", "high", "normal", "info"}
EVIDENCE_STATES = {"verified", "partial", "unknown", "invalid"}


class IncidentEnvelopeError(ValueError):
    """Raised when incident evidence cannot safely cross a service boundary."""


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _identity_text(value: object, field: str, *, maximum: int = 240) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise IncidentEnvelopeError(f"incident_envelope_{field}_invalid")
    return text


def _iso_or_unknown(value: object, field: str, *, required: bool = False) -> str | None:
    if value is None or value == "unknown":
        if required:
            raise IncidentEnvelopeError(f"incident_envelope_{field}_unknown")
        return None
    text = _identity_text(value, field, maximum=80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IncidentEnvelopeError(f"incident_envelope_{field}_invalid") from exc
    if parsed.tzinfo is None:
        raise IncidentEnvelopeError(f"incident_envelope_{field}_timezone_missing")
    return parsed.astimezone(UTC).isoformat()


def build_incident_id(*, incident_type: str, component: str, root_cause: str) -> str:
    material = {
        # Match JavaScript String.toLowerCase() in the Worker coordinator.
        "incident_type": _identity_text(incident_type, "type", maximum=80).lower(),
        "component": _identity_text(component, "component", maximum=80).lower(),
        "root_cause": " ".join(_identity_text(root_cause, "root_cause", maximum=240).lower().split()),
    }
    return _canonical_hash(material)


def build_impact_key(*, impact_type: str, identity: dict[str, Any]) -> str:
    if not isinstance(identity, dict) or not identity:
        raise IncidentEnvelopeError("incident_envelope_impact_identity_missing")
    return _canonical_hash({"type": _identity_text(impact_type, "impact_type", maximum=80), "identity": identity})


def make_incident_envelope(
    *, incident_type: str, component: str, root_cause: str,
    impact_type: str, impact_identity: dict[str, Any], impact: dict[str, Any],
    evidence: list[dict[str, Any]], observed_at: str,
    first_detected_at: str | None = None, source_occurred_at: str | None = None,
    severity: str = "normal", lifecycle: str = "active", evidence_integrity: str = "verified",
    new_impact: bool = False, generation: int = 1, state_version: int = 1,
    issue_numbers: list[int] | None = None, compatibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = {
        "schema_version": SCHEMA,
        "incident_id": build_incident_id(incident_type=incident_type, component=component, root_cause=root_cause),
        "incident_type": incident_type,
        "component": component,
        "root_cause": root_cause,
        "impact_key": build_impact_key(impact_type=impact_type, identity=impact_identity),
        "impact_type": impact_type,
        "impact": impact,
        "evidence": evidence,
        "times": {
            "first_detected_at": first_detected_at,
            "observed_at": observed_at,
            "source_occurred_at": source_occurred_at,
        },
        "severity": severity,
        "lifecycle": lifecycle,
        "evidence_integrity": evidence_integrity,
        "new_impact": bool(new_impact),
        "generation": generation,
        "state_version": state_version,
        "issue_numbers": issue_numbers or [],
        "compatibility": compatibility or {"adapter": "incident-envelope-v2", "legacy_source": None},
    }
    return validate_incident_envelope(envelope)


def validate_incident_envelope(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IncidentEnvelopeError("incident_envelope_object_required")
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IncidentEnvelopeError("incident_envelope_json_invalid") from exc
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise IncidentEnvelopeError("incident_envelope_too_large")
    if value.get("schema_version") != SCHEMA:
        raise IncidentEnvelopeError("incident_envelope_schema_unsupported")
    for field, maximum in (("incident_type", 80), ("component", 80), ("root_cause", 240), ("impact_type", 80)):
        _identity_text(value.get(field), field, maximum=maximum)
    if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("incident_id") or "")):
        raise IncidentEnvelopeError("incident_envelope_incident_id_invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("impact_key") or "")):
        raise IncidentEnvelopeError("incident_envelope_impact_key_invalid")
    if value["incident_id"] != build_incident_id(
        incident_type=value["incident_type"], component=value["component"], root_cause=value["root_cause"],
    ):
        raise IncidentEnvelopeError("incident_envelope_incident_identity_mismatch")
    if value.get("severity") not in SEVERITIES or value.get("lifecycle") not in LIFECYCLES:
        raise IncidentEnvelopeError("incident_envelope_state_invalid")
    if value.get("evidence_integrity") not in EVIDENCE_STATES or not isinstance(value.get("new_impact"), bool):
        raise IncidentEnvelopeError("incident_envelope_evidence_state_invalid")
    for field in ("generation", "state_version"):
        if not isinstance(value.get(field), int) or value[field] < 1:
            raise IncidentEnvelopeError(f"incident_envelope_{field}_invalid")
    impact = value.get("impact")
    evidence = value.get("evidence")
    times = value.get("times")
    compatibility = value.get("compatibility")
    issue_numbers = value.get("issue_numbers")
    if not isinstance(impact, dict) or not impact or not isinstance(evidence, list) or not evidence:
        raise IncidentEnvelopeError("incident_envelope_impact_or_evidence_missing")
    if not isinstance(times, dict) or not isinstance(compatibility, dict) or not isinstance(issue_numbers, list):
        raise IncidentEnvelopeError("incident_envelope_supporting_fields_invalid")
    _iso_or_unknown(times.get("observed_at"), "observed_at", required=True)
    for field in ("first_detected_at", "source_occurred_at"):
        _iso_or_unknown(times.get(field), field)
    for item in evidence:
        if not isinstance(item, dict):
            raise IncidentEnvelopeError("incident_envelope_evidence_row_invalid")
        _identity_text(item.get("repository"), "evidence_repository", maximum=200)
        _identity_text(item.get("workflow"), "evidence_workflow", maximum=200)
        for field in ("run_id", "attempt"):
            if not isinstance(item.get(field), int) or item[field] < 1:
                raise IncidentEnvelopeError(f"incident_envelope_evidence_{field}_invalid")
        if not re.fullmatch(r"[0-9a-f]{40,64}", str(item.get("sha") or "").lower()):
            raise IncidentEnvelopeError("incident_envelope_evidence_sha_invalid")
        artifact_id = item.get("artifact_id")
        artifact_digest = item.get("artifact_digest")
        if artifact_id is not None and (not isinstance(artifact_id, int) or artifact_id < 1):
            raise IncidentEnvelopeError("incident_envelope_artifact_id_invalid")
        if artifact_digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact_digest)):
            raise IncidentEnvelopeError("incident_envelope_artifact_digest_invalid")
        if artifact_id is None or artifact_digest is None:
            if value["evidence_integrity"] == "verified":
                raise IncidentEnvelopeError("incident_envelope_verified_artifact_identity_missing")
    if any(not isinstance(number, int) or number < 1 for number in issue_numbers):
        raise IncidentEnvelopeError("incident_envelope_issue_identity_invalid")
    expected_impact_key = build_impact_key(impact_type=value["impact_type"], identity=impact.get("identity") or {k: v for k, v in impact.items() if k != "description"})
    if value["impact_key"] != expected_impact_key:
        raise IncidentEnvelopeError("incident_envelope_impact_identity_mismatch")
    if value["lifecycle"].startswith("historical_") and value["new_impact"]:
        raise IncidentEnvelopeError("incident_envelope_historical_new_impact_conflict")
    return value
