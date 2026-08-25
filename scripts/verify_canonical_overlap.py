"""Audit that production bundles derive from the repository's canonical contracts.

This is a read-only, offline check.  It intentionally checks the boundaries
between canonical source, generated Railway files, and compatibility JSON
bundles without importing a live service or reading secrets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_GENERATED_RE = re.compile(
    r"^# Canonical source: (?P<source>src/[A-Za-z0-9_/.]+\.py)\n"
    r"# Canonical source SHA256: (?P<digest>[0-9a-f]{64})\n",
    re.MULTILINE,
)


def _sha256(path: Path) -> str:
    # Match the generators' text-mode hashing.  This keeps the audit stable
    # across Windows CRLF checkouts and Linux CI workspaces.
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def check_generated_pair(root: Path, target: Path) -> dict[str, Any]:
    """Return a structured result for one generated Python module."""
    relative_target = target.relative_to(root).as_posix()
    if not target.is_file():
        return {"check": relative_target, "ok": False, "reason": "missing_target"}
    text = target.read_text(encoding="utf-8")
    match = _GENERATED_RE.search(text)
    source_ref: str | None = match.group("source") if match else None
    digest_ref: str | None = match.group("digest") if match else None
    if match is None and target.name == "shared_event_classifier.py":
        source_match = re.search(r'BUNDLE_SOURCE = "(?P<source>src/[^\"]+\.py)"', text)
        digest_match = re.search(r'BUNDLE_SOURCE_SHA256 = "(?P<digest>[0-9a-f]{64})"', text)
        if source_match and digest_match:
            source_ref = source_match.group("source")
            digest_ref = digest_match.group("digest")
    if not source_ref or not digest_ref:
        return {"check": relative_target, "ok": False, "reason": "missing_source_marker"}
    source = root / source_ref
    if not source.is_file():
        return {
            "check": relative_target,
            "ok": False,
            "reason": "missing_canonical_source",
            "source": source_ref,
        }
    actual = _sha256(source)
    return {
        "check": relative_target,
        "ok": actual == digest_ref,
        "reason": None if actual == digest_ref else "source_hash_drift",
        "source": source_ref,
    }


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_json_bundle(root: Path, name: str) -> dict[str, Any]:
    """Ensure Railway root and packaged policy files equal canonical JSON."""
    canonical = root / "config" / name
    copies = (root / "railway-monitor" / name, root / "railway-monitor" / "config" / name)
    if not canonical.is_file():
        return {"check": f"config/{name}", "ok": False, "reason": "missing_canonical"}
    try:
        expected = _json(canonical)
        missing = [path.relative_to(root).as_posix() for path in copies if not path.is_file()]
        drifted = [path.relative_to(root).as_posix() for path in copies if path.is_file() and _json(path) != expected]
    except (OSError, ValueError, TypeError) as exc:
        return {"check": f"config/{name}", "ok": False, "reason": f"invalid_json:{type(exc).__name__}"}
    ok = not missing and not drifted
    return {
        "check": f"config/{name}",
        "ok": ok,
        "reason": None if ok else "bundle_drift",
        "missing": missing,
        "drifted": drifted,
    }


def _text_contains(root: Path, relative: str, needles: tuple[str, ...]) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        return {"check": relative, "ok": False, "reason": "missing_file"}
    text = path.read_text(encoding="utf-8")
    missing = [needle for needle in needles if needle not in text]
    return {"check": relative, "ok": not missing, "reason": None if not missing else "missing_contract", "missing": missing}


def check_gmail_watch_canonical(root: Path) -> dict[str, Any]:
    """Ensure Railway Gmail lease work has one canonical producer.

    The async service module is intentionally only an adapter for the existing
    event loop.  Endpoint constants, lease decisions and cursor persistence
    must remain owned by ``GmailWatchManager``.
    """
    canonical = root / "railway-monitor" / "gmail_watch.py"
    adapter = root / "railway-monitor" / "gmail_watch_service.py"
    if not canonical.is_file() or not adapter.is_file():
        return {"check": "railway-monitor/gmail-watch-canonical", "ok": False, "reason": "missing_file"}
    owner = "CANONICAL_WATCH_OWNER = \"railway-monitor/gmail_watch.py:GmailWatchManager\""
    canonical_text = canonical.read_text(encoding="utf-8")
    adapter_text = adapter.read_text(encoding="utf-8")
    required = (owner, "class GmailWatchManager", "def ensure_watch")
    forbidden = ("class GmailWatchManager", "TOKEN_ENDPOINT =", "WATCH_ENDPOINT =", "def renewal_due")
    missing = [needle for needle in required if needle not in canonical_text]
    duplicate = [needle for needle in forbidden if needle in adapter_text]
    return {
        "check": "railway-monitor/gmail-watch-canonical",
        "ok": not missing and not duplicate and "GmailWatchManager" in adapter_text,
        "reason": None if not missing and not duplicate else "duplicate_watch_producer",
        "missing": missing,
        "duplicate": duplicate,
    }


def audit(root: Path = ROOT) -> dict[str, Any]:
    """Run the offline canonical-overlap audit against *root*."""
    checks: list[dict[str, Any]] = []
    for name in ("creator_providers.json", "event_keywords.json"):
        checks.append(check_json_bundle(root, name))

    generated_root = root / "railway-monitor" / "src"
    generated_targets = sorted(generated_root.glob("*.py")) if generated_root.is_dir() else []
    for target in generated_targets:
        if target.name == "__init__.py":
            continue
        checks.append(check_generated_pair(root, target))
    checks.append(check_generated_pair(root, root / "railway-monitor" / "shared_event_classifier.py"))

    checks.extend(
        [
            check_gmail_watch_canonical(root),
            _text_contains(root, "src/email_intelligence.py", ("creator_ids()", "get_creator_provider")),
            _text_contains(root, "railway-monitor/src/email_intelligence.py", ("creator_ids()", "get_creator_provider")),
            _text_contains(root, "src/news_feed_adapters.py", ("from src.news_intelligence import provider_registry", "for provider in provider_registry()")),
            _text_contains(root, "railway-monitor/shared_event_classifier.py", ("BUNDLE_SOURCE_SHA256", "_KEYWORD_PATH")),
        ]
    )
    failed = [check for check in checks if not check["ok"]]
    return {
        "status": "pass" if not failed else "fail",
        "checks": checks,
        "failed_count": len(failed),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (for offline tests)")
    args = parser.parse_args()
    result = audit(args.root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
