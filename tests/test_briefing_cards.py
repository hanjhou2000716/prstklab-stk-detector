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
    assert [item["label"] for item in facts[:2]] == ["台美市場狀態", "行情比較"]
    assert all(isinstance(item["evidence_refs"], list) for item in facts)
    assert not {item["key"] for item in facts} & {"confidence", "us_risk_sentiment"}
    assert not any(item["key"] == "primary_event" for item in facts)


def test_briefing_summary_keeps_two_fixed_rows_when_market_evidence_is_missing():
    briefing = build_briefing_snapshot({"events": {"items": []}}, "morning")

    assert [item["label"] for item in briefing["summary_facts"]] == ["台美市場狀態", "行情比較"]
    assert briefing["summary_facts"][0]["value"] == "資料不足，台美狀態待確認"
    assert "未取得可核對行情比較" in briefing["summary_facts"][1]["value"]


def test_missing_quote_rows_are_publicly_omitted_but_kept_as_detailed_gaps():
    briefing = build_briefing_snapshot({
        "indices": [
            {"ticker": "TAIEX", "price": 45862.52, "change_percent": -0.70, "quote_date": "2026-09-14"},
            {"ticker": "NASDAQ", "price": 26333.03, "change_percent": 0.96, "quote_date": "2026-09-14"},
            {"ticker": "SOX", "price": 11824.00, "change_percent": 1.81, "quote_date": "2026-09-14"},
        ],
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": []},
    }, "post_close")

    sections = briefing["morning_analysis"]["sections"]
    titles = [item["title"] for item in sections]
    assert titles == ["台股現貨與台指期", "台股輔助統計（官方）"]
    pair = sections[0]
    assert pair["layout"] == "taiwan_pair_v2"
    assert "加權現貨：未取得可核對資料" in pair["facts"][0]
    assert "台指期近月日盤：未取得可核對資料" in pair["facts"][1]
    assert all("美股" not in fact and "Nasdaq" not in fact for section in sections for fact in section["facts"])
    assert all("未公布或本輪未取得" in fact for fact in sections[1]["facts"])
    gaps = briefing["morning_analysis"]["system_analysis"]["data_gaps"]
    gap_by_ticker = {gap["ticker"]: gap for gap in gaps if gap.get("kind") == "quote"}
    assert gap_by_ticker["TAIEX"]["reason"] == "quote_unusable_or_time_unverified"
    assert gap_by_ticker["TXF"]["reason"] == "quote_missing"
    assert {gap["name"] for gap in gaps if gap.get("kind") == "supplementary_statistic"} == {
        "上市市場成交金額", "市場廣度", "三大法人合計買賣超",
    }


def test_all_missing_quote_facts_do_not_leave_public_placeholder_or_observation():
    briefing = build_briefing_snapshot({"events": {"items": []}}, "post_close")

    sections = briefing["morning_analysis"]["sections"]
    assert "加權現貨：未取得可核對資料" in sections[0]["facts"][0]
    assert "台指期近月日盤：未取得可核對資料" in sections[0]["facts"][1]
    assert len(sections[1]["facts"]) == 3
    assert all("未公布或本輪未取得" in fact for fact in sections[1]["facts"])
    assert {gap["ticker"] for gap in briefing["morning_analysis"]["system_analysis"]["data_gaps"] if gap.get("kind") == "quote"} >= {
        "TAIEX", "TXF"
    }


