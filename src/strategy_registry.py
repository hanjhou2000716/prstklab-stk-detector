"""Versioned registry for strategy, data and backtest releases."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REQUIRED_RELEASE_FIELDS = (
    "strategy_id",
    "strategy_version",
    "parameter_hash",
    "universe_version",
    "data_version",
    "code_commit",
    "backtest_release",
)


@dataclass(frozen=True)
class StrategyRelease:
    strategy_id: str
    strategy_version: str
    parameter_hash: str
    universe_version: str
    data_version: str
    code_commit: str
    backtest_release: str
    deployment_date: str | None = None
    retirement_date: str | None = None

    @classmethod
    def create(
        cls, strategy_id: str, strategy_version: str, parameters: dict[str, Any], *,
        universe_version: str, data_version: str, code_commit: str, backtest_release: str,
        deployment_date: str | None = None, retirement_date: str | None = None,
    ) -> StrategyRelease:
        parameter_hash = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()[:16]
        return cls(strategy_id, strategy_version, parameter_hash, universe_version, data_version, code_commit, backtest_release, deployment_date, retirement_date)


class StrategyRegistry:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.rows: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.rows = list(payload.get("releases", [])) if isinstance(payload, dict) else []
        except (OSError, ValueError, TypeError):
            self.rows = []

    def add(self, release: StrategyRelease) -> None:
        row = asdict(release)
        if any(item.get("strategy_id") == release.strategy_id and item.get("strategy_version") == release.strategy_version for item in self.rows):
            return
        self.rows.append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"releases": self.rows}, ensure_ascii=False, indent=2), encoding="utf-8")

    def find(self, strategy_id: str, strategy_version: str) -> dict[str, Any] | None:
        return next((row for row in self.rows if row.get("strategy_id") == strategy_id and row.get("strategy_version") == strategy_version), None)


def validate_strategy_release(row: Any) -> list[str]:
    """Validate a registry row before it can unlock production explainability.

    Registry metadata is provenance, not a score.  A partially populated row
    must therefore fail closed instead of being treated as a valid backtest
    binding merely because its strategy/version happen to match.
    """
    if not isinstance(row, dict):
        return ["strategy_registry must be an object"]
    errors: list[str] = []
    for field in REQUIRED_RELEASE_FIELDS:
        value = row.get(field)
        if value in (None, ""):
            errors.append(f"strategy_registry.{field} is missing")
        elif not isinstance(value, str):
            errors.append(f"strategy_registry.{field} must be a string")
    return errors
