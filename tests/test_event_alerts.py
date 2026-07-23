from src.event_alerts import build_event_snapshot, detect_major_event
from src.scheduled_brief import build_brief


def test_detects_tariff_event_from_headline():
    event = detect_major_event({"title": "1. 美國宣布新一輪關稅措施", "url": "u", "source": "s"})
    assert event is not None
    assert event["short_label"] == "關稅／政策"
    assert event["title"] == "美國宣布新一輪關稅措施"


def test_detects_semiconductor_earnings_but_not_general_semiconductor_news():
    assert detect_major_event({"title": "台積電法說上修展望", "url": "u", "source": "s"})["short_label"] == "半導體財報"
    assert detect_major_event({"title": "半導體族群走勢整理", "url": "u", "source": "s"}) is None


def test_snapshot_has_no_event_conclusion_when_no_threshold_is_met():
    snapshot = build_event_snapshot({"taiwan": [], "us": []}, [])
    assert snapshot["is_major"] is False
    assert snapshot["message"] == "今日無重大市場事件，持續觀察。"


def test_large_representative_move_becomes_market_volatility_event():
    snapshot = build_event_snapshot({"taiwan": [], "us": []}, [{"ticker": "NVDA", "change_percent": -3.5}])
    assert snapshot["items"][0]["short_label"] == "波動顯著"


def test_brief_prefers_major_event_category_but_remains_watch_friendly():
    snapshot = {
        "quotes": [{"ticker": "2330", "change_percent": 1.25}],
        "events": {"items": [{"short_label": "關稅／政策"}]},
    }
    brief = build_brief(snapshot, "intraday")
    assert brief == "盤中｜關稅／政策｜2330📈+1.2%"
    assert len(brief) <= 30
