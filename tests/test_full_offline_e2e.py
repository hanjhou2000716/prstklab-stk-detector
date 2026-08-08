from src.full_offline_e2e import run_full_offline_e2e


def test_full_offline_e2e_composes_release_and_photo_delivery():
    result = run_full_offline_e2e()
    assert result["ok"] is True
    assert result["delivered_count"] == 2
    assert result["file_id_reused"] is True
    assert result["network_calls_mocked"] == 2
