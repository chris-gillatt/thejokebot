# The Joke Bot: Current Priorities

This is the operating brief for open work and lasting decisions. See the [README](README.md) for the product overview, the [operations guide](docs/operations.md) for procedures and the [changelog](CHANGELOG.md) for completed milestones. Detailed implementation history remains in Git commits and PRs.

## Working Principles

- Preserve existing posting, moderation and follow behaviour unless a change explicitly calls for it. Keep changes focused and reversible.
- Keep credentials and audience identifiers out of published data and source control. Use British English in documentation and Conventional Commits with a reason for every change.
- Update [CHANGELOG.md](CHANGELOG.md) in the same substantive commit as every meaningful first-party change, using actual commit dates, newest first. Never create or restore an `Unreleased` section. Preserve the retrospective pre-1.0.0 milestone numbers without claiming they were original releases. Check it before committing and completing work; omit routine automated state/metrics refreshes, not substantive agent or dependency changes.
- Before non-documentation pushes, run `./scripts/preflight-local.sh` separately, then sync with `git pull --rebase`, then push. Do not use a pre-push hook. The gate includes Ruff, Pyright, workflow lint, tests, coverage and local CodeQL; a passing test suite alone is insufficient.
- For docs-only changes, including prose-only agent/process guidance, skip tests, preflight, builds, code lint/type checks, coverage, CodeQL/Sonar, dependency audits and manually dispatched full CI. Review the documentation and links, confirm the diff is docs-only, run `git diff --check`, update the changelog, then rebase/push without waiting for full validation gates. Mixed code/configuration/workflow/dependency changes retain normal validation.
- Maintain at least 90% overall first-party Python coverage and 95% on changed executable lines, with focused tests for material failure paths and safety limits. Sonar analysis must pass its gate **and** report zero unresolved issues.
- Check current first-party Python, npm and GitHub Actions dependency versions before closing a non-documentation work batch; skip these audits for docs-only work. Handle upgrades separately; record a deliberate exception with current and latest stable versions, reason and review trigger below. Treat `references/` submodules as read-only and do not refresh them without an explicit request.

## Operational Risks

| Risk | Constraint |
|---|---|
| Workflow/runtime drift | Preserve entry points, triggers, environment variables and state formats; validate schedule metadata with runtime configuration. |
| Posting, report and follow regressions | Test idempotency, pagination, provider fallback and safety caps at producer and collector boundaries. |
| Bluesky transport workaround | API calls currently use the `requests`/urllib3 transport instead of native httpx because of a prior AWS WAF fingerprint block. If urllib3 is blocked too, evaluate an alternative browser-compatible transport before changing the live path. |
| Session-cache custody | Cached sessions must stay encrypted with `BLUESKY_SESSION_CACHE_KEY`; rotating it requires a fresh credential login. |
| Bluesky graph visibility | Profile counters may include hidden accounts that cannot be hydrated through follower/following queries; do not infer actionable accounts from totals. |

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

Retain the working transport override until an authenticated login from a GitHub Actions runner proves native SDK transport is reliable, or a new block requires a replacement. Evaluate dependency and deployment implications before considering `curl_cffi`.

### Future Dashboard Measures

Do not claim source-specific post engagement, impressions, sentiment, demographics or individual audience outcomes without appropriate, privacy-safe source data. Keep separate the dashboard's observed history and historical estimates.

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
| Require Python 3.14 and test CPython 3.14.10 only | The bot's local and GitHub runtimes already use 3.14.10. Drop 3.12/3.13 support, align analysis targets with 3.14 and retain one authoritative Sonar job. atproto 0.0.73 currently excludes Python 3.15. |
| Separate production outcomes from CI and expose source-time investigation | Lead with observed delivery/checkpoints, preserve existing freshness tolerances, publish allowlisted failed-step/run receipts, and distinguish successful workflows from proven operational recovery or live queues. |
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

Rechecked on 2 November 2026 against PyPI, npm and upstream GitHub Action releases/tags.

- Deliberate exception: AnyIO remains locked at 4.15.1; latest stable is 4.16.0.
  Keep the annotation-only migration separate from transitive runtime dependency
  changes. Review and resolve this upgrade in the next dependency-maintenance
  change, or immediately if an applicable advisory requires it.

- The other 34 Python lock entries use the latest stable releases, resolved together with hashes. This includes atproto 0.0.73, pydantic 2.14.2/core 2.50.2, pytest 9.2.0 and urllib3 2.8.0. The SDK's new `tlds` dependency is included; Python 3.14 is the minimum.
- Ruff is 0.17.3. Explicit rule selection (`E4`, `E7`, `E9`, `F`, plus `C901`) and file inclusion preserve the verified 0.15.13 quality policy rather than adopting unrelated new defaults.
- npm Pyright is 1.1.414, including the local installation. The dashboard uses Chart.js 4.6.1 with a freshly calculated integrity hash.
- All ten first-party GitHub Action repositories are pinned to their latest stable release commits, including setup-python 7.1.0 and Sonar scan 8.4.0. CodeQL uses Action v4.39.1, not a differently versioned bundle release.
- Local lock-generation tools are pip-tools 7.6.2 and pip 26.2.2. Update transitive dependencies through the resolver, never by independently forcing incompatible pins. Recheck currency at the next coherent batch or immediately after an applicable advisory.
