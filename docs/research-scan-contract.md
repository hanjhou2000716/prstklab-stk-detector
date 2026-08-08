# Research scan contract

Research artifacts now carry an explicit execution and publication contract.

| Field | Meaning |
| --- | --- |
| `scan_mode` | `production`, `smoke`, or `debug` execution intent |
| `scan_scope` | `full` for production, `bounded` for diagnostic runs |
| `universe_expected` | Records requested by all strategy sources |
| `universe_scanned` | Completed plus failed records observed in this run |
| `universe_completed` | Records with usable observations in this run |
| `publish_eligible` | Whether the run is allowed to enter the release pipeline |
| `production_eligible` | Full scope, all sources complete, and no failures |
| `blocking_reason` | A machine-readable explanation when production is not eligible |

Smoke and debug runs are diagnostic only. They may upload an Actions artifact
for inspection, but the workflow skips `data-release`, Pages publication, and
the Telegram consumer. This prevents a 30-row smoke scan or a failed local
parser from replacing the public research snapshot.

Production runs remain fail-closed: an incomplete or failed source is retained
in the report with its candidate state and blocking reason, but it cannot be
treated as a complete research universe. Existing releases remain available
until a valid production release replaces them.
