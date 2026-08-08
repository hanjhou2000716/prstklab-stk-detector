# GitHub Actions action pinning

Every third-party GitHub Action used by a workflow or a composite action is
pinned to a full 40-character commit SHA. Mutable tags such as `@v4` and
`@main` are not accepted because they can change the code executed by a future
release without a repository diff.

The pin comments next to the action references identify the upstream release
that was resolved when the pin was added. Updating an action is an explicit
change: resolve the new release tag to its commit, update the SHA, run the
workflow/security tests, and record the change in the PR. Repository-local
composite actions (`./.github/actions/...`) remain path references and are
reviewed as repository code.

The test `test_every_external_workflow_action_is_sha_pinned` scans all workflow
and composite-action YAML files, not just the quality and security workflows.
This keeps scheduled data collection, Pages publishing, Telegram delivery and
research scans under the same supply-chain rule.
