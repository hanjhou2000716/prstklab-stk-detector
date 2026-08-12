import json

from src.run_research_report import attach_backtest_contract, attach_instrument_lineage, default_sources, write_report


def test_backtest_contract_is_not_embedded_as_full_report(tmp_path):
    artifact = tmp_path / "walk-forward.json"
    artifact.write_text(json.dumps({
        "strategies": {"momentum": {"metrics": {"sharpe": 1.2}}},
        "backtest_release_contract": {
            "backtest_release": "backtest-12345678",
            "market": "taiwan",
            "publication_state": "ready",
            "publish_eligible": True,
            "strategy_registry": [{"strategy_id": "momentum"}],
            "performance_summary": {"momentum": {"test": {"sharpe": 0.7}}},
            "research_only": True,
        },
    }), encoding="utf-8")

    report = attach_backtest_contract({
        "status": "diagnostic",
        "candidates": [{"ticker": "2330", "strategy": "value"}],
    }, artifact)

    assert report["backtest_release_status"] == "ready"
    assert report["backtest_release_contract"]["backtest_release"] == "backtest-12345678"
    assert "strategies" not in report["backtest_release_contract"]
    assert report["backtest_release_contract"]["performance_summary"]["momentum"]["test"]["sharpe"] == 0.7
    assert report["candidates"][0]["backtest_release"] == "backtest-12345678"
    assert "strategy_registry" not in report["candidates"][0]


def test_backtest_registry_row_is_stamped_on_matching_candidate(tmp_path):
    artifact = tmp_path / "walk-forward.json"
    artifact.write_text(json.dumps({
        "backtest_release_contract": {
            "backtest_release": "bt1", "publication_state": "ready", "publish_eligible": True,
            "strategy_registry": [{"strategy_id": "value", "strategy_version": "v1", "data_version": "d1", "backtest_release": "bt1", "parameter_hash": "p", "universe_version": "u", "code_commit": "c"}],
        },
    }), encoding="utf-8")
    report = attach_backtest_contract({"candidates": [{"strategy": "value"}]}, artifact)
    assert report["candidates"][0]["strategy_registry"]["strategy_id"] == "value"


def test_missing_or_blocked_backtest_stays_explicitly_unavailable(tmp_path):
    report = attach_backtest_contract({"status": "diagnostic"}, tmp_path / "missing.json")

    assert report["backtest_release_status"] == "blocked"
    assert report["backtest_release_contract"]["publish_eligible"] is False
    assert report["backtest_release_contract"]["blocking_reasons"]


def test_research_without_backtest_keeps_backward_compatible_observation_state():
    report = attach_backtest_contract({"status": "diagnostic"}, None)

    assert report["backtest_release_status"] == "unavailable"
    assert "backtest_release_contract" not in report


def test_default_sources_cover_two_markets_and_two_strategies(tmp_path):
    sources = default_sources(tmp_path)
    assert {(source["market"], source["strategy"]) for source in sources} == {
        ("taiwan", "momentum"), ("us", "momentum"),
        ("taiwan", "price_action"), ("us", "price_action"),
        ("taiwan", "resonance"), ("us", "resonance"),
        ("taiwan", "value"), ("us", "value"),
    }


def test_write_report_creates_dashboard_json(tmp_path):
    output = tmp_path / "site" / "data" / "research-report.json"
    write_report({"status": "測試"}, output)
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "測試"


def test_instrument_lineage_is_stamped_without_guessing_unknown_symbols():
    report = {"candidates": [
        {"ticker": "2330", "market": "taiwan"},
        {"ticker": "UNKNOWN", "market": "us"},
    ]}
    result = attach_instrument_lineage(report)
    assert result["instrument_master_id"].startswith("instrument-")
    assert result["candidates"][0]["instrument_id"] == "twse:2330"
    assert result["candidates"][1]["instrument_resolution"] == "unresolved"
    assert result["candidates"][1]["instrument_id"] is None


def test_production_lineage_can_resolve_explicit_research_universe_rows():
    report = {"candidates": [
        {"ticker": "3037", "symbol": "3037.TW", "name": "欣興", "market": "taiwan"},
        {"ticker": "AAPL", "symbol": "AAPL", "name": "Apple Inc.", "market": "us"},
    ]}
    result = attach_instrument_lineage(report, extend_from_candidates=True)
    assert all(row["instrument_resolution"] == "resolved" for row in result["candidates"])
    assert result["candidates"][0]["instrument_id"] == "taiwan:equity:3037"
    assert result["candidates"][1]["instrument_id"] == "us:equity:aapl"
