# The Joke Bot – Problem Statement

## 1. Purpose
This document is the project-level operating brief for safe, incremental maintenance.
It should stay concise and current, with focus on active priorities and quality rules.

Detailed implementation history belongs in Git commit history and PRs. The milestone
changelog in this file is intentionally brief.

## 2. Working Principles
- Preserve core runtime behaviour unless a change is explicitly approved.
- Use focused, reversible changes; avoid speculative refactors.
- Keep secrets out of source control.
- Use British English in prose/documentation where practical.
- Use Conventional Commits with commit messages that explain why.
- Before push, sync with remote (`git pull --rebase`) because scheduled workflows can update `main`.
- Before commit/push, run local quality checks (`ruff check`, `ruff format --check`, unit tests, and local CodeQL when available) and fix issues proactively.

## 3. Operational Constraints
- The project is automation-first (GitHub Actions + script execution).
- Existing runtime contracts (script entry points, workflow triggers, key env vars) should be treated as stable interfaces.
- Required environment variable names such as `BLUESKY_PASSWORD` and `BLUESKY_USERNAME` should not change casually.
- Bluesky profile counters and raw follow records can exceed hydrated `get_followers`/`get_follows` results; suspended, deactivated, taken-down, or otherwise hidden accounts may still count in totals without materialising in actionable graph queries.

## 4. Current Active Risks
1. Dependency drift and workflow/runtime skew.
2. Behaviour regressions when touching posting/report/follow flows.
3. Scope creep during multi-file maintenance work.

## 5. Active Backlog

### 5.1 Unfollow Re-Engagement Guardrail ✓ Complete
See v1.4 changelog entry.

### 5.2 Logging and Network Guardrails ✓ Complete
See v1.5 changelog entry.

---

### 5.3 Unfollow history not persisted to repo ✓ Complete
See v1.7 changelog entry.

---

### 5.4 BLUESKY_UNFOLLOW_IGNORE undocumented ✓ Complete
See v1.8 changelog entry.

---

### 5.5 Stale `### File:` header comments ✓ Complete
See v1.8 changelog entry.

---

### 5.6 `posted_jokes.txt` legacy file in repo root ✓ Complete
File was already absent from the repository — no action required.

---

### 5.7 `bluesky_create_report_prs.py` missing from README scripts table ✓ Complete
Script was already present in the README table — no action required.

---

### 5.8 Dual source of truth for provider rotation order ✓ Complete
Single source of truth now lives in `bluesky_state.PROVIDER_ROTATION_ORDER`; `bluesky_joke_providers.PRIMARY_PROVIDERS` is derived from it.

---

### 5.9 Python version: schedule bump from 3.11 to 3.12 ✓ Complete
Updated all Python-running workflows from `python-version: "3.11"` to `"3.12"`.

---

### 5.10 Missing concurrency guards on follow/report workflows ✓ Complete
Added `concurrency` blocks with `cancel-in-progress: false` to:
- `bluesky_follow_fellows.yml`
- `bluesky_process_reports.yml`
- `bluesky_follows_and_likes.yml`

---

### 5.11 Investigate GroanDeck as new primary joke provider ✓ Complete
**Priority: Medium**

GroanDeck (`https://groandeck.com/api/v1/random`) is a free REST API with no
sign-up or API key required (30 req/min on the free tier). Response shape is
`{"setup": "...", "punchline": "..."}` — a clean two-part format that maps
naturally to the existing two-part joke assembly already used for JokeAPI. The
pool is substantial (~800+ jokes across categories). No content-safety parameter,
so review the category list to confirm it matches the bot's family-friendly policy
before adding. Candidate for the primary rotation alongside or in place of JokeAPI.

**Resolution:** All 33 GroanDeck categories confirmed family-friendly (~2,200 total
jokes: puns, animals, food, technology, etc.; no adult or dark-humour content).
Added `fetch_from_groandeck()` in `bluesky_joke_providers.py`, appended `groandeck`
to `bluesky_state.PROVIDER_ROTATION_ORDER` (primary rotation is now
`[icanhazdadjoke, jokeapi, groandeck]`), registered in `PROVIDERS` dict. No API key
required. README updated with provider names in `BLUESKY_JOKE_PROVIDER` doc. 4 new
tests added.

---

### 5.12 Investigate HumorAPI as new backup joke provider ✗ Will Not Do
**Priority: Medium**

