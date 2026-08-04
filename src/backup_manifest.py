"""Backup manifest and restore verification without deleting source data."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable


def build_backup_manifest(paths: Iterable[str | Path], *, created_at: str) -> dict[str, Any]:
    files = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        files.append({"path": str(path), "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return {"created_at": created_at, "files": files, "status": "ready" if files else "empty"}


def verify_backup_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    missing, mismatched = [], []
    for item in manifest.get("files", []):
        path = Path(item["path"])
        if not path.is_file():
            missing.append(item["path"])
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item.get("sha256"):
            mismatched.append(item["path"])
    return {"status": "pass" if not missing and not mismatched and manifest.get("files") else "failed", "missing": missing, "mismatched": mismatched}
