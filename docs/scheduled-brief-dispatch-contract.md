# Scheduled brief dispatch contract

Production has four routine anchors, all in `Asia/Taipei`:

| Anchor | Taiwan time |
| --- | ---: |
| `morning` | 06:00 |
| `pre_open` | 08:45 |
| `post_close` | 14:20 |
| `us_premarket` | 21:00 |

The external backup scheduler must send a GitHub `repository_dispatch` with
event type `scheduled-brief` and this sanitized version 3 payload shape:

```json
{
  "event_type": "scheduled-brief",
  "client_payload": {
    "slot": "pre_open",
    "scheduled_slot": "pre_open",
    "dispatch_unix": "%cjo:unixtime%",
    "trace_id": "%cjo:uuid4%",
    "time_zone": "Asia/Taipei",
    "schedule_contract_version": "3",
    "trigger_kind": "cron-job.org",
    "notify": true,
    "force": false
  }
}
```

`dispatch_unix` is expanded by cron-job.org at request time and is used to
validate the dispatch window.  The receiver derives `scheduled_for_at` from
the fixed slot and local date, so a retry does not become a new report time.
It rejects missing or invalid dispatch timestamps, unknown/retired slots, a
future time beyond five minutes, and dispatches past the next anchor.  A valid
run more than 30 minutes late only refreshes Pages and records
`late_schedule`.

Version 2 remains readable when it contains a complete, timezone-aware
`scheduled_for_at`; an incomplete legacy payload is still rejected.

An invalid dispatch still creates a publish-only diagnostic snapshot so the
failure is visible.  The workflow then fails with
`invalid_schedule_context:<reason>`; it does not send Telegram or consume a
formal delivery claim.  The external scheduler should treat that failure as a
contract/configuration incident, not as a successful no-change run.

The repository-side reference builder is
`src.schedule_contract.build_cron_job_dispatch_payload`.  The legacy
`build_scheduled_dispatch_payload` helper remains available for complete v2
payloads so existing audit fixtures can be read without rewriting history.
