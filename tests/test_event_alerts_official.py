from src.event_alerts import build_event_snapshot


def test_official_events_are_prioritized_and_keep_their_source_link():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [],
        {"items": [{
            "title": "FOMC statement",
            "url": "https://www.federalreserve.gov/x",
            "source": "Federal Reserve｜官方發布",
            "short_label": "Fed／貨幣政策",
        }]},
    )

    assert snapshot["is_major"] is True
    assert snapshot["items"][0]["source"] == "Federal Reserve｜官方發布"
