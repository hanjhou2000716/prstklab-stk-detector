"""Gate-Driven v3 requirement, evidence and debt validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "config" / "gate_evidence.json"
SCHEMA_PATH = ROOT / "schemas" / "gate-evidence.schema.json"
ALLOWED_STATUSES = {"NOT_STARTED", "IN_PROGRESS", "NEEDS_REVERIFY", "PASS", "FAIL", "BLOCKED", "REOPENED", "LOCKED"}


def load_registry(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_errors(document: dict[str, Any]) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [f"schema: {error.json_path} {error.message}" for error in validator.iter_errors(document)]


def _path_from_reference(reference: str) -> Path:
    return ROOT / reference.split("#", 1)[0].split(":", 1)[0]


def validate_registry(document: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    """Validate structure and return a redacted, deterministic gate report.

    Default mode is suitable for CI: external debt is reported, never
    converted to a successful production claim. Strict mode is reserved for
    the final pre-merge/production gate.
    """
    errors = _schema_errors(document)
    warnings: list[str] = []
    raw_requirements = document.get("requirements")
    requirements: list[dict[str, Any]] = [item for item in raw_requirements if isinstance(item, dict)] if isinstance(raw_requirements, list) else []
    ids = [str(item.get("id") or "") for item in requirements]
    expected = {f"P0-{number:02d}" for number in range(1, 30)}
    missing = sorted(expected - set(ids))
    duplicate = sorted({item for item in ids if ids.count(item) > 1})
    if missing:
        errors.append(f"missing requirements: {', '.join(missing)}")
    if duplicate:
        errors.append(f"duplicate requirements: {', '.join(duplicate)}")
    for item in requirements:
        status = item.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{item.get('id', '<unknown>')}: invalid status")
            continue
        if status in {"PASS", "LOCKED"}:
            for field in ("implementation", "verification", "evidence", "regression_ids", "preservation_ids"):
                if not item.get(field):
                    errors.append(f"{item.get('id', '<unknown>')}: {status} requires {field}")
            for field in ("implementation", "verification"):
                for reference in item.get(field, []):
                    if not (ROOT / str(reference)).is_file():
                        errors.append(f"{item.get('id', '<unknown>')}: {field} path missing")
            for reference in item.get("evidence", []):
                if not _path_from_reference(str(reference)).is_file():
                    errors.append(f"{item.get('id', '<unknown>')}: evidence path missing")
    for collection_name in ("regressions", "completion_debt", "preservation_contracts"):
        raw_collection = document.get(collection_name, [])
        collection = raw_collection if isinstance(raw_collection, list) else []
        seen: set[str] = set()
        for item in collection:
            if not isinstance(item, dict):
                continue
            identifier = str(item.get("id") or "")
            if identifier in seen:
                errors.append(f"{collection_name}: duplicate {identifier}")
            seen.add(identifier)
            for reference in item.get("evidence", []):
                if not _path_from_reference(str(reference)).is_file():
                    errors.append(f"{collection_name}/{identifier}: evidence path missing")
    raw_regressions = document.get("regressions", [])
    raw_debt = document.get("completion_debt", [])
    regressions = raw_regressions if isinstance(raw_regressions, list) else []
    debt = raw_debt if isinstance(raw_debt, list) else []
    open_regressions = [item.get("id") for item in regressions if isinstance(item, dict) and item.get("status") == "OPEN"]
    open_debt = [item.get("id") for item in debt if isinstance(item, dict) and item.get("status") == "OPEN"]
    if open_regressions:
        warnings.append(f"open regressions: {', '.join(str(item) for item in open_regressions)}")
    if open_debt:
        warnings.append(f"open completion debt: {', '.join(str(item) for item in open_debt)}")
    if strict and (open_regressions or open_debt):
        errors.append("strict gate requires zero OPEN regressions and completion debt")
    status = "fail" if errors else "needs_reverify" if (open_regressions or open_debt) else "pass"
    return {
        "status": status,
        "strict": strict,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "requirement_count": len(requirements),
        "locked_count": sum(item.get("status") == "LOCKED" for item in requirements),
        "open_regression_count": len(open_regressions),
        "open_completion_debt_count": len(open_debt),
    }
