from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_walk_forward_workflow_audits_and_uploads_incomplete_archive():
    workflow = (ROOT / ".github" / "workflows" / "four-strategy-walk-forward.yml").read_text(encoding="utf-8")
    assert "run_backtest_archive_audit" in workflow
    assert "Upload archive audit (including incomplete reports)" in workflow
    assert "if: always()" in workflow


def test_archive_audit_workflow_is_manual_until_historical_data_exists():
    workflow = (ROOT / ".github" / "workflows" / "backtest-archive-audit.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "market: [taiwan, us]" in workflow
