import pytest

from src.emergency_alert import build_emergency_brief, high_risk_confirmation_ready


def test_emergency_alert_keeps_the_watch_message_within_30_characters():
    assert build_emergency_brief("fed", "利率決策公布") == "快訊｜Fed｜利率決策公布"


def test_emergency_alert_normalizes_whitespace_and_rejects_long_message():
    assert build_emergency_brief("market", " 盤中  波動擴大 ") == "快訊｜極端波動｜盤中 波動擴大"
    brief = build_emergency_brief("market", "測" * 40)
    assert len(brief) <= 40
    assert "資訊待核對" not in brief


def test_emergency_alert_supports_black_swan_and_material_positive_categories():
    assert build_emergency_brief("black_swan", "日本強震")


def test_black_swan_warning_can_be_delivered_after_market_sync(monkeypatch):
    monkeypatch.delenv("EXTERNAL_OFFICIAL_CONFIRMED", raising=False)
    monkeypatch.delenv("EXTERNAL_MARKET_SYNC_CONFIRMED", raising=False)
    monkeypatch.setenv("EXTERNAL_MARKET_SYNC_CONFIRMED", "true")
    assert high_risk_confirmation_ready("black_swan", "警戒") is True
    assert high_risk_confirmation_ready("black_swan", "高風險") is False
    assert build_emergency_brief("material_positive", "停火協議確認")


def test_emergency_alert_restricts_categories_to_major_event_scope():
    with pytest.raises(ValueError, match="不支援"):
        build_emergency_brief("rumor", "未證實消息")
