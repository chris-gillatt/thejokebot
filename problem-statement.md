# The Joke Bot: Current Priorities

This is the operating brief for open work and lasting decisions. See the [README](README.md) for the product overview, the [operations guide](docs/operations.md) for procedures and the [changelog](CHANGELOG.md) for completed milestones. Detailed implementation history remains in Git commits and PRs.

## Working Principles

- Preserve existing posting, moderation and follow behaviour unless a change explicitly calls for it. Keep changes focused and reversible.
- Keep credentials and audience identifiers out of published data and source control. Use British English in documentation and Conventional Commits with a reason for every change.
- Before pushing, run `./scripts/preflight-local.sh` separately, then sync with `git pull --rebase`, then push. Do not use a pre-push hook. The gate includes Ruff, Pyright, workflow lint, tests, coverage and local CodeQL; a passing test suite alone is insufficient.
- Maintain at least 90% overall first-party Python coverage and 95% on changed executable lines, with focused tests for material failure paths and safety limits. Sonar analysis must pass its gate **and** report zero unresolved issues.
- Check current first-party Python, npm and GitHub Actions dependency versions before closing a work batch. Handle upgrades separately; record a deliberate exception with current and latest stable versions, reason and review trigger below. Treat `references/` submodules as read-only and do not refresh them without an explicit request.

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

## Standing Decisions

| Decision | Reason |
|---|---|
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

Checked on 31 October 2026 against PyPI, npm and upstream GitHub Action releases. Pyright's declared version (1.1.414) is current, although the local installation is still 1.1.413. Other Action pins are current; the exceptions below are deferred to a separate dependency-maintenance change to keep the dashboard improvements focused. Review these at the next dependency-maintenance batch, or immediately if an applicable security advisory appears. Update transitive Python dependencies through the lock resolver, not independently.

| Dependency | Current locked/pinned version | Latest stable | Reason / review trigger |
|---|---|---|---|
| anyio | 4.14.2 | 4.15.1 | Separate lock refresh; next maintenance batch or advisory. |
| atproto | 0.0.72 | 0.0.73 | Separate SDK compatibility and lock validation; next maintenance batch or advisory. |
| certifi | 2026.7.22 | 2026.10.23 | Separate lock refresh; next maintenance batch or advisory. |
| charset-normalizer | 3.5.1 | 3.5.2 | Separate lock refresh; next maintenance batch or advisory. |
| coverage | 7.16.0 | 7.17.0 | Separate coverage-tool validation; next maintenance batch or advisory. |
| cryptography | 50.0.1 | 50.0.2 | Separate lock refresh; next maintenance batch or advisory. |
| dnspython | 2.8.0 | 2.9.1 | Separate lock refresh; next maintenance batch or advisory. |
| idna | 3.19 | 3.20 | Separate lock refresh; next maintenance batch or advisory. |
| iniconfig | 2.3.0 | 2.3.1 | Separate lock refresh; next maintenance batch or advisory. |
| libipld | 3.4.1 | 3.5.0 | Separate lock refresh; next maintenance batch or advisory. |
| pluggy | 1.6.0 | 1.7.0 | Separate lock refresh; next maintenance batch or advisory. |
| pycparser | 3.0 | 3.12 | Separate lock refresh; next maintenance batch or advisory. |
| pydantic | 2.13.5 | 2.14.2 | Separate compatible resolver update with pydantic-core; next maintenance batch or advisory. |
| pydantic-core | 2.46.5 | 2.50.2 | Follow pydantic's compatible pin; next maintenance batch or advisory. |
| pytest | 9.1.1 | 9.2.0 | Separate test-runner compatibility validation and lock refresh; next maintenance batch or advisory. |
| python-dotenv | 1.2.3 | 1.2.4 | Separate lock refresh; next maintenance batch or advisory. |
| regex | 2026.9.10 | 2026.9.29 | Separate lock refresh; next maintenance batch or advisory. |
| urllib3 | 2.7.0 | 2.8.0 | Validate the transport workaround during a separate lock refresh; next maintenance batch or advisory. |
| websockets | 17.1 | 17.4 | Separate lock refresh; next maintenance batch or advisory. |
| Ruff | 0.15.13 | 0.17.3 | Separate lint-tool behaviour validation; next maintenance batch or advisory. |
| actions/setup-python | 7.0.0 | 7.1.0 | Separate workflow pin update and validation; next maintenance batch or advisory. |
| SonarSource/sonarqube-scan-action | 8.3.0 | 8.4.0 | Separate scanner-action validation and pin update; next maintenance batch or advisory. |
