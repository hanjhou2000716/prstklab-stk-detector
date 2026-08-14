from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "railway-monitor" / "jin10_source.py"
SPEC = importlib.util.spec_from_file_location("railway_jin10_source_test", MODULE)
assert SPEC and SPEC.loader
source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source)


def test_default_arguments_only_use_advertised_limit():
    assert source.default_flash_arguments({"properties": {"limit": {}}}, 25) == {"limit": 25}
    assert source.default_flash_arguments({"properties": {}}, 25) == {}
    assert source.default_flash_arguments({}, 25) == {}