HumorAPI (`https://api.humorapi.com/jokes/random`) has an `exclude-tags=nsfw,dark`
parameter and a `max-length` cap (useful for staying within Bluesky's 300-character
post limit). Requires an API key (`api-key` query param). The quota model is
point-based (1 point per request); the free tier should be adequate for the bot's
usage. Fits naturally as a backup provider alongside `api_ninjas`. Assess whether
the joke pool is suitably family-friendly and add `HUMORAPI_API_KEY` env var, a
`fetch_from_humorapi()` function, and README/`.env.example` documentation if it
passes review.

**Decision:** Do not implement HumorAPI integration due to terms-and-conditions
concerns around permitted use/storage of joke content for this endpoint.

---

### 5.13 Enforce post-length preflight before Bluesky send ✓ Complete
**Priority: High**

Posting previously relied on the API call to reject over-limit payloads. Add a
pre-send guard so provider candidates are filtered and retried before posting,
using the effective joke-length budget after hashtags are appended.

**Resolution:** Implemented in `bluesky_post_joke.py` via
`BLUESKY_MAX_POST_CHARS=300`, `_HASHTAG_SUFFIX_LEN`, and `_MAX_JOKE_CHARS`.
`pick_joke()` now skips over-long jokes and retries like duplicate handling;
if all attempts are duplicates/too long it falls through to next provider.
Test coverage added for skip-and-retry and all-too-long failure paths.

---

### 5.14 Use grapheme-aware length checks for post safety ✓ Complete
**Priority: Medium**

Current length preflight uses Python `len()` (code points), while Bluesky limits
are based on visible character units. For composed emoji and combining marks,
code-point counts may diverge from rendered length. Evaluate and, if needed,
switch to grapheme-cluster counting in the preflight check to avoid false
accept/reject edge cases.

**Resolution:** `bluesky_post_joke.py` now uses grapheme-cluster counting via
the `regex` package (`\X`) for preflight length checks. `_MAX_JOKE_CHARS` is
now derived from grapheme-aware hashtag suffix length, and `pick_joke()`
compares joke length in graphemes rather than code points. Added regression
tests covering combining-mark edge cases and updated dependencies.

---

### 5.15 Add operational hygiene for stale unfollow ignore handles ✓ Complete
**Priority: Low**

`BLUESKY_UNFOLLOW_IGNORE` can accumulate handles that no longer resolve
(`Profile not found`), which now degrades gracefully but still adds noisy logs.
Add a lightweight maintenance task/runbook step to periodically validate ignore
handles and prune stale entries in GitHub Actions secrets.

**Resolution:** Added `bluesky_validate_unfollow_ignore.py` to resolve
`BLUESKY_UNFOLLOW_IGNORE` handles and report stale entries with deterministic
output. Added workflow `.github/workflows/bluesky_validate_unfollow_ignore.yml`
for monthly and manual validation runs using existing Bluesky credentials. Script
defaults to failing when stale handles are detected so repository secrets/vars can
be pruned promptly.

---

### 5.16 Add Ruff lint/format checks in CI ✓ Complete
**Priority: Medium**

Add a lightweight code-quality workflow using Ruff for linting and format
validation. Start in non-invasive mode (`ruff check` and `ruff format --check`)
to surface issues in pull requests without broad refactors. Include a minimal
`pyproject.toml` Ruff configuration only if needed for stable rule selection.

**Resolution:** Added `.github/workflows/ruff_quality.yml` with
`pull_request`, `push` (`main`), and manual dispatch triggers. The workflow uses
Python 3.12 and runs non-invasive checks only: `ruff check .` and
`ruff format --check .`. Added matching local validation commands to `README.md`.

---

### 5.17 Add GitHub CodeQL analysis workflow ✓ Complete
**Priority: Medium**

Add a standard GitHub CodeQL workflow for Python to provide free baseline
security/static analysis and code scanning alerts on pull requests and main
branch updates. Keep configuration minimal initially, then tune query packs and
exclusions only if noise is observed.

**Resolution:** Added `.github/workflows/codeql.yml` using GitHub's standard
CodeQL actions for Python (`init`, `autobuild`, `analyze`) with
`pull_request`, `push` (`main`), weekly schedule, and manual dispatch triggers.
Permissions are scoped to `actions: read`, `contents: read`, and
`security-events: write`. README workflow status table updated with CodeQL badge.

---

### 5.18 Add Syrsly as an additional backup provider ✓ Complete
**Priority: Medium**

