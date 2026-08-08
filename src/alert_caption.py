"""Safe, semantic captions for Telegram and notification previews."""
from __future__ import annotations

import re


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()

def make_caption(*, subject: str, change: str = "", state: str = "觀察", verified: bool = False, icon: str = "🔵") -> str:
    status = "雙來源同向" if verified else state
    parts = [icon, _compact(subject), _compact(change), status]
    text = "｜".join(part for part in parts if part)
    if len(text) <= 40:
        return text
    # Remove optional words first, then preserve whole semantic tokens.
    subject = _compact(subject)
    change = _compact(change)
    for candidate in (f"{icon} {subject}｜{change}｜{status}", f"{icon} {subject}｜{status}", f"{icon}｜{status}"):
        if len(candidate) <= 40:
            return candidate
    return (f"{icon} {status}")[:40]

def validate_caption(caption: str) -> None:
    if not caption.strip() or len(caption) > 40:
        raise ValueError("caption must be 1-40 characters")
