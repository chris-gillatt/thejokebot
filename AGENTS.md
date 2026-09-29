# Repository agent instructions

- Use British English where possible, except where it would interfere with syntax.
- For GitHub issues, pull requests and repository metadata, use the GitHub API or `gh` CLI. Do not use a browser for these tasks. If API access fails, retry or report the access problem.

## Completing issue work

- When committing work for a GitHub issue, include its number in the substantive commit message before pushing (for example, `Closes #126` when the work fully resolves it). Verify the message with `git log -1 --format=%B` before pushing. Do not leave the issue link to a later empty commit.
- Follow the repository's pre-push sequence: run `./scripts/preflight-local.sh`, rebase on the latest remote branch, then push. After the push, verify the remote SHA and monitor all checks for that SHA through the GitHub API or `gh` CLI until they finish.
- When the implementation is complete and remote checks pass, verify that the linked issue is closed as completed. Close it with `gh issue close` if GitHub did not close it automatically, then verify its state through the API. Leave an issue open only if work remains or the user asks for that.