Issue #8 requested adding Syrsly (`https://www.syrsly.com/joke`) as an
additional provider. Implementation uses `https://www.syrsly.com/joke/dad`
as a family-friendly backup source. Added `fetch_from_syrsly()` and registered
`syrsly` in `PROVIDERS` and `BACKUP_PROVIDERS` (ahead of API Ninjas and the
offline jokebook fallback). Added provider tests and env/README documentation.

Because the endpoint can return BOM-prefixed and HTML-escaped text, posting
sanitisation now strips leading UTF-8 BOM markers before final normalisation.

---

### 5.19 Create a starter pack from the Funnies list ✓ Complete
**Priority: Medium**

Issue #14 requested converting The Joke Bot's existing Bluesky list ("Funnies")
into a starter pack, plus operational guardrails so list accounts are followed and
not accidentally removed by unfollow automation.

**Resolution:** Added `resources/jokebot_starter_pack.json` and a new script
`bluesky_manage_starter_pack.py` with hybrid operation (one-time setup and manual
sync). Script can upsert the `app.bsky.graph.starterpack` record from the source
list and optionally follow missing list members.

Added workflow `.github/workflows/bluesky_manage_starter_pack.yml` with manual
dispatch and dry-run default (`apply_changes=false`) for safe roll-out.

`bluesky_unfollow.py` now loads source list members from
`resources/jokebot_starter_pack.json` when enabled and unions those DIDs with
`BLUESKY_UNFOLLOW_IGNORE` protection, preventing accidental removals.

### 5.22 Pull starter-pack metadata from Bluesky ✓ Complete
**Priority: Medium**

Issue #19 identified that the live starter-pack name/description on Bluesky had
diverged from `resources/jokebot_starter_pack.json`, creating a risk that the
existing setup/sync path would overwrite manual live edits on the next run.
Bluesky should remain the source of truth for starter-pack metadata.

**Resolution:** Added `pull_starter_pack_record()` and
`write_starter_pack_config_updates()` to `bluesky_manage_starter_pack.py`.
The new `--mode pull` path fetches the live starter-pack record, shows an
actual dry-run preview of changed fields, and optionally writes those changes
back to `resources/jokebot_starter_pack.json` without touching follows or
source-list membership. The workflow now exposes `pull` mode and commits pulled
config updates back to the branch only when `apply_changes=true`.

## 6. Explicit "Will Not Do" Decisions
Do not revisit these without a concrete operational reason.

| Item | Decision | Reason |
|---|---|---|
| Migrate joke history to a database | Will not do | Current state-file approach is sufficient for operational scale. |
| Rewrite scripts as async | Will not do | No throughput requirement justifies complexity increase. |
| Redesign workflow schedules by default | Will not do | Current cadence works; change only for observed operational need. |
| Remove base64 encoding from state payloads | Will not do | Prevents fragile comparisons and avoids indexing raw joke text. |
| Integrate HumorAPI provider | Will not do | Terms-and-conditions concerns around permitted use/storage of joke content for this endpoint. |

## 7. Completed Milestones (Condensed)
- Multi-provider joke chain implemented with offline last resort (`jokebot_jokebook`).
- Workflow hardening completed (concurrency controls, safer state persistence, retry on push races).
- Security/stability hardening completed (exception narrowing, file locking, safer retries).
- Report pipeline improvements completed (`#report` acknowledgement, like/report rules, jokebook-aware report handling).
- Follow script renamed to `bluesky_follow_fellows.py` to reflect conservative behaviour and reduce misleading framing.
- Unfollow automation now applies safety-first batching controls (per-run cap, inter-batch pause, and throttle-aware early stop).
- Unfollow schedule set to daily at 12:00 UTC to clear the 4,400+ non-follower backlog; revert to twice-yearly once backlog is exhausted.
- Re-engagement guardrail implemented: unfollow history recorded in `bot_state.json`; `follow_fellows` excludes previously-unfollowed DIDs; `follow_back` logs re-engagements.

