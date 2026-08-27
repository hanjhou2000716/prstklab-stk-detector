"""Validate the machine-readable migration requirement traceability ledger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATUSES = frozenset({"NOT_STARTED", "IN_PROGRESS", "NEEDS_REVERIFY", "PASS", "FAIL", "BLOCKED", "REOPENED", "LOCKED"})
REQUIRED_FIELDS = frozenset({"requirement", "task", "implementation", "verification", "evidence", "regression", "status"})


def load_traceability(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the repository traceability ledger."""
    ledger_path = Path(path) if path else Path(__file__).parents[1] / "docs" / "traceability.json"
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"traceability ledger could not be read: {exc}") from exc
    validate_traceability(payload)
    return payload


def validate_traceability(payload: dict[str, Any]) -> None:
    """Reject incomplete or over-claimed requirement evidence."""
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list) or not payload["entries"]:
        raise ValueError("traceability ledger must contain a non-empty entries list")
    seen: set[str] = set()
    for entry in payload["entries"]:
        if not isinstance(entry, dict) or not REQUIRED_FIELDS.issubset(entry):
            raise ValueError("each traceability entry must contain all required fields")
        requirement = str(entry["requirement"]).strip()
        if not requirement or requirement in seen:
            raise ValueError("requirement identifiers must be non-empty and unique")
        seen.add(requirement)
        if entry["status"] not in STATUSES:
            raise ValueError(f"unsupported traceability status: {entry['status']}")
        for field in ("implementation", "verification"):
            values = entry[field]
            if not isinstance(values, list) or not values or not all(str(value).strip() for value in values):
                raise ValueError(f"{field} must be a non-empty list")
        if entry["status"] in {"PASS", "LOCKED"} and not str(entry["evidence"]).strip():
            raise ValueError("PASS/LOCKED entries require objective evidence")

