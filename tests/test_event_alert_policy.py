from datetime import UTC, datetime, timedelta

from src.event_alert_policy import decide_event_alert_policy, event_market_scope


def test_event_alert_policy_uses_market_scope_and_ninety_minute_cooldown():
    event = {"event_type": "global_market", "market_topic": "global_market", "title": "US market update"}
    now = datetime(2026, 9, 7, 2, 0, tzinfo=UTC)
    history = [{
        "alert_lane": "event",
        "market_scope": "us",
        "delivery_status": "delivered",
        "sent_at": (now - timedelta(minutes=30)).isoformat(),
    }]
    decision = decide_event_alert_policy(event, history, now=now)
    assert decision["allowed"] is False
    assert decision["reason"] == "event_market_cooldown"


def test_event_alert_policy_allows_a_new_market_after_cooldown():
    event = {"event_type": "global_market", "market_topic": "global_market", "title": "US market update"}
    now = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)
    history = [{
        "alert_lane": "event",
        "market_scope": "us",
        "delivery_status": "delivered",
        "sent_at": (now - timedelta(minutes=91)).isoformat(),
    }]
    assert decide_event_alert_policy(event, history, now=now)["allowed"] is True


def test_event_alert_policy_keeps_daily_event_cap_even_for_r4():
    event = {"event_type": "energy", "classification": "energy", "prstk_risk_level": "R4", "title": "Supply disruption"}
    now = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    history = [{
        "alert_lane": "event", "market_scope": "global", "delivery_status": "delivered",
        "sent_at": (now - timedelta(hours=1)).isoformat(),
    }, {
        "alert_lane": "event", "market_scope": "taiwan", "delivery_status": "delivered",
        "sent_at": (now - timedelta(hours=3)).isoformat(),
    }]
    decision = decide_event_alert_policy(event, history, now=now)
    assert decision["allowed"] is False
    assert decision["reason"] == "event_daily_budget_exhausted"


def test_market_signal_uses_fixed_floor_and_rolling_volatility():
    event = {
        "kind": "market_signal",
        "instrument": {"ticker": "SOX", "change_percent": 0.7, "volatility_20d_percent": 2.0},
    }
    decision = decide_event_alert_policy(event, [], now=datetime(2026, 9, 7, tzinfo=UTC))
    assert decision["allowed"] is False
    assert decision["reason"] == "sensitive_move_below_threshold"
    assert decision["effective_threshold"] == 1.5


def test_market_scope_maps_core_instruments():
    assert event_market_scope({"kind": "market_signal", "instrument": {"ticker": "TAIEX"}}) == "taiwan"
    assert event_market_scope({"kind": "market_signal", "instrument": {"ticker": "TPEx"}}) == "taiwan"
    assert event_market_scope({"kind": "market_signal", "instrument": {"ticker": "SOX"}}) == "us"
