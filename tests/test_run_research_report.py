import json

from src.run_research_report import attach_backtest_contract, default_sources, write_report


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
    assert report["candidates"][0]["backtest_release"] == "backtest-12345678"


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
