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

A backup job is externally verified only after its enabled state, timezone,
weekday selection, request body, authentication, and recent natural execution
are inspected in cron-job.org. Repository code cannot prove those settings.
If access is unavailable, report each item as unverified; CI success is not
evidence that the external scheduler is configured.

Legacy v2/v3 payloads remain readable under compatibility rules; new jobs must
use version 4.