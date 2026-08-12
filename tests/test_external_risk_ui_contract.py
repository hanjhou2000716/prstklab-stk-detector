from pathlib import Path


def test_external_risk_pending_reason_is_visible_in_alert_card() -> None:
    app = Path("site/app.js").read_text(encoding="utf-8")
    assert "externalRiskReasonLabel" in app
    assert "等待官方核對" in app
    assert "等待市場同步" in app
    assert "目前不具備高風險推播資格" in app
    assert "snapshot.intelligence?.external_event_risk" in app
