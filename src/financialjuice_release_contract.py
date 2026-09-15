"""Fail-closed contract for the FinancialJuice release-to-delivery boundary.

The parser and priority projector already produce the canonical FinancialJuice
rows.  This module is the final producer/consumer contract: it verifies that
the rows published in one market snapshot are the rows referenced by the
priority decisions and that an eligible item uses the correct delivery policy
without turning vendor importance into PRStK risk.
"""

from __future__ import annotations

import math
from typing import Any

from src.financialjuice_contract import VENDOR_PRIORITY_THRESHOLD
from src.financialjuice_notification import financialjuice_notification_key
from src.telegram_client import is_valid_public_summary

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


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


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


__all__ = ["validate_financialjuice_release"]
