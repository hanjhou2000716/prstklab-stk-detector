"""Keep research failure codes separate from bounded diagnostic text."""

from __future__ import annotations

import re

_CODE = re.compile(r"[A-Za-z0-9_.:-]{0,120}")
_LEGACY_REASONS = {
    "GitHub Actions queue pagination incomplete": "writer_queue_pagination_incomplete",
}


def normalize_research_reason(reason: object, detail: object = "") -> tuple[str, str]:
    """Accept v1 text diagnostics without treating them as execution identity."""
    for value in (reason, detail):
        if not isinstance(value, str) or len(value) > 200 or (value and not value.isprintable()):
            raise ValueError("research_terminal_reason_invalid")
    assert isinstance(reason, str) and isinstance(detail, str)
    if _CODE.fullmatch(reason):
        return reason, detail
    code = _LEGACY_REASONS.get(reason, "research_terminal_failure")
    return code, detail or reason
