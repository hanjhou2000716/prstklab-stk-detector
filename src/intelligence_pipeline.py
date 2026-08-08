"""Compose existing intelligence modules into a fail-closed event result."""
from __future__ import annotations

from typing import Any, Iterable

from src.market_impact_graph import build_market_impact_graph
from src.surprise_engine import calculate_surprise

def build_intelligence_context(event: dict[str, Any], observations: Iterable[dict[str, Any]] | None = None, *, macro: dict[str, Any] | None = None) -> dict[str, Any]:
    observations_list = list(observations or [])
    graph = build_market_impact_graph(event, observations_list)
    surprise = calculate_surprise(**(macro or {})) if macro is not None else {"status": "not_provided", "market_direction": "not_determined"}
    synchronized = any(path.get("confidence", 0) >= 0.8 for path in graph.get("paths", []))
    return {
        "market_impact_graph": graph,
        "macro_surprise": surprise,
        "market_sync_confirmed": synchronized,
        "evidence_status": "confirmed" if synchronized else "insufficient_evidence",
        "advice_gate": "observation_only" if not synchronized else "research_only",
        "disclaimer": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
    }
