"""Explicit failure ledger for isolated research workers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_scan_failures(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    failures: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("market") and item.get("strategy"):
            failures.append(item)
    return failures


def apply_scan_failures(report: dict[str, Any], failures: list[dict[str, Any]]) -> dict[str, Any]:
    """Mark worker failures and block publication without inventing candidates."""
    if not failures:
        return report
    failed_keys = {(str(item["market"]), str(item["strategy"])) for item in failures}
    for source in report.get("sources", []):
        key = (str(source.get("market") or ""), str(source.get("strategy") or ""))
        if key not in failed_keys:
            continue
        source["scan_state"] = "failed"
        source["failed_records"] = max(int(source.get("failed_records") or 0), 1)
        source["blocking_reason"] = "research worker failed; candidate output is unavailable"
        source["candidate_state"] = "data_gap"
    report["scan_failures"] = failures
    report["scan_failure_count"] = len(failures)
    report["production_eligible"] = False
    report["publish_eligible"] = False
    report["publication_state"] = "diagnostic"
    report["blocking_reason"] = "one or more research workers failed; preserving last successful release"
    return report
