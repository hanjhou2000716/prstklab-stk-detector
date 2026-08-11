from __future__ import annotations

from src.production_e2e import _ready_bundle, run_offline_e2e


def test_ready_fixture_passes_all_offline_gates():
    report = run_offline_e2e(
        dry_run=lambda: {
            "ok": True,
            "renderer_available": True,
            "card_dimensions": {"width": 1080, "height": 1350},
            "photo_contract": {"dimensions_valid": True, "deep_link_valid": True, "observation_id": "obs-e2e", "delivery_status": "delivered"},
        },
        delivery_check=lambda **_: {"ok": True, "recipient_count": 1, "errors": []},
    )
    assert report["ok"] is True
    assert all(report["checks"].values())


def test_renderer_failure_is_reported_and_blocks_acceptance():
    report = run_offline_e2e(
        dry_run=lambda: {
            "ok": True,
            "renderer_available": False,
            "card_dimensions": {"width": 1080, "height": 1350},
            "photo_contract": {"dimensions_valid": True, "deep_link_valid": True, "delivery_status": "blocked"},
        },
        delivery_check=lambda **_: {"ok": True, "recipient_count": 1, "errors": []},
    )
    assert report["ok"] is False
    assert report["checks"]["offline_pipeline"] is False


def test_ready_fixture_has_complete_research_contract():
    bundle = _ready_bundle()
    assert bundle["research"]["scan_mode"] == "production"
    assert bundle["research"]["universe_completed"] == bundle["research"]["universe_expected"]
