from src.event_alerts import _impact_confirmation, _price_signal_thresholds, build_event_snapshot, detect_major_event
from src.official_event_monitor import select_official_event
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


def test_snapshot_explains_overseas_price_signal_below_threshold():
    snapshot = build_event_snapshot({"taiwan": [], "us": []}, [], indices=[{
        "ticker": "NASDAQ", "name": "Nasdaq", "price": 25772.41,
        "change_percent": 1.57, "change_15m_percent": 0.13,
    }])
    assert snapshot["is_major"] is False
    assert snapshot["suppressed_signals"] == [{
        "ticker": "NASDAQ",
        "name": "Nasdaq",
        "reason": "below_threshold",
        "change_percent": 1.57,
        "change_15m_percent": 0.13,
        "daily_threshold": 2.0,
        "intraday_threshold": 1.0,
        "taiwan_session": False,
    }]


def test_us_index_daily_thresholds_are_two_percent():
    for ticker in ("SOX", "NASDAQ", "DJIA"):
        daily, intraday, taiwan_session = _price_signal_thresholds({"ticker": ticker})
        assert daily == 2.0
        assert intraday == 1.0
        assert taiwan_session is False


def test_sox_at_two_percent_is_a_market_signal():
    below = build_event_snapshot({"taiwan": [], "us": []}, [], indices=[{
        "ticker": "SOX", "name": "費城半導體指數", "price": 100,
        "change_percent": 1.99, "freshness": "live",
    }])
    at_threshold = build_event_snapshot({"taiwan": [], "us": []}, [], indices=[{
        "ticker": "SOX", "name": "費城半導體指數", "price": 100,
        "change_percent": 2.0, "freshness": "live",
    }])
    assert below["items"] == []
    assert below["suppressed_signals"][0]["reason"] == "below_threshold"
    assert at_threshold["items"][0]["instrument"]["ticker"] == "SOX"


def test_djia_and_nasdaq_at_two_percent_are_market_signals():
    snapshot = build_event_snapshot({"taiwan": [], "us": []}, [], indices=[
        {"ticker": "DJIA", "name": "道瓊工業指數", "price": 100, "change_percent": 2.0, "freshness": "live"},
        {"ticker": "NASDAQ", "name": "那斯達克綜合指數", "price": 100, "change_percent": 2.0, "freshness": "live"},
    ])
    assert {item["instrument"]["ticker"] for item in snapshot["items"]} == {"DJIA", "NASDAQ"}
    assert "道瓊" in next(item for item in snapshot["items"] if item["instrument"]["ticker"] == "DJIA")["brief_title"]


def test_us_index_fifteen_minute_threshold_is_one_percent():
    for ticker in ("SOX", "NASDAQ", "DJIA"):
        below = build_event_snapshot({"taiwan": [], "us": []}, [], indices=[{
            "ticker": ticker, "name": ticker, "price": 100,
            "change_percent": 0.2, "change_15m_percent": 0.99, "freshness": "live",
        }])
        at_threshold = build_event_snapshot({"taiwan": [], "us": []}, [], indices=[{
            "ticker": ticker, "name": ticker, "price": 100,
            "change_percent": 0.2, "change_15m_percent": 1.0, "freshness": "live",
        }])
        assert below["items"] == []
        assert at_threshold["items"][0]["instrument"]["ticker"] == ticker


def _live_watch_quote(ticker: str, change_percent: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": ticker,
        "market": "us" if ticker in {"QQQM", "QLD", "TSM", "NVDA"} else "taiwan",
        "price": 100.0,
        "change_percent": change_percent,
        "freshness": "live",
        "source_tier": "public-market",
        "source_url": f"https://finance.yahoo.com/quote/{ticker}",
        "source_domain": "finance.yahoo.com",
        "snapshot_id": "market-test",
        "observation_id": f"obs-{ticker}",
    }


def test_watchlist_price_alert_uses_strict_greater_than_1_50_boundary():
    below = build_event_snapshot({"taiwan": [], "us": []}, [_live_watch_quote("NVDA", 1.49)])
    equal = build_event_snapshot({"taiwan": [], "us": []}, [_live_watch_quote("NVDA", 1.50)])
    above = build_event_snapshot({"taiwan": [], "us": []}, [_live_watch_quote("NVDA", 1.51)])
    assert below["watchlist_price_signals"] == []
    assert equal["watchlist_price_signals"] == []
    assert above["watchlist_price_signals"][0]["instrument"]["ticker"] == "NVDA"
    assert above["watchlist_price_signals"][0]["watchlist_realtime"] is True
    assert above["watchlist_price_signals"][0]["notification_expected"] is True


def test_watchlist_price_alert_supports_negative_boundary_and_preserves_risk_code():
    snapshot = build_event_snapshot({"taiwan": [], "us": []}, [_live_watch_quote("2330", -1.8)])
    event = snapshot["watchlist_price_signals"][0]
    assert event["market_direction"] == "下跌"
    assert event["prstk_risk_level"] in {"R1", "R2", "R3", "R4"}
    assert event["source_trace"]["source_domain"] == "finance.yahoo.com"


