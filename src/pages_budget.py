"""Enforce the bounded public Pages working set before upload."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from src.alert_archive import (
    AlertArchiveError,
    validate_alert_path,
    validate_alert_sha256,
    validate_source_commit,
)

DEFAULT_MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 50_000
MANIFEST_NAME = "data/release-manifest.json"
ALERT_INDEX_NAME = "data/alert-index.json"


class PagesBudgetError(RuntimeError):
    pass


def _inspect_pages_tree(root: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[int, int, int]:
    root = root.resolve(strict=True)
    total = 0
    count = 0
    entries = 0
    package_upper_bound = 1024  # tar end blocks plus ZIP container metadata
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in list(dirnames):
            path = current / name
            if path.is_symlink():
                raise PagesBudgetError("Pages working set contains a symbolic link")
            entries += 1
            relative = path.relative_to(root).as_posix()
            package_upper_bound += 2048 + len(relative.encode("utf-8"))
        for name in filenames:
            path = current / name
            if path.is_symlink() or not path.is_file():
                raise PagesBudgetError("Pages working set contains an unsupported file type")
            count += 1
            entries += 1
            if count > MAX_FILES or entries > MAX_FILES:
                raise PagesBudgetError("Pages working set contains too many files")
            size = path.stat().st_size
            total += size
            if total > max_bytes:
                raise PagesBudgetError("Pages working set exceeds the configured byte budget")
            relative = path.relative_to(root).as_posix()
            padding = (-size) % 512
            # Reserve more than the tar header/PAX path record and ZIP entry
            # metadata can consume, so the uploader's packaged artifact stays
            # below the same 512 MiB limit even when files are incompressible.
            package_upper_bound += size + padding + 2048 + len(relative.encode("utf-8"))
            if package_upper_bound > max_bytes:
                raise PagesBudgetError("Pages packaged artifact exceeds the configured byte budget")
    if package_upper_bound > max_bytes:
        raise PagesBudgetError("Pages packaged artifact exceeds the configured byte budget")
    return total, count, package_upper_bound


def measure_pages_tree(root: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[int, int]:
    total, count, _package_upper_bound = _inspect_pages_tree(root, max_bytes=max_bytes)
    return total, count


def _read_json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PagesBudgetError(f"{label} is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise PagesBudgetError(f"{label} must be an object")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stage_pages_payload(
    source_root: Path,
    output_root: Path,
    *,
    source_commit: str = "",
    retain_notification_ids: set[str] | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[int, int, int]:
    """Copy a compact Pages payload while retaining immutable history by commit.

    The canonical data-release tree is never modified. Cold alert details stay
    in that append-only history; the public index points to a fixed repository
    commit, while the current release and explicitly pending receipt targets
    remain in Pages.
    """
    source = source_root.resolve(strict=True)
    output = output_root.resolve()
    if output == source or source in output.parents or output in source.parents:
        raise PagesBudgetError("Pages staging output must be separate from source")
    if output.exists():
        raise PagesBudgetError("Pages staging output already exists")
    revision = validate_source_commit(source_commit) if source_commit else ""
    retained = {str(item).strip() for item in (retain_notification_ids or set()) if str(item).strip()}
    manifest_path = source / MANIFEST_NAME
    index_path = source / ALERT_INDEX_NAME
    if manifest_path.is_file() != index_path.is_file():
        raise PagesBudgetError("Pages manifest and alert index must be present together")

    omitted: set[str] = set()
    keep_alert_files: set[str] = set()
    archived_count = 0
    if manifest_path.is_file():
        manifest = _read_json_object(manifest_path, "release manifest")
        index = _read_json_object(index_path, "alert index")
        release_id = str(manifest.get("release_id") or "")
        rows = index.get("alerts")
        if not release_id or not isinstance(rows, list):
            raise PagesBudgetError("Pages release or alert index identity is invalid")
        for row in rows:
            if not isinstance(row, dict):
                raise PagesBudgetError("Pages alert index row is invalid")
            path = validate_alert_path(row.get("path"))
            digest = validate_alert_sha256(row.get("sha256"))
            notification_id = str(row.get("notification_id") or "").strip()
            row_release = str(row.get("release_id") or "").strip()
            if not notification_id or not row_release:
                raise PagesBudgetError("Pages alert index identity is incomplete")
            relative_path = (Path("data") / path).as_posix()
            is_current = row_release == release_id
            is_retained = notification_id in retained or row.get("pending_receipt") is True
            existing_source_commit = str(row.get("source_commit") or "").strip()
            if existing_source_commit:
                try:
                    existing_source_commit = validate_source_commit(existing_source_commit)
                except AlertArchiveError as exc:
                    raise PagesBudgetError("indexed alert source commit is invalid") from exc
            if not is_current and not is_retained:
                if existing_source_commit:
                    archived_count += 1
                    continue
                if revision:
                    # Cold rows without a fixed source are bound to the exact
                    # selected commit. Readers still verify the indexed hash,
                    # so packaging need not read multi-GB detail files.
                    row["source_commit"] = revision
                    archived_count += 1
                    continue

            local_path = source / "data" / path
            if not local_path.is_file() or local_path.is_symlink():
                raise PagesBudgetError("indexed alert source is missing or unsafe")
            digest_builder = hashlib.sha256()
            with local_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest_builder.update(chunk)
            if digest_builder.hexdigest() != digest:
                raise PagesBudgetError("indexed alert source hash does not match its index")
            if is_current or is_retained:
                # Existing fixed links are part of the immutable index. Keep
                # them even when this detail must remain in Pages for the
                # current release or a pending receipt.
                if existing_source_commit:
                    row["source_commit"] = existing_source_commit
                elif revision and not is_current:
                    # Pin newly archived receipt targets to the exact selected
                    # history commit, but never rewrite an existing pin.
                    row["source_commit"] = revision
                else:
                    row.pop("source_commit", None)
                keep_alert_files.add(relative_path)
                continue
            if revision:
                # No fixed source commit exists for this cold row and there is
                # a selected immutable archive commit available.
                row["source_commit"] = revision
                archived_count += 1
            else:
                # A verified last-good public bundle may not correspond to a
                # data-release commit. Preserve unpinned historical details in
                # Pages instead of silently redirecting their fixed source.
                row.pop("source_commit", None)
                keep_alert_files.add(relative_path)
        for detail_path in (source / "data" / "alerts").glob("*.json"):
            relative_path = detail_path.relative_to(source).as_posix()
            if relative_path not in keep_alert_files:
                omitted.add(relative_path)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    try:
        for directory, dirnames, filenames in os.walk(source, followlinks=False):
            current = Path(directory)
            rel_dir = current.relative_to(source)
            destination = output / rel_dir
            destination.mkdir(parents=True, exist_ok=True)
            for dirname in list(dirnames):
                child = current / dirname
                if child.is_symlink():
                    raise PagesBudgetError("Pages working set contains a symbolic link")
            for filename in filenames:
                origin = current / filename
                relative = origin.relative_to(source).as_posix()
                if relative in omitted:
                    continue
                if origin.is_symlink() or not origin.is_file():
                    raise PagesBudgetError("Pages working set contains an unsupported file type")
                shutil.copy2(origin, destination / filename)

        if manifest_path.is_file():
            staged_manifest_path = output / MANIFEST_NAME
            staged_index_path = output / ALERT_INDEX_NAME
            manifest = _read_json_object(staged_manifest_path, "staged release manifest")
            _write_json(staged_index_path, index)
            paths = manifest.get("artifact_paths")
            hashes = manifest.get("artifact_hashes")
            if not isinstance(paths, dict) or not isinstance(hashes, dict):
                raise PagesBudgetError("Pages manifest artifact maps are invalid")
            omitted_relative = {item.removeprefix("data/") for item in omitted}
            for name, raw_path in list(paths.items()):
                if raw_path in omitted or raw_path in omitted_relative or name in omitted_relative:
                    paths.pop(name, None)
                    hashes.pop(name, None)
            embedded_index = manifest.get("alert_index")
            if isinstance(embedded_index, dict):
                embedded_index["coverage"] = index.get("coverage", embedded_index.get("coverage", "complete"))
                embedded_index["alerts"] = [dict(row) for row in index["alerts"]]
            deferred_names = manifest.get("deferred_artifacts")
            if isinstance(deferred_names, list):
                manifest["deferred_artifacts"] = sorted(
                    name for name in deferred_names
                    if name in paths or name == "bootstrap.json"
                )
            index_digest = hashlib.sha256(staged_index_path.read_bytes()).hexdigest()
            hashes["alert-index.json"] = index_digest
            bootstrap_path = output / "data" / "bootstrap.json"
            if bootstrap_path.is_file():
                bootstrap = _read_json_object(bootstrap_path, "staged bootstrap")
                deferred = bootstrap.get("deferred_artifacts")
                if isinstance(deferred, dict):
                    deferred_paths = deferred.get("paths")
                    deferred_hashes = deferred.get("hashes")
                    if isinstance(deferred_paths, dict) and isinstance(deferred_hashes, dict):
                        for name, raw_path in list(deferred_paths.items()):
                            if raw_path in omitted or raw_path in omitted_relative or name in omitted_relative:
                                deferred_paths.pop(name, None)
                                deferred_hashes.pop(name, None)
                        deferred_hashes["alert-index.json"] = index_digest
                _write_json(bootstrap_path, bootstrap)
                hashes["bootstrap.json"] = hashlib.sha256(bootstrap_path.read_bytes()).hexdigest()
            _write_json(staged_manifest_path, manifest)

        total, count, _package_upper_bound = _inspect_pages_tree(output, max_bytes=max_bytes)
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return total, count, archived_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("site"))
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--stage", action="store_true", help="create a pruned immutable Pages copy")
    parser.add_argument("--source-root", type=Path, default=Path("site"))
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--retain-notification-id", action="append", default=[])
    args = parser.parse_args()
    if args.max_bytes <= 0:
        print("pages_budget_invalid_limit", file=sys.stderr)
        return 2
    try:
        if args.stage:
            if args.output_root is None:
                print("pages_staging_output_required", file=sys.stderr)
                return 2
            total, files, archived = stage_pages_payload(
                args.source_root, args.output_root,
                source_commit=args.source_commit,
                retain_notification_ids=set(args.retain_notification_id),
                max_bytes=args.max_bytes,
            )
            print(f"pages_budget_ok bytes={total} files={files} archived_alerts={archived} max_bytes={args.max_bytes}")
            return 0
        total, files = measure_pages_tree(args.root, max_bytes=args.max_bytes)
    except (OSError, PagesBudgetError) as exc:
        print(f"pages_budget_failed:{str(exc)[:180]}", file=sys.stderr)
        return 1
    print(f"pages_budget_ok bytes={total} files={files} max_bytes={args.max_bytes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
