import pytest

from src.emergency_alert import build_emergency_brief


def test_emergency_alert_keeps_the_watch_message_within_30_characters():
    assert build_emergency_brief("fed", "利率決策公布") == "快訊｜Fed｜利率決策公布"


def test_emergency_alert_normalizes_whitespace_and_rejects_long_message():
    assert build_emergency_brief("market", " 盤中  波動擴大 ") == "快訊｜極端波動｜盤中 波動擴大"
    with pytest.raises(ValueError, match="超過 30 字"):
        build_emergency_brief("market", "測" * 30)


def test_emergency_alert_restricts_categories_to_major_event_scope():
    with pytest.raises(ValueError, match="不支援"):
        build_emergency_brief("rumor", "未證實消息")
