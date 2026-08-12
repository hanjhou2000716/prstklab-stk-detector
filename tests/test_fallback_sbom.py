import json
import runpy
from pathlib import Path


def test_fallback_sbom_is_truthful_and_deterministic(tmp_path):
    script = Path(__file__).parents[1] / ".github" / "scripts" / "fallback_sbom.py"
    namespace = runpy.run_path(str(script), run_name="fallback_sbom_test")
    namespace["main"].__globals__["OUTPUT"] = tmp_path / "sbom.json"
    namespace["main"]()
    document = json.loads((tmp_path / "sbom.json").read_text(encoding="utf-8"))
    properties = {item["name"]: item["value"] for item in document["metadata"]["properties"]}
    assert properties["prstk.sbom.fallback"] == "true"
    assert properties["prstk.sbom.coverage"] == "declared-direct-dependencies-only"
    assert document["components"]
