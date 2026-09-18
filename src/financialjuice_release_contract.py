"""Fail-closed contract for the FinancialJuice release-to-delivery boundary.

The parser and priority projector already produce the canonical FinancialJuice
rows.  This module is the final producer/consumer contract: it verifies that
the rows published in one market snapshot are the rows referenced by the
priority decisions and that an eligible item uses the correct delivery policy
without turning vendor importance into PRStK risk.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from src.financialjuice_contract import VENDOR_PRIORITY_THRESHOLD
from src.financialjuice_notification import financialjuice_notification_key
from src.financialjuice_summary_contract import SUMMARY_CONTRACT_VERSION
from src.telegram_client import PUBLIC_SUMMARY_VERSION, is_valid_public_summary

_STATUSES = frozenset({
    "eligible",
    "not_eligible",
    "already_cluster_notified",
    "content_incomplete",
    "stale_source_event",
    "invalid_future_source_timestamp",
    "missing_source_timestamp",
    "identity_incomplete",
})

_FJ_SOURCE_ALIASES = frozenset({"financialjuice", "financial_juice", "financial juice", "fj"})
_NON_PUBLIC_STATUSES = frozenset({
    "not_eligible",
    "already_cluster_notified",
    "content_incomplete",
    "stale_source_event",
    "invalid_future_source_timestamp",
    "missing_source_timestamp",
    "identity_incomplete",
})
_PUBLIC_FLAGS = ("public_signal_eligible", "alert_eligible", "vendor_priority_notification")


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def is_financialjuice_row(row: dict[str, Any]) -> bool:
    """Recognize the bounded FJ aliases used by old and new snapshots."""
    for value in (row.get("source_key"), row.get("source"), row.get("content_origin")):
        normalized = " ".join(str(value or "").strip().casefold().replace("_", " ").split())
        if normalized in _FJ_SOURCE_ALIASES:
            return True
    return False


def _row_identity(row: dict[str, Any]) -> str:
    for field in ("observation_id", "item_id", "notification_id", "event_key", "canonical_fact_key"):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def _safe_event_fingerprint(row: dict[str, Any]) -> str:
    payload = {
        "source": row.get("source_key") or row.get("source") or row.get("content_origin"),
        "canonical_fact_key": row.get("canonical_fact_key"),
        "material_fact_version": row.get("material_fact_version"),
        "public_summary_version": row.get("public_summary_version"),
        "public_summary_status": row.get("public_summary_status"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def financialjuice_event_fingerprint(row: dict[str, Any]) -> str:
    """Return the privacy-safe identity used for quarantine/index filtering."""
    return _safe_event_fingerprint(row)


def financialjuice_quarantine_fingerprints(snapshot: dict[str, Any]) -> set[str]:
    """Find quarantined FJ facts without exposing their transport identities."""
    boundary = snapshot.get("financialjuice_release_boundary")
    if isinstance(boundary, dict):
        values = boundary.get("quarantined_event_fingerprints")
        if isinstance(values, list):
            return {str(value).strip() for value in values if str(value).strip()}
    fingerprints: set[str] = set()
    for lane in (
        snapshot.get("events", {}).get("items") if isinstance(snapshot.get("events"), dict) else None,
        snapshot.get("financialjuice_priority_events"),
        snapshot.get("financialjuice_observations"),
    ):
        for row in _rows(lane):
            if is_financialjuice_row(row) and _classify_event(row)[0] == "quarantined":
                fingerprints.add(_safe_event_fingerprint(row))
    return fingerprints


def _explicitly_non_public(row: dict[str, Any]) -> bool:
    # These are producer-owned safety flags.  A missing flag is not treated as
    # false: an unknown FJ row must not be silently downgraded.
    return all(row.get(field) is False for field in _PUBLIC_FLAGS) and row.get("delivery_eligible") is not True


def _summary_ready(row: dict[str, Any]) -> bool:
    version = str(row.get("public_summary_version") or "").strip()
    status = str(row.get("public_summary_status") or "").strip().casefold()
    message = str(row.get("public_short_message") or row.get("brief_title") or "").strip()
    if version == PUBLIC_SUMMARY_VERSION:
        return status == "ready" and is_valid_public_summary(message, source="financialjuice")
    # Historical rows may be rendered through the legacy-compatible path, but
    # an explicitly incomplete row can never be made public by a fallback.
    return status != "incomplete" and is_valid_public_summary(message, source="financialjuice")


def _classify_event(row: dict[str, Any]) -> tuple[str, str]:
    """Return publishable/quarantined/fatal for one release-bound FJ row."""
    public_signal = row.get("public_signal_eligible") is True
    delivery_signal = any(
        row.get(field) is True
        for field in ("alert_eligible", "vendor_priority_notification", "delivery_eligible")
    )
    if public_signal:
        if not _summary_ready(row):
            return "fatal", "public_summary_not_ready"
        status = str(row.get("notification_status") or "").strip()
        # A reviewed, non-priority FJ item may remain visible in the public
        # event lane without being a Telegram candidate.  Only delivery flags
        # require the stronger eligible-status contract.
        if delivery_signal and status and status != "eligible":
            return "fatal", "public_event_status_not_eligible"
        if not delivery_signal and status == "eligible":
            return "fatal", "public_event_status_not_eligible"
        return "publishable", ""
    if delivery_signal:
        return "fatal", "public_summary_not_ready" if not _summary_ready(row) else "unclassifiable_fj_event"
    if _explicitly_non_public(row):
        status = str(row.get("notification_status") or "").strip()
        if status in _NON_PUBLIC_STATUSES or not _summary_ready(row):
            return "quarantined", (
                "public_summary_not_ready"
                if not _summary_ready(row) else "non_publishable_fj_event"
            )
        return "quarantined", "non_publishable_fj_event"
    return "fatal", "unclassifiable_fj_event"


def apply_financialjuice_release_boundary(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Filter non-public FJ rows before manifest projection.

    The direct immutable alert projector remains fail-closed.  This boundary
    prevents an explicitly suppressed optional FJ row from aborting an
    otherwise valid scheduled release while still failing closed on any row
    that could be deliverable or whose disposition is ambiguous.
    """
    events_container = snapshot.get("events")
    event_items = events_container.get("items") if isinstance(events_container, dict) else []
    if not isinstance(event_items, list):
        event_items = []
    quarantined_keys: set[str] = set()
    quarantined_aliases: set[str] = set()
    quarantine_reasons: set[str] = set()
    quarantine_versions: set[str] = set()
    quarantine_fingerprints: set[str] = set()
    fatal_errors: list[str] = []
    retained_events: list[dict[str, Any]] = []

    def process(row: dict[str, Any], lane: str, index: int) -> bool:
        if not is_financialjuice_row(row):
            return True
        identity = _row_identity(row)
        classification, reason = _classify_event(row)
        if classification == "publishable":
            return True
        if classification == "quarantined":
            quarantine_key = identity or f"{lane}:{index}"
            fingerprint = _safe_event_fingerprint(row)
            row_aliases = {
                str(row.get(field) or "").strip()
                for field in (
                    "observation_id", "item_id", "notification_id", "event_key",
                    "event_cluster_key", "canonical_fact_key", "notification_key",
                )
                if str(row.get(field) or "").strip()
            }
            if row_aliases.intersection(quarantined_aliases) or fingerprint in quarantine_fingerprints:
                # The same fact can be present in events, priority and audit
                # lanes with different transport IDs.  Count it once while
                # retaining every alias for downstream filtering.
                quarantined_aliases.update(row_aliases)
                quarantine_reasons.add(reason)
                quarantine_fingerprints.add(fingerprint)
                version = str(row.get("public_summary_version") or "").strip()
                if version:
                    quarantine_versions.add(version)
                return False
            quarantined_keys.add(quarantine_key)
            quarantined_aliases.update(row_aliases)
            quarantine_reasons.add(reason)
            quarantine_fingerprints.add(fingerprint)
            version = str(row.get("public_summary_version") or "").strip()
            if version:
                quarantine_versions.add(version)
            return False
        fatal_errors.append(f"{lane}[{index}]:{reason}")
        return True

    for index, row in enumerate(event_items):
        if isinstance(row, dict) and process(row, "events", index):
            retained_events.append(row)
    if isinstance(events_container, dict):
        events_container["items"] = retained_events

    priority_events = _rows(snapshot.get("financialjuice_priority_events"))
    retained_priority_events: list[dict[str, Any]] = []
    for index, row in enumerate(priority_events):
        if process(row, "priority_events", index):
            retained_priority_events.append(row)
    snapshot["financialjuice_priority_events"] = retained_priority_events

    # A semantically incomplete row may already have been rejected from the
    # public event lane by the producer.  Inspect the bound audit view as well
    # so that the release still records the quarantine (and never silently
    # turns the row into a clean release).
    for index, row in enumerate(_rows(snapshot.get("financialjuice_observations"))):
        process(row, "observations", index)

    # Public observation lanes are filtered by the surviving public event IDs.
    surviving_ids = {_row_identity(row) for row in retained_events if is_financialjuice_row(row)}
    # ``financialjuice_observations`` is the audit lineage consumed by the
    # release contract; keep suppressed rows there so every decision remains
    # traceable.  The public observation lane drops only rows explicitly known
    # to be quarantined; legacy rows without a matching decision remain
    # available to the existing lineage/count contract and are not promoted to
    # the public event lane.
    rows = snapshot.get("external_observations")
    if isinstance(rows, list):
        def is_quarantined(row: dict[str, Any]) -> bool:
            aliases = {
                str(row.get(field) or "").strip()
                for field in (
                    "observation_id", "item_id", "notification_id", "event_key",
                    "event_cluster_key", "canonical_fact_key", "notification_key",
                )
                if str(row.get(field) or "").strip()
            }
            return bool(aliases.intersection(quarantined_aliases)) or _safe_event_fingerprint(row) in quarantine_fingerprints

        snapshot["external_observations"] = [
            row for row in rows
            if not isinstance(row, dict)
            or not is_financialjuice_row(row)
            or not is_quarantined(row)
        ]

    briefing = snapshot.get("briefing")
    if isinstance(briefing, dict):
        for field in ("themes", "secondary_signals", "observations"):
            rows = briefing.get(field)
            if isinstance(rows, list):
                briefing[field] = [
                    row for row in rows
                    if not isinstance(row, dict)
                    or not is_financialjuice_row(row)
                    or _row_identity(row) in surviving_ids
                ]
        keys = briefing.get("displayed_event_keys")
        if isinstance(keys, list):
            briefing["displayed_event_keys"] = [
                value for value in keys if str(value).strip() not in quarantined_aliases
            ]

    status = "invalid" if fatal_errors else "ready_with_quarantine" if quarantined_keys else "ready"
    result = {
        "status": status,
        "alert_projection_status": status,
        "quarantined_alert_count": len(quarantined_keys),
        "quarantined_alert_reasons": sorted(quarantine_reasons),
        "quarantined_summary_versions": sorted(quarantine_versions),
        "quarantined_event_fingerprints": sorted(quarantine_fingerprints),
        "fatal_alert_contract_errors": sorted(set(fatal_errors)),
    }
    contract = snapshot.get("financialjuice_release_contract")
    if isinstance(contract, dict):
        contract.update(result)
    else:
        snapshot["financialjuice_release_contract"] = dict(result)
    return result


