from pathlib import Path

PUBLISH_MARKER = "python -m src.data_release --publish"
WORKFLOW_ROOT = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _publishers() -> list[Path]:
    return sorted(
        path
        for path in WORKFLOW_ROOT.glob("*.yml")
        if PUBLISH_MARKER in path.read_text(encoding="utf-8")
    )


def test_every_data_publisher_is_serialized_and_targets_data_release():
    publishers = _publishers()
    assert publishers
    for path in publishers:
        text = path.read_text(encoding="utf-8")
        assert "group: main-data-writer" in text, f"{path.name} can race data-release"
        assert "DATA_RELEASE_BRANCH: data-release" in text
        assert "--branch \"$DATA_RELEASE_BRANCH\"" in text
        assert "git push origin HEAD:main" not in text


def test_pages_deploy_restores_release_before_validation():
    text = (WORKFLOW_ROOT / "deploy-pages.yml").read_text(encoding="utf-8")
    assert "refs/heads/data-release:refs/remotes/origin/data-release" in text
    assert "--restore --branch data-release" in text
    assert "git restore --source=origin/data-release --worktree -- site/data/" in text
    assert "manifest.get(\"status\") != \"ready\"" in text
    assert "src.release_gate" in text


def test_data_release_is_path_restricted_and_uses_an_isolated_index():
    source = (Path(__file__).resolve().parents[1] / "src" / "data_release.py").read_text(encoding="utf-8")
    assert "GIT_INDEX_FILE" in source
    assert "commit-tree" in source
    assert "refs/heads/{branch}" in source
    assert "site/data" in source
    assert "outside public data" in source
