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
