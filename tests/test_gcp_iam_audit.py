from __future__ import annotations

from src.gcp_iam_audit import (
    DEFAULT_GMAIL_PUBLISHER_PRINCIPAL,
    audit_documents,
    audit_project_policy,
    audit_topic_policy,
)


def test_documented_gmail_publisher_identity_is_the_cli_default() -> None:
    assert DEFAULT_GMAIL_PUBLISHER_PRINCIPAL == (
        "serviceAccount:gmail-api-push@system.gserviceaccount.com"
    )


def test_project_policy_flags_editor_for_protected_runtime_identity() -> None:
    result = audit_project_policy(
        {"bindings": [{"role": "roles/editor", "members": ["serviceAccount:calendar-reader@demo.iam.gserviceaccount.com"]}]},
        protected_principals=["serviceAccount:calendar-reader@demo.iam.gserviceaccount.com"],
    )
    assert result["status"] == "fail"
    assert result["findings"][0]["code"] == "broad_project_role"


def test_topic_policy_requires_pubsub_publisher() -> None:
    result = audit_topic_policy(
        {"bindings": [{"role": "roles/pubsub.publisher", "members": ["serviceAccount:prstk@demo.iam.gserviceaccount.com"]}]},
        publisher_principal="serviceAccount:prstk@demo.iam.gserviceaccount.com",
    )
    assert result["status"] == "pass"


def test_combined_audit_is_not_pass_without_topic_evidence() -> None:
    result = audit_documents(
        {"bindings": [{"role": "roles/pubsub.viewer", "members": ["serviceAccount:prstk@demo.iam.gserviceaccount.com"]}]},
        protected_principals=["serviceAccount:prstk@demo.iam.gserviceaccount.com"],
        publisher_principal="serviceAccount:prstk@demo.iam.gserviceaccount.com",
    )
    assert result["status"] == "not_checked"
    assert result["secret_values_exposed"] is False