def attach_financialjuice_release_diagnostic(snapshot: dict[str, Any], boundary: dict[str, Any]) -> None:
    """Expose only aggregate quarantine diagnostics in the public analysis."""
    count = int(boundary.get("quarantined_alert_count") or 0)
    if count <= 0:
        return
    diagnostic = {
        "status": "degraded",
        "issue": "optional_fj_alert_quarantined",
        "count": count,
        "reasons": list(boundary.get("quarantined_alert_reasons") or []),
        "summary_versions": list(boundary.get("quarantined_summary_versions") or []),
        "checked_at": str(snapshot.get("generated_at") or "") or None,
    }
    briefing = snapshot.get("briefing")
    if isinstance(briefing, dict):
        morning = briefing.get("morning_analysis")
        if isinstance(morning, dict):
            system = morning.setdefault("system_analysis", {})
            if isinstance(system, dict):
                system["financialjuice_alert_quarantine"] = diagnostic
    system_analysis = snapshot.setdefault("system_analysis", {})
    if isinstance(system_analysis, dict):
        system_analysis["financialjuice_alert_quarantine"] = diagnostic


def validate_financialjuice_release(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate the release-bound FJ lineage before the Telegram gate.

    A snapshot with no FinancialJuice observations is valid.  Once the source
    is present, every observation must have exactly one auditable decision and
    every eligible decision must have a corresponding event.  Errors are
    returned rather than raised so callers can persist a safe blocked reason.
    """
    observations = _rows(snapshot.get("financialjuice_observations"))
    decisions = _rows(snapshot.get("financialjuice_priority_decisions"))
    events = _rows(snapshot.get("financialjuice_priority_events"))
    errors: list[str] = []

    observation_ids = {
        str(row.get("observation_id") or "").strip()
        for row in observations
        if str(row.get("observation_id") or "").strip()
    }
    observation_by_id = {
        str(row.get("observation_id") or "").strip(): row
        for row in observations
        if str(row.get("observation_id") or "").strip()
    }
    decision_ids: list[str] = []
    decision_by_id: dict[str, dict[str, Any]] = {}
    for index, decision in enumerate(decisions):
        observation_id = str(decision.get("observation_id") or "").strip()
        status = str(decision.get("notification_status") or "").strip()
        if not observation_id:
            errors.append(f"decision[{index}]:missing_observation_id")
        elif observation_id in decision_by_id:
            errors.append(f"decision[{index}]:duplicate_observation_id")
        else:
            decision_ids.append(observation_id)
            decision_by_id[observation_id] = decision
        if status not in _STATUSES:
            errors.append(f"decision[{index}]:invalid_status")
        if decision.get("release_trace_required") is not True:
            errors.append(f"decision[{index}]:missing_release_trace")
        if status == "eligible":
            try:
                raw_importance = decision.get("vendor_importance")
                importance = float(raw_importance) if raw_importance is not None else -1
            except (TypeError, ValueError):
                importance = -1
            policy = str(decision.get("delivery_policy") or "").strip().casefold()
            if policy == "fj_priority":
                if not math.isfinite(importance) or importance < VENDOR_PRIORITY_THRESHOLD:
                    errors.append(f"decision[{index}]:priority_below_vendor_threshold")
                if decision.get("vendor_priority_notification") is not True:
                    errors.append(f"decision[{index}]:priority_without_priority_flag")
            elif policy == "material_event":
                if decision.get("vendor_priority_notification") is True:
                    errors.append(f"decision[{index}]:material_event_has_priority_flag")
            else:
                errors.append(f"decision[{index}]:missing_delivery_policy")
            if decision.get("public_signal_eligible") is not True:
                errors.append(f"decision[{index}]:eligible_without_public_signal")
            if not is_valid_public_summary(str(decision.get("public_short_message") or ""), source="financialjuice"):
                errors.append(f"decision[{index}]:invalid_public_summary")
            summary_version = str(decision.get("public_summary_version") or "").strip()
            if summary_version:
                if summary_version != PUBLIC_SUMMARY_VERSION:
                    errors.append(f"decision[{index}]:unsupported_public_summary_version")
                if decision.get("public_summary_status") != "ready":
                    errors.append(f"decision[{index}]:public_summary_not_ready")
            summary_contract_version = str(decision.get("summary_contract_version") or "").strip()
            if summary_contract_version and summary_contract_version != SUMMARY_CONTRACT_VERSION:
                errors.append(f"decision[{index}]:unsupported_summary_contract_version")
            decision_key = str(decision.get("canonical_fact_key") or "").strip()
            decision_version = str(decision.get("material_fact_version") or "").strip()
            decision_notification_key = str(decision.get("notification_key") or "").strip()
            if decision.get("identity_contract_status") != "valid":
                errors.append(f"decision[{index}]:identity_contract_invalid")
            if not decision_key:
                errors.append(f"decision[{index}]:missing_canonical_fact_key")
            if not decision_version:
                errors.append(f"decision[{index}]:missing_material_fact_version")
            if not decision_notification_key:
                errors.append(f"decision[{index}]:missing_notification_key")
            elif decision_key and decision_version:
                expected_key = financialjuice_notification_key({
                    "canonical_fact_key": decision_key,
                    "material_fact_version": decision_version,
                })
                if decision_notification_key != expected_key:
                    errors.append(f"decision[{index}]:notification_key_mismatch")
            observation = observation_by_id.get(observation_id)
            for field in ("canonical_fact_key", "material_fact_version", "notification_key"):
                if observation is None or not str(observation.get(field) or "").strip():
                    errors.append(f"decision[{index}]:observation_missing_{field}")
                elif str(observation.get(field)).strip() != str(decision.get(field)).strip():
                    errors.append(f"decision[{index}]:observation_{field}_mismatch")

    if observation_ids and set(decision_ids) != observation_ids:
        missing = sorted(observation_ids.difference(decision_ids))
        extra = sorted(set(decision_ids).difference(observation_ids))
        if missing:
            errors.append("missing_decisions:" + ",".join(missing))
        if extra:
            errors.append("orphan_decisions:" + ",".join(extra))
    if not observation_ids and decisions:
        errors.append("decisions_without_observations")

    event_ids: set[str] = set()
    for index, event in enumerate(events):
        source = str(event.get("source_key") or event.get("source") or "").strip().casefold()
        if source != "financialjuice":
            errors.append(f"event[{index}]:source_not_financialjuice")
        observation_id = str(event.get("observation_id") or "").strip()
        if not observation_id:
            errors.append(f"event[{index}]:missing_observation_id")
            continue
        event_ids.add(observation_id)
        event_decision: dict[str, Any] | None = decision_by_id.get(observation_id)
        if event_decision is None:
            errors.append(f"event[{index}]:missing_decision")
            continue
        if event.get("notification_status") != event_decision.get("notification_status"):
            errors.append(f"event[{index}]:decision_status_mismatch")
        if event.get("notification_status") == "eligible":
            if str(event.get("public_short_message") or event.get("brief_title") or "").strip() != str(
                event_decision.get("public_short_message") or ""
            ).strip():
                errors.append(f"event[{index}]:public_summary_mismatch")
            for field in ("public_summary_version", "public_summary_status", "summary_contract_version"):
                decision_value = str(event_decision.get(field) or "").strip()
                event_value = str(event.get(field) or "").strip()
                if decision_value and decision_value != event_value:
                    errors.append(f"event[{index}]:{field}_mismatch")
        if event.get("source_trace", {}).get("vendor_importance_is_not_risk") is not True:
            errors.append(f"event[{index}]:vendor_risk_separation_missing")
        if event.get("notification_status") == "eligible":
            policy = str(event.get("delivery_policy") or "").strip().casefold()
            if policy == "fj_priority":
                try:
                    importance = float(str(event.get("vendor_importance")))
                except (TypeError, ValueError, OverflowError):
                    importance = -1
                if not math.isfinite(importance) or importance < VENDOR_PRIORITY_THRESHOLD:
                    errors.append(f"event[{index}]:priority_below_vendor_threshold")
                if event.get("vendor_priority_notification") is not True:
                    errors.append(f"event[{index}]:priority_without_priority_flag")
            if policy == "material_event" and event.get("vendor_priority_notification") is True:
                errors.append(f"event[{index}]:material_event_has_priority_flag")
            if policy not in {"fj_priority", "material_event"}:
                errors.append(f"event[{index}]:missing_delivery_policy")
            if event.get("alert_eligible") is not True:
                errors.append(f"event[{index}]:eligible_without_alert_flag")
            public_message = event.get("public_short_message") or event.get("brief_title") or ""
            if not is_valid_public_summary(str(public_message), source="financialjuice"):
                errors.append(f"event[{index}]:invalid_public_summary")
            summary_version = str(event.get("public_summary_version") or "").strip()
            if summary_version:
                if summary_version != PUBLIC_SUMMARY_VERSION:
                    errors.append(f"event[{index}]:unsupported_public_summary_version")
                if event.get("public_summary_status") != "ready":
                    errors.append(f"event[{index}]:public_summary_not_ready")
            summary_contract_version = str(event.get("summary_contract_version") or "").strip()
            if summary_contract_version and summary_contract_version != SUMMARY_CONTRACT_VERSION:
                errors.append(f"event[{index}]:unsupported_summary_contract_version")
            event_key = str(event.get("canonical_fact_key") or "").strip()
            event_version = str(event.get("material_fact_version") or "").strip()
            event_notification_key = str(event.get("notification_key") or "").strip()
            if event.get("identity_contract_status") != "valid":
                errors.append(f"event[{index}]:identity_contract_invalid")
            for field, value in (
                ("canonical_fact_key", event_key),
                ("material_fact_version", event_version),
                ("notification_key", event_notification_key),
            ):
                if not value:
                    errors.append(f"event[{index}]:missing_{field}")
            if event_key != str(event_decision.get("canonical_fact_key") or "").strip():
                errors.append(f"event[{index}]:canonical_fact_key_mismatch")
            if event_version != str(event_decision.get("material_fact_version") or "").strip():
                errors.append(f"event[{index}]:material_fact_version_mismatch")
            if event_notification_key != str(event_decision.get("notification_key") or "").strip():
                errors.append(f"event[{index}]:notification_key_mismatch")
    eligible_ids = {
        observation_id
        for observation_id, decision in decision_by_id.items()
        if decision.get("notification_status") == "eligible"
    }
    if eligible_ids.difference(event_ids):
        errors.append("eligible_events_missing:" + ",".join(sorted(eligible_ids.difference(event_ids))))

    return {
        "ok": not errors,
        "status": "ready" if not errors else "blocked",
        "observation_count": len(observations),
        "decision_count": len(decisions),
        "event_count": len(events),
        "eligible_count": len(eligible_ids),
        "errors": errors,
    }


__all__ = [
    "apply_financialjuice_release_boundary",
    "attach_financialjuice_release_diagnostic",
    "financialjuice_event_fingerprint",
    "financialjuice_quarantine_fingerprints",
    "is_financialjuice_row",
    "validate_financialjuice_release",
]
