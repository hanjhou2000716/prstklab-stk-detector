from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_canonical_parser_bundle_is_generated_and_current() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/sync_railway_canonical_parser.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_bundle_contains_only_canonical_parser_dependencies() -> None:
    expected = {
        "__init__.py",
        "creator_provider_registry.py",
        "creator_source_adapters.py",
        "email_intelligence.py",
        "event_classifier.py",
        "external_event_risk.py",
        "external_source_parsers.py",
        "financialjuice_contract.py",
    }
    actual = {path.name for path in (ROOT / "railway-monitor" / "src").glob("*.py")}
    assert actual == expected


def test_standalone_fallback_configs_match_canonical_payloads() -> None:
    """Root-only compatibility imports must not create a second policy table."""
    for name in ("creator_providers.json", "event_keywords.json"):
        canonical = json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))
        root_bundle = json.loads((ROOT / "railway-monitor" / name).read_text(encoding="utf-8"))
        packaged_bundle = json.loads(
            (ROOT / "railway-monitor" / "config" / name).read_text(encoding="utf-8")
        )
        assert root_bundle == canonical
        assert packaged_bundle == canonical


def test_railway_schema_bundle_matches_canonical_schema() -> None:
    canonical = json.loads((ROOT / "schemas" / "creator-providers.schema.json").read_text(encoding="utf-8"))
    bundled = json.loads(
        (ROOT / "railway-monitor" / "schemas" / "creator-providers.schema.json").read_text(encoding="utf-8")
    )
    assert bundled == canonical
