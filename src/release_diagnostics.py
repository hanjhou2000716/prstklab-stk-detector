"""Write privacy-safe scheduled release preflight diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from src.financialjuice_release_contract import is_financialjuice_row


def _fingerprint(row: dict[str, Any]) -> str:
    payload = {
        "source": row.get("source_key") or row.get("source") or row.get("content_origin"),
        "canonical_fact_key": row.get("canonical_fact_key"),
        "material_fact_version": row.get("material_fact_version"),
        "public_summary_version": row.get("public_summary_version"),
        "public_summary_status": row.get("public_summary_status"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def build_release_preflight_diagnostic(
    snapshot: dict[str, Any] | None,
    *,
    manifest: dict[str, Any] | None = None,
    run_id: str = "",
    workflow_sha: str = "",
    production_sha: str = "",
    slot: str = "",
) -> dict[str, Any]:
    """Return diagnostics without persisting raw event or transport fields."""
    market = snapshot if isinstance(snapshot, dict) else {}
    event_block = market.get("events")
    event_items = event_block.get("items") if isinstance(event_block, dict) else []
    if not isinstance(event_items, list):
        event_items = []
    candidate_lanes = [
        event_items,
        market.get("financialjuice_priority_events"),
        market.get("financialjuice_observations"),
    ]
    fj_rows: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()
    for lane in candidate_lanes:
        if not isinstance(lane, list):
            continue
        for row in lane:
            if not isinstance(row, dict) or not is_financialjuice_row(row):
                continue
            fingerprint = _fingerprint(row)
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            fj_rows.append(row)
    rows = []
    for row in fj_rows:
        rows.append({
            "fingerprint": _fingerprint(row),
            "source_time": row.get("source_time") or row.get("published_at") or row.get("event_time"),
            "public_summary_version": row.get("public_summary_version"),
            "public_summary_status": row.get("public_summary_status"),
            "public_signal_eligible": row.get("public_signal_eligible") is True,
            "alert_eligible": row.get("alert_eligible") is True,
            "vendor_priority_notification": row.get("vendor_priority_notification") is True,
            "notification_status": row.get("notification_status"),
        })
    boundary = market.get("financialjuice_release_boundary")
    if not isinstance(boundary, dict) and isinstance(manifest, dict):
        boundary = manifest
    if not isinstance(boundary, dict):
        boundary = {}
    manifest_status = (
        manifest.get("status")
        if isinstance(manifest, dict)
        else boundary.get("status", "unavailable")
    )
    alert_projection_status = (
        manifest.get("alert_projection_status")
        if isinstance(manifest, dict)
        else boundary.get("alert_projection_status", "unavailable")
    )
    quarantined_alert_count = (
        manifest.get("quarantined_alert_count")
        if isinstance(manifest, dict)
        else boundary.get("quarantined_alert_count", 0)
    )
    quarantined_alert_reasons = (
        manifest.get("quarantined_alert_reasons")
        if isinstance(manifest, dict)
        else boundary.get("quarantined_alert_reasons", [])
    )
    fatal_alert_contract_errors = (
        manifest.get("fatal_alert_contract_errors")
        if isinstance(manifest, dict)
        else boundary.get("fatal_alert_contract_errors", [])
    )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "workflow_sha": workflow_sha,
        "production_sha": production_sha,
        "slot": slot,
        "stage": "release_manifest_preflight",
        "manifest_status": manifest_status,
        "alert_projection_status": alert_projection_status,
        "quarantined_alert_count": quarantined_alert_count,
        "quarantined_alert_reasons": quarantined_alert_reasons,
        "fatal_alert_contract_errors": fatal_alert_contract_errors,
        "quarantined_event_fingerprints": boundary.get("quarantined_event_fingerprints", []),
        "financialjuice_event_count": len(rows),
        "financialjuice_events": rows,
        "pages_write_attempted": False,
        "telegram_operation_count": 0,
        "claim_count": 0,
        "attempt_count": 0,
        "receipt_count": 0,
    }


def write_release_preflight_diagnostic(
    snapshot_path: Path | str,
    output_path: Path | str,
    *,
    manifest_path: Path | str | None = None,
    run_id: str = "",
    workflow_sha: str = "",
    production_sha: str = "",
    slot: str = "",
) -> dict[str, Any]:
    snapshot: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    try:
        value = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        if isinstance(value, dict):
            snapshot = value
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    if manifest_path:
        try:
            value = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            if isinstance(value, dict):
                manifest = value
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    diagnostic = build_release_preflight_diagnostic(
        snapshot,
        manifest=manifest,
        run_id=run_id,
        workflow_sha=workflow_sha,
        production_sha=production_sha,
        slot=slot,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return diagnostic


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a privacy-safe release preflight diagnostic")
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--slot", default="")
    args = parser.parse_args()
    write_release_preflight_diagnostic(
        args.snapshot,
        args.output,
        manifest_path=args.manifest,
        run_id=os.getenv("GITHUB_RUN_ID", ""),
        workflow_sha=os.getenv("GITHUB_SHA", ""),
        production_sha=os.getenv("PRODUCTION_SHA", ""),
        slot=args.slot,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
