import pytest

from src.alert_lifecycle import transition, transition_record


def test_lifecycle_confirmation_escalation_and_resolution():
    assert transition("observation") == "pending_confirmation"
    assert transition("pending_confirmation", official_confirmed=True, second_source=True, market_sync=True) == "confirmed"
    assert transition("confirmed", material_change=True) == "escalated"
    assert transition("escalated", material_change=False) == "deescalated"
    assert transition("deescalated", condition_active=False) == "resolved"


def test_lifecycle_budget_and_invalid_state():
    assert transition("confirmed", budget_allowed=False) == "suppressed"
    with pytest.raises(ValueError):
        transition("unknown")
    record = transition_record("detected", {"official_confirmed": True, "condition_active": True, "budget_allowed": True})
    assert record["from"] == "detected" and record["to"] == "pending_confirmation"


def test_lifecycle_keeps_active_deescalated_and_resolved_states():
    assert transition("deescalated", condition_active=True) == "deescalated"
    assert transition("resolved", condition_active=True) == "resolved"
    assert transition("confirmed", material_change=False) == "confirmed"
