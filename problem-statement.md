# The Joke Bot: Current Priorities

This is the operating brief for open work and lasting decisions. See the [README](README.md) for the product overview, the [operations guide](docs/operations.md) for procedures and the [changelog](CHANGELOG.md) for completed milestones. Detailed implementation history remains in Git commits and PRs.

## Working Principles

- Preserve existing posting, moderation and follow behaviour unless a change explicitly calls for it. Keep changes focused and reversible.
- Keep credentials and audience identifiers out of published data and source control. Use British English in documentation and Conventional Commits with a reason for every change.
- Update [CHANGELOG.md](CHANGELOG.md) in the same substantive commit as every meaningful first-party change. Check it before committing and completing work; omit routine automated state/metrics refreshes, not substantive agent or dependency changes.
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

### Existing CodeQL findings

The 27 October 2026 local CodeQL analysis reported 18 findings outside the dashboard alert change (resource handling, imports, exception/finally behaviour and unused symbols); triage these separately rather than mixing them into the alert fix. Git-persistence integration fixtures now use explicit Git-directory paths and enforce `safe.bareRepository=explicit` in their Git helper, preserving the safety setting while avoiding working-directory discovery of bare repositories.

### Starter-pack inclusion

The manual read-only membership prototype checks candidate packs from retained attributed follows and explicit pack URIs. It does not provide complete reverse membership discovery or inclusion dates. Issue #115 remains open for discovery coverage, a once-per-pack acknowledgement policy, quote-post selection and visual verification before enabling public posts or dashboard membership claims.

### Dashboard Resolution Time

Report-resolution duration should use newly observed aggregate lifecycle events only. Do not infer it from legacy identifier-only state. Add it once there is sufficient history, with a producer-to-collector test and desktop/mobile dashboard verification.

### Transport Review

Retain the working transport override until an authenticated login from a GitHub Actions runner proves native SDK transport is reliable, or a new block requires a replacement. Evaluate dependency and deployment implications before considering `curl_cffi`.

### Future Dashboard Measures

Do not claim source-specific post engagement, impressions, sentiment, demographics or individual audience outcomes without appropriate, privacy-safe source data. Keep separate the dashboard's observed history and historical estimates.

### Python 3.14 annotation simplification

The new minimum permits native deferred annotations, but removing existing `from __future__ import annotations` statements changes annotation introspection. Review that behaviour separately rather than mixing a broad source rewrite into the support-policy change. No first-party version fallbacks or `typing_extensions` imports need removal; the SDK's transitive backports remain dependency-owned.

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

Rechecked on 1 November 2026 against PyPI, npm and upstream GitHub Action releases/tags. No first-party version exceptions remain.

- All 35 Python lock entries use the latest stable releases, resolved together with hashes. This includes atproto 0.0.73, pydantic 2.14.2/core 2.50.2, pytest 9.2.0 and urllib3 2.8.0. The SDK's new `tlds` dependency is included; Python 3.14 is the minimum.
- Ruff is 0.17.3. Explicit rule selection (`E4`, `E7`, `E9`, `F`, plus `C901`) and file inclusion preserve the verified 0.15.13 quality policy rather than adopting unrelated new defaults.
- npm Pyright is 1.1.414, including the local installation. The dashboard uses Chart.js 4.6.1 with a freshly calculated integrity hash.
- All ten first-party GitHub Action repositories are pinned to their latest stable release commits, including setup-python 7.1.0 and Sonar scan 8.4.0. CodeQL uses Action v4.39.1, not a differently versioned bundle release.
- Local lock-generation tools are pip-tools 7.6.2 and pip 26.2.2. Update transitive dependencies through the resolver, never by independently forcing incompatible pins. Recheck currency at the next coherent batch or immediately after an applicable advisory.
