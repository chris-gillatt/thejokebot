# Development Rules Template

Use this file as a starting point for other repositories.

## Language and Style
- Use British English in documentation, comments, and commit messages.
- Use US English only where required by code syntax, API field names, protocol terms, or third-party interfaces.

## Change Discipline
- Keep changes focused and incremental.
- Avoid speculative refactors.
- Track out-of-scope work in a problem statement backlog instead of mixing it into active changes.

## Git Commit Policy
- Use Conventional Commits for every commit subject line.
- Subject format: `<type>(<optional-scope>): <imperative summary>`.
- Include why in every commit message body.
- Separate unrelated work into separate commits.

## Validation Expectations
- Run relevant checks before finishing a task.
- Report what was verified and what could not be verified.

## Terminal Command Workflow
- Avoid heredocs for shell commands and file generation.
- Prefer intermediate files under a dedicated ignored directory (for example, `.agent-tmp/`).
- Keep that directory committed as empty via `.gitkeep` only.

## Problem Statement Workflow
- Maintain a `problem-statement.md` as the active source of scope, decisions, risks, and deferred work.
- Keep TODOs and deferred backlog entries current.
