"""Evidence-backed event-to-market transmission graph."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ImpactEdge:
    source: str
    target: str
    direction: str
    confidence: float
    evidence: tuple[str, ...]
    horizon: str
    invalidation_condition: str

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.direction not in {"up", "down", "mixed", "unknown"}:
            errors.append("invalid direction")
        if not 0 <= self.confidence <= 1:
            errors.append("confidence must be between 0 and 1")
        if not self.source or not self.target:
            errors.append("source and target are required")
        if not self.evidence:
            errors.append("evidence is required")
        if not self.horizon:
            errors.append("horizon is required")
        if not self.invalidation_condition:
            errors.append("invalidation condition is required")
        return errors


class MarketImpactGraph:
    """Small deterministic graph; no edge is created without evidence."""

    def __init__(self, edges: Iterable[ImpactEdge] = ()) -> None:
        self.edges: list[ImpactEdge] = []
        for edge in edges:
            self.add(edge)

    def add(self, edge: ImpactEdge) -> None:
        errors = edge.validate()
        if errors:
            raise ValueError("; ".join(errors))
        if edge not in self.edges:
            self.edges.append(edge)

    def path(self, source: str, target: str) -> list[ImpactEdge]:
        """Return a direct or short chain of edges between two nodes."""
        direct = [edge for edge in self.edges if edge.source == source and edge.target == target]
        if direct:
            return direct
        for first in self.edges:
            if first.source != source:
                continue
            for second in self.edges:
                if second.source == first.target and second.target == target:
                    return [first, second]
        return []

    def event_paths(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        requested = {str(value) for value in (event.get("affected_instruments") or event.get("market_nodes") or [])}
        rows = []
        for edge in self.edges:
            if edge.source in requested or edge.target in requested or not requested:
                rows.append(asdict(edge))
        return rows

    def as_dict(self) -> dict[str, Any]:
        return {"edges": [asdict(edge) for edge in self.edges], "edge_count": len(self.edges)}


def default_market_graph() -> MarketImpactGraph:
    return MarketImpactGraph([
        ImpactEdge("export_control", "ai_semiconductor_supply", "down", .7, ("official_policy",), "weeks", "policy withdrawn or scope narrowed"),
        ImpactEdge("ai_semiconductor_supply", "TSM", "mixed", .6, ("sector_linkage",), "weeks_to_quarters", "capacity or substitution evidence changes"),
        ImpactEdge("ai_semiconductor_supply", "SOX", "mixed", .55, ("sector_linkage",), "days_to_weeks", "index breadth does not confirm sector move"),
        ImpactEdge("oil_supply_disruption", "WTI", "up", .75, ("official_supply_event",), "hours_to_days", "supply resumes or price fails to confirm"),
        ImpactEdge("oil_supply_disruption", "inflation_expectations", "up", .6, ("oil_price_sync",), "days_to_weeks", "oil move reverses or inflation data diverges"),
    ])