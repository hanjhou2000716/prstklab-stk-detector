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

For complete recipient verification, maintain one append-only JSON repository
variable, `SCHEDULED_RECIPIENT_SET_MANIFEST`. The current schema is
`scheduled-recipient-manifest-v1` with a `versions` array. Each version stores
only a fingerprinted version label, an effective UTC timestamp, and the sorted,
deduplicated 12-character recipient hashes; raw chat IDs and sending tokens
must never be included. The manifest parser validates the content fingerprint
and history ordering and selects the version effective at the original slot
anchor. This preserves prior recipient sets so a later subscriber change does
not rewrite historical audit expectations.

Use the read-only `initialize-scheduled-recipient-manifest.yml` workflow to
generate the sanitized value from the same active-subscription resolver used
by the sender. Review and set that single repository variable as a separate
administrative action; the initializer and audit workflow do not have variable
write permission. Missing, malformed, or not-yet-effective versions fail
closed. The audit never falls back to `TELEGRAM_CHAT_IDS` or trusts a claim's
own recipient list as proof that all expected recipients were covered.

A backup job is externally verified only after its enabled state, timezone,
weekday selection, request body, authentication, and recent natural execution
are inspected in cron-job.org. Repository code cannot prove those settings.
If access is unavailable, report each item as unverified; CI success is not
evidence that the external scheduler is configured.

Legacy v2/v3 payloads remain readable under compatibility rules; new jobs must
use version 4.
