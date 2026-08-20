from __future__ import annotations

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
