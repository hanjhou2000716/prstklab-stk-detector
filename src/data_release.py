"""Publish high-frequency public data without committing to ``main``.

The release branch contains only immutable data paths selected by a workflow.
Application code stays on ``main`` while Pages still receives the checked-out
workspace as an artifact.  This module deliberately uses the local git
credential configured by GitHub Actions; it never accepts or prints tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_BRANCH = "data-release"
DEFAULT_INCLUDES = ("site/data",)


class DataReleaseError(RuntimeError):
    """Raised when a data release cannot be restored or published safely."""


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args], check=check, capture_output=True, text=True,
        )
    except OSError as exc:
        raise DataReleaseError(f"git unavailable: {type(exc).__name__}") from exc


def _commit_identity() -> tuple[str, str]:
    """Resolve a non-secret identity accepted by ``git commit-tree``."""
    configured_name = _run("config", "--get", "user.name", check=False).stdout.strip()
    configured_email = _run("config", "--get", "user.email", check=False).stdout.strip()
    name = configured_name or os.environ.get("GIT_AUTHOR_NAME") or os.environ.get("GITHUB_ACTOR") or "github-actions[bot]"
    email = configured_email or os.environ.get("GIT_AUTHOR_EMAIL") or "41898282+github-actions[bot]@users.noreply.github.com"
    return name, email


def _safe_path(raw: str) -> str:
    value = raw.strip().replace("\\", "/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise DataReleaseError(f"unsafe data-release path: {raw!r}")
    if not (value == "site/data" or value.startswith("site/data/") or value == "data" or value.startswith("data/")):
        raise DataReleaseError(f"data-release path is outside public data: {raw!r}")
    return value.rstrip("/")


def _expand_includes(root: Path, includes: list[str]) -> list[str]:
    files: list[str] = []
    for raw in includes or list(DEFAULT_INCLUDES):
        value = _safe_path(raw)
        candidate = root / value
        if candidate.is_dir():
            files.extend(
                path.relative_to(root).as_posix()
                for path in sorted(candidate.rglob("*"))
                if path.is_file()
            )
        elif candidate.is_file():
            files.append(value)
        else:
            # A cache may not exist in every workflow.  Missing optional paths
            # are skipped; a completely empty release is rejected below.
            continue
    return list(dict.fromkeys(files))


def _fetch_branch(branch: str) -> bool:
    result = _run("fetch", "origin", branch, check=False)
    return result.returncode == 0


def restore(*, root: Path | str = Path("."), branch: str = DEFAULT_BRANCH, includes: list[str] | None = None) -> dict[str, Any]:
    """Restore the latest data-only branch into the current checkout."""
    root = Path(root)
    branch = branch.strip() or DEFAULT_BRANCH
    if not _fetch_branch(branch):
        return {"restored": False, "branch": branch, "reason": "branch_missing"}
    files = _expand_includes(root, includes or list(DEFAULT_INCLUDES))
    if not files:
        return {"restored": False, "branch": branch, "reason": "no_local_paths"}
    result = _run("checkout", f"origin/{branch}", "--", *files, check=False)
    if result.returncode:
        raise DataReleaseError(result.stderr.strip() or "data-release restore failed")
    return {"restored": True, "branch": branch, "files": files}


def publish(
    *, root: Path | str = Path("."), branch: str = DEFAULT_BRANCH,
    includes: list[str] | None = None, message: str = "chore: publish immutable data release",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publish selected files as a data-only commit on ``branch``."""
    root = Path(root)
    branch = branch.strip() or DEFAULT_BRANCH
    files = _expand_includes(root, includes or list(DEFAULT_INCLUDES))
    if not files:
        raise DataReleaseError("no data files found for release")
    if dry_run:
        return {"published": False, "dry_run": True, "branch": branch, "files": files}

    _fetch_branch(branch)
    index = root / ".git" / "data-release-index"
    index.unlink(missing_ok=True)
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(index)
    try:
        subprocess.run(["git", "read-tree", "--empty"], check=True, capture_output=True, text=True, env=env)
        subprocess.run(["git", "add", "--", *files], check=True, capture_output=True, text=True, env=env)
        tree = subprocess.run(["git", "write-tree"], check=True, capture_output=True, text=True, env=env).stdout.strip()
        parent_result = _run("rev-parse", f"refs/remotes/origin/{branch}", check=False)
        parent = parent_result.stdout.strip() if parent_result.returncode == 0 else ""
        current_tree = _run("rev-parse", f"{parent}^{{tree}}", check=False).stdout.strip() if parent else ""
        if current_tree and current_tree == tree:
            return {"published": False, "unchanged": True, "branch": branch, "files": files, "tree": tree}
        commit_args = ["commit-tree", tree]
        if parent:
            commit_args.extend(["-p", parent])
        author_name, author_email = _commit_identity()
        commit_env = env.copy()
        commit_env.update({
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        })
        commit_result = subprocess.run(
            ["git", *commit_args], input=message + "\n", check=False,
            capture_output=True, text=True, env=commit_env,
        )
        if commit_result.returncode:
            detail = commit_result.stderr.strip() or commit_result.stdout.strip() or "unknown git error"
            raise DataReleaseError(f"git commit-tree failed: {detail}")
        commit = commit_result.stdout.strip()
        pushed = _run("push", "origin", f"{commit}:{branch}", check=False)
        if pushed.returncode:
            raise DataReleaseError(pushed.stderr.strip() or "data-release push failed")
        return {"published": True, "branch": branch, "commit": commit, "files": files, "tree": tree}
    finally:
        index.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--restore", action="store_true")
    mode.add_argument("--publish", action="store_true")
    parser.add_argument("--branch", default=os.getenv("DATA_RELEASE_BRANCH", DEFAULT_BRANCH))
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--message", default="chore: publish immutable data release")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = restore(branch=args.branch, includes=args.include) if args.restore else publish(
            branch=args.branch, includes=args.include, message=args.message, dry_run=args.dry_run,
        )
    except DataReleaseError as exc:
        print(json.dumps({"published": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
