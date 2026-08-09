from pathlib import Path


def test_production_baseline_records_real_immutable_references():
    text = (Path(__file__).parents[1] / "docs" / "production-baseline-2026-08-09.md").read_text(encoding="utf-8")
    for marker in ("MAIN_HEAD_SHA", "DATA_RELEASE_HEAD_SHA", "release-d9ca5e04b57bf22b", "Safety boundary", "Rollback"):
        assert marker in text
