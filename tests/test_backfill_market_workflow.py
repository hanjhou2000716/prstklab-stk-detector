from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_market_backfill_workflow_preserves_module_imports_and_failure_status() -> None:
    workflow = (ROOT / ".github/workflows/backfill-market-observations.yml").read_text(encoding="utf-8")

    assert "PYTHONPATH: ." in workflow
    assert "set -o pipefail" in workflow
    assert "python scripts/backfill_market_observations.py | tee market-backfill-result.json" in workflow
