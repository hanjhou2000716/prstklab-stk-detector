from __future__ import annotations

import json
import sys
from pathlib import Path

from src.research_worker_runner import run_worker


def test_worker_retries_then_records_failure_without_fabricating_output(tmp_path: Path):
    ledger = tmp_path / "failures.ndjson"
    code = "import sys; print('provider unavailable', file=sys.stderr); raise SystemExit(3)"

    result = run_worker(
        [sys.executable, "-c", code],
        market="us",
        strategy="value",
        ledger=ledger,
        retries=1,
        retry_delay_seconds=0,
    )

    assert result == 0
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["attempts"] == 2
    assert record["exit_code"] == 3
    assert record["publish_eligible"] is False
    assert "provider unavailable" in record["error"]


def test_worker_success_does_not_write_failure_record(tmp_path: Path):
    ledger = tmp_path / "failures.ndjson"
    result = run_worker(
        [sys.executable, "-c", "print('ok')"],
        market="taiwan",
        strategy="momentum",
        ledger=ledger,
        retries=2,
        retry_delay_seconds=0,
    )
    assert result == 0
    assert not ledger.exists()
