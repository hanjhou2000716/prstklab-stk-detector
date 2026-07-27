from src.official_event_monitor import build_official_event_brief, event_key, select_official_event


def test_monitor_prioritizes_current_official_event_source():
    snapshot = {
        "events": {"items": [{"title": "third party headline"}]},
        "official_events": {"items": [{"title": "FOMC statement", "url": "https://www.federalreserve.gov/x"}]},
    }
    assert select_official_event(snapshot)["title"] == "FOMC statement"


def test_monitor_event_key_is_stable_and_changes_for_a_new_release():
    first = {"title": "CPI", "url": "https://www.bls.gov/a", "released_at": "2026-07-25T08:30:00-04:00"}
    second = {**first, "released_at": "2026-08-25T08:30:00-04:00"}
    assert event_key(first) == event_key(first)
    assert event_key(first) != event_key(second)
    assert event_key(None) == "none"


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


def test_price_signal_key_only_changes_when_risk_level_escalates():
    warning = {"kind": "market_signal", "instrument": {"ticker": "SOX", "quote_date": "2026-07-27"}, "risk_level": "警戒"}
    high = {**warning, "risk_level": "高風險"}
    assert event_key(warning) == event_key(warning)
    assert event_key(warning) != event_key(high)
