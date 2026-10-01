from datetime import datetime

from src.briefing_cards import _contagion_inputs, _regime_factors, build_briefing_snapshot
from src.schedule_contract import live_market_phase_at
from src.scheduled_delivery import _briefing_delivery_event, _briefing_evidence_ready


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


def test_sep_28_us_premarket_snapshot_keeps_partial_cash_quotes_and_valid_routine_summary():
    rows = [
        {"ticker": "S&P 500", "price": 7743.41, "change_percent": 0.51, "quote_date": "2026-09-25", "freshness": "recent_close"},
        {"ticker": "NASDAQ", "price": 27068.72, "change_percent": 0.48, "quote_date": "2026-09-25", "freshness": "recent_close"},
        {"ticker": "DJIA", "price": 51828.62, "change_percent": 0.93, "quote_date": "2026-09-25", "freshness": "recent_close"},
        {"ticker": "SOX", "price": 12668.93, "change_percent": 1.41, "quote_date": "2026-09-25", "freshness": "recent_close"},
        {"ticker": "ES", "price": 7777.0, "quote_date": "2026-09-28", "freshness": "recent_close"},
        {"ticker": "NQ", "price": 30725.0, "quote_date": "2026-09-28", "freshness": "recent_close"},
        {"ticker": "YM", "price": 51902.0, "quote_date": "2026-09-28", "freshness": "recent_close"},
    ]
    briefing = build_briefing_snapshot({
        "generated_at": "2026-09-28T13:04:17+00:00",
        "indices": rows,
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": []},
    }, "us_premarket")

    assert briefing["market_scope_key"] == "us"
    assert briefing["data_gap_status"] == "partial"
    assert briefing["digest_status"] == "ready"
    assert briefing["public_short_message"].startswith("📊 美股盤前｜")
    assert briefing["public_short_message"] != "🟡 美股盤前"
    assert "最近收盤標普500+0.51%" in briefing["public_short_message"]
    assert "盤前期貨未取得" not in briefing["public_short_message"]
    assert _briefing_evidence_ready(briefing) is True
    event = _briefing_delivery_event({"briefing": briefing}, "us_premarket")
    assert event is not None
    assert event["source_key"] == "scheduled_brief"
    assert event["public_short_message"] == briefing["public_short_message"]


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
        "generated_at": "2026-09-14T14:00:00+08:00",
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
        "generated_at": "2026-09-14T14:00:00+08:00",
        "indices": [
            {"ticker": "TAIEX", "price": 45862.52, "change_percent": -0.70, "quote_date": "2026-09-14", "quote_time": "2026-09-14T13:30:00+08:00", "freshness": "recent_close"},
            {"ticker": "TXF", "price": 45890, "change": -310, "change_percent": -0.67, "quote_date": "2026-09-14", "quote_time": "2026-09-14T13:45:00+08:00", "freshness": "recent_close", "contract_month": "202610", "contract_basis": "named_month_contract", "quote_basis": "TAIFEX_TXF_DAY|contract=202610|session=regular", "instrument_id": "market:txf:taifex:202610:regular", "session": "regular", "source_url": "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"},
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
    assert sections[0]["facts"] == [
        "加權現貨 45,862.52 點｜漲跌點數未提供（-0.70%）",
        "台指期近月日盤 45,890.00 點｜-310.00 點（-0.67%）",
    ]
    assert all("2026-09-14" not in fact and "202610" not in fact for fact in sections[0]["facts"])
    assert sections[0]["status_notes"] == [
        "現貨｜最近收盤｜資料日 2026-09-14",
        "期貨｜最近已核實日盤｜資料日 2026-09-14｜非即時",
    ]
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
        "標普500 7,743.41 點｜+39.28 點（+0.51%）",
        "那斯達克綜合 27,068.72 點｜+129.35 點（+0.48%）",
        "道瓊 51,828.62 點｜+478.64 點（+0.93%）",
    ]
    assert cash["header_note"] == f"最近收盤｜資料日 {quote_date}"
    assert [fact["text"] for fact in futures["facts_structured"]] == [
        "ES（S&P 500 指數期貨）：盤前行情未取得",
        "NQ（Nasdaq-100 指數期貨）：盤前行情未取得",
        "YM（道瓊指數期貨）：盤前行情未取得",
    ]
    assert len(futures["reference_facts"]) == 3
    assert [row["text"] for row in futures["reference_facts"]] == [
        "ES（S&P 500 指數期貨） 7,805.75 點｜+38.75 點（+0.50%）",
        "NQ（Nasdaq-100 指數期貨） 30,921.75 點｜+155.00 點（+0.50%）",
        "YM（道瓊指數期貨） 52,180.00 點｜+463.00 點（+0.90%）",
    ]
    assert futures["reference_header_note"] == "最近收盤參考｜非盤前即時｜資料日 2026-09-25"
    assert futures["sox_header_note"] == "半導體參考｜最近收盤｜資料日 2026-09-25"
    assert futures["supplementary_facts"][0]["text"] == "費半 12,668.93 點｜+176.39 點（+1.41%）"
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
    assert futures["facts_structured"][0]["text"] == "ES（S&P 500 指數期貨） 7,805.75 點｜+38.75 點（+0.50%）"
    assert futures["facts_structured"][0]["display_change_percent"] == 0.5
    assert futures["reference_facts"] == []
    assert briefing["market_card_projection"]["instruments"][3]["display_state"] == "verified_premarket"


