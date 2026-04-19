# Copilot Instructions for The Joke Bot

## Language and Style
- Always use British English in prose, comments, commit messages, and documentation.
- Use US English only when required by programming syntax, API field names, protocol terms, or third-party interfaces.

## Change Discipline
- Prioritise focused, incremental changes that preserve the bot's existing behaviour unless a change request explicitly asks otherwise.
- Avoid speculative refactors.
- Capture out-of-scope ideas in `problem-statement.md` under a deferred backlog section rather than mixing them into active work.

## Git Commit Policy
- Use Conventional Commits for every commit subject line.
- Subject format: `<type>(<optional-scope>): <imperative summary>`.
- Every commit message must explain why the change is being made.
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

## Problem Statement Workflow
- Keep `problem-statement.md` current as the source of truth for scope, decisions, risks, and deferred work.
- Add TODOs and out-of-scope items there as they arise.
- Do not use `problem-statement-example.md` as a working source file.
