"""Safe immutable source references for archived notification details."""

from __future__ import annotations

import re

ARCHIVE_REPOSITORY = "hanjhou2000716/prstklab-stk-detector"
ARCHIVE_RAW_BASE = "https://raw.githubusercontent.com/hanjhou2000716/prstklab-stk-detector"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_ALERT_PATH_RE = re.compile(r"^alerts/[A-Za-z0-9][A-Za-z0-9._-]*\.json$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AlertArchiveError(ValueError):
    pass


def validate_source_commit(value: object) -> str:
    commit = str(value or "").strip().lower()
    if not _COMMIT_RE.fullmatch(commit):
        raise AlertArchiveError("alert_archive_commit_invalid")
    return commit


def validate_alert_path(value: object) -> str:
    path = str(value or "").strip()
    if not _ALERT_PATH_RE.fullmatch(path):
        raise AlertArchiveError("alert_archive_path_invalid")
    return path


def validate_alert_sha256(value: object) -> str:
    digest = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise AlertArchiveError("alert_archive_sha256_invalid")
    return digest


def immutable_alert_url(commit: object, path: object) -> str:
    revision = validate_source_commit(commit)
    relative = validate_alert_path(path)
    return f"{ARCHIVE_RAW_BASE}/{revision}/site/data/{relative}"
