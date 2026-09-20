from pathlib import Path

from scripts.validate_supabase_migrations import compare


def test_migration_validator_accepts_remote_history_that_is_a_subset_of_repo():
    result = compare(
        Path(__file__).resolve().parents[1],
        "202609170001 market_observation_backup\n202609180001 financialjuice_priority_pending\n",
    )

    assert result["status"] == "ready"
    assert result["unknown_remote_versions"] == []
    assert result["pending_count"] >= 1


def test_migration_validator_blocks_unknown_remote_history():
    result = compare(
        Path(__file__).resolve().parents[1],
        "202609170001 market_observation_backup\n209901010001 unknown\n",
    )

    assert result["status"] == "diverged"
    assert result["unknown_remote_versions"] == ["209901010001"]
