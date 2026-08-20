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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_generated_pair(root: Path, target: Path) -> dict[str, Any]:
    """Return a structured result for one generated Python module."""
    relative_target = target.relative_to(root).as_posix()
    if not target.is_file():
        return {"check": relative_target, "ok": False, "reason": "missing_target"}
    match = _GENERATED_RE.search(target.read_text(encoding="utf-8"))
    if not match:
        return {"check": relative_target, "ok": False, "reason": "missing_source_marker"}
    source = root / match.group("source")
    if not source.is_file():
        return {
            "check": relative_target,
            "ok": False,
            "reason": "missing_canonical_source",
            "source": match.group("source"),
        }
    actual = _sha256(source)
    return {
        "check": relative_target,
        "ok": actual == match.group("digest"),
        "reason": None if actual == match.group("digest") else "source_hash_drift",
        "source": match.group("source"),
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
