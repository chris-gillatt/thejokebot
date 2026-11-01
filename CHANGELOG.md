# Changelog

Notable first-party changes, newest first. Dates come from Git history; related
implementation and corrective commits are grouped rather than repeated.
Routine automated state/dashboard-data refreshes and reference-submodule updates
are not product milestones.

`1.0.0` is the package version established on 28 September 2026. Versions
`0.1.0` through `0.8.0` are retrospective labels for the earlier development
milestones, assigned for readability rather than original release tags or
package versions.
The backfill draws on substantive human, agent and dependency commits and the
[original development milestone register][historical-milestones].

Jump to [2025](#020---2025) or the [project's beginning](#010---2024-12-10).

## 2026-11-01

- Triaged all 18 recorded CodeQL security/quality findings. Restored four
  accidentally nested hashtag tests that pytest never collected, tidied imports
  and removed unused private pagination aliases. Documented the intentional
  Unicode-repair fallback and added regression evidence for three remaining
  model-limited false positives: `ExitStack` file ownership, a lambda inside
  `finally`, and an externally used social test alias. No queries were disabled
  or findings suppressed, and posting/social behaviour is unchanged.
- Assigned chronological pre-1.0.0 milestone versions from `0.1.0` (the initial
  bot) to `0.8.0` (September's packaging and audience improvements), retaining
  the historical dates and commit evidence. These are retrospective labels,
  not newly published releases.
- Expanded the pre-1.0.0 history back to December 2024 with dated, commit-linked
  changes covering posting, social automation, moderation, transport recovery,
  dashboard development and quality safeguards. Replaced unsupported historical
  release labels and the release-pending bucket with dated progress; repository
  guidance now forbids recreating that bucket.
  ([e5818a6b])
- Added a docs-only SDLC exception: review text, links and the diff, but skip
  tests, preflight, builds, code quality/coverage scans, dependency audits and
  manually dispatched full CI. Keep changelog updates and rebase/push discipline;
  mixed code, configuration, workflow or dependency changes retain normal checks.
  ([a6f3aaf0])
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
  ([7f3b39bb])

## 2026-10-31

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

## 2026-10-30

- Extended the default do-not-unfollow protection list and its regression
  assertions. ([61a95264])

## 2026-10-27

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

## 2026-09-29

- Used the bundled jokebook for tagged request replies, capped replies per
  requester and run, and kept reply selection separate from scheduled-post
  duplicate avoidance. ([53a8e080])
- Recorded issue completion requirements: link the issue in the substantive
  commit, verify remote checks and confirm completed issues are closed.
  ([c8406538])

## 1.0.0 - 2026-09-28

- **Packaging (28 September):** Set the application package version to `1.0.0`,
  consolidated direct/development dependencies and build metadata, and retained
  the installed commands introduced earlier in September. ([d84f95fd])
- **Joke requests (27-28 September):** Added tagged requests, persisted scan
  checkpoints and atomic reply state. Protected against duplicate jokes after
  ambiguous post responses. ([f3644cf3], [89030f5c], [ddbf6fab])
- **Domain boundaries (27-28 September):** Separated posting, moderation and
  social state, dashboard collection and social processing while preserving
  workflow commands. ([50dfb60c], [5300297a], [8cec842e], [5ccfc1e3], [298f8107])
- **Persistence (27-28 September):** Centralised workflow state commits,
  constrained persistence targets and checked out current `main` on social
  reruns rather than replaying stale snapshots. Added operational persistence
  canaries. ([7ea20ded], [180f0970], [765d9e75], [3021aac2])
- **Quality (27 September):** Enforced 90% overall Python coverage and
  changed-executable-line coverage, including validation of comparison
  revisions. ([a0081f8d], [b5cf438e])
- **Dependency automation (28 September):** Hardened trusted merge checks and
  restricted CI-event checks to Dependabot branches; applied CodeQL Action
  updates. ([9a8ff330], [786bc635])
- **Documentation (28 September):** Separated the project overview, operations
  procedures and working priorities, moving condensed history into this log.
  The dated backfill above and below restores detail lost in that consolidation.
  ([c3c40094])

## 0.8.0 - September 2026

- **Dependencies (14-21 September):** Updated the atproto SDK, regex, locked
  Pyright tool and Sonar scanning action. ([2bd9115d], [1dae4103], [903101eb],
  [1376bdde])
- **Packaging (12 September):** Established an installable package and central
  repository-path contracts, moved shared modules under the package, installed
  application commands and locked the build backend. This initially used
  placeholder package version `0.0.0`; this log's retrospective milestone
  labels do not change that metadata.
  ([c111bdd7], [92fa0b39])
- **Dashboard scheduling (12 September):** Kept collection on its bounded
  schedule after reverting a refresh-after-operational-workflows experiment.
  ([e118e208])
- **Account protection (12 September):** Expanded the reviewed do-not-unfollow
  defaults. ([79888769])
- **Audience (5 September):** Added source cohorts, aggregate audience-growth
  views and 30/90-day relationship outcomes, with privacy-bounded retention and
  starter-pack context. The outgoing-follow labels were clarified in October.
  ([8d00537e])
- **Top jokes (5 September):** Replaced plain joke cards with native Bluesky
  embeds and responsive layout. ([6055f7e6], [d57e21c9])
- **Type checks and Git discipline (5 September):** Enforced first-party Python
  type checks using locked Pyright and separated validation from pushing.
  ([8cddb812], [cb71e122])
- **Reference policy (5 September):** Stopped automated reference-submodule
  updates, keeping upstream resources outside first-party maintenance.
  ([d1b45282])
- **Sonar and CI (1 September):** Imported coverage, enforced the quality gate
  and exactly zero unresolved issues, scoped analysis to first-party code and
  remediated security findings. ([f24ca035], [91ffacd7], [3ffc3219])
- **Follow-back (1 September):** Extended graph pagination to avoid missing
  accounts on large graphs and stopped excluding current followers because of
  past unfollows. This corrected the follow-back history guard added in August;
  interaction-led following retained its churn protection.
  ([21bb6586], [3069c973])

## 0.7.0 - August 2026

- **Dashboard history and navigation (31 August):** Retained monthly metric
  archives, separated Audience and Operations views and exposed operational
  information without requiring expansion. Added starter-pack follow
  attribution. ([bc5650ee], [dd6e38b1], [026024f6])
- **Account protection (31 August):** Added another reviewed default
  do-not-unfollow protection. ([2214acb8])
- **Provider rotation (25 August):** Advanced rotation from the scheduled
  primary, preventing fallback failures from repeatedly skewing later runs.
  Promoted Syrsly to the reviewed primary pool and distinguished scheduled from
  published provider counts. ([103adb96])
- **Posting provenance and engagement (24 August):** Retained the hashtags
  attached to each post, added period filters for top jokes and clarified
  provider engagement averages. ([3a2f5440], [f62760c6], [965a6a44])
- **Operational metrics (23-24 August):** Added discovery-run outcomes,
  scheduled-delivery reporting, social activity, moderation momentum and
  provider-pressure trends. ([3a123d34], [e14e9641], [6db495ee], [9b5d124e],
  [84978f94])
- **Dashboard launch (22 August):** Published a six-hourly GitHub Pages
  dashboard showing public aggregate account, posting and engagement metrics
  without credentials. Added operational health and reconstructed recent
  account history. ([03332e62], [75f8c245], [92dae92f])
- **State and safety (22-23 August):** Split runtime state by purpose, isolated
  corrupt domain reads, persisted sessions securely and restored configured
  account blocks without unblocking unmanaged accounts.
  ([4b5d8317], [66373122], [978eb405], [305d1b6e])
- **Provider health (22-23 August):** Split rejection reasons in telemetry and
  made provider monitoring deterministic. ([ea8296f2], [c30a4ea4])
- **Unfollow capacity (22 August):** Derived monthly action capacity rather than
  treating every run as an unrelated full-sized clean-up. ([3a0bbb6f])
- **Transport and sessions (17-19 August):** Hardened cached-session recovery
  and retried transient Bluesky responses. ([cf59e3a4], [cd168ef1])
- **Social scheduling (7 August):** Staggered state-writer schedules to avoid
  contention cancelling scheduled posting, and added unfollow-history checks
  to follow-back. The latter was corrected on 1 September.
  ([888e0d86], [4e51d162])
- **Dependencies (24 August):** Updated the atproto SDK and python-dotenv.
  ([28984f61], [7d9711f7])

## 0.6.0 - July 2026

- **State transactions (25 July):** Added locked updates against the latest
  on-disk state, migrated straightforward writers and hardened report PR bodies
  and fail-closed duplicate detection. ([3f1b51e6])
- **Hashtag precedence (17 July):** Restored the configured rotation pool's
  precedence after the posting configuration refactor. ([218b50ca])
- **Report safety and runtime consistency (8 July):** Cleaned temporary PR
  branches on failure, bounded unresolved report-notification retries, aligned
  post verification with runtime configuration and hardened session persistence.
  ([78282227], [7043e369])
- **Posting configuration (8 July):** Centralised resolved hashtag configuration
  and made the posting pool its single source of truth. ([fd7d042e])
- **Smart hashtags (6 July):** Replaced predictable sliding windows with
  reproducible shuffled selection, prevented near-duplicate tag pairs and
  fitted one to three tags into each joke's available length budget. Hardened
  tag validation and fallback-path coverage. ([d814a9a7], [69727bb0])
- **Account protection (9 and 28 July):** Expanded the do-not-unfollow defaults
  through reviewed account-protection changes. ([a1979cb7], [c10cd321])
- **Dependencies (20 July):** Updated setup-python to its next major Action
  version. ([7f5f18ef])

## 0.5.0 - June 2026

- **Hashtag rotation (20 June):** Introduced persisted posting-tag rotation and
  per-post dynamic length budgeting. July's smart selection superseded the
  initial sliding-window approach. ([557e59e2])
- **Behaviour changes (13 June):** Extended duplicate-suppression retention from
  365 to 730 days, reduced follow-response grace from 90 to 30 days and changed
  unfollow clean-up from quarterly to monthly. These are historical defaults,
  not a substitute for current runtime configuration. ([99a2a17c])
- **Dependencies (22-29 June):** Updated checkout/cache Actions and refreshed
  atproto and pytest requirements. ([652346e4], [77e9c34f], [ec6b3d42],
  [dc3b87d0])

## 0.4.0 - May 2026

- **Docs-only CI (24 May):** Added documentation-only change detection so
  Python test and Ruff jobs could skip expensive steps while still reporting
  successful checks. The local SDLC exception was made explicit in November.
  ([91f442ac])
- **Grace tracking (23 May):** Reconciled manual follows with follow-response
  grace rather than treating them as untracked accounts. ([da22a47e])
- **Quality (19-20 May):** Added local workflow linting, coverage gating and
  complexity checks, excluding read-only references from first-party analysis.
  ([9fbc34f2], [6492db1b])
- **Configuration (16-20 May):** Introduced central runtime JSON, schema
  validation, environment overrides and workflow-schedule alignment; completed
  rollout across posting, discovery, unfollow, reports and follows/likes.
  Cadence-aware guardrails rejected risky combinations of schedules and action
  limits, including booleans passed as numeric configuration.
  ([e4bec844], [3d078d5d], [f48833f4], [a9713fd4])
- **Transport recovery (17-19 May):** Replaced the blocked httpx TLS transport
  with requests/urllib3 after Bluesky's WAF rejected the runner fingerprint.
  Removed temporary connectivity workarounds and restored operational workflows
  in stages. ([4d2a0b9b], [2ad20f34])
- **Interaction-led follows (16 May):** Followed eligible authors of recent
  replies, reposts and likes, recording interaction attribution and applying
  grace and churn protections. ([7c5a60f7])
- **Authentication and privacy (13-20 May):** Required configured usernames,
  introduced app-password preference and strengthened credential/identifier
  redaction in operational and report-error logs.
  ([23e696aa], [f974c032], [1ff28d03], [d7593c80])
- **Providers and duplicates (13 May):** Added scheduled provider-health checks
  and treated punctuation-only joke variants as duplicates while preserving
  stored text for history and moderation. ([97ad7446], [b4336b25])
- **Account protection (13 May):** Extended the default do-not-unfollow list
  through reviewed account-protection changes. ([ad4e92e4], [26e52cd0])
- **Social reach (3 May):** Expanded hashtag discovery, action limits and
  rotation, and introduced a follow-back grace period before automatic unfollow.
  ([6c90c3fe], [a3a98c26])
- **Provider policy (3 May):** Reorganised provider tiers and extended
  deduplication memory. ([9bc6e216])
- **Posting frequency (2 May):** Increased scheduled jokes from three to six
  per day. ([4910484e])
- **Starter packs (1-3 May):** Added list-to-starter-pack management, protected
  members from automated unfollow, validated record identifiers and supported
  previewing/persisting live name and description metadata. ([2ec49c6a],
  [0a739bc3])
- **Posting and quality foundations (1 May):** Counted post length in visible
  grapheme clusters, introduced enforced Ruff formatting/lint and CodeQL CI,
  and established the local preflight gate shortly afterwards.
  ([47087060], [f979eaf6], [2c6c5819], [7ec0da8f])
- **Discovery experiment (1 May):** Removed the initial custom-feed audit and
  discovery integration. Saved-feed discovery returned as a bounded feature in
  October; it was not continuously supported throughout this period.
  ([3e2327a5], [7d89bcad])
- **Dependencies (4-25 May):** Refreshed pytest and requests requirements and
  the paths-filter Action. ([ddd3f160], [33299eae], [ff0cd791])

## 0.3.0 - April 2026

- **Provider expansion (21-29 April):** Added GroanDeck as a third primary joke
  source and Syrsly as a backup. ([25895438], [29a73763])
- **Posting text (21 April):** Skipped over-length jokes before API submission,
  repaired mojibake and normalised quotes; May's grapheme-aware guard refined
  the length calculation. ([5e73d243], [6375509e])
- **Reliability (21 April):** Added bounded network retries across automation,
  including transient report-login failures, and aligned workflow Python
  runtimes to 3.12. ([5a0f415e], [f3a87c49], [384fe619])
- **Unfollow safety (20 April):** Added cautious batching with action caps,
  rate-aware stops and pauses. Recorded unfollow history to prevent repeated
  discovery churn, and persisted that history across CI runs.
  ([77ebe258], [c4838ec8], [4535facc])
- **Report moderation (19-20 April):** Turned `#report` replies into reviewed
  denylist PRs, deleted approved reported posts on the next processing run,
  acknowledged reports without liking them, and removed reported bundled jokes
  from the jokebook. ([920fa8ca], [cdc77595], [9dedacd9], [b9f77663])
- **Social engagement (19-29 April):** Added likes for recent replies and repost
  interactions, limiting reply processing to the previous 24 hours.
  ([f9a631b1], [921e58db], [02161dd3])
- **Joke resilience and state (19 April):** Introduced shared provider/state
  modules, provider rotation, persisted JSON joke history and a permanent
  denylist. Added API Ninjas as a backup and a bundled offline jokebook as the
  final fallback. ([f3f47240], [f39bc1dc], [e58f6386], [8bb7dd9d])
- **Error handling and privacy (19 April):** Replaced overly broad network
  catches with specific exceptions, improved deletion/acknowledgement handling,
  reduced sensitive logging and added provider/report regression coverage.
  ([ce9eea2a], [294de59c], [f310b423], [9d6f2725])
- **Automation (19-28 April):** Added state-push rebase/retry and workflow
  concurrency safeguards. Introduced Dependabot minor/patch update automation
  with passing tests as a merge prerequisite and Node 24-compatible Actions.
  ([ac2f2a5b], [78025b2c], [78d52894], [47cd53c8])
- **Safe local operation (18 April):** Added `.env` loading, dry-run and action
  delay controls, repaired follower-search parameters and introduced a read-only
  latest-post verifier with focused unit coverage.
  ([25b25875], [09e5a7e6], [073f552f], [5a8406ef])

## 0.2.0 - 2025

- **June:** Added per-run follow limits, repaired search/API parameter handling
  and dependency installation, and improved follower-generation diagnostics.
  ([0ea84480], [5db73ffc], [88e8a24b])
- **April:** Added persisted duplicate-joke protection and seeded history with
  previously posted jokes recovered from workflow logs. ([7ee7a86a], [a9c7b5f5])
- **February:** Added hashtag-based follower generation, improved joke
  punctuation/encoding handling and restored suspended automation.
  ([e468bf55], [07df1812], [0311a96d])
- **January:** Split follow and unfollow processing onto separate schedules and
  introduced protection for selected accounts. ([64aab0a3], [7f8cd6d2])

## 0.1.0 - 2024-12-10

- Created the scheduled Bluesky joke bot, its initial project documentation
  and follow/unfollow automation. ([625fab5e], [381faf8e], [432b8120])

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
[02161dd3]: https://github.com/chris-gillatt/thejokebot/commit/02161dd34ba697f58fd5fdeda7e7c40af5c34485
[026024f6]: https://github.com/chris-gillatt/thejokebot/commit/026024f66af9f4198e847d1308146cee484b7cba
[0311a96d]: https://github.com/chris-gillatt/thejokebot/commit/0311a96d225e39ab80f2b2114696ba24910b5fa1
[03332e62]: https://github.com/chris-gillatt/thejokebot/commit/03332e62e195e44a1a580c672d9fac5aafac374e
[073f552f]: https://github.com/chris-gillatt/thejokebot/commit/073f552f33d825040896c430ceac00ca8c492a32
[07df1812]: https://github.com/chris-gillatt/thejokebot/commit/07df18125f1e3f78b0b25778f180881ecc47ddbc
[09e5a7e6]: https://github.com/chris-gillatt/thejokebot/commit/09e5a7e6a67f90691b49992d8dcf4ed255a45ff9
[0a739bc3]: https://github.com/chris-gillatt/thejokebot/commit/0a739bc3d0066c0f7840e30b0e19d9b76f6c9915
[0ea84480]: https://github.com/chris-gillatt/thejokebot/commit/0ea84480a712ea2d98c87f0b134ca647fb0c374e
[103adb96]: https://github.com/chris-gillatt/thejokebot/commit/103adb968df134de576e7dcae32ef157a49da6e8
[1376bdde]: https://github.com/chris-gillatt/thejokebot/commit/1376bdde1709fb933ebc5467c5acc23a1f7b09fd
[180f0970]: https://github.com/chris-gillatt/thejokebot/commit/180f09708f3b0bbd929dd78d03e2b6231b379bf2
[1dae4103]: https://github.com/chris-gillatt/thejokebot/commit/1dae4103fa14de37bf9009aa0a52a250afff9fe0
[1ff28d03]: https://github.com/chris-gillatt/thejokebot/commit/1ff28d0300d157ee951a54a01891e65629491c2a
[218b50ca]: https://github.com/chris-gillatt/thejokebot/commit/218b50ca369fd053a294ecf7a2240c957f245f44
[21bb6586]: https://github.com/chris-gillatt/thejokebot/commit/21bb6586f7f9c664641282e37b4fd2588e12002b
[23e696aa]: https://github.com/chris-gillatt/thejokebot/commit/23e696aab584790fe256ce6e85288cc4717dff5e
[25895438]: https://github.com/chris-gillatt/thejokebot/commit/25895438b9d1f209971178839da4fa18db901494
[25b25875]: https://github.com/chris-gillatt/thejokebot/commit/25b25875668d878293c1ad2aa0376a9f30707ac6
[28984f61]: https://github.com/chris-gillatt/thejokebot/commit/28984f61a89bf723238044fbfae081725f0fa097
[294de59c]: https://github.com/chris-gillatt/thejokebot/commit/294de59c9c0f8527349380748840debc6aca90a6
[298f8107]: https://github.com/chris-gillatt/thejokebot/commit/298f8107e3ef209acae0bc48b1524beef6271f6f
[29a73763]: https://github.com/chris-gillatt/thejokebot/commit/29a73763f2946b78bc98f993ef85695b7903a306
[2ad20f34]: https://github.com/chris-gillatt/thejokebot/commit/2ad20f346010ed875ebf4a6c91aff2e651c84b41
[2bd9115d]: https://github.com/chris-gillatt/thejokebot/commit/2bd9115d43977cb63b77e9bdf46592732f99d0d3
[2c6c5819]: https://github.com/chris-gillatt/thejokebot/commit/2c6c58190699402ab3592f7bec771fb6640fc1a9
[2ec49c6a]: https://github.com/chris-gillatt/thejokebot/commit/2ec49c6a42c8590751d8b142c37862459e2bcc12
[3021aac2]: https://github.com/chris-gillatt/thejokebot/commit/3021aac2c605d237a0c21d9fd14865f184f4c4ae
[305d1b6e]: https://github.com/chris-gillatt/thejokebot/commit/305d1b6e9bf6f9db183513d0b783487fcf62ca53
[3069c973]: https://github.com/chris-gillatt/thejokebot/commit/3069c9736385cbf4083b7038557a8ab24c176078
[33299eae]: https://github.com/chris-gillatt/thejokebot/commit/33299eaef70049da66754c188e2ce55a0b96b57b
[381faf8e]: https://github.com/chris-gillatt/thejokebot/commit/381faf8e0e1b057508bbd1b3eb624f9e704c0a06
[384fe619]: https://github.com/chris-gillatt/thejokebot/commit/384fe619ab715a86eeb15bc7c66b5b21313a579a
[3a0bbb6f]: https://github.com/chris-gillatt/thejokebot/commit/3a0bbb6f50aa8e0f2c778a0be7534c6d44be48c9
[3a123d34]: https://github.com/chris-gillatt/thejokebot/commit/3a123d342462dc9abdf047c7d48cc812bdccbfc8
[3a2f5440]: https://github.com/chris-gillatt/thejokebot/commit/3a2f54405bdd1d9026882578e18cf9066a4ea1ba
[3d078d5d]: https://github.com/chris-gillatt/thejokebot/commit/3d078d5da891f1aba1645151bf0cae750f52f960
[3e2327a5]: https://github.com/chris-gillatt/thejokebot/commit/3e2327a5932e5a632021f29d6492ec77ad7b5eec
[3f1b51e6]: https://github.com/chris-gillatt/thejokebot/commit/3f1b51e6669d7bc164b3d46948b14685da753aae
[3ffc3219]: https://github.com/chris-gillatt/thejokebot/commit/3ffc3219c6259f822f90e34b19ac982b9616b6ad
[432b8120]: https://github.com/chris-gillatt/thejokebot/commit/432b81208982ce86000f12026847bd7a5014fa95
[4535facc]: https://github.com/chris-gillatt/thejokebot/commit/4535faccbead91e7f1c1e3b9f0930f8bf9b64b2c
[47087060]: https://github.com/chris-gillatt/thejokebot/commit/4708706011c35559e3e81449acdef16c69a3f555
[47cd53c8]: https://github.com/chris-gillatt/thejokebot/commit/47cd53c8b9fb501cb100f33d0c5e4dee82299c3e
[4910484e]: https://github.com/chris-gillatt/thejokebot/commit/4910484e8ab0d94c50c8d62efc7edb613731630a
[4b5d8317]: https://github.com/chris-gillatt/thejokebot/commit/4b5d8317c80605ca388894f49694c962a2bc5c20
[4d2a0b9b]: https://github.com/chris-gillatt/thejokebot/commit/4d2a0b9b442a89cafc7cf16c3c0d33ccf0e8002c
[4e51d162]: https://github.com/chris-gillatt/thejokebot/commit/4e51d162ac2a8b45e6a3fd02a188fe6ab2b68893
[50dfb60c]: https://github.com/chris-gillatt/thejokebot/commit/50dfb60c44947a35c49391d7fd8c566319f3b87c
[5300297a]: https://github.com/chris-gillatt/thejokebot/commit/5300297aa1aee0ed06d3a027d3ad5b936a65f396
[557e59e2]: https://github.com/chris-gillatt/thejokebot/commit/557e59e2815f9e47ff439b9c1db1cba3516b451c
[5a0f415e]: https://github.com/chris-gillatt/thejokebot/commit/5a0f415eda8b9a8cfcb23364db0005dcd21d3b75
[5a8406ef]: https://github.com/chris-gillatt/thejokebot/commit/5a8406ef1b92e4e4b7feb18ab0872324f78462ca
[5ccfc1e3]: https://github.com/chris-gillatt/thejokebot/commit/5ccfc1e343741c6822a7508861903d6105b872ec
[5db73ffc]: https://github.com/chris-gillatt/thejokebot/commit/5db73ffc6f6bcfc9dfd384e8a6bfc5ebd2e934c9
[5e73d243]: https://github.com/chris-gillatt/thejokebot/commit/5e73d24313c0c9d359443515ee263c5f59a89e80
[6055f7e6]: https://github.com/chris-gillatt/thejokebot/commit/6055f7e692a1ecbfd55d2274d8fb5e774a4dec31
[625fab5e]: https://github.com/chris-gillatt/thejokebot/commit/625fab5eecdb44f1b9100b0c3be8a75f2d4fe4ae
[6375509e]: https://github.com/chris-gillatt/thejokebot/commit/6375509ef18674d23cc64ba9ad54325b9551d10e
[6492db1b]: https://github.com/chris-gillatt/thejokebot/commit/6492db1b0a434aa896e4d66798eb09084a4d6f16
[64aab0a3]: https://github.com/chris-gillatt/thejokebot/commit/64aab0a3605433401dad02c9fb7d3a1597f92ad2
[652346e4]: https://github.com/chris-gillatt/thejokebot/commit/652346e4d29dda91e930aeaca94a9fafaeeb3dd0
[66373122]: https://github.com/chris-gillatt/thejokebot/commit/6637312236045e4da2808730eba74602cacada4f
[69727bb0]: https://github.com/chris-gillatt/thejokebot/commit/69727bb070909da070297ee39fb13e927c457aba
[6c90c3fe]: https://github.com/chris-gillatt/thejokebot/commit/6c90c3fee1e136b720dc44d9951509114a790320
[6db495ee]: https://github.com/chris-gillatt/thejokebot/commit/6db495eea014da0a92865e49d8c68db2d9171484
[7043e369]: https://github.com/chris-gillatt/thejokebot/commit/7043e3692046db6f43e51ee6698326f821ef7580
[75f8c245]: https://github.com/chris-gillatt/thejokebot/commit/75f8c2458b25d37af44591386a424b9668376fc2
[765d9e75]: https://github.com/chris-gillatt/thejokebot/commit/765d9e759eba6f75d36f010cf31ebc80de4feb2e
[77e9c34f]: https://github.com/chris-gillatt/thejokebot/commit/77e9c34f91e34d4966e453317560502cc4888b9e
[77ebe258]: https://github.com/chris-gillatt/thejokebot/commit/77ebe25866dafe2d9395f15d80e0f8287062184f
[78025b2c]: https://github.com/chris-gillatt/thejokebot/commit/78025b2ceb46210b3aa9abb3bcaa5b55a8efea35
[78282227]: https://github.com/chris-gillatt/thejokebot/commit/78282227e4bb5ec1ff91faa6f9bcc986104218cf
[786bc635]: https://github.com/chris-gillatt/thejokebot/commit/786bc635c1ac8ef2146fa9582a2c1faa32b6fbd8
[78d52894]: https://github.com/chris-gillatt/thejokebot/commit/78d528949eb8f2e5a7e4ab2cc574d0752b3216eb
[7c5a60f7]: https://github.com/chris-gillatt/thejokebot/commit/7c5a60f795f623874c9e00c2da141f0dd911591b
[7d9711f7]: https://github.com/chris-gillatt/thejokebot/commit/7d9711f7d2d084e59e5100dc5b95080803c980d1
[7ea20ded]: https://github.com/chris-gillatt/thejokebot/commit/7ea20ded497934e713172f35377bb9d9eae17eac
[7ec0da8f]: https://github.com/chris-gillatt/thejokebot/commit/7ec0da8f2b7ba5b1526daf80585652c143a77a0f
[7ee7a86a]: https://github.com/chris-gillatt/thejokebot/commit/7ee7a86ac4f3fc2d3a51ad6d2a755910a3b68b59
[7f3b39bb]: https://github.com/chris-gillatt/thejokebot/commit/7f3b39bb3a895c68fb21851b935d8dc4644eb5b3
[7f5f18ef]: https://github.com/chris-gillatt/thejokebot/commit/7f5f18efc6b2625dbf7bac233d9b6b0d18bf006b
[7f8cd6d2]: https://github.com/chris-gillatt/thejokebot/commit/7f8cd6d2ddd5d8acfe74799bec771ac38c88145c
[84978f94]: https://github.com/chris-gillatt/thejokebot/commit/84978f9428799d020d9468e903126a3ef7fcbe00
[888e0d86]: https://github.com/chris-gillatt/thejokebot/commit/888e0d86e28d6aba9eea31f8c6def03bd615ae7b
[88e8a24b]: https://github.com/chris-gillatt/thejokebot/commit/88e8a24b0df8b6175386856b88b5ff91a7f2610f
[89030f5c]: https://github.com/chris-gillatt/thejokebot/commit/89030f5c590934210f493b3e2866da88b12bb7b0
[8bb7dd9d]: https://github.com/chris-gillatt/thejokebot/commit/8bb7dd9dc8d699e28ef45915c70cdffc34358743
[8cddb812]: https://github.com/chris-gillatt/thejokebot/commit/8cddb812fde10588f4449c01d65189a6ea87e7e8
[8cec842e]: https://github.com/chris-gillatt/thejokebot/commit/8cec842e6c6a547c490df574d8bcd7b842740bb9
[8d00537e]: https://github.com/chris-gillatt/thejokebot/commit/8d00537e391da0ecf0604d30a1a24fe63580d5b9
[903101eb]: https://github.com/chris-gillatt/thejokebot/commit/903101eb88628faad469b97f3c0f44c184c9307e
[91f442ac]: https://github.com/chris-gillatt/thejokebot/commit/91f442ac4ae703a2b9ed3b89f7fc606458c9a6c7
[91ffacd7]: https://github.com/chris-gillatt/thejokebot/commit/91ffacd78d817149a0f371aab6aeb7a5c1b85436
[920fa8ca]: https://github.com/chris-gillatt/thejokebot/commit/920fa8ca4162271d34c83af0aaf85892c4d795ec
[921e58db]: https://github.com/chris-gillatt/thejokebot/commit/921e58db6f5b088d1387005074a61618ba94e055
[92dae92f]: https://github.com/chris-gillatt/thejokebot/commit/92dae92f61e1fd971dccbba2dae086ff77c081e9
[92fa0b39]: https://github.com/chris-gillatt/thejokebot/commit/92fa0b3969a7ba058ebc15ddfd9d24ce993d38e6
[965a6a44]: https://github.com/chris-gillatt/thejokebot/commit/965a6a4462babe757a547d27ae2803bb81f62a9b
[978eb405]: https://github.com/chris-gillatt/thejokebot/commit/978eb405eefcba07978fa5be9727392390a7bdf7
[97ad7446]: https://github.com/chris-gillatt/thejokebot/commit/97ad744670ceb115d5606b64561c81b45c712fe7
[99a2a17c]: https://github.com/chris-gillatt/thejokebot/commit/99a2a17ccc4b14393ffc0707f2134ef72a715219
[9a8ff330]: https://github.com/chris-gillatt/thejokebot/commit/9a8ff330a30c6ff01161ab6d64105e5b6f45f1b5
[9b5d124e]: https://github.com/chris-gillatt/thejokebot/commit/9b5d124e4690bbc36d574858d39ab25b7b13fd41
[9bc6e216]: https://github.com/chris-gillatt/thejokebot/commit/9bc6e216a58f8e94daa27d72539faa535acf4bc3
[9d6f2725]: https://github.com/chris-gillatt/thejokebot/commit/9d6f272555d77b22930f5fb5ab6fe5b2f82a0406
[9dedacd9]: https://github.com/chris-gillatt/thejokebot/commit/9dedacd94b0f1b75bebae7739afbc4117bff5aff
[9fbc34f2]: https://github.com/chris-gillatt/thejokebot/commit/9fbc34f2c53e8a21a246ba8f81d23d648daed088
[a0081f8d]: https://github.com/chris-gillatt/thejokebot/commit/a0081f8de852fc90efc964dabe808f062e0599ce
[a1979cb7]: https://github.com/chris-gillatt/thejokebot/commit/a1979cb70b99ecf3c913ffe84dbbff161f0d543e
[a3a98c26]: https://github.com/chris-gillatt/thejokebot/commit/a3a98c263168f7de40e759972916305a4937858b
[a6f3aaf0]: https://github.com/chris-gillatt/thejokebot/commit/a6f3aaf0e7f5b6aa22f99989ea3d6209132bd525
[a9713fd4]: https://github.com/chris-gillatt/thejokebot/commit/a9713fd4391ed1689082cee7f2fe695e208b1f76
[a9c7b5f5]: https://github.com/chris-gillatt/thejokebot/commit/a9c7b5f5cb94f2adda8d6a5a157b95fc8331ff2a
[ac2f2a5b]: https://github.com/chris-gillatt/thejokebot/commit/ac2f2a5b42815e88e1128e69950ed42ebd21555e
[b4336b25]: https://github.com/chris-gillatt/thejokebot/commit/b4336b25ced675cd81ffc3d61488cf8d372675a2
[b5cf438e]: https://github.com/chris-gillatt/thejokebot/commit/b5cf438e6f815f41eaadfe48b0e69680bf7ec373
[b9f77663]: https://github.com/chris-gillatt/thejokebot/commit/b9f776634852207b9e7932abf77d34419622b49e
[bc5650ee]: https://github.com/chris-gillatt/thejokebot/commit/bc5650eed0819774443fde295dc571330d3e6f38
[c10cd321]: https://github.com/chris-gillatt/thejokebot/commit/c10cd321517e602ca29e833036495431b0f98ba5
[c111bdd7]: https://github.com/chris-gillatt/thejokebot/commit/c111bdd7ba0def559a8d343f661bedd46c8404a7
[c30a4ea4]: https://github.com/chris-gillatt/thejokebot/commit/c30a4ea40c197486b000582b8db79d0e3c976148
[c3c40094]: https://github.com/chris-gillatt/thejokebot/commit/c3c40094066c9d8c01ff7150a4b053dab4e000d2
[c4838ec8]: https://github.com/chris-gillatt/thejokebot/commit/c4838ec84ed31be1ac2dffdf992232ef768edaf2
[cb71e122]: https://github.com/chris-gillatt/thejokebot/commit/cb71e1226c97a763aad24c59f6eae07581414500
[cd168ef1]: https://github.com/chris-gillatt/thejokebot/commit/cd168ef1c0b5cad741771870ab454bcecbba8523
[cdc77595]: https://github.com/chris-gillatt/thejokebot/commit/cdc775955f5cac576b972af64e71f6a229324f24
[ce9eea2a]: https://github.com/chris-gillatt/thejokebot/commit/ce9eea2a774e75745d68c7bb1668ee7ab29dcc08
[cf59e3a4]: https://github.com/chris-gillatt/thejokebot/commit/cf59e3a4e5a7cf759ac46cc333e41faf4dbad3f8
[d1b45282]: https://github.com/chris-gillatt/thejokebot/commit/d1b45282efb755c5f5a64dee404b25ecc74bbe12
[d57e21c9]: https://github.com/chris-gillatt/thejokebot/commit/d57e21c931a01b19128db9e8cf4e02faa1fda6a5
[d7593c80]: https://github.com/chris-gillatt/thejokebot/commit/d7593c800de0aaf8579d06fdf1116e69d6ef071c
[d814a9a7]: https://github.com/chris-gillatt/thejokebot/commit/d814a9a73fad0a82c308a37fba65174ecc0535e9
[d84f95fd]: https://github.com/chris-gillatt/thejokebot/commit/d84f95fd497ade55526fe75765cf35b8e971a36d
[da22a47e]: https://github.com/chris-gillatt/thejokebot/commit/da22a47e1cd647c55314c168a900cd5e04d3887e
[dc3b87d0]: https://github.com/chris-gillatt/thejokebot/commit/dc3b87d080bc9f287b6da19aa6749413c0e4ffd0
[dd6e38b1]: https://github.com/chris-gillatt/thejokebot/commit/dd6e38b1cf2f04f0b766e78743d3c4401449a12b
[ddbf6fab]: https://github.com/chris-gillatt/thejokebot/commit/ddbf6fab4fed6358538a248dde7ae0b7b6b589ac
[ddd3f160]: https://github.com/chris-gillatt/thejokebot/commit/ddd3f160050bb908d7746cd63f0461e114a3ae43
[e118e208]: https://github.com/chris-gillatt/thejokebot/commit/e118e208f05bc94f9a1fb4ab70f99920ebbcde55
[e14e9641]: https://github.com/chris-gillatt/thejokebot/commit/e14e96418c0ca309b5b8560e995d447ec23ad311
[e468bf55]: https://github.com/chris-gillatt/thejokebot/commit/e468bf55c2a3090139447c7851f556b827ffc0dd
[e4bec844]: https://github.com/chris-gillatt/thejokebot/commit/e4bec84400dca298a61c12161a5f8ce8e477af8b
[e58f6386]: https://github.com/chris-gillatt/thejokebot/commit/e58f6386cb1a68207f02ebe7ad8f674cfd6facb2
[ea8296f2]: https://github.com/chris-gillatt/thejokebot/commit/ea8296f2c6ffd0027370d1afd48a20fb8f0d8e53
[ec6b3d42]: https://github.com/chris-gillatt/thejokebot/commit/ec6b3d4242c83b2fc8c08071ed21ade054fce13c
[f24ca035]: https://github.com/chris-gillatt/thejokebot/commit/f24ca0353630266aef1bdf32fc49ad803d7830a4
[f310b423]: https://github.com/chris-gillatt/thejokebot/commit/f310b423e4a7f5532dd5da9dae7c4f7fd91f491a
[f3644cf3]: https://github.com/chris-gillatt/thejokebot/commit/f3644cf34eca334cc8875585569c7f2d1b10203f
[f39bc1dc]: https://github.com/chris-gillatt/thejokebot/commit/f39bc1dc6f68b15c607957b1d89de30d976856a0
[f3a87c49]: https://github.com/chris-gillatt/thejokebot/commit/f3a87c49efa22218939c037749b25eec12fda037
[f3f47240]: https://github.com/chris-gillatt/thejokebot/commit/f3f47240474dcb45c21e79543d7e342afbaf0209
[f48833f4]: https://github.com/chris-gillatt/thejokebot/commit/f48833f49a46ece1156c333ac6c0ff457b02cc40
[f62760c6]: https://github.com/chris-gillatt/thejokebot/commit/f62760c61b0989ab6beff137b2d8cbb9432e0fc5
[f974c032]: https://github.com/chris-gillatt/thejokebot/commit/f974c032de6a5cbd15a1d63a83580cb353fb902b
[f979eaf6]: https://github.com/chris-gillatt/thejokebot/commit/f979eaf632ea4bcc6d5db637b00614e33efa402e
[f9a631b1]: https://github.com/chris-gillatt/thejokebot/commit/f9a631b1b37611f09383f07ef2e5a2f00e24227a
[fd7d042e]: https://github.com/chris-gillatt/thejokebot/commit/fd7d042ef873974c87fe58aee9bcaab56c1c2d9e
[ff0cd791]: https://github.com/chris-gillatt/thejokebot/commit/ff0cd791ba0c63e9c691d831cdf62fe4c7b18e90
[79888769]: https://github.com/chris-gillatt/thejokebot/commit/7988876908223abdc95b610ce28020ec06b95ebe
[2214acb8]: https://github.com/chris-gillatt/thejokebot/commit/2214acb8915d905b4a3dbe2e1dbce69c36e11a5d
[ad4e92e4]: https://github.com/chris-gillatt/thejokebot/commit/ad4e92e40a48600ea1a8f745dbdb43601eb34901
[26e52cd0]: https://github.com/chris-gillatt/thejokebot/commit/26e52cd03af25d3f42ca302ba8422ef736e98b10
[historical-milestones]: https://github.com/chris-gillatt/thejokebot/blob/1c4fb2667f40dd1a3a12ecfa605e29b970e1ed9f/problem-statement.md#8-changelog-milestones
[e5818a6b]: https://github.com/chris-gillatt/thejokebot/commit/e5818a6ba570e36df4c94a6aa534c053f9613003