"""Bounded atomic file replacement for transient Windows/OneDrive locks."""

from __future__ import annotations

import errno
import time
from pathlib import Path

# Windows/OneDrive scanners can hold a just-written file for several seconds.
# Keep the retry bounded while allowing the normal publication path to recover.
FILE_RETRY_ATTEMPTS = 6
RETRYABLE_FILE_ERRNOS = frozenset({errno.EACCES, errno.EBUSY, errno.EPERM, errno.ETXTBSY})


def replace_with_retry(temporary: Path, destination: Path) -> None:
    """Publish a temporary file atomically, retrying short-lived OS locks."""
    for attempt in range(FILE_RETRY_ATTEMPTS):
        try:
            temporary.replace(destination)
            return
        except OSError as exc:
            if exc.errno not in RETRYABLE_FILE_ERRNOS or attempt == FILE_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(0.1 * (2**attempt))
