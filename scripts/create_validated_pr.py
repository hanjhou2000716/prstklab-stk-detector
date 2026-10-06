"""Create a pull request only after verifying exact candidate evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(command: list[str], *, timeout: int = 90) -> str:
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"command_failed:{command[0]}:{result.stderr.strip()[:240]}")
    return result.stdout.strip()


def _git_output(*args: str) -> str:
    return _run(["git", *args])


def _verify_candidate(repository: str, candidate_sha: str, base_sha: str) -> str:
    verifier = Path(__file__).with_name("verify_quality_validation.py")
    result = subprocess.run(
        [
            sys.executable, str(verifier), "--repo", repository,
            "--candidate-sha", candidate_sha, "--base-sha", base_sha,
        ],
        check=False, capture_output=True, text=True, timeout=600,
    )
    return "" if result.returncode == 0 else (result.stderr or result.stdout).strip()[:500]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    args = parser.parse_args(argv)
    try:
        candidate = args.candidate_sha.lower()
        base = args.base_sha.lower()
        head = _git_output("rev-parse", "HEAD").lower()
        branch = _git_output("branch", "--show-current")
        if head != candidate:
            raise RuntimeError("checked_out_candidate_sha_mismatch")
        if not branch or branch in {"main", "master"}:
            raise RuntimeError("candidate_branch_required")
        if _git_output("status", "--porcelain"):
            raise RuntimeError("working_tree_must_be_clean")

        remote_rows = _git_output("ls-remote", "origin", "refs/heads/main", f"refs/heads/{branch}").splitlines()
        remote_refs = {row.split()[1]: row.split()[0].lower() for row in remote_rows if len(row.split()) >= 2}
        if remote_refs.get("refs/heads/main") != base:
            raise RuntimeError("remote_main_changed_since_candidate_validation")
        if remote_refs.get(f"refs/heads/{branch}") != candidate:
            raise RuntimeError("remote_candidate_branch_moved_or_missing")

        validation_error = _verify_candidate(args.repo, candidate, base)
        if validation_error:
            raise RuntimeError("candidate_validation_blocked:" + validation_error)

        existing = json.loads(_run([
            "gh", "pr", "list", "--state", "open", "--head", branch, "--base", "main",
            "--json", "number,url,headRefOid",
        ]))
        if not isinstance(existing, list):
            raise RuntimeError("existing_pr_response_invalid")
        if existing:
            same = next((item for item in existing if str(item.get("headRefOid") or "").lower() == candidate), None)
            if same:
                print(f"Existing pull request already targets this validated candidate: {same.get('url', '')}")
                return 0
            raise RuntimeError("open_pull_request_for_branch_has_different_candidate")

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as body_file:
            body_file.write(args.body)
            body_path = Path(body_file.name)
        try:
            created = _run([
                "gh", "pr", "create", "--repo", args.repo,
                "--base", "main", "--head", branch,
                "--title", args.title, "--body-file", str(body_path),
            ], timeout=120)
        finally:
            body_path.unlink(missing_ok=True)
        print(created)
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: pull request was not created ({exc})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