def test_compact_market_quote_normalizes_negative_zero_and_keeps_missing_components_explicit():
    briefing = build_briefing_snapshot({
        "as_of": "2026-09-25T08:21:00-04:00",
        "indices": [
            {"ticker": "S&P 500", "price": 100, "change": -0.001, "change_percent": -0.0009, "quote_date": "2026-09-24", "freshness": "recent_close"},
            {"ticker": "NASDAQ", "price": 200, "change_percent": 0.5, "quote_date": "2026-09-24", "freshness": "recent_close"},
            {"ticker": "DJIA", "price": 300, "change": -1, "quote_date": "2026-09-24", "freshness": "recent_close"},
        ],
        "quotes": [], "events": {"items": []},
    }, "us_premarket")

    facts = briefing["morning_analysis"]["sections"][0]["facts"]
    assert facts == [
        "標普500 100.00 點｜0.00 點（0.00%）",
        "那斯達克綜合 200.00 點｜漲跌點數未提供（+0.50%）",
        "道瓊 300.00 點｜-1.00 點（漲跌幅未提供）",
    ]
    assert briefing["morning_analysis"]["sections"][0]["header_note"] == "最近收盤｜資料日 2026-09-24"


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

def test_taiwan_pair_uses_one_verified_display_state_for_rows_and_takeaway():
    from src.briefing_cards import build_briefing_snapshot

    briefing = build_briefing_snapshot({
        "generated_at": "2026-09-28T07:00:00+08:00",
        "indices": [
            {"ticker": "TAIEX", "price": 48024.60, "change": -132.69, "change_percent": -0.28, "quote_date": "2026-09-24", "freshness": "recent_close"},
            {"ticker": "TXF", "price": 48123.00, "change": -189.00, "change_percent": -0.39, "quote_date": "2026-09-24", "quote_time": "2026-09-24T13:45:00+08:00", "freshness": "recent_close", "contract_month": "202610", "contract_basis": "named_month_contract", "quote_basis": "TAIFEX_TXF_DAY|contract=202610|session=regular", "instrument_id": "market:txf:taifex:202610:regular", "session": "regular", "source_url": "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"},
        ],
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": []},
    }, "post_close")

    pair = briefing["morning_analysis"]["sections"][0]
    assert [fact["display_state"] for fact in pair["facts_structured"]] == ["recent_close", "recent_close"]
    assert [fact["display_change_percent"] for fact in pair["facts_structured"]] == [-0.28, -0.39]
    assert "同跌" in pair["takeaway"]


def test_taiwan_pair_suppresses_unverified_direction_and_status_date():
    from src.briefing_cards import build_briefing_snapshot

    briefing = build_briefing_snapshot({
        "generated_at": "2026-09-28T07:00:00+08:00",
        "indices": [
            {"ticker": "TAIEX", "price": 48024.60, "change": -132.69, "change_percent": -0.28, "quote_date": "2026-09-24", "freshness": "recent_close"},
            {"ticker": "TXF", "price": 48123.00, "change": -189.00, "change_percent": -0.39, "quote_date": "2026-09-24", "freshness": "unknown", "contract_month": "202610"},
        ],
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": []},
    }, "post_close")

    pair = briefing["morning_analysis"]["sections"][0]
    txf = pair["facts_structured"][1]
    assert txf["display_state"] == "unavailable"
    assert txf["display_change_percent"] is None
    assert "未核實" in pair["status_notes"][1]
    assert "最近已核實日盤" not in pair["status_notes"][1]
    assert "暫不合併判讀" in pair["takeaway"]
    assert txf["quote"]["change_percent"] == -0.39


