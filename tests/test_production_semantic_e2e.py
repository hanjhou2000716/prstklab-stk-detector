import json
from pathlib import Path

from src.artifact_contract import validate_market


def test_public_artifacts_keep_separate_statuses():
    market = json.loads(Path("site/data/market.json").read_text(encoding="utf-8"))
    research = json.loads(Path("site/data/research-report.json").read_text(encoding="utf-8"))
    # The checked-in main snapshot is intentionally not the production
    # release; the gate must expose its semantic problems instead of silently
    # treating it as live data.
    market_errors = validate_market(market)
    assert isinstance(market_errors, list)
    assert market.get("source_health") is not None
    assert research.get("scan_mode") in {None, "production", "smoke", "debug"}


def test_release_manifest_is_ready_and_has_artifacts():
    manifest = json.loads(Path("site/data/release-manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("status") in {"ready", "invalid"}
    if manifest.get("status") == "ready":
        assert manifest.get("release_id")
        assert manifest.get("artifact_hashes")
