from src.market_digest import build_market_digest


def test_digest_combines_distinct_events_and_quotes_into_one_shared_message():
    result = build_market_digest(
        {
            "generated_at": "2026-09-05T00:00:00+00:00",
            "events": {"items": [
                {
                    "source_key": "financialjuice",
                    "event": "Nscale宣稱Anthropic合約帶來逾千億美元簽約營收",
                    "vendor_importance": 9,
                    "published_at": "2026-09-04T20:00:00+00:00",
                    "observation_id": "fj-1",
                },
                {
                    "source_key": "official",
                    "event": "美國服務業價格指數公布，市場等待後續利率資料",
                    "why_important": "官方數據可核對通膨與利率背景",
                    "published_at": "2026-09-04T18:00:00+00:00",
                    "observation_id": "official-1",
                },
            ]},
            "indices": [
                {"ticker": "SOX", "price": 11657.87, "change_percent": 2.69, "freshness": "recent_close"},
                {"ticker": "NASDAQ", "price": 26586.58, "change_percent": 0.01, "freshness": "recent_close"},
            ],
        },
        "morning",
    )

    assert result["notification_eligible"] is True
    assert len(result["themes"]) == 3
    assert len(result["public_short_message"]) <= 60
    assert result["public_short_message"]
    assert "..." not in result["public_short_message"]
    assert "Nscale" in result["overview"] or "費半" in result["overview"]
    assert all(theme["evidence"] for theme in result["themes"])


def test_digest_prefers_complete_event_over_fragment_title():
    result = build_market_digest(
        {
            "events": {"items": [{
                "source_key": "financialjuice",
                "title": "據《The...",
                "event": "沃勒表示通膨與勞動市場仍是利率判斷的重要依據",
                "observation_id": "fj-waller",
            }]},
        },
        "us_premarket",
    )

    assert result["notification_eligible"] is True
    assert "沃勒" in result["overview"]
    assert "The..." not in result["public_short_message"]


def test_digest_drops_conditional_only_waller_fragment_for_complete_fact():
    result = build_market_digest(
        {"events": {"items": [{
            "source_key": "financialjuice",
            "event": "如果8月通膨數據過熱。",
            "summary": "沃勒表示通膨與勞動市場仍是利率判斷的重要依據。",
            "vendor_importance": 10,
            "observation_id": "fj-waller-fragment",
        }]}},
        "us_premarket",
    )

    assert "沃勒表示通膨與勞動市場" in result["primary_theme"]["what_happened"]
    assert "如果8月通膨數據過熱" not in result["public_short_message"]


def test_digest_reads_existing_reviewed_news_as_evidence():
    result = build_market_digest(
        {
            "news": {"markets": {"us": {"stories": [{
                "title": "美國服務業價格資料公布",
                "summary": "官方資料更新，市場等待後續利率資料。",
                "source_name": "官方市場新聞",
            }]}}},
        },
        "morning",
    )

    assert result["notification_eligible"] is True
    assert any("官方資料更新" in theme["what_happened"] for theme in result["themes"])


def test_digest_uses_only_public_gate_stories_from_new_intelligence_envelope():
    result = build_market_digest(
        {
            "generated_at": "2026-09-05T00:00:00+00:00",
            "news": {
                "us": [{"title": "不應進入摘要的 raw news", "event": "Fed rate decision"}],
                "intelligence": {
                    "taiwan": {"stories": []},
                    "us": {"stories": [{
                        "title": "Fed keeps rates unchanged as inflation cools",
                        "summary": "Fed holds rates while inflation cools.",
                        "public_news_eligible": True,
                        "canonical_url": "https://www.federalreserve.gov/a",
                        "published_at": "2026-09-04T20:00:00+00:00",
                    }]},
                },
            },
        },
        "morning",
    )
    assert any("Fed holds rates" in theme["what_happened"] for theme in result["themes"])
    assert all("不應進入摘要" not in theme["what_happened"] for theme in result["themes"])


def test_digest_suppresses_when_all_inputs_are_fragments_or_retired_creators():
    result = build_market_digest(
        {
            "events": {"items": [
                {"source_key": "financialjuice", "title": "據《The..."},
                {"source_key": "jenny", "event": "財經市場分析"},
            ]},
            "indices": [],
            "quotes": [],
        },
        "morning",
    )

    assert result["notification_eligible"] is False
    assert result["notification_reason"] == "insufficient_evidence"
    assert result["public_short_message"] == ""


def test_digest_does_not_hard_cut_an_overlong_single_fact():
    result = build_market_digest(
        {"events": {"items": [{"source_key": "official", "event": "完整事件" + "重要內容" * 40}]}},
        "morning",
    )

    assert result["notification_eligible"] is False
    assert result["public_short_message"] == ""
    assert len(result["overview"]) <= 140


