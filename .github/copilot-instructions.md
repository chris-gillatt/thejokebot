# Copilot Instructions for The Joke Bot

## Language and Style
- Always use British English in prose, comments, commit messages, and documentation.
- Use US English only when required by programming syntax, API field names, protocol terms, or third-party interfaces.

## Change Discipline
- Prioritise focused, incremental changes that preserve the bot's existing behaviour unless a change request explicitly asks otherwise.
- Avoid speculative refactors.
- Capture out-of-scope ideas in `problem-statement.md` under a deferred backlog section rather than mixing them into active work.

## Changelog Policy
- Update [CHANGELOG.md](../CHANGELOG.md) in the same substantive commit as every meaningful first-party change, including features, fixes, configuration, workflows, dependencies, documentation and project processes. Check this before committing and before declaring the task complete.
- Describe the delivered effect and breaking changes, group related work under actual commit dates, and keep the newest progress first. Never create or restore an `Unreleased` section. Use verified package versions only where relevant; otherwise use dated milestones, not invented releases. Link existing commits or issues when backfilling.
- Omit routine automated state/metrics refreshes and issue-link-only commits. Author-filtered history is a starting point, not a reason to omit meaningful agent or Dependabot changes.

## Version Currency Policy
- For any newly introduced workflow element, GitHub Action, dependency, SDK, or tooling reference, always check and use the latest stable available version at implementation time.
- If the latest version is not used, include an explicit justification in the change notes (for example known vulnerability, incompatibility, upstream regression, or required temporary workaround).
- Treat unverified or stale versions as technical debt; do not introduce them by default.
- Before completing each non-documentation issue, sprint, or coherent batch of work, check all first-party dependency ecosystems (Python, npm, and GitHub Actions) against authoritative upstream sources or current Dependabot results. Skip dependency audits for docs-only changes.
- Update stale dependencies in a separate focused change, or record each deliberate exception with its current version, latest stable version, reason, and review trigger in `problem-statement.md`.

## Git Commit Policy
- Use Conventional Commits for every commit subject line.
- Subject format: `<type>(<optional-scope>): <imperative summary>`.
- Every commit message must explain why the change is being made.
- When a commit resolves a tracked GitHub issue, include a closing keyword in the commit body (for example `Closes #38` or `Resolves #15`). This allows GitHub to automatically close the issue when the commit lands on the default branch.
- Keep unrelated changes in separate commits.
- Before any `git push`, run the relevant validation as a separate command, then sync with the remote (`git pull --rebase` unless there is a deliberate reason not to), and only then push. For docs-only changes, use the lightweight documentation review below instead of preflight or full CI gates. The bot's GitHub Actions workflows can update the branch while local checks run.
- Do not install or rely on a Git pre-push hook for validation; it makes the push operation stale and difficult to recover when automation updates the remote branch.

## Validation Expectations
- Docs-only changes, including prose-only agent instructions and process documentation, must not run tests, preflight, builds, code lint/type checks, coverage, CodeQL, Sonar or dependency audits. Do not install validation dependencies, manually dispatch full CI, or wait for full test/analysis gates solely for documentation. Review wording, links and formatting, confirm the diff is docs-only, and use `git diff --check`; retain changelog updates and the rebase/push sequence. Allow existing automatic docs-only CI skips.
- Changes to executable code, runtime configuration, workflows, dependency manifests/locks or dashboard application assets are not docs-only, even when accompanied by documentation. Run their normal relevant validation.
- Report which checks were run or deliberately skipped under the docs-only rule. For non-documentation work, report dependency currency alongside code validation, including any deferred upgrades and their recorded justification.
- Report what was verified and what could not be verified.
- Treat zero unresolved Sonar issues as a repository quality rule. A passing quality gate alone is insufficient; after analysis, verify that the unresolved issue total is exactly zero.
- Treat posting telemetry, `bot_state.json` provider fields, dashboard metrics JSON, and dashboard rendering as one cross-file contract. Changes to any part must include producer-to-collector tests and local desktop/mobile dashboard verification.

## SonarQube Cloud Workflow
- Use the `sonar-quality` project skill for Sonar configuration, local scans, quality-gate failures, coverage import, and finding remediation.
- Keep `sonar-project.properties` as the scanner source of truth and keep automatic analysis disabled.
- Never expose `SONAR_TOKEN` or analyse `references/**`. When analysis is required for non-documentation work, require both a passing quality gate and the expected unresolved issue count; docs-only changes require no scan or coverage regeneration.
- Generate fresh Python coverage with `--cov=.` before scanning; an empty Cobertura `<source>` makes Sonar report 0% coverage.

## Terminal Command Workflow
- Avoid heredocs for shell commands and file generation to reduce interruption-related issues.
- Prefer temporary files inside `.agent-tmp/` for intermediate command input.
- Keep `.agent-tmp/` out of commits except for `.agent-tmp/.gitkeep`.
- For non-documentation work, use `./scripts/preflight-local.sh`, then `git pull --rebase`, then `git push`. For docs-only work, use lightweight documentation review and `git diff --check`, then rebase and push; do not run preflight or force full CI.

## References Directory Policy
- The `references/` directory contains read-only external resources (submodules, documentation, cookbooks).
- Never make changes to content within `references/`. All content is considered read-only.
- Do not enable automated dependency updates for reference submodules or proactively update their pinned revisions. Refresh a reference only when the user explicitly requests it; upstream maintenance belongs to the owning project.
- Exclude `references/**` from every first-party test, coverage, lint, static-analysis, and editor-analysis configuration. Validate new quality tools against first-party files only.
- Only pull in updates from upstream sources. Changes should only flow in one direction: from upstream → local.
- If any changes appear pending in submodules under `references/`, clear them immediately using:
  - `git restore references/`
  - `git submodule update --init --recursive`
  - `git -C references/<submodule> clean -fd && git -C references/<submodule> reset --hard`
- If you detect drift in `references/`, reset to committed state before proceeding with other work.

## Problem Statement Workflow
- Keep `problem-statement.md` current as the source of truth for scope, decisions, risks, and deferred work.
- Add TODOs and out-of-scope items there as they arise.
- Do not use `problem-statement-example.md` as a working source file.
