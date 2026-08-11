from pathlib import Path


WORKFLOW = Path(".github/workflows/unified-research-report.yml")


def test_production_research_report_is_bound_to_workflow_run_and_commit() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '--run-id "github-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"' in text
    assert '--source-commit-sha "$GITHUB_SHA"' in text

