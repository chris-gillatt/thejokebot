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

## 3. Operational Constraints
- The project is automation-first (GitHub Actions + script execution).
- Existing runtime contracts (script entry points, workflow triggers, key env vars) should be treated as stable interfaces.
- Required environment variable names such as `BLUESKY_PASSWORD` and `BLUESKY_USERNAME` should not change casually.

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

### 5.4 BLUESKY_UNFOLLOW_IGNORE undocumented (Documentation)
**Priority: Low**

`bluesky_unfollow.py` supports a `BLUESKY_UNFOLLOW_IGNORE` env var (comma-separated
full handles to protect from unfollowing) but it appears in neither `.env.example`
nor the README env-vars table. Users running the script locally or customising the
workflow have no way to discover this without reading the source.

Fix: add the variable to both `.env.example` and the README table.

---

### 5.5 Stale `### File:` header comments (Code quality)
**Priority: Low**

Three files — `bluesky_state.py`, `bluesky_follower_utils.py`, and
`bluesky_joke_providers.py` — have a `### File: <filename>` comment as their very
first line. These appear to be stale agent-era artefacts with no value; they are
not a recognised Python convention and would confuse new contributors.

Fix: remove these three lines.

---

### 5.6 `posted_jokes.txt` legacy file in repo root (Housekeeping)
**Priority: Low**

`posted_jokes.txt` exists in the repo root but the state module explicitly states
it has been superseded by `bot_state.json`. Its presence may confuse contributors
into thinking it is still active. Verify it is genuinely unused, then remove it (or
add a brief note in `.gitignore` if it needs to be retained as a local dev artefact).

---

### 5.7 `bluesky_create_report_prs.py` missing from README scripts table (Documentation)
**Priority: Low**

The README `Scripts` table lists six scripts but omits `bluesky_create_report_prs.py`.
It is documented further down under "Report workflow (technical detail)" but a
contributor scanning the table would not know it exists.

Fix: add a row for `bluesky_create_report_prs.py` to the table.

---

### 5.8 Dual source of truth for provider rotation order (Code quality)
**Priority: Low**

`PROVIDER_ROTATION_ORDER` in `bluesky_state.py` and `PRIMARY_PROVIDERS` in
`bluesky_joke_providers.py` both enumerate the primary providers. Adding a new
primary provider requires updating both lists; missing one silently breaks either
rotation state or the pick-joke logic. Consolidate to a single source of truth
(the state module is the natural owner).

---

### 5.9 Python version: schedule bump from 3.11 to 3.12 (Maintenance)
**Priority: Low**

All workflows pin `python-version: "3.11"`. Python 3.11 reaches end-of-life in
October 2026; 3.12 is the current stable release. The codebase uses no 3.11-only
features. Schedule a bump to 3.12 across all workflows before EOL to stay on a
supported runtime.

---

### 5.10 `bluesky_follow_fellows.yml` missing concurrency guard (Workflow safety)
**Priority: Low**

`bluesky_follow_fellows.yml` (runs every Friday) has no `concurrency:` block.
`bluesky_process_reports.yml` (runs every 30 minutes) and
`bluesky_follows_and_likes.yml` (runs every 2 hours) also lack concurrency guards.
If a run takes longer than expected or a manual `workflow_dispatch` overlaps with a
scheduled run, two jobs could attempt simultaneous writes to `bot_state.json`. The
`bluesky_post_joke.yml` pattern (`cancel-in-progress: false`) is the model to
follow.

---

### 5.11 Investigate GroanDeck as new primary joke provider
**Priority: Medium**

GroanDeck (`https://groandeck.com/api/v1/random`) is a free REST API with no
sign-up or API key required (30 req/min on the free tier). Response shape is
`{"setup": "...", "punchline": "..."}` — a clean two-part format that maps
naturally to the existing two-part joke assembly already used for JokeAPI. The
pool is substantial (~800+ jokes across categories). No content-safety parameter,
so review the category list to confirm it matches the bot's family-friendly policy
before adding. Candidate for the primary rotation alongside or in place of JokeAPI.

---

### 5.12 Investigate HumorAPI as new backup joke provider
**Priority: Medium**

HumorAPI (`https://api.humorapi.com/jokes/random`) has an `exclude-tags=nsfw,dark`
parameter and a `max-length` cap (useful for staying within Bluesky's 300-character
post limit). Requires an API key (`api-key` query param). The quota model is
point-based (1 point per request); the free tier should be adequate for the bot's
usage. Fits naturally as a backup provider alongside `api_ninjas`. Assess whether
the joke pool is suitably family-friendly and add `HUMORAPI_API_KEY` env var, a
`fetch_from_humorapi()` function, and README/`.env.example` documentation if it
passes review.

## 6. Explicit "Will Not Do" Decisions
Do not revisit these without a concrete operational reason.

| Item | Decision | Reason |
|---|---|---|
| Migrate joke history to a database | Will not do | Current state-file approach is sufficient for operational scale. |
| Rewrite scripts as async | Will not do | No throughput requirement justifies complexity increase. |
| Redesign workflow schedules by default | Will not do | Current cadence works; change only for observed operational need. |
| Remove base64 encoding from state payloads | Will not do | Prevents fragile comparisons and avoids indexing raw joke text. |

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
