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
- Before pushing local commits, sync with remote changes first (normally `git pull --rebase`) because scheduled and manual bot workflows can update `main` between local edits and push time.

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
- Structured logging and stronger pagination/network safeguards (bounded retries).

### 12.0 Explicit "Will Not Do" Decisions

These were evaluated and deliberately ruled out. Do not revisit without a concrete operational reason.

| Item | Decision | Reason |
|---|---|---|
| Migrate joke history to a database | Will not do | No operational problem justifies the migration risk or complexity. `posted_jokes.txt` is sufficient. |
| Rewrite scripts as async | Will not do | No throughput or latency requirement that sync code cannot meet. |
| Redesign workflow schedules | Will not do | Current cadence is working; change only if an operational problem emerges. |
| Change or remove the joke source | Will not do | `icanhazdadjoke` is the established source; change is out of scope unless resilience work requires a fallback. |
| Remove base64 encoding from `posted_jokes.txt` | Will not do | Encoding is intentional: (1) it prevents brittle comparison failures on special characters (commas, apostrophes, etc.) from uncontrolled joke API output; (2) it stops raw joke text appearing in GitHub search results. Do not revert to plain text. |

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

### 12.2 Multi-Provider Joke Source with Retry Handler (Deferred)

Requirement summary:
- The bot currently fetches jokes exclusively from `icanhazdadjoke`. If that API is unavailable, returns a 429/529, or gives an empty response, the bot falls back to a hardcoded static joke.
- The static fallback is a last resort, not a real joke. A pool of real provider fallbacks is preferable.

Why this matters:
- API availability cannot be controlled; having a second (and third) source means the bot keeps posting real jokes even when one provider has an outage.
- Different providers may offer different joke styles, adding variety without requiring a curated library.

Implementation direction (future):
1. Define a small provider interface: `fetch_joke() -> str | None` per provider module.
2. Implement at least two additional providers (candidates: `official-joke-api.appspot.com`, `v2.jokeapi.dev`, `api.api-ninjas.com/v1/dadjokes`, `redd.it/r/dadjokes` RSS, `groandeck.com/developers`, `rapidapi.com/KegenGuyll/api/dad-jokes`, `humorapi.com/docs/#Random-Joke`).
3. In `bluesky_post_joke.py`, attempt providers in order, skipping any that raise an exception or return a status outside 2xx.
4. Apply the existing `MAX_ATTEMPTS` / deduplication logic against `posted_jokes.txt` across all providers combined.
5. Retain the static fallback only after all providers are exhausted.
6. Add unit tests for the provider-rotation logic (no live HTTP calls; mock `fetch_joke()`).

Constraints:
- Base64 encoding of jokes in `bot_state.json` must be preserved (see Section 12.0).
- Provider selection order should be deterministic (not random) to simplify debugging.
- Do not change the post content format or hashtags.
- `api.api-ninjas.com/v1/dadjokes` should be treated as a backup-only provider in default operation because its joke pool is very small; it should only be used after the primary providers fail unless explicitly selected for testing.
- `jokebot_jokebook` (bundled `resources/jokebot_jokebook.json`) must remain the final resort in the backup chain and must never be added to the primary rotation.

**Status: complete.** Provider chain implemented: `icanhazdadjoke` → `jokeapi` → `api_ninjas` → `jokebot_jokebook` (offline, 446 jokes, always available).

### 12.3 Workflow and Automation Hardening from Live Run Review (Deferred)

Requirement summary:
- Recent manual GitHub Actions runs for `bluesky_post_joke`, `bluesky_follow_back`, and `bluesky_generate_followers` all completed successfully.
- No immediate production bug was exposed, but the runs identified a few worthwhile hardening improvements.

Why this matters:
- `bluesky_generate_followers.py` currently executes live follow actions without the same runtime safety controls already added to follow-back/unfollow flows.
- `bluesky_post_joke.yml` writes and pushes runtime state, so overlapping manual and scheduled runs can create avoidable git push/rebase churn.
- `bluesky_generate_followers.py` currently logs every followed DID individually, which is useful for audit but noisy in workflow logs.