def test_taiwan_pair_keeps_partial_verified_quote_but_does_not_infer_direction():
    from src.briefing_cards import build_briefing_snapshot

    briefing = build_briefing_snapshot({
        "generated_at": "2026-09-28T07:00:00+08:00",
        "indices": [
            {"ticker": "TAIEX", "price": 48024.60, "change": -132.69, "quote_date": "2026-09-24", "freshness": "recent_close"},
            {"ticker": "TXF", "price": 48123.00, "change": -189.00, "change_percent": -0.39, "quote_date": "2026-09-24", "quote_time": "2026-09-24T13:45:00+08:00", "freshness": "recent_close", "contract_month": "202610", "contract_basis": "named_month_contract", "quote_basis": "TAIFEX_TXF_DAY|contract=202610|session=regular", "instrument_id": "market:txf:taifex:202610:regular", "session": "regular", "source_url": "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"},
        ],
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": []},
    }, "post_close")

    pair = briefing["morning_analysis"]["sections"][0]
    taiex = pair["facts_structured"][0]
    assert taiex["display_state"] == "recent_close"
    assert taiex["display_change_percent"] is None
    assert "48,024.60 點" in taiex["text"]
    assert "漲跌幅未提供" in taiex["text"]
    assert "不比較方向" in pair["takeaway"]


def test_taiwan_pair_rejects_impossible_calendar_date():
    from src.briefing_cards import build_briefing_snapshot

    briefing = build_briefing_snapshot({
        "generated_at": "2026-09-28T07:00:00+08:00",
        "indices": [
            {"ticker": "TAIEX", "price": 48024.60, "change_percent": -0.28, "quote_date": "2026-02-30", "freshness": "recent_close"},
            {"ticker": "TXF", "price": 48123.00, "change_percent": -0.39, "quote_date": "2026-02-28", "freshness": "recent_close", "contract_month": "202610"},
        ],
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": []},
    }, "post_close")

    pair = briefing["morning_analysis"]["sections"][0]
    taiex = pair["facts_structured"][0]
    assert taiex["display_state"] == "unavailable"
    assert taiex["display_change_percent"] is None
    assert "行情未核實" in pair["status_notes"][0]
    assert "2026-02-30" not in pair["status_notes"][0]
    assert "暫不合併判讀" in pair["takeaway"]

def test_us_cash_header_and_observation_ignore_an_invalid_quote_date():
    briefing = build_briefing_snapshot({
        "generated_at": "2026-09-28T07:00:00+08:00",
        "indices": [
            {"ticker": "S&P 500", "price": 7800.0, "change_percent": 0.51, "quote_date": "2026-09-25", "freshness": "recent_close"},
            {"ticker": "NASDAQ", "price": 27000.0, "change_percent": 0.48, "quote_date": "2026-02-30", "freshness": "recent_close"},
            {"ticker": "DJIA", "price": 52000.0, "change_percent": 0.93, "quote_date": "2026-09-25", "freshness": "recent_close"},
        ],
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": []},
    }, "us_premarket")

    cash = briefing["morning_analysis"]["sections"][0]
    invalid = cash["facts_structured"][1]
    assert invalid["display_state"] == "unavailable"
    assert invalid["display_change_percent"] is None
    assert "2026-02-30" not in cash["header_note"]
    assert cash["takeaway"] == "指數表現分別呈現，避免用單一指數代表整體美股。"



