"""Versioned registry for four research strategies."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class StrategyRecord:
    strategy_id: str
    strategy_version: str
    parameter_hash: str
    universe_version: str
    data_version: str
    code_commit: str
    backtest_release: str | None = None
    deployment_date: str | None = None
    retirement_date: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def parameter_hash(parameters: Mapping[str, Any]) -> str:
    payload = json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def register_strategy(strategy_id: str, *, version: str, parameters: Mapping[str, Any], universe_version: str, data_version: str, code_commit: str, backtest_release: str | None = None) -> StrategyRecord:
    if not strategy_id or not version or not code_commit:
        raise ValueError("strategy_id, version and code_commit are required")
    return StrategyRecord(strategy_id, version, parameter_hash(parameters), universe_version, data_version, code_commit, backtest_release)
