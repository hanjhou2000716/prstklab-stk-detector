from pathlib import Path


def test_quality_workflow_uses_full_static_analysis():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    assert "ruff check src tests" in workflow
    assert "mypy src" in workflow
    assert "ruff check src/data_release.py" not in workflow
