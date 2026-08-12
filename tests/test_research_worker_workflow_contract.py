from pathlib import Path

WORKFLOW = Path(".github/workflows/unified-research-report.yml")

def test_all_research_workers_have_bounded_timeout_and_failure_ledger() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "WORKER_TIMEOUT_SECONDS" in text
    assert text.count("--timeout-seconds \"$WORKER_TIMEOUT_SECONDS\"") == 8
    assert text.count("--ledger research-artifacts/scan-failures.ndjson") == 8
