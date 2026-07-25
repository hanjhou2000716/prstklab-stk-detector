from src.official_event_monitor import build_official_event_brief, event_key, select_official_event


def test_monitor_selects_only_current_official_event_source():
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
