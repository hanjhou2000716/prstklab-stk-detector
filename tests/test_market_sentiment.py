from __future__ import annotations

from datetime import datetime

from src.market_sentiment import project_market_sentiments


def _risk():
    return {
        "taiwan": {
            "sentiment_signal_eligible": True,
            "sentiment": {
                "score": 31.8,
                "label": "恐慌",
                "calculation_state": "fresh",
                "data_quality": "primary",
                "date": "2026-09-30",
                "calculated_at": "2026-09-30T14:28:00+08:00",
                "source_label": "TAIEX Macro FGI",
                "source_url": "https://example.tw/fgi",
            },
        },
        "us": {
            "sentiment_signal_eligible": True,
            "sentiment": {
                "score": 31.5,
                "label": "Fear",
                "updated_at": "2026-09-30T00:00:00+00:00",
                "source_label": "CNN Fear & Greed",
                "source_url": "https://example.com/fear-greed",
            },
        },
    }


def test_market_scopes_only_project_their_own_fresh_sentiment():
    as_of = datetime.fromisoformat("2026-09-30T06:28:00+00:00")
    risk = _risk()
    taiwan = project_market_sentiments(risk, market_scope="taiwan", as_of=as_of)
    us = project_market_sentiments(risk, market_scope="us", as_of=as_of)
    assert [(item["market"], item["score"], item["text"]) for item in taiwan] == [
        ("taiwan", 31.8, "台股情緒31.8／恐慌")
    ]
    assert [(item["market"], item["score"]) for item in us] == [("us", 31.5)]
    assert project_market_sentiments(risk, market_scope=None, as_of=as_of) == [*taiwan, *us]


def test_stale_unverified_or_missing_sentiment_is_omitted_without_cross_market_fill():
    as_of = datetime.fromisoformat("2026-09-30T06:28:00+00:00")
    risk = _risk()
    risk["taiwan"]["sentiment"]["calculated_at"] = "2026-09-28T14:28:00+08:00"
    risk["us"]["sentiment_signal_eligible"] = False
    assert project_market_sentiments(risk, market_scope="taiwan", as_of=as_of) == []
    assert project_market_sentiments(risk, market_scope="us", as_of=as_of) == []


def test_sentiment_rejects_naive_or_invalid_source_identity_and_out_of_range_score():
    as_of = datetime.fromisoformat("2026-09-30T06:28:00+00:00")
    risk = _risk()
    risk["taiwan"]["sentiment"]["data_quality"] = "unverified"
    risk["us"]["sentiment"]["score"] = 101
    assert project_market_sentiments(risk, market_scope="taiwan", as_of=as_of) == []
    assert project_market_sentiments(risk, market_scope="us", as_of=as_of) == []
    assert project_market_sentiments(_risk(), market_scope="taiwan", as_of="2026-09-30T06:28:00") == []
