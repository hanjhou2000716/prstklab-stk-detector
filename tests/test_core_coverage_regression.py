from datetime import UTC, datetime, timedelta

import pytest

from src.alert_budget import decide_alert_budget
from src.alert_caption import make_caption
from src.alert_contract import AlertEnvelope
from src.deep_link_router import parse_deep_link, resolve_deep_link

NOW = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)


def test_budget_covers_invalid_timestamp_and_event_update_cap():
    history = [
        {"event_key": "evt", "sent_at": "not-a-time"},
        {"event_key": "evt", "sent_at": (NOW - timedelta(minutes=10)).isoformat()},
    ]
    result = decide_alert_budget(
        {"event_key": "evt", "importance": "normal"},
        history,
        now=NOW,
        max_updates_per_event=2,
    )
    assert result["allowed"] is False
    assert result["reason"] == "event_update_budget_exhausted"


def test_caption_fallback_keeps_semantic_status_under_limit():
    caption = make_caption(
        subject="這是一個非常長的事件標題，需要安全壓縮而不能切斷關鍵字",
        change="+123.45%",
        state="等待官方核對",
    )
    assert len(caption) <= 40
    assert "等待官方核對" in caption


def test_deep_link_normalizes_unknown_view_and_missing_alert():
    link = parse_deep_link("https://example.test/?release=r1&alert=a1&view=not-a-view")
    assert link.view == "event"
    result = resolve_deep_link(link, manifest={"release_id": "r1"}, alerts=[])
    assert result["status"] == "missing"


def test_alert_contract_rejects_invalid_enum_and_missing_timezone():
    envelope = AlertEnvelope(
        alert_id="a1",
        event_cluster_key="e1",
        alert_type="unknown",
        lifecycle_state="observation",
        severity="normal",
        title="事件",
        short_caption="事件",
        release_id="r1",
        snapshot_id="s1",
        created_at="2026-08-10T08:00:00+00:00",
    )
    with pytest.raises(ValueError, match="invalid alert"):
        envelope.validate()

    envelope.alert_type = "market_risk"
    envelope.created_at = "2026-08-10T08:00:00"
    with pytest.raises(ValueError, match="timezone"):
        envelope.validate()


def test_caption_fallback_uses_safe_template_when_subject_is_too_long():
    caption = make_caption(
        subject="X" * 200,
        change="+9.9%",
        state="等待官方核對",
        icon="!",
    )
    assert caption == "!｜等待官方核對"


def test_alert_contract_rejects_overlong_caption():
    envelope = AlertEnvelope(
        alert_id="a1",
        event_cluster_key="e1",
        alert_type="briefing",
        lifecycle_state="detected",
        severity="normal",
        title="title",
        short_caption="x" * 41,
        release_id="r1",
        snapshot_id="s1",
        created_at=NOW.isoformat(),
    )
    with pytest.raises(ValueError, match="short_caption"):
        envelope.validate()


def test_alert_contract_rejects_out_of_range_quality_score():
    envelope = AlertEnvelope(
        alert_id="a1",
        event_cluster_key="e1",
        alert_type="briefing",
        lifecycle_state="detected",
        severity="normal",
        title="title",
        short_caption="ok",
        data_quality_score=101,
        release_id="r1",
        snapshot_id="s1",
        created_at=NOW.isoformat(),
    )
    with pytest.raises(ValueError, match="data_quality_score"):
        envelope.validate()

