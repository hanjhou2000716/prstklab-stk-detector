from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src import market_data, taifex_daily, taiwan_market_statistics
from src.market_data import build_market_snapshot
from src.market_source_watch import TAIPEI, watch_quote_updates


@pytest.fixture
def offline_market_snapshot(monkeypatch):
    monkeypatch.setattr(
        "src.market_data.get_quote",
        lambda item, session=None: {
            **item,
            "price": 1,
            "quote_time": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        },
    )
    monkeypatch.setattr("src.market_data.get_market_status", lambda market: {
        "label": market,
        "calendar": "XTAI" if market == "taiwan" else "NYSE",
        "calendar_status": "confirmed_open",
        "is_trading_day": True,
    })
    monkeypatch.setattr("src.taifex_calendar.get_taifex_index_futures_status", lambda **_kwargs: {
        "label": "台指期日盤", "calendar": "TAIFEX", "calendar_provider": "TAIFEX",
        "calendar_status": "confirmed_open", "is_trading_day": True,
        "calendar_version": "TAIFEX-2026", "calendar_coverage_start": "2026-01-01",
        "calendar_coverage_end": "2026-12-31", "calendar_source_published_on": ["2025-10-30"],
        "calendar_source_document": "台期交字第1140003036號函", "calendar_verified_on": "2026-09-25",
        "calendar_source_urls": [
            "https://www.taifex.com.tw/file/taifex/CHINESE/11/attach/2026.pdf",
        ],
    })
    monkeypatch.setattr("src.taifex_daily.fetch_latest_verified_txf", lambda **_kwargs: None)
    monkeypatch.setattr("src.taifex_daily.validated_txf_backup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.risk_news.build_risk_snapshot", lambda: {
        "taiwan": {"label": "台股", "errors": ["台指波動率資料暫時無法取得"]},
        "us": {"label": "美股", "errors": []},
    })
    captured_news: dict[str, object] = {}

    def fake_news_snapshot(**kwargs):
        captured_news.update(kwargs)
        return {"errors": [], "taiwan": [], "us": []}

    monkeypatch.setattr("src.risk_news.build_news_snapshot", fake_news_snapshot)
    monkeypatch.setattr("src.official_events.fetch_official_events", lambda: {
        "items": [{"title": "Fed FOMC statement", "topic_key": "fed"}], "errors": []
    })
    monkeypatch.setattr("src.event_alerts.build_event_snapshot", lambda news, quotes, official=None, indices=None: {})
    monkeypatch.setattr("src.macro_summary.build_macro_summary", lambda events, risk, program=None: {})
    monkeypatch.setattr("src.macro_program_feed.fetch_yutinghao_latest_program", lambda: None)
    # Keep this unit test offline and deterministic.  The crypto cross-check
    # is an external provider path and must be covered by its own adapter
    # tests, not allowed to change the aggregate quote status here.
    monkeypatch.setattr(
        "src.phase_two_sources.build_phase_two_snapshot",
        lambda: {"crypto_spot": [], "public_market_secondary": None, "sources": []},
    )
    # Keep the direct cross-check path deterministic as well when the
    # preceding MOPS/provenance fixes are merged into main.  This test is
    # scoped to the risk-provider error, not public crypto availability.
    monkeypatch.setattr("src.market_data.apply_crypto_spot_crosscheck", lambda indices, _spot: indices)
    monkeypatch.setattr("src.taiwan_market_statistics.fetch_twse_market_statistics", lambda **_kwargs: {
        "status": "complete", "errors": [], "turnover": {}, "breadth": {},
        "institutional_flows": {}, "observed_date": "2026-09-07", "is_proxy": False,
    })
    monkeypatch.setattr("src.taiwan_market_statistics.fetch_twse_taiex_recent_close", lambda **_kwargs: None)
    monkeypatch.setattr("src.market_backup.from_environment", lambda: None)
    monkeypatch.setattr("src.market_data.apply_crypto_spot_crosscheck", lambda indices, _spot: indices)
    monkeypatch.setattr("src.research_cards.load_research_cards", lambda: {
        "status": "研究報告", "sources": [], "candidates": [{
            "ticker": "2330", "name": "台積電", "market": "taiwan", "strategy": "price_action", "rank": 1,
        }],
    })

    return captured_news