def test_sep_30_briefing_projects_historical_txf_and_only_taiwan_sentiment():
    from unittest.mock import patch

    snapshot = {
        "generated_at": "2026-09-30T14:28:00+08:00",
        "indices": [
            {
                "ticker": "TAIEX", "price": 48024.60, "change": 310.18, "change_percent": 0.65,
                "quote_date": "2026-09-30", "quote_time": "2026-09-30T13:30:00+08:00",
                "freshness": "recent_close",
            },
            {
                "ticker": "TXF", "price": 47767.0, "change": -356.0, "change_percent": -0.74,
                "quote_date": "2026-09-29", "quote_time": "2026-09-29T13:45:00+08:00",
                "freshness": "stale", "data_status": "stale", "stale_used": True, "backup_used": True,
                "quote_delayed": True, "contract_month": "202610", "contract_basis": "named_month_contract",
                "quote_basis": "TAIFEX_TXF_DAY|contract=202610|session=regular",
                "instrument_id": "market:txf:taifex:202610:regular", "session": "regular",
                "source_url": "https://openapi.taifex.com.tw/v1/DailyMarketReportFut",
            },
        ],
        "risk": {
            "taiwan": {
                "sentiment_signal_eligible": True,
                "sentiment": {
                    "score": 31.8, "label": "恐慌", "calculation_state": "fresh",
                    "data_quality": "primary", "date": "2026-09-30",
                    "calculated_at": "2026-09-30T14:28:00+08:00",
                    "source_label": "TAIEX Macro FGI",
                    "source_url": "https://example.tw/fgi",
                },
            },
        },
        "events": {"items": []},
    }
    with (
        patch("src.taifex_daily.get_taifex_index_futures_status", return_value={"calendar_status": "confirmed_open"}),
        patch("src.taifex_daily._calendar_open", return_value=True),
        patch("src.taifex_daily._session_gap", return_value=1),
        patch("src.taifex_daily._contract_is_unexpired", return_value=True),
    ):
        briefing = build_briefing_snapshot(snapshot, "post_close")

    pair = briefing["morning_analysis"]["sections"][0]
    txf = pair["facts_structured"][1]
    projection = briefing["market_card_projection"]
    assert txf["display_state"] == "historical_reference"
    assert txf["display_change_percent"] == -0.74
    assert "2026-09-29" in txf["status_note"]
    assert "非即時" in txf["status_note"]
    assert "47,767.00 點" in txf["text"]
    assert "資料日不同" in pair["takeaway"]
    assert "同跌" not in pair["takeaway"]
    assert [item["text"] for item in projection["sentiments"]] == ["台股情緒31.8／恐慌"]
    assert briefing["market_sentiments"] == projection["sentiments"]


def test_taifex_source_attempts_survive_into_read_only_card_diagnostics():
    briefing = build_briefing_snapshot({
        "generated_at": "2026-09-30T14:28:00+08:00",
        "indices": [],
        "quotes": [],
        "macro_quotes": [],
        "events": {"items": []},
        "errors": [{
            "ticker": "TXF",
            "message": "not shown in the notification",
            "source_attempts": [
                {"source": "taifex_openapi", "outcome": "not_published"},
                {"source": "taifex_daily_table", "outcome": "connection_failed"},
                {"source": "taifex_saved_backup", "outcome": "backup_expired"},
            ],
        }],
    }, "post_close")
    gaps = briefing["morning_analysis"]["system_analysis"]["data_gaps"]
    txf_gap = next(item for item in gaps if item.get("ticker") == "TXF")
    assert [item["outcome"] for item in txf_gap["source_attempts"]] == [
        "not_published", "connection_failed", "backup_expired",
    ]


def test_official_twse_cash_close_is_routine_display_not_live_alert_evidence():
    briefing = build_briefing_snapshot({
        "generated_at": "2026-10-01T08:50:10+08:00",
        "indices": [{
            "ticker": "TAIEX", "price": 47940.13, "previous_close": 47631.96,
            "change": 308.17, "change_percent": 0.65,
            "quote_date": "2026-09-30", "quote_time": "2026-09-30T13:30:00+08:00",
            "freshness": "recent_close", "data_status": "最近收盤",
            "source_tier": "official", "source_label": "TWSE",
            "source_url": "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK",
            "quote_basis": "TWSE_TAIEX_DAILY_CLOSE", "quote_delayed": True,
            "stale_used": False, "alert_eligible": False,
        }],
        "quotes": [], "macro_quotes": [], "events": {"items": []},
    }, "pre_open")
    fact = briefing["market_card_projection"]["cards"][0]["facts_structured"][0]
    assert fact["display_state"] == "recent_close"
    assert fact["display_change_percent"] == 0.65
    assert "47,940.13 點" in fact["text"]
    assert "2026-09-30" in fact["status_note"]
