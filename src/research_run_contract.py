"""Traceable execution metadata for public research reports.

The report snapshot is a data product, not merely a collection of CSV rows.
Keeping the run identity next to the rows prevents a later market refresh from
being mistaken for a fresh research scan.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from typing import Any


def _iso(value: Any) -> str:
    if value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(UTC).isoformat()
    return datetime.now(UTC).isoformat()


def _source_commit_sha(explicit: str | None = None) -> str | None:
    value = explicit or os.getenv("GITHUB_SHA") or os.getenv("SOURCE_COMMIT_SHA")
    if value:
        return str(value)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha or None


def build_research_run(
    *,
    scan_mode: str,
    scan_scope: str,
    started_at: Any,
    finished_at: Any,
    run_id: str | None = None,
    source_commit_sha: str | None = None,
) -> dict[str, Any]:
    """Build machine-readable run lineage without inventing source evidence."""
    environment_id = os.getenv("GITHUB_RUN_ID")
    attempt = os.getenv("GITHUB_RUN_ATTEMPT")
    resolved_run_id = run_id or os.getenv("RESEARCH_RUN_ID")
    if not resolved_run_id and environment_id:
        resolved_run_id = f"github-{environment_id}-{attempt or '1'}"
    if not resolved_run_id:
        resolved_run_id = f"local-{_iso(started_at).replace(':', '').replace('+00:00', 'Z')}"
    return {
        "run_id": str(resolved_run_id),
        "source_commit_sha": _source_commit_sha(source_commit_sha),
        "run_started_at": _iso(started_at),
        "run_finished_at": _iso(finished_at),
        "scan_mode": str(scan_mode),
        "scan_scope": str(scan_scope),
        "producer": "src.run_research_report",
        "producer_version": "research-run-contract-v1",
    }


def attach_research_run(report: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Attach run metadata to the report and every visible candidate."""
    run = build_research_run(**kwargs)
    report["research_run"] = run
    report["run_id"] = run["run_id"]
    report["source_commit_sha"] = run["source_commit_sha"]
    for candidate in report.get("candidates", []):
        if isinstance(candidate, dict):
            candidate["research_run_id"] = run["run_id"]
            candidate["source_commit_sha"] = run["source_commit_sha"]
    return report