## 8. Changelog (Milestones)
- v0.1: Initial governance draft.
- v0.7: Multi-provider chain complete.
- v0.8: Workflow hardening complete.
- v0.9: Security/stability hardening complete.
- v1.0: Error-handling improvements complete.
- v1.1: Low-priority quality hardening complete.
- v1.2: Jokebook report handling fix complete.
- v1.3: Unfollow batching safeguards added (rate-aware stop, per-run action cap, configurable batch pause) to support cautious large clean-ups.
- v1.4: Re-engagement guardrail (5.1) implemented. `unfollow_history` section added to `bot_state.json`. Each live unfollow is recorded. `bluesky_follow_fellows.py` excludes all previously-unfollowed DIDs. `bluesky_follows_and_likes.py` logs re-engagements when a previously-unfollowed DID is detected in the current followers list. 5 new state-layer tests added; suite at 68 passing.
- v1.5: Logging and network guardrails (5.2) complete. Narrowed remaining bare `except Exception` handlers in `bluesky_follower_utils.py`, `bluesky_follow_fellows.py`, and `bluesky_follows_and_likes.py` to `(requests.RequestException, TimeoutError)`. Non-network defensive catches (`extract_text`, base64 decode, SDK attribute access) left as-is — they wrap arbitrary data, not network calls. Suite remains at 68 passing.
- v1.6: Unfollow schedule changed to daily at 12:00 UTC to clear ~4,400 non-follower backlog (200 per run). Also fixed `atproto_client.exceptions.NetworkError` not being caught by narrowed exception handlers, and corrected bare username `theonion` → `theonion.bsky.social` for AT identifier validity.
- v1.7: Fixed `bluesky_unfollow.yml` missing `contents: write` permission and state-persist step. Unfollow history was silently lost at the end of every CI run, making the re-engagement guardrail ineffective. Added push-retry step matching the pattern in `bluesky_post_joke.yml`.
- v1.8: Low-priority housekeeping batch. Documented `BLUESKY_UNFOLLOW_IGNORE` in `.env.example` and README (5.4). Removed stale `### File:` header lines from `bluesky_state.py`, `bluesky_follower_utils.py`, and `bluesky_joke_providers.py` (5.5). Confirmed `posted_jokes.txt` and `bluesky_create_report_prs.py` README row already resolved (5.6, 5.7).
- v1.9: Resolved provider-rotation dual source of truth (5.8). `bluesky_joke_providers.PRIMARY_PROVIDERS` now derives from `bluesky_state.PROVIDER_ROTATION_ORDER`, with a test guard to keep them aligned.
- v1.10: Completed Python runtime maintenance bump (5.9). All workflows running project scripts now use `python-version: "3.12"`.
- v1.11: Added missing workflow concurrency guards (5.10) to follow-fellows, follows-and-likes, and process-reports using the same `cancel-in-progress: false` safety model as post-joke.
- v1.12: Added GroanDeck as a third primary provider (5.11). `fetch_from_groandeck()` added, all 33 categories reviewed and confirmed family-friendly. Primary rotation extended to `[icanhazdadjoke, jokeapi, groandeck]`.
- v1.13: Added pre-post length guard (5.13). `pick_joke()` now skips over-long jokes before API send, retries within provider attempts, and falls through provider chain when necessary.
- v1.14: Added Syrsly as a backup provider (5.18) using the dad-joke endpoint, plus BOM sanitisation hardening for provider text normalisation.
- v1.15: Hardened starter-pack update path (5.19 follow-on): full AT URI validation with DID and collection enforcement; removed misleading slug default for `record_key`; shared list-member DID helpers moved to `bluesky_follower_utils`; 5 new regression tests. Prompt file added for reusable code review. Suite at 105 passing.
- v1.16: Added Ruff code-quality CI checks (5.16) via `.github/workflows/ruff_quality.yml` with non-invasive lint/format validation (`ruff check .`, `ruff format --check .`) on pull requests and `main` updates. README local validation guidance updated to match.
- v1.17: Completed repo-wide Ruff formatting pass and switched `ruff_quality` format validation to strict enforcement (removed advisory mode), so formatting drift now fails CI.
- v1.18: Added baseline GitHub CodeQL scanning (5.17) via `.github/workflows/codeql.yml` for Python on pull requests, `main` updates, weekly schedule, and manual dispatch.
- v1.19: Completed grapheme-aware post-length preflight (5.14) in `bluesky_post_joke.py` using `regex` grapheme-cluster counting so composed characters are measured by visible units instead of code points.
- v1.20: Marked HumorAPI integration (5.12) as will-not-do due to terms-and-conditions concerns around content use/storage for that endpoint.
- v1.21: Completed stale ignore-handle hygiene (5.15) by adding a dedicated validator script and monthly/manual workflow to surface and prune unresolved `BLUESKY_UNFOLLOW_IGNORE` entries.
- v1.22: Completed starter-pack metadata pull support (5.22). `bluesky_manage_starter_pack.py` now supports `--mode pull` to preview and optionally persist live Bluesky name/description changes back into `resources/jokebot_starter_pack.json`, and the workflow can commit those updates back to the branch. Suite at 144 passing.
- v1.23: Code-review follow-ups and quality hardening. Fixed loop lambda closures in `bluesky_follow_fellows.py` (CS-8) to use default-argument pattern. Made `get_int_env()` public and removed duplication in `bluesky_unfollow.py` (CS-3, CR-1). Added explicit `permissions: contents: read` to `bluesky_follow_fellows.yml` (CS-2). Added `BLUESKY_USERNAME` env var to `bluesky_follows_and_likes.yml` (CS-4). Fixed `STATE_FILE` path resolution to use `__file__`-relative path (CS-7). Improved error diagnostics in `bluesky_create_report_prs.py` (CS-6). Added test coverage for `collect_report_proposals()` notification paging and filtering (CS-9). Suite now at 140 passing (formatter-affected count update).