def test_digest_keeps_structured_quote_evidence_separate_from_source_evidence():
    event = {
        "source_key": "financialjuice",
        "event": "官方公布半導體出口管制更新，市場等待後續細節",
        "observation_id": "fj-semi-1",
        "published_at": "2026-09-04T20:00:00+00:00",
        "market_evidence": [{
            "ticker": "SOX",
            "name": "費半",
            "price": 11735.26,
            "change_percent": 3.37,
            "currency": "點",
            "quote_date": "2026-09-04",
            "freshness": "recent_close",
            "source_url": "https://finance.yahoo.com/quote/%5ESOX",
        }],
    }
    result = build_market_digest(
        {"generated_at": "2026-09-05T00:00:00+00:00", "events": {"items": [event]}},
        "us_premarket",
    )

    primary = result["primary_theme"]
    assert primary["source_evidence"][0]["source_key"] == "financialjuice"
    assert primary["quote_evidence"] == [{
        "ticker": "SOX",
        "name": "費半",
        "price": 11735.26,
        "change_percent": 3.37,
        "currency": "點",
        "quote_date": "2026-09-04",
        "freshness": "recent_close",
        "source_url": "https://finance.yahoo.com/quote/%5ESOX",
    }]
    assert result["quote_evidence"] == primary["quote_evidence"]

    compact_event = {**event, "market_evidence": [{"ticker": "SOX"}]}
    hydrated = build_market_digest(
        {
            "generated_at": "2026-09-05T00:00:00+00:00",
            "events": {"items": [compact_event]},
            "indices": [{
                "ticker": "SOX",
                "price": 11735.26,
                "change_percent": 3.37,
                "freshness": "recent_close",
                "source_url": "https://finance.yahoo.com/quote/%5ESOX",
            }],
        },
        "us_premarket",
    )
    assert hydrated["primary_theme"]["quote_evidence"][0]["ticker"] == "SOX"
    assert hydrated["primary_theme"]["quote_evidence"][0]["price"] == 11735.26

    changed_quote = {**event, "market_evidence": [{**event["market_evidence"][0], "price": 12000.0, "change_percent": 5.0}]}
    changed = build_market_digest(
        {"generated_at": "2026-09-05T00:00:00+00:00", "events": {"items": [changed_quote]}},
        "us_premarket",
    )
    assert changed["briefing_id"] == result["briefing_id"]


def test_digest_does_not_attach_unrelated_snapshot_quotes_to_an_event():
    result = build_market_digest(
        {
            "generated_at": "2026-09-05T00:00:00+00:00",
            "events": {"items": [{
                "source_key": "financialjuice",
                "event": "巴林國防軍表示防空系統攔截多次空中攻擊",
                "vendor_importance": 10,
                "published_at": "2026-09-04T23:00:00+00:00",
                "observation_id": "fj-bahrain",
            }]},
            "indices": [
                {"ticker": "NASDAQ", "price": 26586.58, "change_percent": 0.01, "freshness": "recent_close"},
                {"ticker": "SOX", "price": 11657.87, "change_percent": 2.69, "freshness": "recent_close"},
            ],
        },
        "us_premarket",
    )

    assert result["primary_theme"]["quote_evidence"] == []
    assert not any(signal.get("source") == "市場報價" for signal in result["secondary_signals"])


def test_digest_only_hydrates_quotes_for_structured_event_tickers():
    result = build_market_digest(
        {
            "generated_at": "2026-09-05T00:00:00+00:00",
            "events": {"items": [{
                "source_key": "official",
                "event": "半導體出口資料完成官方更新並等待後續核對",
                "market_evidence": [{"ticker": "費半"}],
                "published_at": "2026-09-04T23:00:00+00:00",
            }]},
            "indices": [{
                "ticker": "SOX",
                "price": 11657.87,
                "change_percent": 2.69,
                "freshness": "recent_close",
            }],
        },
        "us_premarket",
    )

    assert result["primary_theme"]["quote_evidence"][0]["ticker"] == "SOX"
    assert result["primary_theme"]["quote_evidence"][0]["price"] == 11657.87


def test_digest_deduplicates_cross_source_event_and_caps_secondary_signals():
    items = [{
        "source_key": "financialjuice",
        "event": "官方確認能源設施遭到攻擊，後續供應狀況待核對",
        "published_at": "2026-09-04T23:00:00+00:00",
        "notification_status": "eligible",
        "observation_id": "fj-energy",
    }, {
        "source_key": "official",
        "event": "官方確認能源設施遭到攻擊，後續供應狀況待核對",
        "published_at": "2026-09-04T22:00:00+00:00",
        "observation_id": "official-energy",
    }]
    items.extend({
        "source_key": "official",
        "event": f"第{index}項官方市場資料完成更新並等待後續核對",
        "published_at": f"2026-09-04T{index + 10:02d}:00:00+00:00",
        "observation_id": f"official-{index}",
    } for index in range(1, 6))
    result = build_market_digest(
        {"generated_at": "2026-09-05T00:00:00+00:00", "events": {"items": items}},
        "morning",
    )

    assert len(result["secondary_signals"]) == 3
    keys = result["displayed_event_keys"]
    assert len(keys) == len(set(keys))
    assert not any(signal["canonical_event_key"] == result["primary_theme"]["canonical_event_key"]
                   for signal in result["secondary_signals"])
