from pathlib import Path


def test_refresh_dashboard_feeds_reviewed_creator_records_into_canonical_release():
    workflow = Path(".github/workflows/refresh-dashboard.yml").read_text(encoding="utf-8")
    assert 'if [ -f "creator/public-records.json" ]; then' in workflow
    assert 'arguments+=(--creator-records "creator/public-records.json")' in workflow
    assert 'python -m src.release_manifest "${arguments[@]}"' in workflow


def test_refresh_dashboard_keeps_creator_input_optional_and_fail_soft():
    workflow = Path(".github/workflows/refresh-dashboard.yml").read_text(encoding="utf-8")
    block = workflow.split("- name: Build and publish immutable data release", 1)[1]
    assert "invalid input remains fail-soft" in block.replace("\n", " ")
    assert "--allow-stale-research" in block
