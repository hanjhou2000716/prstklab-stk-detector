# Scheduled brief dispatch contract

Production has four routine anchors, all in `Asia/Taipei`:

| Anchor | Taiwan time |
| --- | ---: |
| `morning` | 06:00 |
| `pre_open` | 08:45 |
| `post_close` | 14:20 |
| `us_premarket` | 21:00 |

The external backup scheduler must send a GitHub `repository_dispatch` with
event type `scheduled-brief` and this sanitized payload shape:

```json
{
  "event_type": "scheduled-brief",
  "client_payload": {
    "slot": "pre_open",
    "scheduled_slot": "pre_open",
    "scheduled_for_at": "2026-09-08T08:45:00+08:00",
    "time_zone": "Asia/Taipei",
    "schedule_contract_version": "2",
    "trigger_kind": "cron-job.org",
    "force": false
  }
}
```

`scheduled_for_at` is the original anchor time, not the retry time.  It must
include an explicit offset.  The receiver rejects missing or naive timestamps,
unknown/retired slots, a future time beyond five minutes, and a timestamp that
does not match the fixed anchor.  A valid run more than 30 minutes late only
refreshes Pages and records `late_schedule`.

An invalid dispatch still creates a publish-only diagnostic snapshot so the
failure is visible.  The workflow then fails with
`invalid_schedule_context:<reason>`; it does not send Telegram or consume a
formal delivery claim.  The external scheduler should treat that failure as a
contract/configuration incident, not as a successful no-change run.

The repository-side reference builder is
`src.schedule_contract.build_scheduled_dispatch_payload`.  It is intended to
keep the external cron-job.org configuration aligned with the GitHub receiver.
