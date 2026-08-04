"""Explainable cross-asset contagion checks for public market observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ContagionSignal:
    name: str
    active: bool
    severity: str
    evidence: tuple[str, ...]
    quality: str = "complete"

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "active": self.active, "severity": self.severity,
                "evidence": list(self.evidence), "quality": self.quality}


def _number(values: Mapping[str, Any], key: str) -> float | None:
    try:
        value = float(values[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value


def _signal(name: str, active: bool, evidence: list[str], *, severity: str = "warning") -> ContagionSignal:
    return ContagionSignal(name, active, severity if active else "normal", tuple(evidence))


def detect_contagion(observations: Mapping[str, Any], *, correlations: Mapping[str, float] | None = None) -> list[ContagionSignal]:
    """Detect simultaneous cross-asset stress without imputing missing prices.

    Values are normalized daily changes (decimal fractions) where available. A signal
    is only active when all required observations are present; missing inputs are
    disclosed as ``data_gap`` instead of being treated as calm markets.
    """
    out: list[ContagionSignal] = []
    pairs = [("equity_bond_selloff", ("equity_return", "bond_return"), lambda a, b: a < -0.01 and b < -0.005,
              "equity and bond both fell"),
             ("usd_risk_surge", ("usd_return", "equity_return"), lambda a, b: a > 0.005 and b < -0.01,
              "USD rose while equities fell"),
             ("gold_vix_stress", ("gold_return", "vix_return"), lambda a, b: a > 0.01 and b > 0.05,
              "gold and VIX rose together"),
             ("asia_semiconductor_lead", ("asia_return", "semiconductor_return"), lambda a, b: a < -0.015 and b < -0.02,
              "Asia and semiconductor proxies fell together"),
             ("crypto_risk_turn", ("crypto_return", "equity_return"), lambda a, b: a < -0.05 and b < -0.01,
              "crypto and equities fell together")]
    for name, keys, predicate, evidence in pairs:
        values = [_number(observations, key) for key in keys]
        if any(value is None for value in values):
            out.append(ContagionSignal(name, False, "unknown", ("data_gap:" + ",".join(keys),), "partial"))
            continue
        out.append(_signal(name, bool(predicate(values[0], values[1])), [evidence]))
    for name, value in (correlations or {}).items():
        if value < -0.75:
            out.append(_signal(f"correlation_break:{name}", True, [f"rolling correlation={value:.2f}"], severity="high"))
    return out


def active_contagion(signals: Sequence[ContagionSignal]) -> list[ContagionSignal]:
    return [signal for signal in signals if signal.active]