def test_public_observations_add_structure_without_repeating_quote_lines():
    briefing = build_briefing_snapshot({
        "indices": [
            {"ticker": "TAIEX", "price": 45862.52, "change_percent": -0.70, "quote_date": "2026-09-14", "quote_time": "2026-09-14T13:30:00+08:00", "freshness": "recent_close"},
            {"ticker": "TXF", "price": 45890, "change": -310, "change_percent": -0.67, "quote_date": "2026-09-14", "quote_time": "2026-09-14T13:45:00+08:00", "freshness": "recent_close", "contract_month": "202610", "quote_basis": "TAIFEX_TXF_DAY|contract=202610|session=regular", "source_url": "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"},
            {"ticker": "TPEx", "price": 394.41, "change_percent": -0.28, "quote_date": "2026-09-14"},
            {"ticker": "NASDAQ", "price": 26333.04, "change_percent": 0.96, "quote_date": "2026-09-14"},
            {"ticker": "SOX", "price": 11824.00, "change_percent": 1.81, "quote_date": "2026-09-14"},
        ],
        "quotes": [{"ticker": "2330", "price": 2380.0, "change_percent": -1.24, "quote_date": "2026-09-14"}],
        "taiwan_market_statistics": {
            "turnover": {"trade_value": 321_050_000_000, "unit": "元", "observed_date": "2026-09-14", "source_url": "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"},
            "breadth": {"scope_verified": True, "advancing": 410, "declining": 720, "unchanged": 85, "observed_date": "2026-09-14", "source_url": "https://openapi.twse.com.tw/v1/opendata/twtazu_od"},
            "institutional_flows": {"total_net": -4_520_000_000, "unit": "元", "observed_date": "2026-09-14", "source_url": "https://www.twse.com.tw/rwd/zh/fund/BFI82U"},
        },
        "events": {"items": []},
    }, "post_close")

    sections = briefing["morning_analysis"]["sections"]
    assert [item["title"] for item in sections] == ["台股現貨與台指期", "台股輔助統計（官方）"]
    assert sections[0]["layout"] == "taiwan_pair_v2"
    assert "同日收盤方向" in sections[0]["takeaway"]
    projection = briefing["market_card_projection"]
    assert projection["version"] == "taiwan-market-cards-v2"
    assert projection["market_scope"] == "taiwan"
    assert projection["market_date"] == "2026-09-14"
    assert [item["ticker"] for item in projection["instruments"]] == ["TAIEX", "TXF"]
    statistics = next(item for item in sections if item["title"] == "台股輔助統計（官方）")
    assert "上漲 410／下跌 720" in statistics["market_observation"]
    assert "3,210.50 億元" in statistics["market_observation"]
    assert "賣超 45.20 億元" in statistics["market_observation"]
    assert all(item["quote"].get("source_url") for item in statistics["facts_structured"])


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


def test_us_premarket_cards_combine_cash_futures_and_sox_without_relabeling_closes():
    quote_date = "2026-09-25"
    rows = [
        {"ticker": "S&P 500", "price": 7743.41, "change": 39.28, "change_percent": 0.51, "quote_date": quote_date, "quote_time": f"{quote_date}T16:00:00-04:00", "freshness": "recent_close", "source_label": "Yahoo", "source_url": "https://finance.example/spx"},
        {"ticker": "NASDAQ", "price": 27068.72, "change": 129.35, "change_percent": 0.48, "quote_date": quote_date, "quote_time": f"{quote_date}T16:00:00-04:00", "freshness": "recent_close", "source_label": "Yahoo"},
        {"ticker": "DJIA", "price": 51828.62, "change": 478.64, "change_percent": 0.93, "quote_date": quote_date, "quote_time": f"{quote_date}T16:00:00-04:00", "freshness": "recent_close", "source_label": "Yahoo"},
        {"ticker": "ES", "price": 7805.75, "change": 38.75, "change_percent": 0.50, "quote_date": quote_date, "freshness": "recent_close", "contract_basis": "continuous_contract", "source_label": "Yahoo"},
        {"ticker": "NQ", "price": 30921.75, "change": 155.00, "change_percent": 0.50, "quote_date": quote_date, "freshness": "recent_close", "contract_basis": "continuous_contract", "source_label": "Yahoo"},
        {"ticker": "YM", "price": 52180.00, "change": 463.00, "change_percent": 0.90, "quote_date": quote_date, "freshness": "recent_close", "contract_basis": "continuous_contract", "source_label": "Yahoo"},
        {"ticker": "SOX", "price": 12668.93, "change": 176.39, "change_percent": 1.41, "quote_date": quote_date, "freshness": "recent_close", "source_label": "Yahoo"},
        {"ticker": "TAIEX", "price": 48024.6, "change_percent": -0.28, "quote_date": quote_date, "freshness": "recent_close"},
    ]
    briefing = build_briefing_snapshot({
        "as_of": "2026-09-25T08:20:00-04:00",
        "release_id": "release-us-1",
        "snapshot_id": "snapshot-us-1",
        "indices": rows,
        "quotes": [],
        "events": {"items": []},
    }, "us_premarket")

    sections = briefing["morning_analysis"]["sections"]
    assert [section["layout"] for section in sections] == ["us_cash_v2", "us_futures_sox_v2"]
    cash, futures = sections
    assert [fact["text"] for fact in cash["facts_structured"]] == [
        "標普500 +0.51%", "那斯達克綜合 +0.48%", "道瓊 +0.93%",
    ]
    assert cash["header_note"] == f"資料日 {quote_date}"
    assert [fact["text"] for fact in futures["facts_structured"]] == [
        "ES（S&P 500 指數期貨）：盤前行情未取得",
        "NQ（Nasdaq-100 指數期貨）：盤前行情未取得",
        "YM（道瓊指數期貨）：盤前行情未取得",
    ]
    assert len(futures["reference_facts"]) == 3
    assert all("最近收盤" in row["text"] and "資料日 2026-09-25" in row["text"] for row in futures["reference_facts"])
    assert "費半最近收盤" in futures["supplementary_facts"][0]["text"]
    projection = briefing["market_card_projection"]
    assert projection["version"] == "us-market-cards-v2"
    assert projection["market_scope"] == "us"
    assert projection["slot"] == "us_premarket"
    assert projection["market_date"] == quote_date
    assert projection["release_id"] == "release-us-1"
    assert projection["snapshot_id"] == "snapshot-us-1"
    assert projection["cards"] == sections
    assert all(item["source_note"] for item in briefing["observations"])
    assert [topic["title"] for topic in briefing["market_topics"]] == [
        "美股三大指數｜最近收盤", "美股盤前期貨與半導體參考",
    ]
    assert not any("TAIEX" in str(topic) for topic in briefing["market_topics"])


