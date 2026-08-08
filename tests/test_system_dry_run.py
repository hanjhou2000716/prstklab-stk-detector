from src.system_dry_run import run_dry_run


def test_system_dry_run_is_fail_closed_and_traceable():
    result = run_dry_run()
    assert result["ok"] is True
    assert result["lifecycle"] == "pending_confirmation"
    assert result["deep_link"] == "ok"
