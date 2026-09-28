# Changelog

## 1.0.0 - 2026-09-28

- Packaged the application under `src/thejokebot` with installed command entry points and consolidated package metadata.
- Added tagged joke requests with persisted checkpoints and duplicate-reply protection.
- Split runtime state, dashboard collection and social processing along domain boundaries while retaining existing workflows.
- Strengthened changed-line coverage, workflow persistence, security and trusted Dependabot merge checks.

## 0.0.7 - September 2026

- Added dashboard audience growth and 30/90-day reciprocity insights, responsive native embeds for top jokes, and a separate Operations view.
- Introduced CI SonarQube quality-gate and zero-issue checks, pinned Pyright type checks, and local validation guidance.
- Hardened workflow schedules, session handling and provider health after operational feedback.

## 0.0.6 - August 2026

- Published the six-hourly GitHub Pages dashboard with public account, engagement and posting history.
- Expanded aggregate operations reporting with discovery outcomes, delivery, moderation, provider pressure and starter-pack attribution.
- Split runtime state by purpose; added durable monthly dashboard history and configured account-block restoration.

## 0.0.5 - June-July 2026

- Tuned joke retention and unfollow cadence, then rotated posting hashtags with a length-aware budget.
- Restored hashtag-pool precedence, protected selected accounts from automatic unfollow and tightened local lint/test discipline.

## 0.0.4 - May 2026

- Introduced starter-pack management, metadata synchronisation and unfollow protection.
- Added Ruff, CodeQL and local preflight checks; enforced grapheme-aware post-length limits.
- Added a follow-back grace period, interaction-led follows and centralised, validated runtime configuration.

## 0.0.3 - April 2026

- Added multiple live joke providers with an offline fallback, duplicate avoidance and a permanent denylist.
- Introduced `#report` moderation PRs, approved-post removal, reply liking and cautious unfollow batching.
- Hardened workflow concurrency, state persistence, network retries and Python 3.12 automation.

## 0.0.2 - 2025

- Split follow and unfollow automation onto separate schedules and restored suspended workflows.
- Added persistent duplicate-joke protection and improved handling of joke punctuation and encoding.

## 0.0.1 - 2024-12-10

- Created the scheduled Bluesky joke bot and initial follow/unfollow automation.