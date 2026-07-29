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
    assert "日內 -2.41%" in event["trigger"]
    assert "點數 -1,082.00" in event["trigger"]
    assert event["related"][0]["ticker"] == "NASDAQ"
    assert "費半" in event["market_context"]
    assert "台股權值" in event["stock_observation"]


def test_taiex_persistent_high_risk_signal_has_hourly_realert_policy_and_escalation_stage():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [], indices=[{
            "ticker": "TAIEX", "name": "臺灣加權指數", "market": "taiwan", "price": 41739.05,
            "change": -1895, "change_percent": -4.34, "quote_time": "2026-07-28T13:10:00+08:00",
            "quote_date": "2026-07-28", "currency": "點",
        }],
    )
    event = snapshot["items"][0]
    assert event["realert_interval_minutes"] == 60
    assert ":極端:" in event["signal_state"]


def test_high_risk_price_alert_is_downgraded_without_related_market_confirmation():
    snapshot = build_event_snapshot({"taiwan": [], "us": []}, [], indices=[
        {"ticker": "SOX", "name": "SOX", "price": 100, "change_percent": -4.0},
        {"ticker": "NASDAQ", "name": "Nasdaq", "price": 100, "change_percent": -0.2},
    ])
    event = snapshot["items"][0]
    assert event["risk_level"] == "警戒"
    assert event["impact_confirmation"]["confirmed"] is False


def test_major_event_includes_neutral_transmission_and_stock_observation():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": [{"title": "美國宣布新一輪關稅措施", "url": "u"}]}, [],
    )
    event = snapshot["items"][0]
    assert "供應鏈" in event["why_important"]
    assert "費半" in event["market_context"]
    assert "台股電子" in event["stock_observation"]


def test_delayed_intraday_quote_cannot_trigger_an_urgent_price_signal():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [], indices=[
            {"ticker": "TAIEX", "name": "臺灣加權指數", "market": "taiwan",
             "price": 43234.0, "change_percent": -3.6, "quote_delayed": True},
        ],
    )
    assert snapshot["is_major"] is False


def test_uncrosschecked_taiex_intraday_quote_cannot_trigger_an_urgent_price_signal():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [], indices=[
            {"ticker": "TAIEX", "name": "臺灣加權指數", "market": "taiwan", "price": 43234.0,
             "change_percent": -3.6, "quote_time": "2026-07-29T10:00:00+08:00",
             "crosscheck_status": "官方來源部分缺漏"},
        ],
    )
    assert snapshot["is_major"] is False


def test_gold_daily_move_requires_the_policy_five_percent_threshold():
    snapshot = build_event_snapshot({"taiwan": [], "us": []}, [], indices=[{
        "ticker": "GOLD", "name": "\u9ec3\u91d1", "price": 4000, "change_percent": 4.9,
    }])
    assert snapshot["is_major"] is False


def test_sox_15_minute_acceleration_triggers_before_the_daily_threshold():
    snapshot = build_event_snapshot({"taiwan": [], "us": []}, [], indices=[{
        "ticker": "SOX", "name": "費城半導體指數", "price": 11489.11, "change": -330,
        "change_percent": -2.79, "change_15m_percent": -1.04, "currency": "點",
    }])

    event = snapshot["items"][0]
    assert event["brief_title"] == "費半價格訊號觸發｜急跌｜警戒"
    assert "15分鐘 -1.04%" in event["trigger"]


def test_sox_fast_rebound_after_a_drop_is_a_distinct_warning_signal():
    snapshot = build_event_snapshot({"taiwan": [], "us": []}, [], indices=[{
        "ticker": "SOX", "name": "費城半導體指數", "price": 11454.77, "change": -364,
        "change_percent": -3.08, "change_15m_percent": 1.88, "currency": "點",
    }])

    event = snapshot["items"][0]
    assert event["brief_title"] == "費半價格訊號觸發｜突然大漲｜警戒"
    assert "反彈" in event["why_important"]


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
