"""Shared, auditable event classification for news and live alerts.

Both the scheduled news report and the live monitor must evaluate the same
facts.  This module deliberately accepts a record rather than a single
headline so descriptions, impact notes and market quotes cannot be silently
ignored by the classifier.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


_KEYWORD_PATH = Path(__file__).resolve().parents[1] / "config" / "event_keywords.json"


def _load_keywords() -> dict[str, Any]:
    try:
        return json.loads(_KEYWORD_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


KEYWORD_DATABASE = _load_keywords()
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    key: tuple(str(value) for value in values if str(value).strip())
    for key, values in (KEYWORD_DATABASE.get("categories") or {}).items()
    if isinstance(values, list)
}
BLACK_SWAN_TERMS = tuple(str(value) for value in KEYWORD_DATABASE.get("black_swan", ()) if str(value).strip())
MATERIAL_POSITIVE_TERMS = tuple(str(value) for value in KEYWORD_DATABASE.get("material_positive", ()) if str(value).strip())


def normalize_text(value: Any) -> str:
    """Normalize multilingual text without losing CJK characters."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _iter_text(value: Any, key: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _iter_text(child, str(child_key))
    elif isinstance(value, (list, tuple, set)):
        for child in value:
            yield from _iter_text(child, key)
    elif isinstance(value, (str, int, float)) and value not in (None, ""):
        yield str(value)


def build_haystack(record: dict[str, Any] | str) -> str:
    """Combine all descriptive fields and quote context into one classifier input."""
    values = [record] if isinstance(record, str) else list(_iter_text(record))
    return normalize_text(" ".join(values))


def _contains(term: str, haystack: str) -> bool:
    candidate = normalize_text(term)
    if not candidate:
        return False
    if candidate in haystack:
        return True
    # CJK aliases and English phrases are both commonly split by punctuation.
    compact_candidate = re.sub(r"[\s\-_/|:：,，。.!！?？]+", "", candidate)
    compact_haystack = re.sub(r"[\s\-_/|:：,，。.!！?？]+", "", haystack)
    return len(compact_candidate) >= 3 and compact_candidate in compact_haystack


def _first_hit(terms: Iterable[str], haystack: str) -> str:
    return next((str(term) for term in terms if _contains(str(term), haystack)), "")


def classify_event_fields(record: dict[str, Any] | str) -> dict[str, Any]:
    """Classify a news story or live flash with matched aliases and reason."""
    haystack = build_haystack(record)
    # De-escalation must win over generic war/attack aliases.
    positive = _first_hit(MATERIAL_POSITIVE_TERMS, haystack)
    if positive:
        return {"category": "material_positive", "reason": "material_positive_keyword", "matched_terms": [positive], "text": haystack}
    black = _first_hit(BLACK_SWAN_TERMS, haystack)
    if black:
        return {"category": "black_swan", "reason": "black_swan_keyword", "matched_terms": [black], "text": haystack}
    # A Trump mention becomes actionable only with a policy or de-escalation
    # action; the dedicated aliases are kept in the JSON database.
    trump = KEYWORD_DATABASE.get("trump") or {}
    entities = tuple(str(item) for item in trump.get("entities", ()) if str(item).strip())
    policy_actions = tuple(str(item) for item in trump.get("policy_actions", ()) if str(item).strip())
    taco = tuple(str(item) for item in trump.get("taco", ()) if str(item).strip())
    if _first_hit(taco, haystack):
        hit = _first_hit(taco, haystack)
        return {"category": "policy", "reason": "trump_taco_keyword", "matched_terms": [hit], "text": haystack}
    if _first_hit(entities, haystack) and _first_hit(policy_actions, haystack):
        hit = _first_hit(policy_actions, haystack)
        return {"category": "policy", "reason": "trump_policy_keyword", "matched_terms": [hit], "text": haystack}
    # Policy and conflict are checked before broad energy terms so an Iran /
    # shipping / supply story is not reduced to an ordinary oil headline.
    for category in ("conflict", "policy", "fed", "macro", "semiconductor", "market", "energy"):
        hit = _first_hit(CATEGORY_KEYWORDS.get(category, ()), haystack)
        if hit:
            if category == "energy":
                context = _first_hit(tuple(KEYWORD_DATABASE.get("energy_context", ())), haystack)
                if not context:
                    return {"category": None, "reason": "energy_requires_material_context", "matched_terms": [hit], "text": haystack}
            return {"category": category, "reason": f"{category}_keyword", "matched_terms": [hit], "text": haystack}
    return {"category": None, "reason": "keyword_no_match", "matched_terms": [], "text": haystack}


def notification_gate(category: str | None, *, official_confirmed: bool, market_sync_confirmed: bool) -> dict[str, Any]:
    """Return a transparent notification state for strict geopolitical events."""
    strict = category in {"black_swan", "conflict"}
    if not strict:
        return {"status": "eligible", "reasons": []}
    reasons: list[str] = []
    if not official_confirmed:
        reasons.append("等待官方核對")
    if not market_sync_confirmed:
        reasons.append("等待市場同步")
    return {"status": "ready" if not reasons else "pending", "reasons": reasons}
