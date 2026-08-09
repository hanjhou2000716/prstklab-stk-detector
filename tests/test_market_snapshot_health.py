from datetime import datetime
from zoneinfo import ZoneInfo

from src.market_data import build_market_snapshot


def test_risk_source_failure_is_not_labeled_as_a_market_quote_failure(monkeypatch):
    monkeypatch.setattr(
        "src.market_data.get_quote",
        lambda item, session=None: {
            **item,
            "price": 1,
            "quote_time": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        },
    )
    monkeypatch.setattr("src.market_data.get_market_status", lambda market: {"label": market})
    monkeypatch.setattr("src.risk_news.build_risk_snapshot", lambda: {
        "taiwan": {"label": "台股", "errors": ["台指波動率資料暫時無法取得"]},
        "us": {"label": "美股", "errors": []},
    })
    monkeypatch.setattr("src.risk_news.build_news_snapshot", lambda: {"errors": [], "taiwan": [], "us": []})
    monkeypatch.setattr("src.official_events.fetch_official_events", lambda: {"items": [], "errors": []})
    monkeypatch.setattr("src.event_alerts.build_event_snapshot", lambda news, quotes, official=None, indices=None: {})
    monkeypatch.setattr("src.macro_summary.build_macro_summary", lambda events, risk, program=None: {})
    monkeypatch.setattr("src.macro_program_feed.fetch_yutinghao_latest_program", lambda: None)
    monkeypatch.setattr("src.phase_two_sources.build_phase_two_snapshot", lambda: {"crypto_spot": None, "public_market_secondary": None, "sources": []})
    monkeypatch.setattr("src.research_cards.load_research_cards", lambda: {
        "status": "研究報告", "sources": [], "candidates": [{
            "ticker": "2330", "name": "台積電", "market": "taiwan", "strategy": "price_action", "rank": 1,
        }],
    })

    snapshot = build_market_snapshot()

    # Optional quote providers can still leave a visible unavailable card;
    # the aggregate must disclose that degraded state instead of claiming all
    # market data is live.  The risk-source error remains separately scoped.
    assert snapshot["data_status"] == "即時"
    assert snapshot["scan"]["scope"] == "公開市場定時掃描"
    assert snapshot["scan"]["completed_at"] == snapshot["generated_at"]
    assert snapshot["errors"] == [{
        "ticker": "台股風險指標",
        "message": "台指波動率資料暫時無法取得",
        "scope": "risk",
    }]
    assert "allocation" not in snapshot
    candidate = snapshot["research_report"]["candidates"][0]
    assert candidate["ticker"] == "2330"
    assert "reference_close" not in candidate
