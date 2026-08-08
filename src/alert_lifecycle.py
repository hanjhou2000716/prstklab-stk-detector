"""Deterministic alert state transitions; fail closed on missing evidence."""
from __future__ import annotations

from typing import Any

STATES = ("detected", "observation", "pending_confirmation", "confirmed", "escalated", "deescalated", "resolved", "suppressed")

def transition(current: str, *, official_confirmed: bool = False, second_source: bool = False, market_sync: bool = False, material_change: bool = False, condition_active: bool = True, budget_allowed: bool = True) -> str:
    if current not in STATES:
        raise ValueError("unknown lifecycle state")
    if not budget_allowed:
        return "suppressed"
    if not condition_active:
        return "resolved"
    if current in {"detected", "observation"}:
        return "confirmed" if official_confirmed and second_source and market_sync else "pending_confirmation"
    if current == "pending_confirmation":
        return "confirmed" if official_confirmed and second_source and market_sync else current
    if current == "confirmed":
        return "escalated" if material_change else current
    if current == "escalated":
        return "deescalated" if not material_change else current
    if current == "deescalated":
        return "resolved" if not condition_active else current
    return current

def transition_record(current: str, evidence: dict[str, Any]) -> dict[str, Any]:
    nxt = transition(current, **{key: evidence.get(key, False) for key in ("official_confirmed", "second_source", "market_sync", "material_change", "condition_active", "budget_allowed")})
    return {"from": current, "to": nxt, "evidence": evidence}