def test_risk_source_failure_is_not_labeled_as_a_market_quote_failure(offline_market_snapshot):
    snapshot = build_market_snapshot()
    captured_news = offline_market_snapshot

    assert captured_news["official_events"]["items"][0]["topic_key"] == "fed"

    # Optional quote providers can still leave a visible unavailable card;
    # the aggregate must disclose that degraded state instead of claiming all
    # market data is live.  Risk and official-cash source errors remain scoped.
    assert snapshot["data_status"] == "即時"
    assert snapshot["scan"]["scope"] == "公開市場定時掃描"
    assert snapshot["scan"]["completed_at"] == snapshot["generated_at"]
    assert len(snapshot["errors"]) == 3
    assert {row.get("scope") for row in snapshot["errors"]} == {"index", "risk"}
    assert next(row for row in snapshot["errors"] if row.get("scope") == "risk") == {
        "ticker": "台股風險指標",
        "message": "台指波動率資料暫時無法取得",
        "scope": "risk",
    }
    index_errors = {row["ticker"]: row for row in snapshot["errors"] if row.get("scope") == "index"}
    assert "TXF" in index_errors
    assert "TAIFEX" in index_errors["TXF"]["message"]
    assert "TAIEX" in index_errors
    assert index_errors["TAIEX"]["source_attempts"][-1] == {
        "source": "twse_saved_official_backup",
        "outcome": "backup_store_unavailable",
    }
    assert snapshot["markets"]["taiwan_cash"]["calendar_provider"] == "pandas_market_calendars"
    assert snapshot["markets"]["taiwan_cash"]["calendar"] == "XTAI"
    assert snapshot["markets"]["taiwan_futures"]["calendar_provider"] == "TAIFEX"
    assert snapshot["markets"]["taiwan_futures"]["calendar"] == "TAIFEX"
    assert snapshot["markets"]["taiwan_cash"]["calendar"] != snapshot["markets"]["taiwan_futures"]["calendar"]
    assert "allocation" not in snapshot
    candidate = snapshot["research_report"]["candidates"][0]
    assert candidate["ticker"] == "2330"
    assert "reference_close" not in candidate


