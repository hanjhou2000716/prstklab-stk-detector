from src.backtest_costs import CostModel
from src.strategy_registry import StrategyRegistry, StrategyRelease


def test_taiwan_net_return_includes_costs():
    result = CostModel.for_market("taiwan").net_return(0.01)
    assert result["net_return"] < result["gross_return"]
    assert result["cost_bps"] > 0


def test_strategy_registry_deduplicates_version(tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.json")
    release = StrategyRelease.create("momentum", "1.0", {"threshold": 80}, universe_version="u1", data_version="d1", code_commit="abc", backtest_release="bt1")
    registry.add(release)
    registry.add(release)
    assert len(registry.rows) == 1

