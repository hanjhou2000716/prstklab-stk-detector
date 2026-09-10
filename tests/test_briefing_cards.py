from datetime import datetime

from src.briefing_cards import _contagion_inputs, _regime_factors, build_briefing_snapshot
from src.schedule_contract import live_market_phase_at


def test_live_market_phase_uses_current_taipei_phase_for_pages_refreshes():
    assert live_market_phase_at(datetime.fromisoformat("2026-09-10T14:54:59+08:00")) == (
        "post_close",
        "2026-09-10",
    )


def test_live_market_briefing_does_not_fall_back_to_morning_label():
    briefing = build_briefing_snapshot(
        {
            "generated_at": "2026-09-10T06:54:59+00:00",
            "indices": [
                {"ticker": "TAIEX", "price": 26000, "change_percent": 0.8},
                {"ticker": "TPEx", "price": 300, "change_percent": 0.6},
                {"ticker": "NASDAQ", "price": 20000, "change_percent": -0.29},
                {"ticker": "SOX", "price": 5000, "change_percent": 0.37},
                {"ticker": "DJIA", "price": 45000, "change_percent": -0.51},
            ],
            "quotes": [],
            "macro_quotes": [],
            "events": {"items": []},
        },
        "post_close",
    )

    assert briefing["slot"] == "post_close"
    assert briefing["title"] == "台股盤後儀表板"
    assert "晨報" not in briefing["public_short_message"]


def test_regime_factors_omit_stale_quotes_and_expose_partial_evidence():
    factors = _regime_factors(
        {
            "TAIEX": {"change_percent": 2.0, "freshness": "live"},
            "NASDAQ": {"change_percent": 1.0, "freshness": "stale"},
            "SOX": {"change_percent": -1.0, "freshness": "live"},
        },
        {},
    )
    assert "trend" in factors
    assert "breadth" not in factors


def test_regime_factors_do_not_use_delayed_quote_as_market_evidence():
    factors = _regime_factors(
        {"TAIEX": {"change_percent": 8.0, "quote_delayed": True}}, {},
    )
    assert factors == {}


def test_contagion_inputs_are_bound_to_snapshot_quotes_and_vix():
    inputs = _contagion_inputs(
        {"TAIEX": {"change_percent": -3.2}, "DXY": {"change_percent": 1.1}},
        {"taiwan": {"vix": {"change_percent": 12.0}}},
    )
    assert inputs["equities"]["change_percent"] == -3.2
    assert inputs["vix"]["change_percent"] == 12.0
    assert inputs["usd"]["change_percent"] == 1.1


def test_briefing_summary_facts_are_structured_and_quote_led_without_news_event():
    briefing = build_briefing_snapshot({
        "generated_at": "2026-09-07T07:00:00+00:00",
        "indices": [
            {"ticker": "TAIEX", "price": 26000, "change_percent": 0.8, "quote_date": "2026-09-07", "source_label": "Yahoo"},
            {"ticker": "TPEx", "price": 300, "change_percent": 0.6, "quote_date": "2026-09-07", "source_label": "Yahoo"},
            {"ticker": "NASDAQ", "price": 20000, "change_percent": -0.29, "quote_date": "2026-09-04", "source_label": "Yahoo"},
            {"ticker": "SOX", "price": 5000, "change_percent": 3.37, "quote_date": "2026-09-04", "source_label": "Yahoo"},
            {"ticker": "DJIA", "price": 45000, "change_percent": -0.51, "quote_date": "2026-09-04", "source_label": "Yahoo"},
        ],
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": []},
    }, "morning")

    facts = briefing["summary_facts"]
    assert [item["label"] for item in facts[:3]] == ["市場狀態", "信心", "行情比較"]
    assert all(isinstance(item["evidence_refs"], list) for item in facts)
    assert not any(item["key"] == "primary_event" for item in facts)


def test_observation_cards_follow_quote_led_digest_without_raw_publisher_tail():
    briefing = build_briefing_snapshot({
        "generated_at": "2026-09-07T07:00:00+00:00",
        "indices": [
            {"ticker": "TAIEX", "price": 26000, "change_percent": 0.8},
            {"ticker": "NASDAQ", "price": 20000, "change_percent": -0.29},
            {"ticker": "SOX", "price": 5000, "change_percent": 3.37},
            {"ticker": "DJIA", "price": 45000, "change_percent": -0.51},
        ],
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": [{
            "event": "全球半導體產值上看2兆美元，亞洲AI供應鏈成焦點，台積電曝量產優勢-財經焦點情報站 - CMoney投資網誌。",
        }]},
    }, "morning")

    observation_text = " ".join(
        value for card in briefing["observations"] for value in card.values()
    )
    assert "CMoney" not in observation_text
    assert "財經焦點情報站" not in observation_text
    assert "行情主導" in briefing["observations"][-1]["event"]