## 9. Code Review: Issues Resolved

Conducted 1 May 2026 against HEAD (`19f0c1c`). All findings have since been addressed. This section documents the review for completeness and as a record of the analysis process.

---

### 🟢 Resolved Issues (v1.23)

#### CR-1 — `bluesky_process_reports.py`: bare `int()` coercions of env vars ✓ Fixed
**File:** `bluesky_process_reports.py`, lines 255–256.

**Status:** Fixed in v1.23. `get_int_env()` is now public (previously private `_get_int_env`), and both `BLUESKY_REPORT_PAGE_LIMIT` and `BLUESKY_REPORT_MAX_PAGES` use safe parsing with defaults.

### 🟢 Resolved Suggestions (v1.23)

#### CS-1 — `bluesky_follow_fellows.py`: module-level `client`/`username` globals
**Status:** Not addressed — remains future optimisation candidate. Function arguments pattern now used consistently throughout. Does not block operations.

#### CS-2 — `bluesky_follow_fellows.yml`: no `permissions` block ✓ Fixed
**File:** `.github/workflows/bluesky_follow_fellows.yml`, line 12.

**Status:** Fixed in v1.23. Workflow now explicitly declares `permissions: contents: read`.

#### CS-3 — `bluesky_unfollow.py`: duplicates `_get_int_env`/`_get_float_env` ✓ Fixed
**File:** `bluesky_unfollow.py` and `bluesky_common.py`.

**Status:** Fixed in v1.23. `_get_int_env` renamed to `get_int_env` (public), and `bluesky_unfollow.py` now imports and reuses it with `minimum=0` argument.

#### CS-4 — `bluesky_follows_and_likes.yml`: missing `BLUESKY_USERNAME` env var ✓ Fixed
**File:** `.github/workflows/bluesky_follows_and_likes.yml`, line 38.

**Status:** Fixed in v1.23. Workflow now explicitly passes `BLUESKY_USERNAME: ${{ vars.BLUESKY_USERNAME }}` to the script.

#### CS-5 — `bluesky_manage_starter_pack.py`: `_build_starter_pack_record` overwrites `createdAt` ✓ Fixed
**File:** `bluesky_manage_starter_pack.py`, lines 110 and 183–198.

**Status:** Fixed in v1.22. `_build_starter_pack_record()` now preserves the original `createdAt` timestamp when updating an existing record, fetching it from the live record if needed.

#### CS-6 — `bluesky_create_report_prs.py`: stderr suppressed on git/gh command failures ✓ Fixed
**File:** `bluesky_create_report_prs.py`, lines 21–26.

**Status:** Fixed in v1.23. `run_command()` now prints stderr on failure for better debugging.

#### CS-7 — `bluesky_state.py`: `STATE_FILE` is CWD-relative ✓ Fixed
**File:** `bluesky_state.py`, line 28.

**Status:** Fixed in v1.23. `STATE_FILE` now uses `Path(__file__).resolve().parent` for deterministic path resolution.
```python
def _build_starter_pack_record(starter_cfg, source_list_uri, created_at=None):
    return {
        ...
        "createdAt": created_at or dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
```

#### CS-6 — `bluesky_create_report_prs.py`: stderr suppressed on git/gh command failures
**File:** `bluesky_create_report_prs.py`, `run_command()`.

