"""Restore a valid immutable release for GitHub Pages.

The data-release branch is append-only, but its newest commit can be produced
while research is still stale or incomplete.  Pages must never publish that
invalid snapshot and must not turn the expected fail-closed decision into a
failed workflow/email storm.  This module walks the immutable history from
newest to oldest, validates each snapshot with the production manifest gate,
and selects the newest valid snapshot.  When no valid snapshot exists it
returns success with ``publish=false``; the existing public Pages release is
then left untouched.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any


class PagesReleaseError(RuntimeError):
    """Raised when the immutable release history cannot be inspected safely."""


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, check=False, capture_output=True, text=True
        )
    except OSError as exc:  # pragma: no cover - exercised by deployment runtime
        raise PagesReleaseError(f"git unavailable: {type(exc).__name__}") from exc


def _clear_data(root: Path) -> None:
    data_root = root / "site" / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    for child in data_root.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _restore_archive(root: Path, commit: str) -> bool:
    """Restore only ``site/data`` from *commit* without changing the index."""
    try:
        result = subprocess.run(
            ["git", "archive", commit, "site/data"],
            cwd=root,
            check=False,
            capture_output=True,
        )
    except OSError as exc:  # pragma: no cover - deployment runtime
        raise PagesReleaseError(f"git unavailable: {type(exc).__name__}") from exc
    if result.returncode:
        return False
    _clear_data(root)
    archive_bytes = bytes(result.stdout or b"")
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
            root_resolved = root.resolve()
            members = archive.getmembers()
            for member in members:
                target = (root / member.name).resolve()
                if not target.is_relative_to(root_resolved):
                    raise PagesReleaseError("data-release archive escapes checkout")
            archive.extractall(root)
    except (OSError, tarfile.TarError) as exc:
        raise PagesReleaseError(
            f"cannot restore data-release archive: {type(exc).__name__}"
        ) from exc
    return True


def _commits(root: Path, branch: str, max_commits: int) -> list[str]:
    result = _run_git(root, "rev-list", f"--max-count={max_commits}", f"origin/{branch}")
    if result.returncode:
        raise PagesReleaseError(result.stderr.strip() or f"cannot inspect origin/{branch}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _validate(root: Path, *, require_production_research: bool) -> tuple[bool, dict[str, Any]]:
    command = [sys.executable, "-m", "src.release_manifest"]
    if require_production_research:
        command.append("--require-production-research")
    result = subprocess.run(command, cwd=root, check=False, capture_output=True, text=True)
    payload: dict[str, Any] = {}
    for line in reversed((result.stdout or "").splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    ready = result.returncode == 0 and payload.get("status") == "ready"
    return ready, payload


def restore_latest_valid(
    *,
    root: Path | str = Path("."),
    branch: str = "data-release",
    max_commits: int = 100,
    require_production_research: bool = True,
) -> dict[str, Any]:
    """Select the newest production-valid immutable release.

    The returned ``publish`` flag is the workflow contract.  ``False`` is a
    successful, fail-closed no-op: no invalid artifact is uploaded and the
    previously published Pages release remains available.
    """
    root = Path(root).resolve()
    branch = branch.strip() or "data-release"
    if max_commits <= 0:
        raise PagesReleaseError("max_commits must be positive")
    commits = _commits(root, branch, max_commits)
    rejected: list[dict[str, Any]] = []
    for commit in commits:
        if not _restore_archive(root, commit):
            rejected.append({"commit": commit, "reason": "missing_site_data"})
            continue
        ready, manifest = _validate(root, require_production_research=require_production_research)
        if ready:
            return {
                "publish": True,
                "selected_commit": commit,
                "release_id": str(manifest.get("release_id") or ""),
                "rejected_count": len(rejected),
            }
        rejected.append({
            "commit": commit,
            "release_id": str(manifest.get("release_id") or ""),
            "status": str(manifest.get("status") or "invalid"),
            "validation_errors": list(manifest.get("validation_errors") or [])[:5],
        })

    _clear_data(root)
    return {
        "publish": False,
        "reason": "no_valid_production_release",
        "rejected_count": len(rejected),
        "latest_rejections": rejected[:5],
    }


def _write_outputs(result: dict[str, Any]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    lines = [
        f"{key}={str(value).lower() if isinstance(value, bool) else value}"
        for key, value in result.items()
        if not isinstance(value, (dict, list))
    ]
    with Path(output).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--branch", default=os.getenv("DATA_RELEASE_BRANCH", "data-release"))
    parser.add_argument("--max-commits", type=int, default=100)
    parser.add_argument("--require-production-research", action="store_true")
    args = parser.parse_args()
    try:
        result = restore_latest_valid(
            root=args.root,
            branch=args.branch,
            max_commits=args.max_commits,
            require_production_research=args.require_production_research,
        )
    except PagesReleaseError as exc:
        print(json.dumps({"publish": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    _write_outputs(result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
