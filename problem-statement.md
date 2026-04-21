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
- v1.8: Low-priority housekeeping batch. Documented `BLUESKY_UNFOLLOW_IGNORE` in `.env.example` and README (5.4). Removed stale `### File:` header lines from `bluesky_state.py`, `bluesky_follower_utils.py`, and `bluesky_joke_providers.py` (5.5). Confirmed `posted_jokes.txt` and `bluesky_create_report_prs.py` README row already resolved (5.6, 5.7).
- v1.9: Resolved provider-rotation dual source of truth (5.8). `bluesky_joke_providers.PRIMARY_PROVIDERS` now derives from `bluesky_state.PROVIDER_ROTATION_ORDER`, with a test guard to keep them aligned.
- v1.10: Completed Python runtime maintenance bump (5.9). All workflows running project scripts now use `python-version: "3.12"`.
- v1.11: Added missing workflow concurrency guards (5.10) to follow-fellows, follows-and-likes, and process-reports using the same `cancel-in-progress: false` safety model as post-joke.
- v1.12: Added GroanDeck as a third primary provider (5.11). `fetch_from_groandeck()` added, all 33 categories reviewed and confirmed family-friendly. Primary rotation extended to `[icanhazdadjoke, jokeapi, groandeck]`.
