# Changelog

## Unreleased

Progress on `main` since 1.0.0, grouped by commit date rather than invented release
versions. Routine automated state and dashboard-data refreshes are omitted.

### 2026-11-01

- Added a docs-only SDLC exception: review text, links and the diff, but skip
  tests, preflight, builds, code quality/coverage scans, dependency audits and
  manually dispatched full CI. Keep changelog updates and rebase/push discipline;
  mixed code, configuration, workflow or dependency changes retain normal checks.
- **Breaking:** Raised the minimum to Python 3.14 and removed Python 3.12/3.13
  support. Aligned packaging, Pyright, Ruff and Sonar, removed the legacy CI leg,
  regenerated the lock, and covered malformed timestamps and corrupt joke
  history. Python 3.15 remains excluded by the atproto SDK. ([ebf45c7c])
- Moved the primary local and GitHub runtimes to CPython 3.14.10, with verified
  macOS/Linux binary dependencies and editable/distributable package builds.
  The initial 3.12 compatibility check was subsequently removed. ([a8e1fc70])
- Updated the complete hash-locked Python environment, Ruff, GitHub Actions and
  Chart.js to current stable versions, refreshed Chart.js integrity verification,
  and restored the locked local Pyright installation. ([e8648faf])
- Backfilled missing project progress and made changelog updates part of the SDLC:
  meaningful changes must update this log in the same substantive commit.

### 2026-10-31

- Added provider candidate, rejection and error counters, confirmed publication
  shares, sample-aware historical comparisons and concentration trends without
  changing provider-selection behaviour. ([eddd583a])
- Made Operations outcome-led: delivery slots, source checkpoint freshness,
  sanitised failed-step receipts, retry-aware incident/recovery timelines and
  missed/delayed-slot inspection. Separated production attention from CI failures.
  ([20998488])
- Made slot-exception inspection keyboard-accessible using a native button and
  labelled region, resolving the accessibility finding without suppressing it.
  ([67f81b42])

### 2026-10-30

- Extended the default do-not-unfollow protection list and its regression
  assertions. ([61a95264])

### 2026-10-27

- Distinguished completed outgoing follows from incoming audience growth,
  disclosed relationship-outcome numerators and sample sizes, and rendered the
  configured protection duration rather than a hard-coded value. ([9c5004f8])
- Added independent Audience/Operations historical controls, complete UTC-day
  periods, preceding-period comparisons and retained-history trends. Missing
  days remain gaps and incomplete observations are labelled honestly. ([9f08dd9d])
- Added immutable joke-engagement observations at matched ages: 24-30 and
  168-174 hours. Compare mature publishing cohorts and disclose missed samples
  without fabricating historical counts. ([7a03d7b5])
- Replaced generic operational warnings with specific workflow failure counts,
  uncertain state-persistence run details and overdue joke-request checks.
  ([43c9df56])
- Added bounded discovery from saved Bluesky feeds alongside hashtag discovery
  under the existing action budget, with durable feed rotation and read-only
  dry-run previews. ([7d89bcad], [30d2eef8])
- Checkpointed confirmed unfollows against fresh social state and published valid
  checkpoints even after command failure, while preserving failed job outcomes
  and read-only dry runs. ([5ff127b4], [5005e470])
- Checkpointed follows, attribution, likes and joke replies as explicit operations
  against fresh transactions, preserving duplicate-reply checks, page receipts
  and monotonic scan boundaries instead of saving stale snapshots. ([468072c5])
- Checkpointed moderation deletions and acknowledgement receipts, retained
  acknowledgement retries and wrote proposal output atomically. ([d9a3af7e])
- Added a durable report-proposal outbox with verified review-PR delivery,
  independent retries and validated orphan-branch recovery. ([5ff86d0a])
- Added manual, read-only inspection of known starter-pack membership, with
  positive/negative/unknown evidence, explicit discovery limits and a fixed
  report path. No account actions or public membership claims are made.
  ([877a3c98], [460638e6])
- Improved trusted Dependabot prerequisite diagnostics and deterministic
  starter-pack tests; explicitly marked the handled dashboard startup promise
  as intentionally unawaited to unblock Sonar checks. ([36781454], [29bbbe2b])
- Applied Dependabot updates for setup-node 7.1.0, Sonar scan 8.3.0, CodeQL
  Actions 4.39.1 and setuptools 84.2.1. ([7bbc85d7], [6826b29c], [661c5e8d], [c2662e08])
- Made Git-persistence integration fixtures use explicit bare-repository paths
  and enforce `safe.bareRepository=explicit` without weakening Git safety.
  ([e62e1490])

### 2026-09-29

