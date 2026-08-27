"""Compatibility import for the zero-cost report repository."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SOURCE = Path(__file__).parents[2] / "app" / "db" / "repository.py"
_SPEC = importlib.util.spec_from_file_location("prstk_app._repository_impl", _SOURCE)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - packaging error
    raise ImportError("report repository implementation is unavailable")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

RepositoryError = _MODULE.RepositoryError
SupabaseRepository = _MODULE.SupabaseRepository
InMemoryRepository = _MODULE.InMemoryRepository

__all__ = ["RepositoryError", "SupabaseRepository", "InMemoryRepository"]
