# Canonical public release publisher

Production workflows use `python -m src.canonical_release_publisher` for
market, event and research releases. The command is the boundary between
producers and the public Pages artifact:

1. Build the release manifest from the three public artifacts.
2. Persist the manifest atomically and require `status=ready`.
3. Re-run the local schema, provenance, hash and cross-artifact release gate.
4. Publish the selected immutable paths to `data-release`.
5. Re-check the local release gate before allowing downstream Pages delivery.

The publisher never deploys Pages and never sends Telegram. Those steps remain
separate, so a failed publication cannot be mistaken for a deliverable alert.
`--dry-run` performs the manifest and gate checks without pushing a branch.

```bash
python -m src.canonical_release_publisher \
  --branch data-release \
  --include site/data \
  --dry-run
```

If the manifest is invalid, the command exits non-zero and reports a bounded
reason such as `manifest_invalid` or `local_release_gate_failed`. It does not
invent missing market, event or research data. The existing `main-data-writer`
workflow concurrency group serializes writers to the immutable branch; Pages
propagation and the public release gate remain required before notification.
