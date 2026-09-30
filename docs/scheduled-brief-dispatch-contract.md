# Scheduled brief dispatch contract

Configure four enabled backup jobs. Keep notify=true and force=false.

| Slot | Time zone | Local time | Days |
| --- | --- | ---: | --- |
| morning | Asia/Taipei | 06:00 | Daily, including weekends |
| pre_open | Asia/Taipei | 08:45 | Monday-Friday |
| post_close | Asia/Taipei | 14:20 | Monday-Friday |
| us_premarket | America/New_York | 09:00 | Monday-Friday |

The receiver owns exchange holiday policy. The backup service must not infer
trading days, rewrite a slot after queueing, or extend a delivery window.
Delayed or retried requests retain the original slot identity and idempotency
key; after the fixed 30-minute window they may publish diagnostics but must not
notify.

Use POST and send a GitHub repository_dispatch event of type scheduled-brief.
Generate the body from src.schedule_contract.build_cron_job_dispatch_payload(slot).
New jobs use contract version 4 and this payload shape (replace slot and
time_zone for each configured job):

    {
      "event_type": "scheduled-brief",
      "client_payload": {
        "slot": "morning",
        "scheduled_slot": "morning",
        "dispatch_unix": "%cjo:unixtime%",
        "trace_id": "%cjo:uuid4%",
        "time_zone": "Asia/Taipei",
        "schedule_contract_version": "4",
        "trigger_kind": "cron-job.org",
        "notify": true,
        "force": false
      }
    }

The US job must use America/New_York. dispatch_unix is expanded at request
time and binds the dispatch to its original anchor. The receiver rejects
missing, malformed, future, cross-slot, or out-of-window dispatches. Delayed
runs preserve the original slot date; after 30 minutes they are publish-only.
The 15-minute post-slot audit reads the immutable receipt ledger and never
dispatches, repairs, or sends.

## Read-only receipt audit trigger

The same cron-job.org account may invoke the independent
`scheduled-brief-slot-audit.yml` workflow at these deadlines:

| Slot being audited | Audit time zone | Audit time |
| --- | --- | ---: |
| morning | Asia/Taipei | 06:45 daily |
| pre_open | Asia/Taipei | 09:30 Monday-Friday |
| post_close | Asia/Taipei | 15:05 Monday-Friday |
| us_premarket | America/New_York | 09:45 Monday-Friday |

Use the GitHub `POST /repos/{owner}/{repo}/dispatches` endpoint with event type
`scheduled-slot-receipt-audit` and a client payload containing the audited
slot plus `%cjo:unixtime%`. The audit receiver derives the fixed anchor date
from that dispatch timestamp in the slot's exchange time zone, validates that
the request arrived after the 45-minute audit deadline, and rejects a
cross-date timestamp. Optional `slot_date` and `scheduled_for_at` fields are
checked against that derived identity, never trusted as replacements for it.
If dispatch time is delayed over 12 hours and no explicit slot date is present,
the request is rejected as ambiguous. With an explicit date it remains bounded
to 72 hours. The receiver checks the exchange calendar and original anchor; it
does not send, dispatch a recovery run, or mutate the receipt ledger.

Example request body for the Taiwan pre-open audit:

    {
      "event_type": "scheduled-slot-receipt-audit",
      "client_payload": {
        "slot": "pre_open",
        "dispatch_unix": "%cjo:unixtime%",
        "trace_id": "%cjo:uuid4%"
      }
    }

The external caller's GitHub credential needs only repository-dispatch
permission (`contents:write` on a fine-grained token); the workflow itself is
restricted to `actions:read` and `contents:read` and has no Telegram sender or
Supabase service-role credentials.

For complete recipient verification, maintain these repository variables as
one independently reviewed recipient-set record:

- `SCHEDULED_RECIPIENT_HASHES`: comma-separated expected active recipient
  hashes (first 12 lowercase hex characters of SHA-256 over each configured
  chat ID; never store the chat IDs here).
- `SCHEDULED_RECIPIENT_SET_VERSION`: `recipients-<fingerprint>`, where
  `<fingerprint>` is the first 16 lowercase hex characters of SHA-256 over
  canonical JSON (sorted keys, compact separators) containing the sorted,
  de-duplicated lowercase hashes and normalized UTC effective timestamp. The
  code exposes `recipient_set_version(hashes, effective_at)` as the canonical
  calculation.
- `SCHEDULED_RECIPIENT_SET_EFFECTIVE_AT`: timezone-aware ISO-8601 timestamp
  (prefer UTC, for example `2026-09-30T00:00:00Z`) from which that exact list
  is valid. The audit verifies that the version fingerprint matches both the
  list and timestamp and blocks a slot earlier than this time rather than
  applying today's list retroactively.

Update the hash list, version, and effective time together whenever the active
subscriber set changes. Missing or malformed metadata fails closed. The audit
never falls back to `TELEGRAM_CHAT_IDS` or trusts the claim's own recipient set
as proof that all recipients were covered.

A backup job is externally verified only after its enabled state, timezone,
weekday selection, request body, authentication, and recent natural execution
are inspected in cron-job.org. Repository code cannot prove those settings.
If access is unavailable, report each item as unverified; CI success is not
evidence that the external scheduler is configured.

Legacy v2/v3 payloads remain readable under compatibility rules; new jobs must
use version 4.
