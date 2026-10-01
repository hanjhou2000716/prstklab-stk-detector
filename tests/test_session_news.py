from __future__ import annotations

from datetime import datetime, UTC

from src.session_news import build_session_news_summary


def _story(title: str, url: str, published_at: str, *, summary: str = "市場開盤焦點。", market: str = "us") -> dict:
    return {
        "title": title,
        "summary": summary,
        "canonical_url": url,
        "published_at": published_at,
        "market": market,
        "public_news_eligible": True,
        "event_cluster_key": url,
        "provider": "Reuters",
    }


def test_session_summary_selects_qualified_candidate_outside_top_five_and_binds_session():
    stories = [
        _story(f"Fed market rates update {index}", f"https://news.example/{index}",
               f"2024-01-04T21:{index:02d}:00+00:00", summary="聯準會公布利率決策，市場關注通膨。")
        for index in range(1, 8)
    ]
    payload = {
        "news": {"intelligence": {"us": {"stories": stories[:5], "editorial_candidates": stories}}},
    }
    result = build_session_news_summary(
        payload,
        "morning",
        datetime(2024, 1, 5, 2, 0, tzinfo=UTC),
        [{"ticker": "S&P 500", "price": 4800, "change_percent": 0.5, "freshness": "recent_close", "quote_date": "2024-01-04"}],
        market_scope_key=None,
    )
    assert result["status"] == "selected"
    assert result["story_id"] in {story["canonical_url"] for story in stories}
    assert result["target_session_date"] == "2024-01-04"
    assert len(result["summary_sentences"]) == 2
    assert len(result["summary"]) <= 140
    assert "不推論新聞因果" in result["summary_sentences"][1]


def test_session_summary_rejects_future_undated_cross_market_and_ineligible_news():
    payload = {"news": {"intelligence": {"taiwan": {"editorial_candidates": [
        _story("台股開盤新聞", "https://news.example/future", "2024-01-03T01:00:00+00:00", market="taiwan"),
        _story("台股盤前新聞", "https://news.example/no-date", "", market="taiwan"),
        _story("美股開盤新聞", "https://news.example/us", "2024-01-03T00:00:00+00:00", market="us"),
        {**_story("促銷推薦", "https://news.example/ineligible", "2024-01-03T00:00:00+00:00", market="taiwan"), "public_news_eligible": False},
    ]}}}}
    result = build_session_news_summary(
        payload, "pre_open", datetime(2024, 1, 3, 0, 45, tzinfo=timezone.utc), [],
        market_scope_key="taiwan",
    )
    assert result["status"] == "unavailable"
    assert result["source_url"] == ""
    assert "資料不足" in result["summary"]


def test_historical_session_story_is_explicit_and_quote_fallback_does_not_claim_news():
    historical = _story(
        "Market close wrap",
        "https://news.example/close",
        "2024-01-03T22:00:00+00:00",
        summary="市場收盤重點。",
        market="us",
    )
    result = build_session_news_summary(
        {"news": {"intelligence": {"us": {"editorial_candidates": [historical]}}}},
        "morning",
        datetime(2024, 1, 5, 2, 0, tzinfo=timezone.utc),
        [{"ticker": "S&P 500", "price": 4800, "change_percent": -0.25, "freshness": "recent_close", "quote_date": "2024-01-03"}],
    )
    assert result["status"] == "recent_session_reference"
    assert "最近交易日參考" in result["reference_label"]
    assert "非本日" in result["reference_label"]

    fallback = build_session_news_summary(
        {"news": {"intelligence": {"us": {"editorial_candidates": []}}}},
        "morning",
        datetime(2024, 1, 5, 2, 0, tzinfo=timezone.utc),
        [{"ticker": "S&P 500", "price": 4800, "change_percent": 0, "freshness": "recent_close", "quote_date": "2024-01-04"}],
    )
    assert fallback["status"] == "market_data_fallback"
    assert "新聞未取得" in fallback["headline"]
    assert len(fallback["summary_sentences"]) == 2
