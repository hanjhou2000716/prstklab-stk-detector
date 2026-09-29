"""Fetch immutable GitHub Actions run metadata without exposing credentials."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch_run_context(repository: str, run_id: str, token: str, *, opener: Callable[..., Any] = urlopen) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("workflow_run_identity_invalid")
    if not str(run_id).isdigit() or not token:
        raise ValueError("workflow_run_identity_invalid")
    request = Request(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"workflow_run_metadata_unavailable:{type(exc).__name__}") from None
    if not isinstance(payload, dict) or str(payload.get("id") or "") != str(run_id):
        raise RuntimeError("workflow_run_identity_mismatch")
    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        raise RuntimeError("workflow_run_created_at_missing")
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("workflow_run_created_at_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("workflow_run_created_at_invalid")
    run_started_at = payload.get("run_started_at")
    if isinstance(run_started_at, str) and run_started_at:
        try:
            started = datetime.fromisoformat(run_started_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("workflow_run_started_at_invalid") from exc
        if started.tzinfo is None or started.utcoffset() is None:
            raise RuntimeError("workflow_run_started_at_invalid")
        normalized_started = started.isoformat()
    else:
        normalized_started = ""
    attempt = payload.get("run_attempt", 1)
    if not isinstance(attempt, int) or attempt < 1:
        raise RuntimeError("workflow_run_attempt_invalid")
    return {
        "created_at": parsed.isoformat(),
        "run_started_at": normalized_started,
        "run_attempt": str(attempt),
    }


def fetch_created_at(repository: str, run_id: str, token: str, *, opener: Callable[..., Any] = urlopen) -> str:
    """Backward-compatible accessor for the immutable cron occurrence anchor."""
    return fetch_run_context(repository, run_id, token, opener=opener)["created_at"]


def main() -> int:
    try:
        context = fetch_run_context(
            os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("GITHUB_RUN_ID", ""),
            os.environ.get("GITHUB_TOKEN", ""),
        )
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for key, value in context.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
