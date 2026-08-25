# Creator media runtime contract

Creator attachments remain private, but existence under the configured media
root is not treated as proof that a file is sendable.  The dispatch boundary
now validates every candidate before calling Telegram:

1. the filename is derived from the episode key and remains inside the media
   root;
2. the file is within the shared maximum size;
3. the MIME type is allowed and its magic bytes match;
4. only a `private_ready` result crosses into the photo sender.

Invalid, empty, oversized, or mismatched files take the existing text-only
degradation path.  No invalid bytes, local path, or private URL is written to
the public artifact.  A valid attachment remains bound to the episode and
release by the existing receipt/hash contract.

## Rollback

Revert the dispatch validation commit to restore the previous file-existence
check.  The release and Telegram gates remain unchanged; rollback does not
publish the private media root.
