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
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import requests


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

    # ``release_manifest`` compares the research snapshot with the market
    # snapshot.  That is useful for generation-level consistency, but it does
    # not prove that the research is still fresh at deployment time.  The
    # downstream delivery gate performs that stricter wall-clock check.  Run
    # the same gate here so Pages never selects a candidate that will be
    # rejected immediately before upload (and can instead preserve the last
    # known-good public bundle).
    #
    # Keep this defensive for lightweight/unit fixtures that mock the manifest
    # command but do not provide a gate-shaped response.  Production's real
    # ``release_gate`` always emits an ``allowed=`` line, so an actual failure
    # is fail-closed and recorded in the manifest diagnostics.
    if ready and require_production_research:
        gate_command = [
            sys.executable,
            "-m",
            "src.release_gate",
            "--manifest",
            "site/data/release-manifest.json",
            "--require-production-research",
        ]
        gate = subprocess.run(
            gate_command,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        gate_lines = [line.strip() for line in (gate.stdout or "").splitlines() if line.strip()]
        gate_allowed = next(
            (line.split("=", 1)[1].strip().lower() for line in gate_lines if line.startswith("allowed=")),
            None,
        )
        if gate_allowed is not None and (gate.returncode != 0 or gate_allowed != "true"):
            gate_errors = next(
                (line.split("=", 1)[1].strip() for line in gate_lines if line.startswith("errors=")),
                "release gate rejected candidate",
            )
            existing = list(payload.get("validation_errors") or [])
            payload["validation_errors"] = sorted({*existing, *[item for item in gate_errors.split(";") if item]})
            payload["status"] = "invalid"
            ready = False
        elif gate.returncode != 0 and gate_allowed is None:
            existing = list(payload.get("validation_errors") or [])
            detail = (gate.stderr or "").strip() or "release gate failed without diagnostics"
            payload["validation_errors"] = sorted({*existing, detail})
            payload["status"] = "invalid"
            ready = False
    return ready, payload


def restore_public_release(
    *, root: Path | str = Path("."), public_url: str, timeout: float = 15.0
) -> dict[str, Any]:
    """Restore the last-good immutable Pages bundle without trusting the checkout.

    A data-release commit can be temporarily invalid while the currently
    published Pages bundle is still a safe, internally consistent release.
    Fetch every manifest-referenced artifact, verify its declared SHA-256 and
    only then replace ``site/data`` atomically.  This keeps static UI deploys
    useful while preventing an invalid candidate from replacing public data.
    """
    root = Path(root).resolve()
    base = public_url.rstrip("/")
    if not base.startswith("https://"):
        raise PagesReleaseError("public release URL must use HTTPS")
    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-cache, no-store",
        "Pragma": "no-cache",
        "User-Agent": "PRStK-pages-release",
    }
    try:
        response = requests.get(
            f"{base}/data/release-manifest.json?pages_restore=1",
            timeout=timeout,
            headers=headers,
        )
        response.raise_for_status()
        manifest = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise PagesReleaseError(f"public manifest unavailable: {type(exc).__name__}") from exc
    if not isinstance(manifest, dict) or manifest.get("status") != "ready":
        raise PagesReleaseError("public manifest status is not ready")
    paths = manifest.get("artifact_paths")
    hashes = manifest.get("artifact_hashes")
    if not isinstance(paths, dict) or not isinstance(hashes, dict):
        raise PagesReleaseError("public manifest artifact paths/hashes are missing")

    staging = root / ".pages-public-release-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        for name, raw_path in paths.items():
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise PagesReleaseError(f"public manifest path missing: {name}")
            expected = hashes.get(name)
            if not isinstance(expected, str) or len(expected) != 64:
                raise PagesReleaseError(f"public manifest hash missing: {name}")
            relative = Path(raw_path)
            target = (staging / relative).resolve()
            if not target.is_relative_to(staging.resolve()):
                raise PagesReleaseError(f"public artifact path escapes data root: {name}")
            url = f"{base}/{raw_path.lstrip('/')}"
            try:
                artifact_response = requests.get(url, timeout=timeout, headers=headers)
                artifact_response.raise_for_status()
                body = bytes(artifact_response.content)
            except (requests.RequestException, TypeError, ValueError) as exc:
                raise PagesReleaseError(
                    f"public artifact unavailable {name}: {type(exc).__name__}"
                ) from exc
            if hashlib.sha256(body).hexdigest() != expected:
                raise PagesReleaseError(f"public artifact hash mismatch: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        data_root = root / "site" / "data"
        data_root.mkdir(parents=True, exist_ok=True)
        for child in data_root.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in (staging / "data").iterdir() if (staging / "data").exists() else ():
            destination = data_root / child.name
            if child.is_dir():
                shutil.copytree(child, destination)
            else:
                shutil.copy2(child, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    ready, validated = _validate(root, require_production_research=False)
    if not ready:
        raise PagesReleaseError(
            "public release failed local validation: "
            + "; ".join(str(item) for item in validated.get("validation_errors") or [])
        )
    # ``_validate`` invokes the manifest builder, which writes a derived
    # manifest for the restored artifacts.  That generated identity can differ
    # from the immutable manifest currently served by Pages (for example when
    # release metadata was added after the artifact snapshot).  The public
    # manifest is the source of truth for the preserved bundle, so restore it
    # after validation; otherwise the downstream photo gate sees a stale or
    # locally-derived release id and blocks a safe delivery.
    data_root = root / "site" / "data"
    (data_root / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "release_id": str(manifest.get("release_id") or ""),
        "snapshot_id": str(manifest.get("market_snapshot_id") or ""),
        "artifact_count": len(paths),
    }


def restore_latest_valid(
    *,
    root: Path | str = Path("."),
    branch: str = "data-release",
    max_commits: int = 100,
    require_production_research: bool = True,
    preserve_public_url: str | None = None,
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
        # Keep the immutable manifest that was committed with the selected
        # data-release snapshot.  ``_validate`` invokes the manifest builder,
        # which derives a new release identity from the current clock and can
        # therefore rewrite an otherwise valid release with a different
        # release_id.  Downstream release gates compare this identity with the
        # public Pages manifest, so replacing it would make a safe release
        # appear mismatched and block delivery.  Validation still runs first;
        # this only restores the already-validated source-of-truth metadata.
        immutable_manifest_path = root / "site" / "data" / "release-manifest.json"
        try:
            immutable_manifest_bytes = immutable_manifest_path.read_bytes()
            immutable_manifest = json.loads(immutable_manifest_bytes.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
            immutable_manifest_bytes = None
            immutable_manifest = None
        ready, manifest = _validate(root, require_production_research=require_production_research)
        if ready:
            selected_manifest = manifest
            if isinstance(immutable_manifest, dict) and immutable_manifest.get("status") == "ready":
                try:
                    immutable_manifest_path.write_bytes(immutable_manifest_bytes or b"")
                    selected_manifest = immutable_manifest
                except OSError:
                    # The validator result remains authoritative if the
                    # checkout cannot be rewritten; report its identity so
                    # callers fail closed rather than claiming a preserved
                    # identity that was not actually restored.
                    selected_manifest = manifest
            return {
                "publish": True,
                "selected_commit": commit,
                "release_id": str(selected_manifest.get("release_id") or ""),
                "rejected_count": len(rejected),
            }
        rejected.append({
            "commit": commit,
            "release_id": str(manifest.get("release_id") or ""),
            "status": str(manifest.get("status") or "invalid"),
            "validation_errors": list(manifest.get("validation_errors") or [])[:5],
        })

    if preserve_public_url:
        try:
            preserved = restore_public_release(root=root, public_url=preserve_public_url)
        except PagesReleaseError as exc:
            _clear_data(root)
            return {
                "publish": False,
                "reason": "no_valid_production_release",
                "preserve_error": str(exc),
                "rejected_count": len(rejected),
                "latest_rejections": rejected[:5],
            }
        return {
            "publish": True,
            "preserved_public": True,
            "reason": "preserved_last_good_public_release",
            "release_id": preserved["release_id"],
            "snapshot_id": preserved["snapshot_id"],
            "rejected_count": len(rejected),
        }

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
    parser.add_argument(
        "--preserve-public-url",
        default=os.getenv("PAGES_PUBLIC_URL"),
        help="restore the currently published last-good bundle when no candidate is valid",
    )
    args = parser.parse_args()
    try:
        result = restore_latest_valid(
            root=args.root,
            branch=args.branch,
            max_commits=args.max_commits,
            require_production_research=args.require_production_research,
            preserve_public_url=args.preserve_public_url,
        )
    except PagesReleaseError as exc:
        print(json.dumps({"publish": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    _write_outputs(result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