@pytest.mark.parametrize(
    ("scenario", "expected_cash", "expected_txf", "expected_requests"),
    [
        ("verified", 39151.81, 39200, []),
        ("stale_reread", 39151.81, 39200, ["txf"]),
        ("taifex_conflict", 39151.81, None, ["txf", "backup"]),
        ("stale_watch", 39151.81, 38062, ["txf"]),
        ("expired_contract", 39151.81, 38062, ["txf"]),
        ("missing_date", 38195.43, 38062, ["txf", "cash"]),
        ("partial_cash", 39151.81, 39200, ["cash"]),
    ],
)
def test_post_close_watcher_reuses_only_verified_quotes_and_preserves_conflict_checks(
    monkeypatch, offline_market_snapshot, scenario,
    expected_cash, expected_txf, expected_requests,
):
    today = "2026-11-26"
    yesterday = "2026-11-25"
    now = datetime(2026, 11, 26, 14, 40, tzinfo=TAIPEI)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(market_data, "datetime", FixedDatetime)
    monkeypatch.setattr(market_data, "_latest_completed_session_date", lambda _quote, _now: now.date())

    def evidence(source, *, observed=today, outcome="verified"):
        return {"source": source, "outcome": outcome, "target_date": today, "observed_date": observed}

    cash = {
        "ticker": "TAIEX", "quote_date": today, "quote_time": f"{today}T13:30:00+08:00",
        "price": 39151.81, "change": 956.38, "change_percent": 2.50,
        "instrument_id": "twse:taiex", "quote_basis": "TWSE_TAIEX_DAILY_CLOSE", "source_tier": "official",
        "source_url": "https://www.twse.com.tw/exchangeReport/MI_INDEX",
        "source_attempts": [evidence("twse_mi_index_json")],
    }
    txf = {
        "ticker": "TXF", "quote_date": today, "quote_time": f"{today}T13:45:00+08:00",
        "price": 39200, "change": 1138, "change_percent": 2.99, "freshness": "recent_close",
        "contract_month": "202612", "session": "regular", "source_tier": "official",
        "instrument_id": "market:txf:taifex:202612:regular",
        "quote_basis": "TAIFEX_TXF_DAY|contract=202612|session=regular",
        "source_url": taifex_daily.TAIFEX_DAILY_API,
        "source_attempts": [
            evidence("taifex_openapi"), evidence("taifex_daily_table"),
            evidence("taifex_selection", outcome="selected:taifex_openapi"),
        ],
    }
    older_txf = {**txf, "quote_date": yesterday, "quote_time": f"{yesterday}T13:45:00+08:00", "price": 38062}
    if scenario in {"stale_reread", "taifex_conflict"}:
        txf["source_attempts"].pop(1)
    if scenario == "stale_watch":
        txf = older_txf
    if scenario == "expired_contract":
        txf.update(
            contract_month="202611",
            instrument_id="market:txf:taifex:202611:regular",
            quote_basis="TAIFEX_TXF_DAY|contract=202611|session=regular",
        )
    if scenario == "missing_date":
        cash.pop("quote_date")
        txf.pop("quote_date")

    if scenario == "partial_cash":
        cash.pop("change_percent")
    calls = []

    def fetch_txf(*, diagnostics, **_kwargs):
        calls.append("txf")
        if scenario == "taifex_conflict":
            diagnostics.append(evidence("taifex_official_comparison", outcome="same_day_official_conflict"))
            return None
        return dict(older_txf)

    def fallback_txf(*_args, excluded_observed_dates, **_kwargs):
        calls.append("backup")
        assert excluded_observed_dates == {today}
        return None

    def fetch_cash(**_kwargs):
        calls.append("cash")
        if scenario == "partial_cash":
            return {**cash, "change_percent": 2.50}
        return {**cash, "quote_date": yesterday, "price": 38195.43}

    monkeypatch.setattr(taifex_daily, "fetch_latest_verified_txf", fetch_txf)
    monkeypatch.setattr(taifex_daily, "validated_txf_backup", fallback_txf)
    monkeypatch.setattr(taiwan_market_statistics, "fetch_twse_taiex_recent_close", fetch_cash)
    monkeypatch.setattr(taiwan_market_statistics, "fetch_twse_market_statistics", lambda **_kwargs: {
        "status": "complete",
        "turnover": {
            "source_url": taiwan_market_statistics.TWSE_FMTQIK_URL, "is_proxy": False,
            "observed_date": None if scenario in {"missing_date", "partial_cash"} else today,
            "taiex": 39150, "change": 954.57,
        },
    })
    overrides = {"cash_quote": cash, "futures_quote": txf}
    if scenario in {"stale_watch", "expired_contract", "partial_cash"}:
        updated, _ = watch_quote_updates(overrides, {}, now=now)
        assert "cash_quote" in updated
        assert ("futures_quote" in updated) is (scenario == "partial_cash")

    snapshot = build_market_snapshot(official_close_overrides=overrides)
    rows = {row["ticker"]: row for row in snapshot["indices"]}
    assert calls == expected_requests
    assert rows["TAIEX"]["price"] == expected_cash
    assert snapshot["taiwan_market_statistics"]["turnover"]["taiex"] == 39150
    assert rows.get("TXF", {}).get("price") == expected_txf
    if scenario in {"verified", "stale_reread"}:
        assert any(
            row.get("outcome") == "selected:taifex_openapi" and row.get("observed_date") == today
            for row in rows["TXF"]["source_attempts"]
        )
