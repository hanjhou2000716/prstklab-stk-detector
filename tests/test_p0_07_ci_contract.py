import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHA_ACTION = re.compile(r"[^@]+@[0-9a-f]{40}")


def test_reproducible_python_environment_is_locked():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = ROOT / "uv.lock"
    assert lock.is_file()
    assert "requires-python" in pyproject
    assert "ruff" in pyproject and "mypy" in pyproject
    assert "pytest-cov" in pyproject


def test_quality_workflow_runs_full_quality_and_coverage_gates():
    workflow = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    for required in (
        "uv sync --locked --all-groups",
        "--cov=src",
        "--cov-fail-under=80",
        "--cov-fail-under=90",
        "uv run ruff check src tests",
        "uv run mypy src",
        "python -m compileall -q src railway-monitor",
    ):
        assert required in workflow


def test_all_workflow_actions_are_immutable_sha_pinned():
    workflow_files = sorted((ROOT / ".github").rglob("*.y*ml"))
    assert workflow_files
    for path in workflow_files:
        text = path.read_text(encoding="utf-8")
        uses = re.findall(r"^\s*-?\s*uses:\s+([^\s#]+)", text, flags=re.MULTILINE)
        external = [item for item in uses if not item.startswith("./")]
        assert external
        assert all(SHA_ACTION.fullmatch(item) for item in external), (path.name, external)


def test_security_workflow_contains_supply_chain_and_analysis_jobs():
    workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    for required in ("dependency-review:", "codeql:", "sbom:", "fallback_sbom.py"):
        assert required in workflow

