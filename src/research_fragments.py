"""Merge Taiwan research scan fragments before building the public report.

Batch workers intentionally write offset-specific artifacts so a failed batch
can be retried without discarding completed work.  The report producer must
therefore consume the complete set, not only ``*-scan-0.csv``.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

_STRATEGIES = ("momentum", "price-action", "resonance")


def _number(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _merge_summary(paths: list[Path]) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            summaries.append(value)
    if not summaries:
        return {}

    result = dict(summaries[0])
    additive = ("requested", "data_complete", "failed", "universe_scanned", "universe_completed", "universe_failed")
    for key in additive:
        values = [_number(item.get(key)) for item in summaries]
        if any(value is not None for value in values):
            result[key] = sum(value or 0 for value in values)
    expected = [_number(item.get("universe_expected")) for item in summaries]
    if any(value is not None for value in expected):
        result["universe_expected"] = max(value or 0 for value in expected)
    result["offset"] = 0
    result["fragment_count"] = len(summaries)
    completed = _number(result.get("universe_completed")) or _number(result.get("data_complete")) or 0
    failed = _number(result.get("universe_failed")) or _number(result.get("failed")) or 0
    requested = _number(result.get("universe_expected")) or _number(result.get("requested")) or 0
    result["scan_state"] = "complete" if requested > 0 and completed >= requested and failed == 0 else "building"
    result["status"] = "complete" if result["scan_state"] == "complete" else "partial"
    return result


def _merge_csv(paths: list[Path], destination: Path) -> int:
    rows: dict[str, dict[str, str]] = {}
    fieldnames: list[str] = []
    for path in paths:
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except OSError:
            continue
        with handle:
            reader = csv.DictReader(handle)
            for name in reader.fieldnames or []:
                if name not in fieldnames:
                    fieldnames.append(name)
            for row in reader:
                ticker = str(row.get("ticker") or "").strip()
                if ticker:
                    rows[ticker] = row
    if not fieldnames:
        return 0
    ordered = list(rows.values())
    def score(row: dict[str, str]) -> float:
        try:
            return float(row.get("score") or "-inf")
        except ValueError:
            return float("-inf")
    ordered.sort(key=score, reverse=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered)
    return len(ordered)


def merge_taiwan_scan_fragments(data_dir: Path) -> list[dict[str, Any]]:
    """Merge offset fragments and return a concise audit of the work done."""
    audits: list[dict[str, Any]] = []
    for strategy in _STRATEGIES:
        prefix = f"taiwan-{strategy}-scan-"
        paths = sorted(data_dir.glob(f"{prefix}*.csv"))
        indexed = [path for path in paths if path.stem.rsplit("-", 1)[-1].isdigit()]
        if len(indexed) <= 1:
            continue
        summary_paths = [data_dir / path.name.replace("-scan-", "-summary-").replace(".csv", ".json") for path in indexed]
        destination = data_dir / f"taiwan-{strategy}-scan-0.csv"
        count = _merge_csv(indexed, destination)
        summary = _merge_summary(summary_paths)
        if summary:
            (data_dir / f"taiwan-{strategy}-summary-0.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        audits.append({"strategy": strategy, "fragment_count": len(indexed), "candidate_rows": count})
    return audits
