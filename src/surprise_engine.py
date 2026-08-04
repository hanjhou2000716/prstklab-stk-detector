"""Transparent macro surprise and first-reaction calculations."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class SurpriseResult:
    actual: float | None
    expected: float | None
    previous: float | None
    revision: float | None
    surprise: float | None
    surprise_z: float | None
    direction: str
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "actual": self.actual,
            "expected": self.expected,
            "previous": self.previous,
            "revision": self.revision,
            "surprise": self.surprise,
            "surprise_z": self.surprise_z,
            "direction": self.direction,
            "evidence": self.evidence,
        }


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def calculate_surprise(
    *, actual: Any, expected: Any = None, previous: Any = None, prior_revision: Any = None,
    historical_std: Any = None,
) -> SurpriseResult:
    """Calculate surprise without inventing missing forecasts or revisions."""
    a, e, p, old = map(_number, (actual, expected, previous, prior_revision))
    std = _number(historical_std)
    surprise = a - e if a is not None and e is not None else None
    z = surprise / std if surprise is not None and std and std > 0 else None
    revision = p - old if p is not None and old is not None else None
    if surprise is None:
        direction = "unknown"
        evidence = "expected_value_unavailable"
    elif surprise > 0:
        direction = "above_expected"
        evidence = "actual_above_expected"
    elif surprise < 0:
        direction = "below_expected"
        evidence = "actual_below_expected"
    else:
        direction = "in_line"
        evidence = "actual_matches_expected"
    return SurpriseResult(a, e, p, revision, surprise, z, direction, evidence)


def first_market_reaction(*, before: Any, after: Any, benchmark_before: Any = None, benchmark_after: Any = None) -> dict[str, Any]:
    """Describe the observed move; do not translate it into a prediction."""
    b, a = _number(before), _number(after)
    bb, ba = _number(benchmark_before), _number(benchmark_after)
    move = (a - b) / b * 100 if b and a is not None else None
    benchmark_move = (ba - bb) / bb * 100 if bb and ba is not None else None
    relative = move - benchmark_move if move is not None and benchmark_move is not None else None
    return {
        "before": b,
        "after": a,
        "move_percent": round(move, 4) if move is not None else None,
        "benchmark_move_percent": round(benchmark_move, 4) if benchmark_move is not None else None,
        "relative_move_percent": round(relative, 4) if relative is not None else None,
        "direction": "up" if move is not None and move > 0 else "down" if move is not None and move < 0 else "flat" if move is not None else "unknown",
        "observed_only": True,
    }


def build_macro_evidence(event: dict[str, Any]) -> dict[str, Any]:
    result = calculate_surprise(
        actual=event.get("actual"), expected=event.get("expected"), previous=event.get("previous"),
        prior_revision=event.get("prior_revision"), historical_std=event.get("historical_std"),
    )
    reaction = first_market_reaction(
        before=event.get("market_before"), after=event.get("market_after"),
        benchmark_before=event.get("benchmark_before"), benchmark_after=event.get("benchmark_after"),
    )
    return {"release": result.as_dict(), "market_reaction": reaction, "prediction": False}