# The Joke Bot: Current Priorities

This is the operating brief for open work and lasting decisions. See the [README](README.md) for the product overview, the [operations guide](docs/operations.md) for procedures and the [changelog](CHANGELOG.md) for completed milestones. Detailed implementation history remains in Git commits and PRs.

## Working Principles

- Preserve existing posting, moderation and follow behaviour unless a change explicitly calls for it. Keep changes focused and reversible.
- Keep credentials and audience identifiers out of published data and source control. Use British English in documentation and Conventional Commits with a reason for every change.
- Update [CHANGELOG.md](CHANGELOG.md) in the same substantive commit as every meaningful first-party change, using actual commit dates, newest first. Never create or restore an `Unreleased` section. Preserve the retrospective pre-1.0.0 milestone numbers without claiming they were original releases. Check it before committing and completing work; omit routine automated state/metrics refreshes, not substantive agent or dependency changes.
- Before non-documentation pushes, run `./scripts/preflight-local.sh` separately, then sync with `git pull --rebase`, then push. Do not use a pre-push hook. The gate includes Ruff, Pyright, workflow lint, tests, coverage and local CodeQL; a passing test suite alone is insufficient.
- For docs-only changes, including prose-only agent/process guidance, skip tests, preflight, builds, code lint/type checks, coverage, CodeQL/Sonar, dependency audits and manually dispatched full CI. Review the documentation and links, confirm the diff is docs-only, run `git diff --check`, update the changelog, then rebase/push without waiting for full validation gates. Mixed code/configuration/workflow/dependency changes retain normal validation.
- Maintain at least 90% overall first-party Python coverage and 95% on changed executable lines, with focused tests for material failure paths and safety limits. Sonar analysis must pass its gate **and** report zero unresolved issues.
- Check current first-party Python, npm and GitHub Actions dependency versions before closing a non-documentation work batch; skip these audits for docs-only work. Handle upgrades separately; record a deliberate exception with current and latest stable versions, reason and review trigger below. Keep `references/` content read-only; weekly Dependabot PRs refresh only the three registered upstream pins and auto-merge after their applicable checks. Reference-only PRs skip Python tests, coverage and Sonar; mixed first-party changes retain full validation.

## Operational Risks

| Risk | Constraint |
|---|---|
| Workflow/runtime drift | Preserve entry points, triggers, environment variables and state formats; validate schedule metadata with runtime configuration. |
| Posting, report and follow regressions | Test idempotency, pagination, provider fallback and safety caps at producer and collector boundaries. |
| Posting and checkpoint failures | Login/send failures exit non-zero; retain whether publication is confirmed in telemetry and attempt the posting checkpoint after an executed command. Never blindly retry an uncertain send. |
| Failed-attempt observation | Read exact attempt logs and retain separate workflow/run/attempt identities with observed conclusions. Measured changes can warn of uncertain persistence, never prove lost state or turn failures into successful workflows; unavailable telemetry remains unknown. |
| Approved jokebook reports | Review bundled-entry removal and the source-post denylist instruction together. Only approved resources authorise deletion; recover exact remaining resource changes, preserve unrelated exclusions and never recreate closed reviews. |
| Unfollow protection reads | Verify every configured protected handle and completely read the enabled source list before candidate reconciliation; unreadable or incomplete protection data must abort with a non-zero result. |
| Bluesky transport availability | Native SDK httpx transport passed authenticated local and independent hosted-runner checks on 2 November 2026. A prior block required an adapter, now removed. If a new block occurs, investigate and validate a replacement before changing the live path; do not assume the previous firewall cause still applies. |
| Session-cache custody | Cached sessions must stay encrypted with `BLUESKY_SESSION_CACHE_KEY`; rotating it requires a fresh credential login. Restored sessions are returned only after their authenticated DID matches the configured account; mismatches discard the cache, and unresolved transient identity reads block account actions. |
| Bluesky graph visibility | Profile counters may include hidden accounts that cannot be hydrated through follower/following queries; do not infer actionable accounts from totals. |
| Ambiguous social creates | Follow and block records use stable TID keys and exact reconciliation; interaction likes use stable record keys; starter-pack upserts use a deterministic key per account and source list. Never treat a retry with a new key as confirmation of an earlier write. |
| Content-creator protection | Completely read the bot's own likes and reposts before unfollow candidate selection. Retain creator DIDs permanently, independently of follow grace; incomplete reads must stop unfollows. Follow existing and new creators gradually, at most 10 per social run, without overriding explicit exclusions or account blocks. |

