"""Verify durable recipient-level delivery evidence from a pinned ledger."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from src.scheduled_recipient_manifest import parse_recipient_manifest


def verify_delivery_claim(
    payload: object,
    notification_key: str,
    *,
    expected_recipient_hashes: set[str] | frozenset[str] | None = None,
    recipient_set_version: str = "",
) -> dict[str, Any]:
    """Require a complete exact-recipient claim without disclosing hashes."""
    key = str(notification_key or "").strip()
    if not key:
        return {"verified": False, "reason": "notification_key_missing", "recipient_count": 0}
    if not isinstance(payload, Mapping):
        return {"verified": False, "reason": "ledger_payload_invalid", "recipient_count": 0}
    claims = payload.get("delivery_claims")
    if not isinstance(claims, Mapping):
        return {"verified": False, "reason": "delivery_claims_missing", "recipient_count": 0}
    claim = claims.get(key)
    if not isinstance(claim, Mapping):
        return {"verified": False, "reason": "notification_claim_missing", "recipient_count": 0}
    if str(claim.get("notification_key") or key) != key:
        return {"verified": False, "reason": "notification_claim_identity_mismatch", "recipient_count": 0}
    recipients = claim.get("recipient_hashes")
    delivered = claim.get("delivered_recipient_hashes")
    if not isinstance(recipients, list) or not isinstance(delivered, list):
        return {"verified": False, "reason": "recipient_receipt_fields_missing", "recipient_count": 0}
    expected = {str(item).strip() for item in recipients if str(item).strip()}
    actual = {str(item).strip() for item in delivered if str(item).strip()}
    if not expected:
        return {"verified": False, "reason": "recipient_set_empty", "recipient_count": 0}
    if len(expected) != len(recipients) or len(actual) != len(delivered):
        return {"verified": False, "reason": "recipient_hash_list_invalid", "recipient_count": len(expected)}
    if any(not re.fullmatch(r"[0-9a-f]{12}", item) for item in expected | actual):
        return {"verified": False, "reason": "recipient_hash_list_invalid", "recipient_count": len(expected)}
    if expected_recipient_hashes is not None and expected != set(expected_recipient_hashes):
        return {
            "verified": False,
            "reason": "recipient_set_does_not_match_effective_manifest",
            "recipient_count": len(expected_recipient_hashes),
            "recipient_set_version": recipient_set_version,
        }
    if str(claim.get("status") or "").casefold() != "delivered":
        return {
            "verified": False, "reason": "claim_not_delivered", "recipient_count": len(expected),
            "recipient_set_version": recipient_set_version,
        }
    failed = claim.get("failed_recipient_hashes")
    if isinstance(failed, list) and any(str(item).strip() for item in failed):
        return {
            "verified": False, "reason": "failed_recipient_receipts_present", "recipient_count": len(expected),
            "recipient_set_version": recipient_set_version,
        }
    if actual != expected:
        return {
            "verified": False, "reason": "recipient_coverage_incomplete", "recipient_count": len(expected),
            "recipient_set_version": recipient_set_version,
        }
    return {
        "verified": True, "reason": "all_configured_recipient_receipts_persisted",
        "recipient_count": len(expected), "recipient_set_version": recipient_set_version,
    }


def _effective_manifest_from_env() -> tuple[frozenset[str] | None, str, str]:
    raw = os.getenv("SCHEDULED_RECIPIENT_SET_MANIFEST", "")
    try:
        manifest = parse_recipient_manifest(raw)
    except ValueError as exc:
        return None, "", str(exc)
    anchor_raw = os.getenv("RECEIPT_SLOT_ANCHOR", "").strip()
    if not anchor_raw:
        return None, "", "receipt_slot_anchor_missing"
    try:
        anchor = datetime.fromisoformat(anchor_raw.replace("Z", "+00:00"))
    except ValueError:
        return None, "", "receipt_slot_anchor_invalid"
    if anchor.tzinfo is None or anchor.utcoffset() is None:
        return None, "", "receipt_slot_anchor_invalid"
    applicable = manifest.for_anchor(anchor)
    if applicable is None:
        return None, "", "expected_recipient_set_not_effective_for_slot"
    return applicable.recipient_hashes, applicable.version, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--notification-key", default=os.getenv("NOTIFICATION_KEY", ""))
    parser.add_argument("--ledger-commit", default=os.getenv("LEDGER_COMMIT", ""))
    args = parser.parse_args()
    result: dict[str, Any]
    try:
        payload = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
        expected, set_version, manifest_error = _effective_manifest_from_env()
        if manifest_error:
            result = {
                "verified": False, "reason": manifest_error,
                "recipient_count": 0, "recipient_set_version": "",
            }
        else:
            result = verify_delivery_claim(
                payload,
                args.notification_key,
                expected_recipient_hashes=expected,
                recipient_set_version=set_version,
            )
    except (OSError, UnicodeError, json.JSONDecodeError):
        result = {"verified": False, "reason": "ledger_read_failed", "recipient_count": 0}
    result["ledger_commit"] = str(args.ledger_commit or "")[:64]
    result["notification_key"] = str(args.notification_key or "")[:160]
    output = os.getenv("GITHUB_OUTPUT", "").strip()
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"verified={str(result['verified']).lower()}\n")
            handle.write(f"reason={result['reason']}\n")
            handle.write(f"recipient_count={result['recipient_count']}\n")
            handle.write(f"recipient_set_version={result.get('recipient_set_version', '')}\n")
            handle.write(f"ledger_commit={result['ledger_commit']}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
