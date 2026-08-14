"""Test import shim for the standalone ``railway-monitor`` directory."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_path = Path(__file__).with_name("railway-monitor") / "runtime_config.py"
_spec = spec_from_file_location("_railway_runtime_config", _path)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load {_path}")
_module = module_from_spec(_spec)
_spec.loader.exec_module(_module)

configuration_health = _module.configuration_health
delivery_shared_secret = _module.delivery_shared_secret

__all__ = ["configuration_health", "delivery_shared_secret"]
