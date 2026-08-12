"""Build a truthful, direct-dependency SBOM when Syft is unavailable."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "prstk-sbom.cdx.json"
REQUIREMENT_FILES = (ROOT / "requirements.txt", ROOT / "requirements-production.txt")


def _components() -> list[dict[str, str]]:
    seen: set[str] = set()
    components: list[dict[str, str]] = []
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)\s*(?:==|>=|<=|~=|>|<)?\s*([^;\s#]+)?")
    for file in REQUIREMENT_FILES:
        if not file.exists():
            continue
        for line in file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-")):
                continue
            match = pattern.match(line)
            if not match:
                continue
            name, version = match.group(1), match.group(2) or "unspecified"
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            components.append({"type": "library", "name": name, "version": version})
    return components


def main() -> None:
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "prstk-stock-detector"},
            "properties": [
                {"name": "prstk.sbom.fallback", "value": "true"},
                {
                    "name": "prstk.sbom.coverage",
                    "value": "declared-direct-dependencies-only",
                },
                {
                    "name": "prstk.sbom.reason",
                    "value": "Syft download unavailable; retry on next workflow run",
                },
            ],
        },
        "components": _components(),
    }
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
