from pathlib import Path


def test_non_creator_production_paths_do_not_call_photo_delivery():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "src/scheduled_delivery.py",
        "src/official_event_monitor.py",
        "src/emergency_alert.py",
        "src/financialjuice_notification.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "send_photo_briefs" not in source
        assert "render_alert_card" not in source


def test_creator_photo_exception_remains_isolated():
    source = (Path(__file__).resolve().parents[1] / "src/creator_notification.py").read_text(encoding="utf-8")
    assert "send_photo_briefs" in source