def test_us_futures_only_show_as_premarket_with_verified_session_timestamp_and_contract():
    row = {
        "ticker": "ES", "price": 7805.75, "change": 38.75, "change_percent": 0.50,
        "quote_date": "2026-09-25", "quote_time": "2026-09-25T08:20:00-04:00",
        "freshness": "live", "session": "premarket", "contract_basis": "continuous_contract",
        "quote_source": "Yahoo", "source_url": "https://finance.example/es",
    }
    briefing = build_briefing_snapshot({
        "as_of": "2026-09-25T08:21:00-04:00",
        "indices": [row], "quotes": [], "events": {"items": []},
    }, "us_premarket")
    futures = briefing["morning_analysis"]["sections"][1]
    assert futures["facts_structured"][0]["text"] == "ES（S&P 500 指數期貨）：7,805.75（+38.75 點，+0.50%）"
    assert futures["facts_structured"][0]["display_change_percent"] == 0.5
    assert futures["reference_facts"] == []
    assert briefing["market_card_projection"]["instruments"][3]["display_state"] == "verified_premarket"


def test_us_delayed_or_out_of_session_futures_never_appear_as_premarket_quotes():
    rows = [
        {"ticker": "ES", "price": 7805.75, "change_percent": 0.5, "quote_time": "2026-09-25T08:20:00-04:00", "freshness": "live", "contract_basis": "continuous_contract", "source_label": "Yahoo"},
        {"ticker": "NQ", "price": 30921.75, "change_percent": 0.5, "quote_time": "2026-09-25T08:20:00-04:00", "freshness": "live", "session": "premarket", "quote_delayed": True, "contract_basis": "continuous_contract", "source_label": "Yahoo"},
        {"ticker": "YM", "price": 52180.00, "change_percent": 0.9, "quote_time": "2026-09-25T09:30:00-04:00", "freshness": "live", "session": "premarket", "contract_basis": "continuous_contract", "source_label": "Yahoo"},
    ]
    briefing = build_briefing_snapshot({
        "as_of": "2026-09-25T08:21:00-04:00",
        "indices": rows, "quotes": [], "events": {"items": []},
    }, "us_premarket")

    futures = briefing["morning_analysis"]["sections"][1]
    assert all(fact["text"].endswith("盤前行情未取得") for fact in futures["facts_structured"])
    assert futures["reference_facts"] == []
    assert all(item["display_state"] == "premarket_unavailable" for item in briefing["market_card_projection"]["instruments"][3:6])


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
