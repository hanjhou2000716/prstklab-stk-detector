from src.event_alerts import build_event_snapshot
from src.market_linkage import linked_market_quotes, resolve_event_market_links


def _indices():
    return [
        {
            "ticker": "TAIEX", "name": "臺灣加權指數", "price": 47042,
            "change_percent": -0.6, "quote_time": "2026-09-08T13:00:00+08:00",
            "crosscheck_sources": [{
                "provider": "TAIFEX", "label": "TAIFEX", "price": 22800,
                "change_percent": -0.4, "quote_time": "2026-09-08T13:00:00+08:00",
            }],
        },
        {"ticker": "TPEx", "price": 409, "change_percent": 1.7},
    ]


def test_formosa_petrochemical_resolves_company_taiex_and_txf_without_network_lookup():
    event = {"title": "6505 台塑化公告 2026 年 8 月合併營業額", "corporate_event": True}
    resolved = resolve_event_market_links(event, _indices())

    assert resolved["linked_markets"] == ["6505", "TAIEX", "TXF"]
    assert resolved["market_linkage_status"] == "resolved"
    assert [row["ticker"] for row in linked_market_quotes(event, _indices())] == ["TAIEX", "TXF"]
    assert resolved["market_sync_confirmed"] is False


def test_corporate_event_snapshot_exposes_linkage_but_keeps_sync_gate_independent():
    snapshot = build_event_snapshot(
        {"taiwan": [], "us": []}, [],
        official={"items": [{
            "title": "6505 台塑化公告 2026 年 8 月合併營業額",
            "source_key": "mops", "corporate_event": True,
            "source_tier": "official", "relevance": "official",
        }]},
        indices=_indices(),
    )
    event = snapshot["items"][0]

    assert event["linked_markets"] == ["6505", "TAIEX", "TXF"]
    assert event["market_linkage_status"] == "resolved"
    assert event["market_sync_confirmed"] is False
    assert event["corporate_alert_eligible"] is False


def test_explicit_taiwan_company_instrument_gets_baseline_without_name_alias():
    resolved = resolve_event_market_links(
        {"instrument": {"ticker": "9999", "name": "未列入別名表公司", "market": "twse"}},
        _indices(),
    )

    assert resolved["linked_markets"] == ["9999", "TAIEX", "TXF"]
    assert resolved["market_linkage_status"] == "resolved"
