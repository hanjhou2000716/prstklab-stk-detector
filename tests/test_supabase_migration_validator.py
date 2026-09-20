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


def test_migration_validator_reads_only_remote_column_from_cli_table():
    result = compare(
        Path(__file__).resolve().parents[1],
        "   Local          | Remote         | Time (UTC)\n"
        "202609170001     | 202609170001   | 2026-09-20\n"
        "202609180001     |                |                 \n",
    )

    assert result["status"] == "ready"
    assert "202609180001" in result["pending_local_versions"]
    assert result["remote_count"] == 1


def test_migration_validator_blocks_duplicate_local_versions(tmp_path):
    migrations = tmp_path / "supabase" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "202609170001_first.sql").write_text("select 1;", encoding="utf-8")
    (migrations / "202609170001_second.sql").write_text("select 1;", encoding="utf-8")
    result = compare(tmp_path, "202609170001\n")

    assert result["status"] == "diverged"
    assert result["duplicate_local_versions"] == ["202609170001"]
