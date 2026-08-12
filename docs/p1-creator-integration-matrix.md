# Creator integration status

The creator path is now production-integrated for sanitized public records:

1. The scheduled worker reads an optional external `CREATOR_RECORDS_PATH`.
2. The same records are attached to the market snapshot and briefing.
3. The manifest builder creates `creator-release.json` bound to the parent
   market/event snapshots and includes its input hash in the release identity.
4. Release validation and the Mini App loader reject mismatched lineage.

Private email bodies, attachments, local paths, private URLs and credentials
remain outside the public artifact and Telegram path. Creator media remains
`partially_integrated` because only sanitized availability/hash metadata is
allowed in the public release.
