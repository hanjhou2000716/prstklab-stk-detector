import re
from pathlib import Path


def test_hardened_ci_actions_are_sha_pinned():
    root = Path(__file__).resolve().parents[1]
    for name in ("quality.yml", "security.yml"):
        workflow = (root / ".github" / "workflows" / name).read_text(encoding="utf-8")
        uses = re.findall(r"^\s*-?\s*uses:\s+([^\s#]+)", workflow, flags=re.MULTILINE)
        assert uses
        assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", item) for item in uses), (name, uses)


def test_every_external_workflow_action_is_sha_pinned():
    """Prevent a new workflow from reintroducing mutable action tags."""
    root = Path(__file__).resolve().parents[1]
    files = sorted((root / ".github").rglob("*.y*ml"))
    assert files
    for path in files:
        workflow = path.read_text(encoding="utf-8")
        uses = re.findall(r"^\s*-?\s*uses:\s+([^\s#]+)", workflow, flags=re.MULTILINE)
        external = [item for item in uses if not item.startswith("./")]
        assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", item) for item in external), (path, external)


def test_quality_workflow_uses_locked_environment_and_coverage():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    preflight = (root / "scripts" / "quality_preflight.py").read_text(encoding="utf-8")
    assert "uv sync --locked --all-groups" in workflow
    assert "scripts/quality_preflight.py --static" in workflow
    assert "scripts/quality_preflight.py --tests" in workflow
    assert "--cov=src" in preflight
    assert "src/alert_contract.py" in preflight
    assert "coverage\", \"erase" in preflight
    assert "--cov-fail-under=80" in preflight
    assert "--fail-under=90" in preflight
    assert "ruff\", \"check\", \"src\", \"tests\", \"scripts" in preflight
    assert "mypy\", \"src\", \"scripts/quality_preflight.py" in preflight
