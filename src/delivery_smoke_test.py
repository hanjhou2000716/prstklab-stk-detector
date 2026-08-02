"""Validate the Telegram -> GitHub -> Railway delivery configuration.

The default mode is a local dry-run: it never calls Telegram or Railway and
prints only non-secret counts/statuses.  Pass ``--send`` deliberately when a
real, 30-character smoke message is wanted.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from src.config import get_settings
from src.telegram_client import mini_app_button, send_briefs, summarize_deliveries, validate_brief


SMOKE_TEXT = "測試｜派送鏈路驗證"


def validate_delivery_configuration() -> dict[str, Any]:
    settings = get_settings()
    errors: list[str] = []
    legacy_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if legacy_chat_id:
        errors.append("TELEGRAM_CHAT_ID is deprecated; configure TELEGRAM_CHAT_IDS only")
    if not settings.telegram_chat_ids:
        errors.append("TELEGRAM_CHAT_IDS is empty")
    if not settings.dashboard_url.startswith("https://"):
        errors.append("DASHBOARD_URL must use HTTPS")
    try:
        validate_brief(SMOKE_TEXT)
        mini_app_button(settings.dashboard_url)
    except ValueError as error:
        errors.append(str(error))

    callback_url = os.environ.get("RAILWAY_STATUS_URL", "").strip()
    callback_secret = bool(os.environ.get("RAILWAY_STATUS_SHARED_SECRET", "").strip())
    if bool(callback_url) != callback_secret:
        errors.append("RAILWAY_STATUS_URL and RAILWAY_STATUS_SHARED_SECRET must be configured together")
    if callback_url and not callback_url.startswith("https://"):
        errors.append("RAILWAY_STATUS_URL must use HTTPS")

    return {
        "ok": not errors,
        "recipient_count": len(settings.telegram_chat_ids),
        "legacy_singular_configured": bool(legacy_chat_id),
        "dashboard_https": settings.dashboard_url.startswith("https://"),
        "callback_configured": bool(callback_url and callback_secret),
        "smoke_text_length": len(SMOKE_TEXT),
        "errors": errors,
    }


def run_smoke_test(*, send: bool = False) -> dict[str, Any]:
    report = validate_delivery_configuration()
    if not report["ok"] or not send:
        return report

    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        report["ok"] = False
        report["errors"] = ["TELEGRAM_BOT_TOKEN is empty"]
        return report
    deliveries = send_briefs(
        token=token,
        chat_ids=settings.telegram_chat_ids,
        text=SMOKE_TEXT,
        dashboard_url=settings.dashboard_url,
    )
    summary = summarize_deliveries(deliveries)
    report.update({
        "sent": True,
        "delivered_count": summary.delivered_count,
        "failed_count": summary.failed_count,
        "failed_recipient_count": len(summary.failed_recipient_hashes),
        "ok": summary.failed_count == 0,
    })
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="send one deliberate smoke message")
    args = parser.parse_args()
    report = run_smoke_test(send=args.send)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