## Deferred Work

### CodeQL baseline

Triaged the full first-party security-and-quality suite on 1 November 2026.
Restored four hashtag tests that were accidentally nested and never collected,
tidied seven import findings, removed three unused private pagination aliases,
and explained the intentional Unicode-repair fallback. No actionable findings
remain from the original 18; the scanner still reports these three false
positives, without query exclusions or suppressions:

| Rule | Location | Evidence and disposition |
|---|---|---|
| `py/file-not-closed` | [State locks](src/thejokebot/state_store.py) | `ExitStack.enter_context` owns the handles. Regression tests verify closure after successful shared/exclusive locking, acquisition failure, consumer failure and unlock failure. |
| `py/exit-from-finally` | [Posting checkpoint](src/thejokebot/commands/post_joke.py) | The flagged return belongs to a lambda, not the enclosing `finally`. A regression test proves the original unexpected exception propagates while the posting checkpoint and failure telemetry are retained. |
| `py/unused-global-variable` | [Social test alias](src/thejokebot/commands/follows_and_likes.py) | `_joke_request_candidate` is used by the joke-request tests; retain the compatibility seam. |

Re-triage these if their code changes, and investigate any new findings rather
than treating a successful scanner exit as proof of clean results.
Git-persistence fixtures continue to enforce `safe.bareRepository=explicit`.

### Starter-pack inclusion

The candidate-based acknowledgement pilot builds on the read-only membership
prototype. Agreed scope: retained attributed-follow packs and explicit pack URIs;
baseline existing memberships without thanks, then acknowledge newly observed
memberships at most once per pack URI. The proposed post mentions the creator,
quotes an eligible original from the dashboard's combined-engagement top six,
and links the pack rather than creating a second share.