- Used the bundled jokebook for tagged request replies, capped replies per
  requester and run, and kept reply selection separate from scheduled-post
  duplicate avoidance. ([53a8e080])
- Recorded issue completion requirements: link the issue in the substantive
  commit, verify remote checks and confirm completed issues are closed.
  ([c8406538])

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

[ebf45c7c]: https://github.com/chris-gillatt/thejokebot/commit/ebf45c7cab5bcbdd98701093eefc4fc34a85e04d
[a8e1fc70]: https://github.com/chris-gillatt/thejokebot/commit/a8e1fc70a965bfd0073e0a3becb7a4aeab8cc8fa
[e8648faf]: https://github.com/chris-gillatt/thejokebot/commit/e8648faf537ed1e0b6fffe262ccb3c84a15a0028
[eddd583a]: https://github.com/chris-gillatt/thejokebot/commit/eddd583a2bdb66e4c437f9c323588d21a5a28bd7
[20998488]: https://github.com/chris-gillatt/thejokebot/commit/2099848873ac00a222eceb79f14bb1eef4c220c7
[67f81b42]: https://github.com/chris-gillatt/thejokebot/commit/67f81b421938c99acfb8bb434cff008527ef518e
[61a95264]: https://github.com/chris-gillatt/thejokebot/commit/61a95264d108f11a6a3068ed751689bbe560b189
[9c5004f8]: https://github.com/chris-gillatt/thejokebot/commit/9c5004f824b6c443e9d3334a4043dba4d49195bc
[9f08dd9d]: https://github.com/chris-gillatt/thejokebot/commit/9f08dd9d4661ce884df29fdab290d35d7861707a
[7a03d7b5]: https://github.com/chris-gillatt/thejokebot/commit/7a03d7b5e38fd05468ad1d03d169b46abdeae7a1
[43c9df56]: https://github.com/chris-gillatt/thejokebot/commit/43c9df56840c497c98df3a7fef514d7b4eb84829
[7d89bcad]: https://github.com/chris-gillatt/thejokebot/commit/7d89bcad47ea6a3a30b8c7e309c00341a6aa1b35
[30d2eef8]: https://github.com/chris-gillatt/thejokebot/commit/30d2eef850b8f8eb7725e03c5993d57e7704dd70
[5ff127b4]: https://github.com/chris-gillatt/thejokebot/commit/5ff127b4af97ad8217922a6fcf63867f578657da
[5005e470]: https://github.com/chris-gillatt/thejokebot/commit/5005e470fa50eebfae01f644b9c0e754eb3f9624
[468072c5]: https://github.com/chris-gillatt/thejokebot/commit/468072c5de72875338fbf8be4daa567d86cbacb5
[d9a3af7e]: https://github.com/chris-gillatt/thejokebot/commit/d9a3af7e2fa6ca7f92d4a9584f6da722c1bf2b83
[5ff86d0a]: https://github.com/chris-gillatt/thejokebot/commit/5ff86d0afffb0441170c47d814317fbfac40480d
[877a3c98]: https://github.com/chris-gillatt/thejokebot/commit/877a3c98d0d87cd35d6e55858a55a7733935ec75
[460638e6]: https://github.com/chris-gillatt/thejokebot/commit/460638e6bdbd1e898cf43fd8caad0ab6ecb656bc
[36781454]: https://github.com/chris-gillatt/thejokebot/commit/367814543b385b824ae238bc67e360a03c6f52cb
[29bbbe2b]: https://github.com/chris-gillatt/thejokebot/commit/29bbbe2b2dcb5af0ba0bcf0341d92cb31778bba9
[7bbc85d7]: https://github.com/chris-gillatt/thejokebot/commit/7bbc85d773a1272ae5b18fa3045ba1fb1aaa832f
[6826b29c]: https://github.com/chris-gillatt/thejokebot/commit/6826b29cbd99d595ea88e0aa6d48b515bd1c26c4
[661c5e8d]: https://github.com/chris-gillatt/thejokebot/commit/661c5e8d8ee19ab10634b8cb0f476c713994a8bb
[c2662e08]: https://github.com/chris-gillatt/thejokebot/commit/c2662e08f84a2d35c4ea7d5861f2c5b5e11a0bb7
[e62e1490]: https://github.com/chris-gillatt/thejokebot/commit/e62e1490cc3221acd3cc60a62eb9430937d3827d
[53a8e080]: https://github.com/chris-gillatt/thejokebot/commit/53a8e0800e526f4a87e5a16f1b637e25107a5cee
[c8406538]: https://github.com/chris-gillatt/thejokebot/commit/c840653869b51c19f190b009688206a30b7dd45f