from src.artifact_contract import validate_market


def _market(raw_observation: dict) -> dict:
    return {
        "generated_at": "2026-08-12T00:00:00+00:00",
        "snapshot_id": "snapshot-12345678",
        "indices": [],
        "quotes": [],
        "source_health": {},
        "raw_observation": raw_observation,
    }


def test_required_raw_observation_must_be_recorded() -> None:
    errors = validate_market(_market({
        "enabled": False,
        "required": True,
        "recorded": False,
        "state": "unavailable",
        "reason": "required_not_configured",
    }))
    assert any("required=true requires recorded=true" in error for error in errors)


def test_recorded_raw_observation_requires_id_and_consistent_state() -> None:
    errors = validate_market(_market({
        "enabled": True,
        "required": False,
        "recorded": True,
        "state": "recorded",
    }))
    assert any("requires enabled, recorded and observation_id" in error for error in errors)


def test_optional_disabled_raw_observation_is_valid() -> None:
    assert validate_market(_market({
        "enabled": False,
        "required": False,
        "recorded": False,
        "state": "disabled",
        "reason": "not_configured",
    })) == []
