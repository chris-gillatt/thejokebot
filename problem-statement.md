# The Joke Bot – Problem Statement (Working Draft v0.1)

## 1. Background
This repository automates posting jokes to Bluesky and includes supporting follower-management scripts. It has been running for around a year and remains functional, but it was produced with older tooling and has grown without a formal long-term maintenance process.

A key objective for the next phase is to reduce regressions and circular rework by enforcing clear rules, explicit scope control, and durable decision tracking.

## 2. Problem
The project lacks a formal operating framework for iterative development. As a result:
- Changes can drift out of scope.
- Decisions and failed approaches are not always captured.
- Regressions are easier to introduce when revisiting old areas.

## 3. Goal
Create a disciplined, low-risk development workflow that preserves core bot behaviour while enabling focused modernisation over time.

## 4. In Scope (Current Phase)
- Establish project development rules and references.
- Introduce a durable, maintained problem statement document.
- Set up local environment scaffolding for safe testing (`.env` + `.env.example`).
- Add a local shallow reference repository for Bluesky docs.

## 5. Out of Scope (Current Phase)
- Behavioural changes to posting/following logic.
- Large refactors of production scripts.
- API strategy changes beyond documentation and planning.

## 6. Working Rules
- Use British English in prose and documentation where possible.
- Use Conventional Commits for all commits.
- Commit messages must include why the change was made.
- Keep changes focused; defer non-critical ideas to Section 12.
- Avoid heredocs in terminal workflows; prefer temporary files in `.agent-tmp/`.

## 7. Constraints and Assumptions
- Core functionality (joke posting cadence and intent) must remain intact during modernisation.
- The project is automation-first (GitHub Actions + script execution).
- Secrets must never be committed.
- Existing GitHub Actions runtime contracts must be preserved unless deliberately changed and documented.
- In practice this means script entry points, workflow file expectations, and required environment variable names such as `BLUESKY_PASSWORD` and `BLUESKY_USERNAME` should not be changed casually, because continuity depends on them.

## 8. Known Risks
1. Dependency drift due to unpinned package installation in workflows.
2. Regression risk when modernising API calls without a test baseline.
3. Scope creep while touching multiple scripts in one pass.

## 9. Immediate TODOs
1. Confirm and document a minimal maintenance workflow for this repository.
2. Build an agreed phased implementation plan from the current findings.
3. Execute phase 1 hardening changes only after approval.
4. Add lightweight verification checks as changes land.

## 10. Success Criteria for This Governance Setup
- Rules are committed and visible to future contributors and AI agents.
- A project-specific problem statement is in place and actively usable.
- Local environment setup is reproducible without exposing credentials.
- Bluesky reference docs are available locally for implementation decisions.

## 11. Definition of Done (for this setup task)
- `problem-statement.md` exists with clear scope and TODO/deferred sections.
- Copilot/project instruction rules are added to the repository.
- `.env` is ignored and `.env.example` is committed with key names only.
- Bluesky docs reference repository exists under `references/` as a shallow submodule.

## 12. Deferred Backlog (Post-Setup)
- Full dependency and workflow normalisation.
- Shared auth/config utility module.
- API usage modernisation for follow/unfollow scripts.
- Dry-run and additional test coverage for bot workflows.
- Structured logging and stronger pagination/network safeguards.

### 12.1 Unfollow Re-Engagement Guardrail (Deferred)

Requirement summary:
- Do not repeatedly follow and unfollow the same accounts.
- Keep a persistent record of accounts the bot has unfollowed.
- An account should remain excluded from auto-follow flows unless it has followed `thejokebot` again since the unfollow event.

Why this matters:
- Repeated follow/unfollow cycles can look like nagging behaviour and may risk policy issues even when unintended.
- The current logic does not retain unfollow history, so it cannot apply this guardrail yet.

Implementation direction (future):
1. Add durable unfollow history storage (for example a tracked state file or small local database).
2. Record minimum fields: DID, unfollow timestamp, reason/source script.
3. Update follow-back and follower-generation selection logic to exclude previously unfollowed DIDs by default.
4. Remove exclusion only when there is evidence the DID followed `thejokebot` after the recorded unfollow timestamp.
5. Add dry-run visibility and tests for this decision path.

Operational rule (effective now):
- Do not run live unfollow automation as part of normal operations until this guardrail is implemented and tested.

## 13. Change Log (Problem Statement)
- v0.1: Initial project-specific draft created to establish governance baseline.
- v0.2: Added deferred unfollow re-engagement guardrail and temporary live-unfollow hold.
- v0.3: Added GitHub Actions runtime contract constraint to protect operational continuity.
