"""Evidence-first explainability cards for research candidates."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def build_explainability_card(candidate: Mapping[str, Any], *, strategy: str, as_of: str, data_quality: str, risk_factors: Sequence[str] = (), invalidation: Sequence[str] = ()) -> dict[str, Any]:
    """Keep passed/failed conditions and evidence visible instead of one opaque score."""
    passed = list(candidate.get("checks") or candidate.get("conditions") or [])
    failed = list(candidate.get("failed_checks") or [])
    return {
        "ticker": str(candidate.get("ticker") or candidate.get("symbol") or ""),
        "strategy": strategy,
        "as_of": as_of,
        "passed_conditions": passed,
        "failed_conditions": failed,
        "data_quality": data_quality,
        "risk_factors": list(risk_factors),
        "invalidation_conditions": list(invalidation),
        "event_context": list(candidate.get("events") or []),
        "not_a_buy_signal": True,
        "disclaimer": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
    }


def explainability_complete(card: Mapping[str, Any]) -> bool:
    return bool(card.get("ticker") and card.get("strategy") and card.get("as_of") and card.get("data_quality") is not None and "not_a_buy_signal" in card)
