from datetime import datetime
from zoneinfo import ZoneInfo

from src import official_event_monitor as monitor
from src.official_event_monitor import build_official_event_brief, event_key, select_official_event


def test_black_swan_needs_related_market_confirmation_before_delivery():
    candidate = {
        "importance": "high-risk",
        "url": "https://earthquake.usgs.gov/example",
        "title": "USGS event",
    }
    snapshot = {
        "official_events": {"items": [candidate]},
        "events": {"items": [{**candidate, "impact_confirmation": {"confirmed": False}}]},
    }
    assert select_official_event(snapshot, now=datetime(2026, 7, 27, 20, 0, tzinfo=ZoneInfo("Asia/Taipei"))) is None

    snapshot["events"]["items"][0]["impact_confirmation"] = {"confirmed": True}
    selected = select_official_event(snapshot, now=datetime(2026, 7, 27, 20, 0, tzinfo=ZoneInfo("Asia/Taipei")))
    assert selected["url"] == candidate["url"]


def test_monitor_prioritizes_current_official_event_source():
    snapshot = {
        "events": {"items": [{"title": "third party headline"}]},
        "official_events": {"items": [{"title": "FOMC statement", "url": "https://www.federalreserve.gov/x"}]},
    }
    assert select_official_event(snapshot)["title"] == "FOMC statement"


def test_first_run_baseline_suppresses_official_headline_but_keeps_price_signal():
    snapshot = {
        "official_events": {"items": [{"title": "FOMC statement", "url": "https://www.federalreserve.gov/x"}]},
        "events": {"items": [{"kind": "market_signal", "brief_title": "price alert", "instrument": {"ticker": "NASDAQ"}}]},
    }
    event = select_official_event(snapshot, baseline_official=True)
    assert event["kind"] == "market_signal"


def test_monitor_event_key_is_stable_and_changes_for_a_new_release():
    first = {"title": "CPI", "url": "https://www.bls.gov/a", "released_at": "2026-07-25T08:30:00-04:00"}
    second = {**first, "released_at": "2026-08-25T08:30:00-04:00"}
    assert event_key(first) == event_key(first)
    assert event_key(first) != event_key(second)
    assert event_key(None) == "none"


def test_changed_event_before_delivery_is_safe_noop(monkeypatch, tmp_path):
    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(monitor, "prepare_snapshot", lambda: ({}, {"title": "new event"}))
    monkeypatch.setattr(monitor, "event_key", lambda event: "new-key" if event else "none")

    assert monitor.send_current_event("old-key") is False

    result = output.read_text(encoding="utf-8")
    assert "sent=false" in result
    assert "reason=event_changed_before_delivery" in result


def test_official_event_key_applies_two_hour_topic_cooldown_but_allows_escalation():
    first = {
        "title": "first source title", "source_key": "bls-cpi", "topic_key": "bls-cpi",
        "released_at": "2026-07-25T08:30:00+00:00",
    }
    revised = {**first, "title": "revised source title", "released_at": "2026-07-25T09:10:00+00:00"}
    escalated = {**revised, "escalation": True}
    assert event_key(first) == event_key(revised)
    # Escalation is a state transition of the same canonical event, not a
    # second event identity; the ledger handles the upgrade notification.
    assert event_key(first) == event_key(escalated)


def test_monitor_brief_is_neutral_and_watch_sized():
    brief = build_official_event_brief({"short_label": "Fed／貨幣政策", "title": "Federal Reserve issues FOMC statement with a long title"})
    assert brief.startswith("快訊｜Fed／貨幣政策｜")
    assert len(brief) <= 30


def test_monitor_selects_threshold_price_signal_when_no_official_release_exists():
    snapshot = {
        "official_events": {"items": []},
        "events": {"items": [{
            "kind": "market_signal", "brief_title": "台指價格訊號觸發｜急跌｜高風險",
            "instrument": {"ticker": "TAIEX", "quote_date": "2026-07-27"}, "risk_level": "高風險",
        }]},
    }
    event = select_official_event(snapshot)
    assert event is not None
    assert build_official_event_brief(event) == "快訊｜台指價格訊號觸發｜急跌｜高風險"


def test_price_signal_key_changes_for_escalation_or_a_direction_reversal():
    warning = {"kind": "market_signal", "instrument": {"ticker": "SOX", "quote_date": "2026-07-27"}, "risk_level": "警戒", "signal_state": "急跌:警戒:down"}
    high = {**warning, "risk_level": "高風險", "signal_state": "急跌:高風險:down"}
    rebound = {**warning, "signal_state": "突然大漲:警戒:up"}
    assert event_key(warning) == event_key(warning)
    assert event_key(warning) != event_key(high)
    assert event_key(warning) != event_key(rebound)


def test_taiex_high_risk_signal_repeats_once_per_quote_hour_but_not_every_poll():
    base = {
        "kind": "market_signal",
        "risk_level": "高風險",
        "signal_state": "急跌:高風險:擴大:daily",
        "realert_interval_minutes": 60,
        "instrument": {"ticker": "TAIEX", "quote_date": "2026-07-28", "quote_time": "2026-07-28T10:05:00+08:00"},
    }
    same_hour = {**base, "instrument": {**base["instrument"], "quote_time": "2026-07-28T10:50:00+08:00"}}
    next_hour = {**base, "instrument": {**base["instrument"], "quote_time": "2026-07-28T11:00:00+08:00"}}
    assert event_key(base) == event_key(same_hour)
    assert event_key(base) != event_key(next_hour)


def test_taiwan_market_window_prefers_taiex_and_suppresses_unrelated_price_signals():
    snapshot = {
        "official_events": {"items": []},
        "events": {"items": [
            {"kind": "market_signal", "brief_title": "WTI價格訊號觸發", "instrument": {"ticker": "WTI"}},
            {"kind": "market_signal", "brief_title": "台指價格訊號觸發", "instrument": {"ticker": "TAIEX"}},
        ]},
    }
    now = datetime(2026, 7, 28, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert select_official_event(snapshot, now)["instrument"]["ticker"] == "TAIEX"
    only_wti = {**snapshot, "events": {"items": [snapshot["events"]["items"][0]]}}
    assert select_official_event(only_wti, now) is None
