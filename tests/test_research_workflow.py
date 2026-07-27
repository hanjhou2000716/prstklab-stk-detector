from pathlib import Path


def test_research_workflow_is_independent_from_pages_deployment_lock():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "unified-research-report.yml").read_text(encoding="utf-8")

    assert "group: unified-research-report" in workflow
    assert "types: [unified-research-report]" in workflow
    assert "github.event.client_payload.taiwan_limit" in workflow
    assert "actions/deploy-pages" not in workflow
    assert "actions/upload-pages-artifact" not in workflow
