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


def test_offline_e2e_uses_mock_delivery_without_production_recipients(monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_IDS", raising=False)
    report = run_offline_e2e(
        dry_run=lambda: {
            "ok": True,
            "renderer_available": True,
            "card_dimensions": {"width": 1080, "height": 1350},
            "photo_contract": {
                "dimensions_valid": True,
                "deep_link_valid": True,
                "observation_id": "obs-e2e",
                "delivery_status": "delivered",
            },
        }
    )
    assert report["ok"] is True
    assert report["telegram"]["mocked"] is True


def test_offline_e2e_exposes_creator_delivery_contract():
    report = run_offline_e2e(
        dry_run=lambda: {
            "ok": True,
            "renderer_available": True,
            "card_dimensions": {"width": 1080, "height": 1350},
            "photo_contract": {
                "dimensions_valid": True,
                "deep_link_valid": True,
                "observation_id": "obs-e2e",
                "delivery_status": "delivered",
            },
        },
        delivery_check=lambda **_: {"ok": True, "recipient_count": 1, "errors": []},
    )
    assert report["checks"]["creator_delivery_contract"] is True
    assert report["creator_delivery"]["notification_key"].startswith("creator:production-e2e-creator-episode:")
    assert report["checks"]["creator_release_contract"] is True
    assert report["creator_release"]["insight_count"] == 0


def test_offline_e2e_exercises_compound_financialjuice_and_morning_batch_lanes():
    report = run_offline_e2e(
        dry_run=lambda: {
            "ok": True,
            "renderer_available": True,
            "card_dimensions": {"width": 1080, "height": 1350},
            "photo_contract": {
                "dimensions_valid": True,
                "deep_link_valid": True,
                "observation_id": "obs-e2e",
                "delivery_status": "delivered",
            },
        },
        delivery_check=lambda **_: {"ok": True, "recipient_count": 1, "errors": []},
    )
    assert report["checks"]["financialjuice_compound_lane"] is True
    assert report["checks"]["creator_morning_batch_lane"] is True
    assert report["financialjuice_lane"]["item_count"] == 2
    assert report["financialjuice_lane"]["independent_cluster_count"] == 2
    assert report["financialjuice_lane"]["eligible_importances"] == [9]
    assert report["financialjuice_lane"]["below_threshold_importances"] == [7]
    assert report["financialjuice_lane"]["vendor_risk_separation"] is True
    assert report["creator_morning_batch"]["received_count"] == 2
