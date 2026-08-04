"""Strict archive contract for point-in-time walk-forward research."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence


REQUIRED_DATASETS = ("bars", "adjustments", "dividends", "membership", "filings", "delisted", "benchmark")


def validate_archive_manifest(manifest: Mapping[str, Any], datasets: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    reasons: list[str] = []
    missing = [name for name in REQUIRED_DATASETS if not datasets.get(name)]
    if missing:
        reasons.append("missing datasets: " + ", ".join(missing))
    if manifest.get("point_in_time") is not True:
        reasons.append("manifest is not point_in_time")
    if manifest.get("survivorship_bias_checked") is not True:
        reasons.append("survivorship bias audit not confirmed")
    if manifest.get("currency_adjustment_policy") in (None, ""):
        reasons.append("currency adjustment policy missing")
    for name, records in datasets.items():
        for record in records:
            if not isinstance(record, Mapping) or not record.get("as_of"):
                reasons.append(f"{name} record missing as_of")
                break
            try:
                date.fromisoformat(str(record["as_of"])[:10])
            except ValueError:
                reasons.append(f"{name} record has invalid as_of")
                break
    return {"status": "ready" if not reasons else "incomplete", "reasons": reasons,
            "required_datasets": list(REQUIRED_DATASETS), "point_in_time": not reasons}