def test_midday_briefing_includes_japan_korea_and_public_observation_cards():
    snapshot = {
        "indices": [
            {"ticker": "TAIEX", "name": "臺灣加權指數", "price": 43800},
            {"ticker": "NIKKEI", "name": "日經225", "price": 40000},
            {"ticker": "KOSPI", "name": "韓國綜合", "price": 3000},
        ],
        "quotes": [{"ticker": "2330", "name": "台積電", "price": 1200}],
        "macro_quotes": [{"ticker": "DXY", "change_percent": 0.2}],
        "events": {"items": [{
            "brief_title": "台指價格訊號觸發｜急跌｜警戒",
            "summary": "臺灣加權指數 43,800",
            "trigger": "日內變動 -1.5%，達 -1.0% 警戒門檻。",
            "market_context": "同步觀察費半與 Nasdaq。",
        }]},
    }

    briefing = build_briefing_snapshot(snapshot, "midday")

    assert briefing["title"] == "台股午盤儀表板"
    assert {item["ticker"] for item in briefing["markets"]} == {"TAIEX", "2330", "NIKKEI", "KOSPI"}
    assert [item["title"] for item in briefing["observations"]] == [
        "台股總經", "台積電／半導體", "科技產業", "利率／匯率／黃金能源", "加密市場", "風險提醒",
    ]
    assert "台指" in briefing["observations"][0]["event"]
    assert "美國10年債殖利率" in briefing["observations"][3]["event"]


def test_briefing_markets_include_djia_alongside_nasdaq_and_sox():
    briefing = build_briefing_snapshot({
        "indices": [
            {"ticker": "NASDAQ", "name": "那斯達克綜合指數", "price": 100},
            {"ticker": "SOX", "name": "費城半導體指數", "price": 200},
            {"ticker": "DJIA", "name": "道瓊工業指數", "price": 300},
        ],
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": []},
    }, "us_open")
    assert {item["ticker"] for item in briefing["markets"]} == {"NASDAQ", "SOX", "DJIA"}
    us_topic = next(topic for topic in briefing["market_topics"] if topic["title"] == "美股相關")
    assert {item["ticker"] for item in us_topic["items"]} == {"NASDAQ", "SOX", "DJIA"}


def test_midday_briefing_explains_cross_market_move_and_technical_location():
    context = {"window_days": 20, "long_window_days": 60, "low": 100, "high": 120, "long_low": 90, "long_high": 130, "position_pct": 90, "zone": "接近20日壓力區", "as_of": "2026-08-03", "status": "ok"}
    snapshot = {
        "indices": [
            {"ticker": "TAIEX", "price": 118, "change_percent": 1.2, "technical_context": context},
            {"ticker": "TPEx", "price": 115, "change_percent": 0.8, "technical_context": context},
            {"ticker": "NASDAQ", "price": 100, "change_percent": 1.0, "technical_context": context},
            {"ticker": "SOX", "price": 200, "change_percent": 1.5, "technical_context": context},
        ],
        "quotes": [{"ticker": "2330", "price": 1100, "change_percent": 2.0, "technical_context": context}],
        "events": {"items": [{
            "brief_title": "半導體需求更新",
            "summary": "公開財報顯示資本支出展望上修。",
            "why_important": "可能改變 AI 供應鏈需求預期，但仍需後續公司指引確認。",
            "market_context": "費半、Nasdaq 與台積電同步上行，形成跨市場確認。",
            "stock_observation": "觀察下一交易時段是否維持同向，以及成交量是否放大。",
        }]},
    }

    briefing = build_briefing_snapshot(snapshot, "midday")
    semiconductor = briefing["observations"][1]
    assert "台積電 1,100.00" in semiconductor["event"]
    assert "同步上行" in semiconductor["market_impact"]
    assert "20日區間" in semiconductor["watch"]
    assert "60日" in semiconductor["watch"]
    assert "資料截至 2026-08-03" in semiconductor["watch"]
