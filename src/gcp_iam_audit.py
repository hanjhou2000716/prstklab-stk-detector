"""Read-only Google Cloud IAM checks for the Gmail Pub/Sub boundary."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_BROAD_ROLES = frozenset({"roles/owner", "roles/editor", "roles/viewer"})
_PUBLISH_ROLE = "roles/pubsub.publisher"


def _members(binding: dict[str, Any]) -> Iterable[str]:
    values = binding.get("members")
    if not isinstance(values, list):
        return ()
    return (str(member).strip() for member in values if str(member).strip())


def _bindings(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get("bindings"), list):
        return []
    return [item for item in document["bindings"] if isinstance(item, dict)]


def _principal_set(values: Iterable[str]) -> set[str]:
    return {str(value).strip() for value in values if str(value).strip()}


def audit_project_policy(
    document: dict[str, Any],
    *,
    protected_principals: Iterable[str] = (),
) -> dict[str, Any]:
    """Audit project IAM without making a policy mutation."""

    protected = _principal_set(protected_principals)
    findings: list[dict[str, str]] = []
    roles_by_principal: dict[str, list[str]] = {}
    for binding in _bindings(document):
        role = str(binding.get("role") or "").strip()
        if not role:
            continue
        for member in _members(binding):
            roles_by_principal.setdefault(member, []).append(role)
            if member in protected and role in _BROAD_ROLES:
                findings.append({"code": "broad_project_role", "principal": member, "role": role})

    return {
        "status": "fail" if findings else "pass",
        "findings": findings,
        "protected_principals": sorted(protected),
        "roles_by_principal": {key: sorted(set(value)) for key, value in sorted(roles_by_principal.items())},
        "policy_present": bool(_bindings(document)),
        "secret_values_exposed": False,
    }


def audit_topic_policy(document: dict[str, Any], *, publisher_principal: str) -> dict[str, Any]:
    """Require the Gmail push identity to publish through the topic IAM."""

    principal = str(publisher_principal or "").strip()
    matches = [
        binding
        for binding in _bindings(document)
        if str(binding.get("role") or "").strip() == _PUBLISH_ROLE
        and principal in set(_members(binding))
    ]
    return {
        "status": "pass" if principal and matches else "fail",
        "publisher_principal": principal,
        "publish_role": _PUBLISH_ROLE,
        "publisher_binding_present": bool(matches),
        "secret_values_exposed": False,
    }


def audit_documents(
    project_policy: dict[str, Any],
    *,
    protected_principals: Iterable[str] = (),
    topic_policy: dict[str, Any] | None = None,
    publisher_principal: str = "",
) -> dict[str, Any]:
    """Combine project and topic checks into one safe result."""

    project = audit_project_policy(project_policy, protected_principals=protected_principals)
    topic = (
        audit_topic_policy(topic_policy, publisher_principal=publisher_principal)
        if topic_policy is not None
        else {"status": "not_checked", "secret_values_exposed": False}
    )
    statuses = {project["status"], topic["status"]}
    status = "fail" if "fail" in statuses else "pass" if statuses == {"pass"} else "not_checked"
    return {"status": status, "project": project, "topic": topic, "secret_values_exposed": False}


def _main() -> int:
    parser = argparse.ArgumentParser(description="Audit Google Cloud IAM JSON without changing policy")
    parser.add_argument("project_policy", type=Path)
    parser.add_argument("--protected-principal", action="append", default=[])
    parser.add_argument("--topic-policy", type=Path)
    parser.add_argument("--publisher-principal", default="")
    args = parser.parse_args()
    project = json.loads(args.project_policy.read_text(encoding="utf-8"))
    topic = json.loads(args.topic_policy.read_text(encoding="utf-8")) if args.topic_policy else None
    result = audit_documents(
        project,
        protected_principals=args.protected_principal,
        topic_policy=topic,
        publisher_principal=args.publisher_principal,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] in {"pass", "not_checked"} else 1


if __name__ == "__main__":  # pragma: no cover - CLI wrapper
    raise SystemExit(_main())


__all__ = ["audit_documents", "audit_project_policy", "audit_topic_policy"]
