"""Provider-specific configuration built on the shared JSON adapter."""

from src.adapters.catalog import ADAPTER_CATALOG, build_adapter, build_adapter_catalog

__all__ = ["ADAPTER_CATALOG", "build_adapter", "build_adapter_catalog"]