def test_watchlist_stale_delayed_or_missing_provenance_cannot_alert():
    stale = {**_live_watch_quote("NVDA", 3.0), "freshness": "stale"}
    delayed = {**_live_watch_quote("NVDA", 3.0), "quote_delayed": True}
    no_provenance = {key: value for key, value in _live_watch_quote("NVDA", 3.0).items()
                     if key not in {"source_tier", "source_url", "source_domain", "snapshot_id", "observation_id"}}
    for quote, reason in ((stale, "quote_stale"), (delayed, "quote_delayed"), (no_provenance, "missing_quote_provenance")):
        snapshot = build_event_snapshot({"taiwan": [], "us": []}, [quote])
        assert snapshot["watchlist_price_signals"] == []
        assert snapshot["suppressed_signals"][0]["reason"] == reason


def test_realtime_watchlist_candidate_is_retained_when_other_cards_fill_limit():
    official_items = [
        detect_major_event({"title": title, "url": f"https://example.com/{index}", "source": "official"})
        for index, title in enumerate((
            "美國宣布新一輪關稅措施",
            "Fed 緊急政策聲明",
            "半導體出口限制更新",
            "地緣衝突影響能源供應",
        ))
    ]
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []},
        [_live_watch_quote("NVDA", 2.1)],
        official={"items": [item for item in official_items if item]},
    )
    assert len(snapshot["items"]) == 4
    assert any(item.get("watchlist_realtime") for item in snapshot["items"])


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
    assert event["realert_interval_minutes"] is None
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


def test_news_body_and_impact_are_classified_as_one_event():
    event = detect_major_event({
        "title": "全球｜美國與伊朗局勢｜重要事件",
        "summary": "伊朗與美國談判後，原油供應與航運風險受到關注。",
        "market_impact": "WTI 原油單日 -5.63%。",
        "url": "https://www.reuters.com/world/",
    })
    assert event is not None
    assert event["classification"] in {"conflict", "black_swan"}
    assert event["matched_terms"]


def test_taiwan_routine_corporate_notice_does_not_borrow_nasdaq_move():
    """A MOPS board-date notice must stay observe-only in the Taiwan scope."""
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []},
        [],
        official={"items": [{
            "title": "2603 長榮：公告本公司115年第二季合併財務報告董事會召開日期為115年8月13日",
            "source_key": "mops",
            "source_tier": "official",
            "relevance": "official",
            "url": "https://mops.twse.com.tw/mops/#/web/t05st02",
            "source_url": "https://mops.twse.com.tw/mops/#/web/t05st02",
            "released_at": "2026-08-05T09:45:51+08:00",
            "published_at": "2026-08-05T09:45:51+08:00",
            "issuer_ticker": "2603",
        }]},
        indices=[
            {"ticker": "NASDAQ", "price": 26584.99, "change_percent": 2.59},
            {"ticker": "SOX", "price": 12179.26, "change_percent": 6.55},
        ],
    )
    event = snapshot["items"][0]
    assert event["corporate_event"] is True
    assert event["corporate_routine"] is True
    assert event["related"] == []
    assert event["market_move"] is None
    assert event["market_direction"] is None
    assert event["notification_status"] == "observe_only"
    assert select_official_event(snapshot) is None


def test_taiwan_corporate_event_uses_taiex_sync_only():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []},
        [],
        official={"items": [{
            "title": "2603 長榮：重大合併案公告",
            "source_key": "mops",
            "source_tier": "official",
            "relevance": "official",
            "url": "https://mops.twse.com.tw/mops/#/web/t05st02",
            "source_url": "https://mops.twse.com.tw/mops/#/web/t05st02",
            "released_at": "2026-08-05T09:45:51+08:00",
            "published_at": "2026-08-05T09:45:51+08:00",
            "issuer_ticker": "2603",
        }]},
        indices=[
            {"ticker": "TAIEX", "price": 43100, "change_percent": 1.2,
             "quote_time": "2026-08-05T09:50:00+08:00"},
            {"ticker": "NASDAQ", "price": 26584.99, "change_percent": 6.55},
        ],
    )
    event = snapshot["items"][0]
    assert [item["ticker"] for item in event["related"]] == ["TAIEX"]
    assert event["market_move"] == "+1.2%"
    assert event["notification_status"] == "eligible"


def test_news_event_exposes_pending_reasons_when_oil_time_is_unknown():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": [{
            "title": "全球｜美國與伊朗局勢｜重要事件",
            "summary": "伊朗與美國談判後，原油供應與航運風險受到關注。",
            "market_impact": "WTI 原油單日 -5.63%。",
            "source": "Reuters",
            "url": "https://www.reuters.com/world/",
        }]},
        [],
        indices=[{"ticker": "WTI", "price": 80, "change_percent": -5.63, "quote_time": "2026-08-03T04:21:00+08:00"}],
    )
    event = next(item for item in snapshot["items"] if item.get("kind") == "major_event")
    assert event["notification_status"] == "pending"
    assert "等待官方核對" in event["notification_reasons"]
    assert "等待市場同步" in event["notification_reasons"]


