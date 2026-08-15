# Creator release on `refresh-dashboard`

`refresh-dashboard` now passes the reviewed, privacy-safe
`creator/public-records.json` input to the same `src.release_manifest` builder
used by the scheduled brief. This removes the previous split where the public
market refresh produced `creator_status=not_available` even though the
Creator contract and Mini App renderer were already present.

The input is optional and remains fail-soft:

- Missing input does not block the market release.
- Records are still filtered by the Creator parser/privacy contract.
- Historical records are rendered as history; they are not reclassified as a
  current-day morning batch.
- Creator failures cannot invalidate the market/event release.
- Telegram remains release-gated and is not enabled by this workflow.

After a refresh, verify `creator_status`, `creator_public_status`,
`creator_snapshot_id`, and `creator_public_artifact_hash` in the public release
manifest, then run the public release smoke check before any notification lane.