Implementation direction (future):
1. Add `BLUESKY_DRY_RUN` and `BLUESKY_ACTION_DELAY_SECONDS` support to `bluesky_generate_followers.py` so follow-generation has the same safety controls as the other automation scripts.
2. Add workflow `concurrency` control to `bluesky_post_joke.yml` so only one post/state-writing run can execute at a time.
3. Reduce `bluesky_generate_followers.py` log noise by logging counts and a small sample of followed DIDs instead of printing every DID by default.
4. Preserve enough auditability that follow decisions can still be reviewed when needed.

**Status: complete.** Concurrency guard added to `bluesky_post_joke.yml` (78025b2). Per-DID logs removed from `bluesky_generate_followers.py` and replaced with summary by tag + sample (78025b2).

## 13. Change Log (Problem Statement)
- v0.1: Initial project-specific draft created to establish governance baseline.
- v0.2: Added deferred unfollow re-engagement guardrail and temporary live-unfollow hold.
- v0.3: Added GitHub Actions runtime contract constraint to protect operational continuity.
- v0.4: Added Section 12.0 explicit "will not do" decisions (including base64 rationale). Added Section 12.2 multi-provider joke source with retry handler.
- v0.5: Added Section 12.3 workflow and automation hardening backlog items from successful live GitHub Actions review.
- v0.6: Added an explicit pull/rebase-before-push working rule to reduce avoidable push rejections from concurrent workflow updates.
- v0.7: Completed Section 12.2 provider chain. Added `jokebot_jokebook` offline provider (446 jokes, b64-encoded in `resources/jokebot_jokebook.json`) as the final resort after all live providers fail. Updated constraints and status.
- v0.8: Completed Section 12.3 workflow hardening. Added concurrency guard to `bluesky_post_joke.yml` to prevent scheduled/manual run races. Reduced log noise in `bluesky_generate_followers.py` by replacing per-DID logs with tag summary + sample. Renamed resource files for clarity: `official_jokes.json` → `jokebot_jokebook.json`, `joke_denylist.json` → `jokebot_denylist.json`. Implemented report acknowledgement feature: bot now replies to #report with acknowledgement message. Implemented reply liking with 24-hour cutoff and #report skip logic. Added 31 new unit tests covering new code (state helpers, report processing, like_replies, retry chain). All 55 tests pass.
- v0.9: **Critical security and stability hardening**. Fixed bare exception handlers in `bluesky_post_joke.py`, `bluesky_follows_and_likes.py`, and `bluesky_process_reports.py` — now catch only `(ValueError, RequestException, TimeoutError)` instead of all exceptions, preventing unintended masking of `KeyboardInterrupt`, `MemoryError`, and fatal errors. Added file-level locking (`fcntl.flock()`) to `bluesky_state.py` load/save to prevent concurrent mutations when two automation scripts run simultaneously. All 55 tests pass.
- v1.0: **Error handling and operational improvements**. Enhanced `bluesky_process_reports.py` to distinguish transient errors (network/timeout) from permanent errors (invalid URIs/format) in `_delete_post()` and `acknowledge_report()` — now returns `(success, should_retry)` tuples so only permanent failures are recorded to avoid retry spam. Made unfollow ignore list configurable via `BLUESKY_UNFOLLOW_IGNORE` environment variable while maintaining default list (theonion). Updated tests to verify new tuple returns. All 55 tests pass.
- v1.1: **Low-priority quality hardening complete**. Removed unused global initialisation in `bluesky_generate_followers.py` (no eager `Client()` construction and no redundant env pre-read). Added a runtime safety guard to `bluesky_follower_utils.fetch_paginated_data()` via `max_runtime_seconds` to reduce long-running hangs. Expanded docstrings in `bluesky_process_reports.py` for notification extraction and proposal collection flow clarity. All 55 tests pass.
- v1.2: **Issue #5 fix (jokebook report handling)**. Report proposals now carry `source_provider` from state. In `bluesky_create_report_prs.py`, reports tied to `jokebot_jokebook` now create jokebook-removal PRs by deleting the reported base64 entry from `resources/jokebot_jokebook.json` instead of adding it to `resources/jokebot_denylist.json`. Added unit tests for proposal routing and jokebook removal helpers. All 59 tests pass.
