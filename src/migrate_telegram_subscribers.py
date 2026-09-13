"""One-time, idempotent migration of the legacy Telegram recipient secret."""

from __future__ import annotations

import os
from pathlib import Path

import requests

from src.config import parse_chat_ids
from src.telegram_subscriptions import (
    TelegramMigrationResult,
    TelegramSubscriptionError,
    migrate_legacy_chat_ids_result,
)


def _write_summary(result: TelegramMigrationResult, *, workflow_sha: str, production_sha: str) -> None:
    """Write only safe migration metadata to the GitHub job summary."""
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    lines = [
        "## Telegram 訂閱遷移",
        "",
        f"- migration_status: `{result.migration_status}`",
        f"- prerequisite_status: `{result.prerequisite_status}`",
        f"- migrated_count: `{result.migrated_count}`",
        f"- reason: `{result.reason or 'none'}`",
        f"- workflow_sha: `{workflow_sha or 'unknown'}`",
        f"- production_sha: `{production_sha or 'unknown'}`",
        "",
    ]
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _write_outputs(result: TelegramMigrationResult, *, workflow_sha: str, production_sha: str) -> None:
    """Expose the safe status to a reusable GitHub workflow caller."""
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    lines = [
        f"migration_status={result.migration_status}",
        f"prerequisite_status={result.prerequisite_status}",
        f"migrated_count={result.migrated_count}",
        f"reason={result.reason or 'none'}",
        f"workflow_sha={workflow_sha or 'unknown'}",
        f"production_sha={production_sha or 'unknown'}",
    ]
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    workflow_sha = os.getenv("GITHUB_SHA", "").strip()
    production_sha = os.getenv("PRODUCTION_SHA", "").strip() or workflow_sha
    try:
        result = migrate_legacy_chat_ids_result(
            parse_chat_ids(os.getenv("TELEGRAM_CHAT_IDS")),
            editor_chat_id=os.getenv("TELEGRAM_EDITOR_CHAT_ID", "8869592162").strip() or "8869592162",
        )
    except TelegramSubscriptionError as exc:
        result = TelegramMigrationResult(
            migration_status="failed",
            prerequisite_status="failed",
            migrated_count=0,
            reason=str(exc),
        )
        _write_outputs(result, workflow_sha=workflow_sha, production_sha=production_sha)
        _write_summary(result, workflow_sha=workflow_sha, production_sha=production_sha)
        print(f"Telegram 訂閱遷移失敗：{exc}")
        return 1
    except requests.exceptions.RequestException:
        result = TelegramMigrationResult(
            migration_status="failed",
            prerequisite_status="failed",
            migrated_count=0,
            reason="telegram_subscription_request_failed",
        )
        _write_outputs(result, workflow_sha=workflow_sha, production_sha=production_sha)
        _write_summary(result, workflow_sha=workflow_sha, production_sha=production_sha)
        print("Telegram 訂閱遷移失敗：telegram_subscription_request_failed")
        return 1
    _write_outputs(result, workflow_sha=workflow_sha, production_sha=production_sha)
    _write_summary(result, workflow_sha=workflow_sha, production_sha=production_sha)
    if result.migration_status == "blocked_prerequisite":
        print(f"Telegram 訂閱遷移已安全略過：{result.reason or 'prerequisite_missing'}")
    elif result.migration_status == "already_applied":
        print(f"Telegram 訂閱遷移已完成；既有資料已核對，{result.reason or 'no_new_rows'}。")
    else:
        print(f"Telegram 訂閱遷移完成；新增或核對 {result.migrated_count} 筆，不重新啟用既有退訂。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