def test_oil_sync_requires_five_percent_move_and_event_time():
    related = [{
        "ticker": "WTI", "price": 80, "change_percent": -5.63,
        "quote_time": "2026-08-03T04:21:00+08:00",
    }]
    same_time = _impact_confirmation({}, related, "2026-08-03T04:10:00+08:00")
    assert same_time["confirmed"] is True
    stale_time = _impact_confirmation({}, related, "2026-08-03T08:00:00+08:00")
    assert stale_time["confirmed"] is False
    below_threshold = _impact_confirmation({}, [{**related[0], "change_percent": -4.99}], "2026-08-03T04:10:00+08:00")
    assert below_threshold["confirmed"] is False


def test_market_signal_keeps_quote_provenance_for_mini_app_trace():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [], indices=[{
            "ticker": "NASDAQ", "name": "Nasdaq", "price": 100.0,
            "change": -3.0, "change_percent": -2.5,
            "quote_time": "2026-08-01T13:00:00+00:00",
            "quote_source": "Yahoo public quote", "source_url": "https://finance.yahoo.com/quote/%5EIXIC",
            "source_domain": "finance.yahoo.com", "fetched_at": "2026-08-01T13:01:00+00:00",
        }],
    )
    event = snapshot["items"][0]
    assert event["source_trace"]["source_url"].startswith("https://finance.yahoo.com/")
    assert event["source_trace"]["source_domain"] == "finance.yahoo.com"
    assert event["source_trace"]["checked_at"].startswith("2026-08-01T13:01")


def test_public_news_enters_realtime_observation_without_high_risk_claim():
    snapshot = build_event_snapshot({"us": [{
        "title": "Nvidia export control urges policy review",
        "url": "https://www.cnyes.com/news/1",
    }]}, [], indices=[])
    assert len(snapshot["items"]) == 1
    event = snapshot["items"][0]
    assert event["notification_status"] == "eligible"
    assert event["public_observation"] is True
    assert event["prstk_risk_level"] in {"R1", "R2"}
    assert event["official_confirmed"] is False


def test_google_conflict_observation_stays_pending_without_official_and_sync():
    snapshot = build_event_snapshot({"us": [{
        "title": "Iran conflict attack rumor spreads",
        "url": "https://news.google.com/articles/1",
    }]}, [], indices=[])
    assert len(snapshot["items"]) == 1
    event = snapshot["items"][0]
    assert event["notification_status"] == "pending"
    assert event["notification_expected"] is False
    assert event["high_risk_eligible"] is False


def test_delayed_intraday_quote_cannot_trigger_an_urgent_price_signal():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [], indices=[
            {"ticker": "TAIEX", "name": "臺灣加權指數", "market": "taiwan",
             "price": 43234.0, "change_percent": -3.6, "quote_delayed": True},
        ],
    )
    assert snapshot["is_major"] is False


def test_stale_quote_cannot_trigger_an_urgent_price_signal():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [], indices=[
            {"ticker": "TAIEX", "name": "台灣加權指數", "market": "taiwan",
             "price": 43234.0, "change_percent": 8.0, "freshness": "stale"},
        ],
    )
    assert snapshot["is_major"] is False
    assert snapshot["suppressed_signals"] == [{
        "ticker": "TAIEX", "reason": "quote_stale",
    }]


def test_unavailable_quote_cannot_trigger_an_urgent_price_signal():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [], indices=[
            {"ticker": "TAIEX", "name": "台灣加權指數", "market": "taiwan",
             "price": 43234.0, "change_percent": 8.0, "freshness": "unavailable"},
        ],
    )
    assert snapshot["is_major"] is False
    assert snapshot["suppressed_signals"] == [{
        "ticker": "TAIEX", "reason": "quote_unavailable",
    }]


def test_rebound_is_not_labelled_as_an_upward_rally():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [], indices=[{
            "ticker": "SOX", "name": "費城半導體指數", "price": 11454.77,
            "change": -364, "change_percent": -3.08,
            "change_15m_percent": 1.88, "currency": "點",
        }],
    )
    event = snapshot["items"][0]
    assert "快速反彈" in event["brief_title"]
    assert "大漲" not in event["brief_title"]


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
    assert event["brief_title"] == "費半價格訊號觸發｜快速反彈｜警戒"
    assert "反彈" in event["why_important"]


def test_brief_prefers_major_event_category_but_remains_watch_friendly():
    snapshot = {
        "quotes": [{"ticker": "2330", "change_percent": 1.25}],
        "events": {"items": [{"short_label": "關稅／政策"}]},
    }
    brief = build_brief(snapshot, "intraday")
    assert brief == "盤中｜關稅／政策｜2330📈+1.2%"
    assert len(brief) <= 40


def test_brief_uses_compact_event_pattern_and_risk_title():
    snapshot = {
        "quotes": [{"ticker": "2330", "change_percent": -2.41}],
        "events": {"items": [{"brief_title": "台指價格訊號觸發｜急跌｜高風險"}]},
    }
    assert build_brief(snapshot, "intraday") == "盤中｜台指價格訊號觸發｜急跌｜高風險"
