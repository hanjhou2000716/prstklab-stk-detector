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
