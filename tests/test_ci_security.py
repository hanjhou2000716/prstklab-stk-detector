import re
from pathlib import Path


def test_hardened_ci_actions_are_sha_pinned():
    root = Path(__file__).resolve().parents[1]
    for name in ("quality.yml", "security.yml"):
        workflow = (root / ".github" / "workflows" / name).read_text(encoding="utf-8")
        uses = re.findall(r"^\s*-?\s*uses:\s+([^\s#]+)", workflow, flags=re.MULTILINE)
        assert uses
        assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", item) for item in uses), (name, uses)


def test_quality_workflow_uses_locked_environment_and_coverage():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    assert "uv sync --locked --all-groups" in workflow
    assert "--cov=src" in workflow
    assert "--cov=src.alert_contract" in workflow
    assert "Enforce core release and delivery coverage gate" in workflow
    assert "coverage erase" in workflow
    assert "--cov-fail-under=80" in workflow
    assert "uv run ruff" in workflow
    assert "uv run mypy" in workflow
