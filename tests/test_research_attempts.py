import json
from datetime import UTC, datetime, timedelta

from src.research_attempts import claim_strategies

NOW = datetime(2026, 9, 5, 8, tzinfo=UTC)
SLOT = "taiwan:2026-09-04:close-research"


def test_same_slot_strategy_is_claimed_once_per_hour(tmp_path):
    path = tmp_path / "attempts.json"
    first = claim_strategies(path, slot_key=SLOT, target_market="taiwan", strategies=["value"], now=NOW)
    second = claim_strategies(
        path, slot_key=SLOT, target_market="taiwan", strategies=["value"],
        now=NOW + timedelta(minutes=59),
    )
    assert first["allowed_strategies"] == ["value"]
    assert second["allowed_strategies"] == []
    assert second["suppressed"] == {"value": "retry_cooldown"}


def test_same_slot_strategy_has_three_bounded_attempts(tmp_path):
    path = tmp_path / "attempts.json"
    for index in range(3):
        result = claim_strategies(
            path, slot_key=SLOT, target_market="taiwan", strategies=["value"],
            now=NOW + timedelta(hours=index),
        )
        assert result["allowed_strategies"] == ["value"]
    fourth = claim_strategies(
        path, slot_key=SLOT, target_market="taiwan", strategies=["value"],
        now=NOW + timedelta(hours=3),
    )
    assert fourth["allowed_strategies"] == []
    assert fourth["suppressed"] == {"value": "attempt_limit_reached"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert next(iter(payload["slots"].values()))["attempts"] == 3


def test_both_market_claim_requires_both_slot_pairs(tmp_path):
    path = tmp_path / "attempts.json"
    result = claim_strategies(
        path,
        slot_key="taiwan:2026-09-04:close-research,us:2026-09-04:close-research",
        target_market="both", strategies=["value"], now=NOW,
    )
    assert result["allowed_strategies"] == ["value"]
    assert set(result["claims"]["value"]) == {"taiwan", "us"}


def test_both_market_run_with_one_due_slot_is_suppressed(tmp_path):
    result = claim_strategies(
        tmp_path / "attempts.json", slot_key=SLOT, target_market="both",
        strategies=["value"], now=NOW,
    )
    assert result["allowed_strategies"] == []
    assert result["suppressed"] == {"value": "slot_incomplete"}
