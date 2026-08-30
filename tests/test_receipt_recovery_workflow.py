from pathlib import Path

WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "receipt-only-recovery.yml").read_text(
    encoding="utf-8"
)


def test_receipt_recovery_is_explicit_and_never_sends_telegram() -> None:
    assert "confirm_recovery" in WORKFLOW
    assert "DELIVERY_RECEIPT_KIND: production" in WORKFLOW
    assert "python -m src.delivery_callback" in WORKFLOW
    assert "TELEGRAM_BOT_TOKEN" not in WORKFLOW
    assert "sendMessage" not in WORKFLOW
    assert "sendPhoto" not in WORKFLOW


def test_receipt_recovery_preserves_release_lineage() -> None:
    for field in ("TRACE_ID", "ALERT_ID", "RELEASE_ID", "SNAPSHOT_ID"):
        assert field in WORKFLOW
    assert "DELIVERY_MODE: text" in WORKFLOW
    assert "contents: read" in WORKFLOW
