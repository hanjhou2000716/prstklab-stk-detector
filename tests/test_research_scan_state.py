from __future__ import annotations

from src.research_report import _normalize_scan_state
from src.research_scan_state import classify_scan_state


def test_partial_failure_is_building_not_complete() -> None:
    assert classify_scan_state(expected=10, completed=9, failed=1) == "building"


def test_all_failed_is_failed() -> None:
    assert classify_scan_state(expected=10, completed=0, failed=10) == "failed"


def test_empty_successful_scan_is_complete() -> None:
    assert classify_scan_state(expected=10, completed=10, failed=0) == "complete"


def test_report_boundary_repairs_legacy_contradiction() -> None:
    assert _normalize_scan_state(
        {"scan_state": "complete", "requested": 10, "data_complete": 9, "failed": 1},
        file_readable=True,
    ) == "building"

