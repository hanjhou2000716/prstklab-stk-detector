import json
import subprocess
import sys

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


def test_repair_state_reuses_verified_report_without_refreshing_success_time(tmp_path):
    previous = tmp_path / "previous.json"
    output = tmp_path / "repaired.json"
    previous.write_text(json.dumps({
        "generated_at": "2026-09-04T16:00:00+08:00",
        "source_commit_sha": "scan-sha",
        "run_id": "github-scan",
        "scan_mode": "production",
        "scan_scope": "full",
        "publication_state": "mixed_strategy",
        "publish_eligible": True,
        "production_eligible": False,
        "sources": [{
            "market": "taiwan", "strategy": "value", "scan_state": "building",
            "scan_trading_date": "2026-08-31",
            "last_successful_generated_at": "2026-08-31T10:46:00+08:00",
            "execution_version": "old-scan", "data_hash": "old-hash",
        }],
        "candidates": [{"market": "taiwan", "strategy": "value", "ticker": "2330", "list_type": "formal"}],
    }), encoding="utf-8")
    result = subprocess.run([
        sys.executable, "-m", "src.run_research_report",
        "--scan-mode", "production", "--previous-report", str(previous),
        "--output", str(output), "--target-market", "taiwan",
        "--target-strategy", "value", "--research-action", "repair_state",
        "--run-id", "repair-run", "--source-commit-sha", "repair-sha",
    ], check=True, capture_output=True, text=True)
    assert "輸出" in result.stdout
    repaired = json.loads(output.read_text(encoding="utf-8"))
    source = repaired["sources"][0]
    assert repaired["research_action"] == "repair_state"
    assert repaired["target_strategy"] == "value"
    assert repaired["repair_state"] is True
    assert source["scan_trading_date"] == "2026-08-31"
    assert source["last_successful_generated_at"] == "2026-08-31T10:46:00+08:00"
    assert source["execution_version"] == "old-scan"
    assert source["data_hash"] == "old-hash"
    assert source["historical_fallback"] is True
    assert repaired["candidates"][0]["research_version_state"] == "historical"


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
