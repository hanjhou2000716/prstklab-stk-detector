from pathlib import Path

WORKFLOW = Path(".github/workflows/unified-research-report.yml")


def test_production_research_report_is_bound_to_workflow_run_and_commit() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '--run-id "github-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"' in text
    assert '--source-commit-sha "$GITHUB_SHA"' in text


def test_scheduled_research_uses_bounded_mops_batch_and_persists_cache() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "default: '50'" in text
    assert "MOPS_MAX_REFRESH: ${{ inputs.mops_max_refresh || github.event.client_payload.mops_max_refresh || '50' }}" in text
    assert "name: Persist incremental research caches" in text
    assert "--include data/taiwan-mops-pristine-history.json" in text
    assert "steps.research_gate.outputs.publish != 'true'" in text

