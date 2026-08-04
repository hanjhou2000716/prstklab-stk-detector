"""Small static audit for workflow permissions and secret exposure."""

from __future__ import annotations

from typing import Any


def audit_workflow(text: str) -> dict[str, Any]:
    lower = text.lower()
    reasons: list[str] = []
    if "permissions:" not in lower:
        reasons.append("workflow permissions are not explicit")
    if "pull-requests: write" in lower and "contents: read" not in lower:
        reasons.append("write job lacks a minimal read declaration")
    if "echo ${{ secrets." in lower or "print(secrets." in lower:
        reasons.append("secret may be written to logs")
    return {"status": "pass" if not reasons else "failed", "reasons": reasons, "secret_safe": not any("secret" in reason for reason in reasons)}
