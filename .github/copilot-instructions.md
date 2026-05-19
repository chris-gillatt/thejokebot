# Copilot Instructions for The Joke Bot

## Language and Style
- Always use British English in prose, comments, commit messages, and documentation.
- Use US English only when required by programming syntax, API field names, protocol terms, or third-party interfaces.

## Change Discipline
- Prioritise focused, incremental changes that preserve the bot's existing behaviour unless a change request explicitly asks otherwise.
- Avoid speculative refactors.
- Capture out-of-scope ideas in `problem-statement.md` under a deferred backlog section rather than mixing them into active work.

## Version Currency Policy
- For any newly introduced workflow element, GitHub Action, dependency, SDK, or tooling reference, always check and use the latest stable available version at implementation time.
- If the latest version is not used, include an explicit justification in the change notes (for example known vulnerability, incompatibility, upstream regression, or required temporary workaround).
- Treat unverified or stale versions as technical debt; do not introduce them by default.

## Git Commit Policy
- Use Conventional Commits for every commit subject line.
- Subject format: `<type>(<optional-scope>): <imperative summary>`.
- Every commit message must explain why the change is being made.
- When a commit resolves a tracked GitHub issue, include a closing keyword in the commit body (for example `Closes #38` or `Resolves #15`). This allows GitHub to automatically close the issue when the commit lands on the default branch.
- Keep unrelated changes in separate commits.
- Before any `git push`, sync with the remote first (`git pull --rebase` unless there is a deliberate reason not to) because the bot's GitHub Actions workflows can update the branch between local changes and push time.

## Validation Expectations
- Run relevant checks before finishing a task (script run, lint, or targeted tests where available).
- Report what was verified and what could not be verified.

## Terminal Command Workflow
- Avoid heredocs for shell commands and file generation to reduce interruption-related issues.
- Prefer temporary files inside `.agent-tmp/` for intermediate command input.
- Keep `.agent-tmp/` out of commits except for `.agent-tmp/.gitkeep`.
- Treat `git pull --rebase` before `git push` as the default terminal workflow for this repository unless the user explicitly asks for a different git strategy.

## References Directory Policy
- The `references/` directory contains read-only external resources (submodules, documentation, cookbooks).
- Never make changes to content within `references/`. All content is considered read-only.
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
