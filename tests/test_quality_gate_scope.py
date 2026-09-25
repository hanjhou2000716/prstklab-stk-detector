from pathlib import Path


def test_quality_workflow_uses_full_static_analysis():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    preflight = (Path(__file__).parents[1] / "scripts" / "quality_preflight.py").read_text(encoding="utf-8")
    assert "scripts/quality_preflight.py --static" in workflow
    assert "check\", \"src\", \"tests\", \"scripts" in preflight
    assert "mypy\", \"src\", \"scripts/quality_preflight.py" in preflight
    assert "ruff check src/data_release.py" not in preflight
