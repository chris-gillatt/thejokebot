# Repository agent instructions

- Use British English where possible, except where it would interfere with syntax.
- For GitHub issues, pull requests and repository metadata, use the GitHub API or `gh` CLI. Do not use a browser for these tasks. If API access fails, retry or report the access problem.

## Dependency check cadence

- For non-documentation implementation, first read the last completed dependency-check record in `problem-statement.md`. A completed check is reusable for 14 days; while it is current, do not ask again or rerun the broad audit merely because a new task starts or completes.
- If no completed check is recorded or it is 14 days old or older, ask "Shall we do a dependency check first?" and wait for the user's decision before investigation, planning or implementation. An agreed check includes applying compatible upgrades as a separate validated change, using [the dependency-check skill](.github/skills/dependency-check/SKILL.md).
- Record completion date, scope, evidence and exceptions. An attempted or partial audit does not reset the date. For date-only records, use Asia/Singapore calendar dates; a check dated 15 November is next due on 29 November.
- Still verify newly introduced dependencies, Actions, SDKs and tooling at implementation time. Investigate applicable security advisories and concrete compatibility failures when discovered; these targeted checks do not require restarting the broad audit.
- Agree an explicit owner and a concrete review date or named work trigger for any deferred check or upgrade. Documentation-only work remains exempt from dependency audits and executable validation.

## Completing any change

- Update [CHANGELOG.md](CHANGELOG.md) in the same substantive commit as every meaningful non-documentation first-party change. Omit documentation-only updates, planning notes and prose-only agent/process guidance; mixed-change entries should describe the delivered effect, not accompanying documentation edits. Use actual commit dates, newest first; never create or restore an `Unreleased` section. Preserve the pre-1.0.0 retrospective milestone numbers without claiming they were original releases. Verify applicable entries before committing and completing the task; follow the [changelog policy](.github/copilot-instructions.md#changelog-policy) for grouping, dates and automation exclusions.
- Every dated changelog section must retain a version heading in the form `## X.Y.Z - YYYY-MM-DD`; preserve existing historical month/year headings. Never add a date-only section. Extend an existing section for the same commit date; for a new date, continue the version sequence using a major increment for breaking changes, minor for backwards-compatible features, or patch for fixes, performance, configuration, workflows and dependencies. These are changelog milestones unless an actual release is verified: do not invent release tags or change package metadata solely to match them. Check chronological and version ordering before completing the change.
- For docs-only changes, including prose-only agent guidance, skip tests, preflight, builds, code lint/type checks, coverage, CodeQL/Sonar and dependency audits. Do not install validation tools, dispatch full CI or wait for full validation gates solely for docs. Review the text and links, confirm only documentation changed, run `git diff --check`, omit changelog entries, then rebase/push. Mixed code/configuration/workflow/dependency changes retain normal validation.

## Completing issue work

- When committing work for a GitHub issue, include its number in the substantive commit message before pushing (for example, `Closes #126` when the work fully resolves it). Verify the message with `git log -1 --format=%B` before pushing. Do not leave the issue link to a later empty commit.
- Follow the repository's pre-push sequence: run `./scripts/preflight-local.sh` for non-documentation work, or lightweight documentation review and `git diff --check` for docs-only work; rebase on the latest remote branch, then push. Verify the remote SHA. Monitor required checks for non-documentation work; do not force or wait for full validation gates solely for docs-only changes.
- When the work is complete and any required non-documentation checks pass, verify that the linked issue is closed as completed. Docs-only work does not require full validation gates. Close it with `gh issue close` if GitHub did not close it automatically, then verify its state through the API. Leave an issue open only if work remains or the user asks for that.
