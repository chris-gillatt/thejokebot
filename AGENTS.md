# Repository agent instructions

- Use British English where possible, except where it would interfere with syntax.
- For GitHub issues, pull requests and repository metadata, use the GitHub API or `gh` CLI. Do not use a browser for these tasks. If API access fails, retry or report the access problem.

## Completing any change

- Update [CHANGELOG.md](CHANGELOG.md) in the same substantive commit as every meaningful first-party change, including documentation and process changes. Use actual commit dates, newest first; never create or restore an `Unreleased` section. Preserve the pre-1.0.0 retrospective milestone numbers without claiming they were original releases. Verify the entry before committing and completing the task; follow the [changelog policy](.github/copilot-instructions.md#changelog-policy) for grouping, dates and automation exclusions.
- For docs-only changes, including prose-only agent guidance, skip tests, preflight, builds, code lint/type checks, coverage, CodeQL/Sonar and dependency audits. Do not install validation tools, dispatch full CI or wait for full validation gates solely for docs. Review the text and links, confirm only documentation changed, run `git diff --check`, update the changelog, then rebase/push. Mixed code/configuration/workflow/dependency changes retain normal validation.

## Completing issue work

- When committing work for a GitHub issue, include its number in the substantive commit message before pushing (for example, `Closes #126` when the work fully resolves it). Verify the message with `git log -1 --format=%B` before pushing. Do not leave the issue link to a later empty commit.
- Follow the repository's pre-push sequence: run `./scripts/preflight-local.sh` for non-documentation work, or lightweight documentation review and `git diff --check` for docs-only work; rebase on the latest remote branch, then push. Verify the remote SHA. Monitor required checks for non-documentation work; do not force or wait for full validation gates solely for docs-only changes.
- When the work is complete and any required non-documentation checks pass, verify that the linked issue is closed as completed. Docs-only work does not require full validation gates. Close it with `gh issue close` if GitHub did not close it automatically, then verify its state through the API. Leave an issue open only if work remains or the user asks for that.
