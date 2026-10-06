from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts import create_validated_pr


def _args() -> list[str]:
    return [
        "--repo", "hanjhou2000716/prstklab-stk-detector",
        "--candidate-sha", "a" * 40,
        "--base-sha", "b" * 40,
        "--title", "Luna6 integration fix",
        "--body", "Validated candidate.",
    ]


def test_pr_creation_is_blocked_when_exact_candidate_evidence_is_missing(monkeypatch, capsys):
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="a" * 40, stderr="")
        if command[:3] == ["git", "branch", "--show-current"]:
            return SimpleNamespace(returncode=0, stdout="fix/luna6", stderr="")
        if command[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[:3] == ["git", "ls-remote", "origin"]:
            return SimpleNamespace(
                returncode=0,
                stdout=f"{'b' * 40}\trefs/heads/main\n{'a' * 40}\trefs/heads/fix/luna6\n",
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(create_validated_pr.subprocess, "run", fake_run)
    monkeypatch.setattr(create_validated_pr, "_verify_candidate", lambda *_args: "no_exact_validation")

    assert create_validated_pr.main(_args()) == 1
    assert not any(command[:3] == ["gh", "pr", "create"] for command in commands)
    assert "candidate_validation_blocked:no_exact_validation" in capsys.readouterr().err


def test_pr_creation_occurs_only_after_candidate_validation_and_remote_sha_checks(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="a" * 40, stderr="")
        if command[:3] == ["git", "branch", "--show-current"]:
            return SimpleNamespace(returncode=0, stdout="fix/luna6", stderr="")
        if command[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[:3] == ["git", "ls-remote", "origin"]:
            return SimpleNamespace(
                returncode=0,
                stdout=f"{'b' * 40}\trefs/heads/main\n{'a' * 40}\trefs/heads/fix/luna6\n",
                stderr="",
            )
        if command[:3] == ["gh", "pr", "list"]:
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        if command[:3] == ["gh", "pr", "create"]:
            body_path = command[command.index("--body-file") + 1]
            assert Path(body_path).read_text(encoding="utf-8") == "Validated candidate."
            return SimpleNamespace(returncode=0, stdout="https://github.com/example/repo/pull/1", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(create_validated_pr.subprocess, "run", fake_run)
    monkeypatch.setattr(create_validated_pr, "_verify_candidate", lambda *_args: "")

    assert create_validated_pr.main(_args()) == 0
    create_index = next(i for i, command in enumerate(commands) if command[:3] == ["gh", "pr", "create"])
    assert commands.index(["gh", "pr", "list", "--state", "open", "--head", "fix/luna6", "--base", "main", "--json", "number,url,headRefOid"]) < create_index
