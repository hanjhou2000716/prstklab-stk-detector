from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "quality.yml"


def test_quality_workflow_runs_tests_and_non_network_smoke_validation():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pytest -q" in workflow
    assert "python -m compileall -q src railway-monitor" in workflow
    assert "python -m src.delivery_smoke_test" in workflow
    assert "TELEGRAM_BOT_TOKEN: \"\"" in workflow
    assert "--send" not in workflow
