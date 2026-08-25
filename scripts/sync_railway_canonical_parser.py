"""Generate the canonical external-parser package for Railway's root image.

Railway currently builds from ``railway-monitor`` only.  This bundle is a
generated deployment artifact, not a second parser implementation: the
source modules and their ``config`` inputs are copied from the repository
canonical modules and CI verifies that the tracked bundle is current.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
RAILWAY_ROOT = ROOT / "railway-monitor"
TARGET_ROOT = RAILWAY_ROOT / "src"
CONFIG_FILES = ("creator_providers.json", "event_keywords.json")
SCHEMA_FILES = ("creator-providers.schema.json",)
ENTRYPOINT = "external_source_parsers.py"
HEADER = "# GENERATED FILE: do not edit manually.\n# Run scripts/sync_railway_canonical_parser.py to refresh it.\n"


def _module_closure() -> tuple[str, ...]:
    pending = [ENTRYPOINT]
    seen: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in seen:
            continue
        path = SOURCE_ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"canonical parser dependency is missing: {path}")
        seen.add(relative)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module: str | None = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import) and node.names:
                module = node.names[0].name
            if not module or not module.startswith("src."):
                continue
            dependency = Path(module.replace(".", "/") + ".py").relative_to("src")
            if (SOURCE_ROOT / dependency).is_file():
                pending.append(str(dependency))
    return tuple(sorted(seen))


def _render_module(relative: str) -> str:
    source = (SOURCE_ROOT / relative).read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return f"{HEADER}# Canonical source: src/{relative}\n# Canonical source SHA256: {digest}\n\n{source}"


def _expected() -> dict[Path, str]:
    expected: dict[Path, str] = {TARGET_ROOT / "__init__.py": HEADER}
    for relative in _module_closure():
        expected[TARGET_ROOT / relative] = _render_module(relative)
    config_root = ROOT / "config"
    target_config = RAILWAY_ROOT / "config"
    for name in CONFIG_FILES:
        source = config_root / name
        raw = source.read_text(encoding="utf-8")
        payload = json.loads(raw)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        expected[target_config / name] = serialized
        # The root-only Railway image has a compatibility import path when the
        # generated ``src`` package cannot be imported.  Keep those fallback
        # files generated from the exact same canonical payload instead of
        # leaving an unmanaged second provider/keyword table.
        expected[RAILWAY_ROOT / name] = raw if raw.endswith("\n") else raw + "\n"
    target_schemas = RAILWAY_ROOT / "schemas"
    for name in SCHEMA_FILES:
        source = ROOT / "schemas" / name
        raw = source.read_text(encoding="utf-8")
        expected[target_schemas / name] = raw if raw.endswith("\n") else raw + "\n"
    return expected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when the generated bundle is stale")
    args = parser.parse_args()
    expected = _expected()
    actual_paths = {path for path in TARGET_ROOT.rglob("*.py") if path.is_file()} if TARGET_ROOT.exists() else set()
    actual_paths |= {path for path in (RAILWAY_ROOT / "config").glob("*.json") if path.is_file()}
    actual_paths |= {RAILWAY_ROOT / name for name in CONFIG_FILES if (RAILWAY_ROOT / name).is_file()}
    actual_paths |= {RAILWAY_ROOT / "schemas" / name for name in SCHEMA_FILES if (RAILWAY_ROOT / "schemas" / name).is_file()}
    if args.check:
        if any(not path.is_file() or path.read_text(encoding="utf-8") != content for path, content in expected.items()):
            print("railway canonical parser bundle is stale")
            return 1
        if actual_paths != set(expected):
            print("railway canonical parser bundle has unexpected or missing files")
            return 1
        return 0
    for path, content in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    for stale in actual_paths - set(expected):
        stale.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
