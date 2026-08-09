import json
import subprocess
import sys

from src.system_dry_run import run_dry_run


def test_system_dry_run_is_fail_closed_and_traceable():
    result = run_dry_run()
    assert result["ok"] is True
    assert result["lifecycle"] == "pending_confirmation"
    assert result["deep_link"] == "ok"
    assert result["card_rendered"] is True
    assert result["card_dimensions"] == {"width": 1080, "height": 1350}
    assert result["photo_contract"] == {
        "mocked": True,
        "caption_valid": True,
        "dimensions_valid": True,
        "deep_link_valid": True,
        "delivery_status": "delivered" if result["renderer_available"] else "blocked",
        "release_id": "dry-release",
        "snapshot_id": "dry-snapshot",
    }


def test_system_dry_run_module_entrypoint_emits_json():
    completed = subprocess.run(
        [sys.executable, "-m", "src.system_dry_run"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["release_id"] == "dry-release"
