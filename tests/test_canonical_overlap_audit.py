from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_canonical_overlap import audit, check_generated_pair, check_json_bundle

ROOT = Path(__file__).parents[1]


def test_canonical_overlap_audit_passes_for_repository() -> None:
    result = audit(ROOT)
    assert result["status"] == "pass", json.dumps(result, ensure_ascii=False)


def test_generated_pair_detects_source_hash_drift(tmp_path: Path) -> None:
    source = tmp_path / "src" / "example.py"
    target = tmp_path / "railway-monitor" / "src" / "example.py"
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    target.write_text(
        "# Canonical source: src/example.py\n"
        "# Canonical source SHA256: " + ("0" * 64) + "\n\nVALUE = 1\n",
        encoding="utf-8",
    )
    result = check_generated_pair(tmp_path, target)
    assert result["ok"] is False
    assert result["reason"] == "source_hash_drift"


def test_json_bundle_detects_drift(tmp_path: Path) -> None:
    canonical = tmp_path / "config" / "creator_providers.json"
    root_copy = tmp_path / "railway-monitor" / "creator_providers.json"
    packaged_copy = tmp_path / "railway-monitor" / "config" / "creator_providers.json"
    canonical.parent.mkdir(parents=True)
    root_copy.parent.mkdir(parents=True)
    packaged_copy.parent.mkdir(parents=True)
    canonical.write_text('{"providers": []}\n', encoding="utf-8")
    root_copy.write_text('{"providers": []}\n', encoding="utf-8")
    packaged_copy.write_text('{"providers": [{"id": "drift"}]}\n', encoding="utf-8")
    result = check_json_bundle(tmp_path, "creator_providers.json")
    assert result["ok"] is False
    assert result["reason"] == "bundle_drift"
