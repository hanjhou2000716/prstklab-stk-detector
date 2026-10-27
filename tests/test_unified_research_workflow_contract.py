from pathlib import Path

WORKFLOW = Path(".github/workflows/unified-research-report.yml")


def test_production_research_report_is_bound_to_workflow_run_and_commit() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '--run-id "github-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"' in text
    assert '--source-commit-sha "$GITHUB_SHA"' in text


def test_scheduled_research_uses_bounded_mops_batch_and_persists_cache() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "default: '50'" in text
    assert "MOPS_MAX_REFRESH: ${{ github.event.client_payload.mops_max_refresh || '50' }}" in text
    assert "name: Persist incremental research caches" in text
    assert "--include data/taiwan-mops-pristine-history.json" in text
    assert "steps.research_gate.outputs.publish != 'true'" in text


def test_research_workflow_runs_only_selected_market_strategy_pairs():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--selected-pairs \"$SCANNED_PAIRS\"" in text
    assert "RUN_US_MOMENTUM" in text and "RUN_TAIWAN_MOMENTUM" in text
    assert "env.RUN_US_MOMENTUM == 'true'" in text
    assert "env.RUN_TAIWAN_MOMENTUM == 'true'" in text
    assert "RUN_{market.upper()}_{strategy.upper()}" in (Path("src/research_selection.py")).read_text(encoding="utf-8")
    assert "research_due_market_strategy_pairs_suppressed" in text


def test_current_research_noop_skips_publication_and_has_explicit_terminal_status():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "RESEARCH_NOOP" in text
    assert 'reason = selection_reason or "research_slot_already_current"' in text
    assert "RESEARCH_DUE={'false' if noop" in Path("src/research_selection.py").read_text(encoding="utf-8")

