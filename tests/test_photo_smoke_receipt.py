from pathlib import Path

WORKFLOW = Path(".github/workflows/notify.yml").read_text(encoding="utf-8")
SCRIPT = Path("src/photo_smoke_test.py").read_text(encoding="utf-8")


def test_photo_smoke_exports_delivery_receipt_fields():
    assert "GITHUB_OUTPUT" in SCRIPT
    for field in ("trace_id", "alert_id", "release_id", "snapshot_id", "delivery_mode", "delivered_count", "failed_count"):
        assert f"{field}=" in SCRIPT


def test_photo_smoke_persists_scoped_receipt_without_broadcasting():
    assert "inputs.photo_test == true" in WORKFLOW
    assert "RAILWAY_STATUS_SHARED_SECRET" in WORKFLOW
    assert "DELIVERY_RECEIPT_KIND: text_acceptance" in WORKFLOW
    callback = WORKFLOW.split("Persist text acceptance delivery receipt to Railway", 1)[1]
    assert "continue-on-error: true" not in callback.split("run: python -m src.delivery_callback", 1)[0]
