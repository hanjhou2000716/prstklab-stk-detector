import json

from src.delivery_receipt_verifier import _effective_manifest_from_env, verify_delivery_claim
from src.scheduled_recipient_manifest import recipient_set_version


def _payload(status="delivered", delivered=None, failed=None):
    recipients = ["a1b2c3d4e5f6", "0a1b2c3d4e5f"]
    return {
        "delivery_claims": {
            "scheduled-anchor:taiwan:2026-10-06:morning": {
                "kind": "scheduled_brief",
                "notification_key": "scheduled-anchor:taiwan:2026-10-06:morning",
                "anchor_key": "taiwan:2026-10-06:morning",
                "status": status,
                "recipient_hashes": recipients,
                "delivered_recipient_hashes": recipients if delivered is None else delivered,
                "failed_recipient_hashes": failed or [],
            },
        },
    }


def test_durable_receipt_requires_exact_effective_recipient_set():
    expected = {"a1b2c3d4e5f6", "0a1b2c3d4e5f"}
    result = verify_delivery_claim(
        _payload(),
        "scheduled-anchor:taiwan:2026-10-06:morning",
        expected_recipient_hashes=expected,
        recipient_set_version="recipients-testversion",
    )

    assert result["verified"] is True
    assert result["recipient_count"] == 2
    assert result["recipient_set_version"] == "recipients-testversion"
    assert "a1b2c3d4e5f6" not in json.dumps(result)


def test_durable_receipt_blocks_manifest_drift_and_partial_delivery():
    key = "scheduled-anchor:taiwan:2026-10-06:morning"
    expected = {"a1b2c3d4e5f6", "0a1b2c3d4e5f"}
    mismatch = verify_delivery_claim(
        _payload(), key, expected_recipient_hashes={"ffeeddccbbaa"},
    )
    partial = verify_delivery_claim(
        _payload(delivered=["a1b2c3d4e5f6"]), key,
        expected_recipient_hashes=expected,
    )
    failed = verify_delivery_claim(
        _payload(failed=["ffeeddccbbaa"]), key,
        expected_recipient_hashes=expected,
    )

    assert mismatch["reason"] == "recipient_set_does_not_match_effective_manifest"
    assert partial["reason"] == "recipient_coverage_incomplete"
    assert failed["reason"] == "failed_recipient_receipts_present"


def test_durable_receipt_rejects_missing_claim_or_empty_recipients():
    key = "scheduled-anchor:taiwan:2026-10-06:morning"
    missing = verify_delivery_claim({"delivery_claims": {}}, key)
    empty = verify_delivery_claim({"delivery_claims": {key: {
        "status": "delivered",
        "recipient_hashes": [],
        "delivered_recipient_hashes": [],
    }}}, key)

    assert missing["reason"] == "notification_claim_missing"
    assert empty["reason"] == "recipient_set_empty"


def test_effective_manifest_requires_original_slot_anchor(monkeypatch):
    hashes = ["a1b2c3d4e5f6", "0a1b2c3d4e5f"]
    effective_at = "2026-10-06T03:22:53.338640Z"
    manifest = {
        "schema_version": "scheduled-recipient-manifest-v1",
        "versions": [{
            "version": recipient_set_version(set(hashes), effective_at),
            "effective_at": effective_at,
            "recipient_hashes": hashes,
        }],
    }
    monkeypatch.setenv("SCHEDULED_RECIPIENT_SET_MANIFEST", json.dumps(manifest))
    monkeypatch.delenv("RECEIPT_SLOT_ANCHOR", raising=False)

    assert _effective_manifest_from_env() == (None, "", "receipt_slot_anchor_missing")

    monkeypatch.setenv("RECEIPT_SLOT_ANCHOR", "2026-10-06T03:00:00Z")
    assert _effective_manifest_from_env() == (
        None, "", "expected_recipient_set_not_effective_for_slot",
    )