The manual workflow supports baseline and preview only. A permanent social-state
ledger, immutable pending intents, deterministic record keys, repository
compare-and-swap and exact-receipt verification protect local explicitly approved
publishing against repeated runs and ambiguous writes. Discovery remains partial
and inclusion dates unknown. Issue #115 remains open for approved live
desktop/mobile quote rendering, automated activation, broader discovery and any
dashboard membership claims. See the [pilot procedures](docs/operations.md#starter-pack-acknowledgement-pilot-115).

### Dashboard Resolution Time

Delivered prospective approved-post removal timing: from the bot first recording
a valid report proposal to a successful approved-post deletion. The dashboard
publishes only aggregate samples from the last 30 days and shows a median after
three completed removals. Failed deletions, reviews closed without removal and
legacy identifier-only records are excluded; there is no historical backfill or
claim to measure every report outcome. Pending timings remain in moderation
state; the latest 5,000 anonymous completed samples are retained. Timing begins
with the next persisted report scan, so the live display initially says
`Collecting`. Producer-to-collector and desktop/mobile checks cover both the
collecting state and a sufficient-sample fixture.

### Transport Review

Completed on 2 November 2026. Independent hosted-runner comparisons
([first run](https://github.com/chris-gillatt/thejokebot/actions/runs/41450167268),
[second run](https://github.com/chris-gillatt/thejokebot/actions/runs/41450315596))
and a local comparison all passed fresh native and adapter logins, authenticated
session identity checks and three profile reads per transport. Both runners
used Ubuntu 24.04, Python 3.14.10, atproto 0.0.73 and httpx 0.28.1. These runs
establish current read-only connectivity, not permanent reliability or posting.

Removed the production adapter in favour of native SDK transport, preserving
the 30-second timeout, credential selection, retry and session-cache controls.
No new dependency is required; requests remains in use by first-party providers.
The manual `bluesky_check_transport` workflow now checks native transport only,
without public/state writes or session-cache access. It fails visibly without
automatic fallback. Investigate any future block separately and evaluate
dependency/deployment implications before introducing `curl_cffi` or another
transport.

### Future Dashboard Measures

Do not claim source-specific post engagement, impressions, sentiment, demographics or individual audience outcomes without appropriate, privacy-safe source data. Keep separate the dashboard's observed history and historical estimates.

### Dashboard History Series

Measured on 10 November 2026 in the VS Code Chromium 150 browser on macOS.
Whole-array daily filtering scaled to roughly one second for three years and
2.8 seconds for five years. A weakly held UTC-day index now groups each dataset
once for reuse across rendering consumers and periods. Treat merged datasets
as read-only; fresh history creates a replacement dataset and therefore a fresh
index. No dependency or history-schema change is required.

| Selection | Days | Workflow/activity records | Previous median | Indexed first call | Indexed repeat median |
|---|---:|---:|---:|---:|---:|
| Current all-history preview | 281 | 3,825 / 2,083 | 23.5 ms | 8.6 ms | 3.6 ms |
| One-year projection | 365 | 13,140 / 8,760 | 111.9 ms | 15.2 ms | 7.7 ms |
| Three-year projection | 1,096 | 39,456 / 26,304 | 1,017.6 ms | 40.2 ms | 23.1 ms |
| Five-year projection | 1,826 | 65,736 / 43,824 | 2,833.5 ms | 31.3 ms | 10.3 ms |

Synthetic projections use 36 workflow attempts, 24 activity records, four
account snapshots and four operational observations per day. Timings exclude
fixture construction and network/chart rendering, with warm-up before median
samples. All-history, custom multi-year and adversarial gap/retry/partial-data
fixtures produced exactly equal outputs. Desktop (1440x1000) and mobile-width
(390x844) measurements used the same desktop CPU, not real mobile hardware.
After forced garbage collection, one five-year result plus its index retained
about 1.04 MiB versus 0.21 MiB previously: approximately 0.83 MiB additional
heap for the material latency reduction. These are local samples, not a
cross-device performance guarantee.

### Python 3.14 annotation simplification

Completed on 2 November 2026: removed the 30 legacy
`from __future__ import annotations` imports from first-party application and
maintenance scripts. Python 3.14 now defers annotation evaluation natively.
Direct `__annotations__` and default `annotationlib.get_annotations()` access
returns runtime values rather than strings; callers needing textual forms should
request `annotationlib.Format.STRING`. First-party code does not consume
stringified annotations. Regression tests verify annotation resolution and
deferred forward references; operational behaviour and signatures are unchanged.
No first-party version fallbacks or `typing_extensions` imports need removal;
the SDK's transitive backports remain dependency-owned.

## Standing Decisions

| Decision | Reason |
|---|---|
| Keep every dated changelog milestone versioned | Continue semantic-version-style milestone numbers alongside actual commit dates, reuse same-day sections and classify breaking changes explicitly. Retrospective labels do not imply release tags or package metadata changes. |
| Require Python 3.14 and test CPython 3.14.10 only | The bot's local and GitHub runtimes already use 3.14.10. Drop 3.12/3.13 support, align analysis targets with 3.14 and retain one authoritative Sonar job. atproto 0.0.73 currently excludes Python 3.15. |
| Separate production outcomes from CI and expose source-time investigation | Lead with observed delivery/checkpoints, preserve existing freshness tolerances, publish allowlisted failed-step/run receipts, and distinguish successful workflows from proven operational recovery or live queues. |
| Preserve confirmed-post evidence across checkpoint failures | A confirmed external post with failed local state persistence must remain a failed workflow, retain `posted=true` telemetry and avoid an automatic send retry. |
| Separate provider access, candidate supply and confirmed publication contribution | Preserve posting decisions and legacy telemetry, disclose detailed sample coverage, and use descriptive period/concentration changes without automatic rotation changes or new alert thresholds. |
| Observe joke response in 24–30-hour and 168–174-hour bands | Keep the existing six-hour collector, freeze the first in-band reading, show mature publishing-cohort samples and misses, and never reconstruct earlier checkpoints from later totals. Retain public-post-only receipts for 400 days outside Pages. |
| Use independent historical controls and complete UTC-day comparisons | Keep Audience and Operations periods separate; preserve explicit scopes for current counters and cohort checkpoints, and never turn missing history into zeroes or sum rolling delivery windows. |
| Separate completed outgoing follows from observed incoming relationship outcomes | Follow completion is operational execution, not follower acquisition; show cohort sample sizes and derive protection durations from collected data. |
| Show specific operational alert reasons and available workflow/run details | Distinguish repeated CI failures, overdue joke-request checks and uncertain state persistence without implying that Python assertions or posting necessarily failed. |
| Keep state files instead of a database | Current operational scale does not justify a migration. |
| Keep synchronous command execution | No throughput requirement justifies an async rewrite. |
| Use domain-scoped locked transactions for runtime state mutations | Preserve newer state while retaining confirmed-action receipts, retry queues and notification checkpoints. |
| Change workflow schedules only for observed needs | Current cadence and action caps are safety controls. |
| Retain encoded joke state | Avoid fragile comparisons and indexing raw joke text. |
| Do not integrate HumorAPI | Content use and storage terms are unsuitable. |

## Dependency Exceptions

Rechecked on 13 November 2026 against the Python package index, npm registry,
upstream Action releases and current Dependabot results. No dependency upgrades
were made as part of #145, R04, R05, R06 or S01;
keep them in a separate resolver-validated batch so this behaviour fix remains
focused and the lock stays coherent. Review the deferred versions before the
next dependency batch or sooner if an applicable advisory appears.

- `requirements.lock` has these installed versions behind the package-index
  latest: atproto 0.0.73 -> 0.0.74, click 8.5.0 -> 8.5.1, coverage 7.17.0 -> 7.17.3, dnspython 2.9.1 ->
  2.9.2, pydantic 2.14.2 -> 2.14.3, pydantic-core 2.50.2 -> 2.50.4, regex
  2026.9.29 -> 2026.11.9, and typing-inspection 0.4.4 -> 0.4.5.
- Local Python tooling has pip 26.2.2 -> 26.3 and Ruff 0.17.3 -> 0.17.5
  available. pip-tools remains 7.6.2. Ruff's explicit rule selection (`E4`,
  `E7`, `E9`, `F`, plus `C901`) and file inclusion preserve the verified quality
  policy rather than adopting unrelated new defaults.
- `npm outdated --json` reported no available npm updates. Pyright remains
  1.1.414, and the dashboard uses Chart.js 4.6.1 with a freshly calculated
  integrity hash.
- Current first-party GitHub Action refs remain full-SHA pinned. Merged
  Dependabot PRs #142 and #143 contain the CodeQL refresh and Sonar scan 8.4.1
  update; the changed refs are present on this branch. The action-pin checker
  validates SHA immutability, while Dependabot results provide release currency.
- The Sonar scan Action remains at 8.4.1 while upstream stable is 8.5.0.
  Defer this CI-tool upgrade to a separate analysis-validated dependency change,
  rather than mixing it into #145. Review at the next dependency batch or sooner
  for an applicable advisory. The other nine Action repositories match current
  stable releases, including CodeQL Action 4.39.3 (its separate bundle releases
  are not Action versions). No open Dependabot vulnerability alerts were reported.
- Update transitive Python dependencies through the resolver, never by
  independently forcing incompatible pins. The 2 November lock refresh included
  AnyIO 4.16.0, atproto 0.0.73, pytest 9.2.0 and urllib3 2.8.0; Python 3.14
  remains the minimum.
