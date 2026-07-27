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
    assert snapshot["items"][0]["short_label"] == "NVDA價格訊號觸發"


def test_taiex_large_drop_creates_a_detailed_high_risk_alert_card():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [], indices=[
            {"ticker": "TAIEX", "name": "臺灣加權指數", "price": 43769.19, "change": -1082,
             "change_percent": -2.41, "currency": "點"},
            {"ticker": "NASDAQ", "name": "那斯達克綜合指數", "price": 25137.69, "change": -553.21,
             "change_percent": -2.15, "currency": "點"},
        ],
    )
    event = snapshot["items"][0]
    assert event["brief_title"] == "台指價格訊號觸發｜急跌｜高風險"
    assert "-2.0% 高風險門檻" in event["trigger"]
    assert event["related"][0]["ticker"] == "NASDAQ"


def test_delayed_intraday_quote_cannot_trigger_an_urgent_price_signal():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [], indices=[
            {"ticker": "TAIEX", "name": "臺灣加權指數", "market": "taiwan",
             "price": 43234.0, "change_percent": -3.6, "quote_delayed": True},
        ],
    )
    assert snapshot["is_major"] is False


def test_brief_prefers_major_event_category_but_remains_watch_friendly():
    snapshot = {
        "quotes": [{"ticker": "2330", "change_percent": 1.25}],
        "events": {"items": [{"short_label": "關稅／政策"}]},
    }
    brief = build_brief(snapshot, "intraday")
    assert brief == "盤中｜關稅／政策｜2330📈+1.2%"
    assert len(brief) <= 30


def test_brief_uses_compact_event_pattern_and_risk_title():
    snapshot = {
        "quotes": [{"ticker": "2330", "change_percent": -2.41}],
        "events": {"items": [{"brief_title": "台指價格訊號觸發｜急跌｜高風險"}]},
    }
    assert build_brief(snapshot, "intraday") == "盤中｜台指價格訊號觸發｜急跌｜高風險"
