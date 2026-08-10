"""Formal evidence state contract for public market events.

The event classifier can discover a story before it has enough evidence for a
notification.  This module makes that distinction explicit and serializable:
discovery is visible research, while only corroborated or officially confirmed
events can satisfy the corresponding delivery gate.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

EVIDENCE_STATES = (
    "discovery",
    "single_source",
    "pending_crosscheck",
    "corroborated",
    "official_confirmed",
)


def _domains(record: dict[str, Any]) -> set[str]:
    values = record.get("crosscheck_domains") or record.get("verified_domains") or ()
    return {str(value).strip().lower().removeprefix("www.") for value in values if str(value).strip()}


def evidence_state(record: dict[str, Any]) -> str:
    """Derive a conservative state from normalized provenance fields."""
    tier = str(record.get("source_tier") or "").strip().lower()
    official = tier == "official" or bool(record.get("official_confirmed"))
    crosscheck = str(record.get("crosscheck_status") or "").strip().lower()
    if crosscheck == "official_confirmed" or (official and record.get("cross_checked") is True):
        return "official_confirmed"
    if crosscheck == "corroborated" or record.get("cross_checked") is True:
        return "corroborated"
    domains = _domains(record)
    if tier == "discovery" and not domains:
        return "discovery"
    if len(domains) < 2:
        return "single_source"
    return "pending_crosscheck"


def evidence_reason(state: str, *, official_confirmed: bool = False, market_sync: bool = False) -> str:
    """Return a user-facing reason without implying that missing evidence is safe."""
    if state == "discovery":
        return "等待第二來源"
    if state in {"single_source", "pending_crosscheck"}:
        return "等待第二來源" if not official_confirmed else "等待市場同步"
    if state == "corroborated" and not market_sync:
        return "等待市場同步"
    if state == "official_confirmed" and not market_sync:
        return "等待市場同步"
    return "證據已核對"


def attach_evidence_state(record: dict[str, Any]) -> dict[str, Any]:
    """Attach stable evidence metadata to an event record."""
    item = dict(record)
    state = evidence_state(item)
    item["evidence_state"] = state
    item["evidence_reason"] = evidence_reason(
        state,
        official_confirmed=bool(item.get("official_confirmed")) or state == "official_confirmed",
        market_sync=bool(item.get("market_sync_confirmed") or item.get("market_sync")),
    )
    item["evidence_domains"] = sorted(_domains(item))
    item["evidence_sufficient"] = state in {"corroborated", "official_confirmed"}
    return item


def summarize_evidence(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Count states for source-health and Mini App aggregate display."""
    counts = {state: 0 for state in EVIDENCE_STATES}
    for record in records:
        state = evidence_state(record)
        counts[state] = counts.get(state, 0) + 1
    return counts