**Problem:** `subprocess.run(..., capture_output=True)` captures both stdout and stderr but neither is printed on failure. When `git checkout -b`, `git push`, or `gh pr create` fails, the raised `CalledProcessError` carries no human-readable diagnostic. Debugging CI failures requires digging into raw exception tracebacks.

**Fix:**
```python
#### CS-6 — `bluesky_create_report_prs.py`: stderr suppressed on git/gh command failures ✓ Fixed
**File:** `bluesky_create_report_prs.py`, lines 21–26.

**Status:** Fixed in v1.23. `run_command()` now prints stderr on failure for better debugging.

#### CS-7 — `bluesky_state.py`: `STATE_FILE` is CWD-relative ✓ Fixed
**File:** `bluesky_state.py`, line 28.

**Status:** Fixed in v1.23. `STATE_FILE` now uses `Path(__file__).resolve().parent` for deterministic path resolution.

#### CS-8 — Loop lambda closures: inconsistent late-binding pattern ✓ Complete
**File:** `bluesky_follows_and_likes.py` (`follow_back`), `bluesky_follow_fellows.py` (`follow`).

**Problem:** Several loop lambdas capture the loop variable by reference rather than by value, e.g.:
```python
lambda: client.follow(did)
```
Because `retry_network_call` is synchronous this is safe today, but it is inconsistent with `bluesky_manage_starter_pack.py` which correctly uses:
```python
lambda current_did=did: client.follow(current_did)
```
The default-argument pattern is the idiomatic Python fix and removes the implicit dependency on synchronous execution order.

**Resolution:** Fixed `bluesky_follow_fellows.py` line 59 to use the default-argument pattern. `bluesky_follows_and_likes.py` line 73 already uses the correct pattern.

#### CS-9 — Test coverage gaps ✓ Complete
The following significant paths are now covered:

| Area | Status |
|---|---|
| `bluesky_manage_starter_pack.ensure_following_list_members()` | ✓ Covered (follow-sync path added in v1.22 tests). |
| `bluesky_process_reports.collect_report_proposals()` | ✓ Covered (notification collection tests added; max-pages limit, empty cursor, already-processed skipping, non-reply marking). |
| `bluesky_process_reports.delete_approved_report_posts()` | ✓ Covered (delete, skip-already-deleted, missing-URI, invalid-URI tests). |
| `bluesky_state.load_state()` / `save_state()` with locking | ✓ Covered (round-trip file-locking test added). |
| `bluesky_follow_fellows.main()` | ✓ Covered (smoke tests for re-engagement exclusion and unfollowed DID filtering). |

All items now have unit test coverage. Suite remains at 140 passing tests.

---

### ✅ Good Practices

- **Atomic state writes** via `os.replace()` from a temp file prevent partial-write corruption on interruption — consistent across `bluesky_state.py`, `bluesky_denylist.py`, and `bluesky_create_report_prs.py`.
- **File-level locking** (`fcntl.flock`) on Unix guards against concurrent read/write races in `bluesky_state.py`.
- **Defensive pagination**: cursor deduplication, page-count cap, and wall-clock runtime guard in `bluesky_follower_utils.fetch_paginated_data`.
- **Dry-run default** on all mutating operations. Workflows default `apply_changes=false`; state-mutating scripts check `BLUESKY_DRY_RUN`.
- **Retry wrappers** with configurable exponential backoff (`retry_network_call`) applied consistently across all network calls.
- **Exception narrowing**: no bare `except Exception` in network paths; exceptions are narrowed to `(requests.RequestException, TimeoutError, atproto_client.exceptions.NetworkError)`.
- **Shared helpers** in `bluesky_follower_utils` (pagination, list-member DID extraction) eliminate duplication across scripts.
- **AT URI validation** with DID match and collection enforcement in `bluesky_manage_starter_pack` guards against inadvertent writes to wrong records.
- **Concurrency guards** (`cancel-in-progress: false`) on all workflow files prevent overlapping runs.
- **Dependabot auto-merge** gated behind a full test run and restricted to patch/minor semver updates only.
- **Single source of truth** for provider rotation in `bluesky_state.PROVIDER_ROTATION_ORDER`; `bluesky_joke_providers.PRIMARY_PROVIDERS` is derived from it, backed by a test guard.
- **Report pipeline idempotency**: processed/acknowledged/deleted URIs are tracked in state to prevent duplicate actions across runs.
