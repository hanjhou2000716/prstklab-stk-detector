# Scheduled Creator records input

The scheduled briefing workflow supports an opt-in `CREATOR_RECORDS_PATH`
repository variable. When it is empty or the file is absent, the workflow
behaves exactly as before. When present, the file is passed to
`src.release_manifest --creator-records` only if it exists.

The file must be an already-sanitized JSON array (or `{ "records": [...] }`)
outside `site/`. The manifest CLI rejects paths inside the Pages tree, and the
Creator pipeline rechecks public-safe fields, source allow-list, and episode
deduplication before publication. The source file is therefore not uploaded
as a Pages artifact.

The variable is intentionally optional: Gmail/creator ingress remains a
separate private boundary, and an absent or failed optional source cannot
block the core market release or be interpreted as an empty event scan.
