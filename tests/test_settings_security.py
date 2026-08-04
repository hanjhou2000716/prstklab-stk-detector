import pytest

from src.settings_contract import load_runtime_settings
from src.workflow_security_audit import audit_workflow


def test_runtime_settings_are_typed_and_secret_free():
    result = load_runtime_settings({"DASHBOARD_URL": "https://example.test", "FRESHNESS_MINUTES": "15"})
    assert result.freshness_minutes == 15
    with pytest.raises(ValueError):
        load_runtime_settings({"DASHBOARD_URL": "http://insecure"})


def test_workflow_audit_rejects_secret_logging():
    result = audit_workflow("permissions:\n  contents: read\nrun: echo ${{ secrets.TOKEN }}")
    assert result["status"] == "failed"
