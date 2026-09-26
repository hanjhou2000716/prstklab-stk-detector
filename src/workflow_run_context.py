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

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any, Callable


def fetch_created_at(repository: str, run_id: str, token: str, *, opener: Callable[..., Any] = urlopen) -> str:
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
    created_at = payload.get("created_at") if isinstance(payload, dict) else None
    if not isinstance(created_at, str):
        raise RuntimeError("workflow_run_created_at_missing")
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("workflow_run_created_at_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("workflow_run_created_at_invalid")
    return parsed.isoformat()


def main() -> int:
    try:
        value = fetch_created_at(
            os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("GITHUB_RUN_ID", ""),
            os.environ.get("GITHUB_TOKEN", ""),
        )
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"created_at={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
