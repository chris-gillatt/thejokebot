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

### Dashboard Resolution Time

Report-resolution duration should use newly observed aggregate lifecycle events only. Do not infer it from legacy identifier-only state. Add it once there is sufficient history, with a producer-to-collector test and desktop/mobile dashboard verification.

### State Transactions

Review remaining direct state saves in report, social and unfollow workflows for a domain-scoped locked transaction migration. Mutations are interleaved with network actions, so preserve existing checkpoints and idempotency rather than doing a mechanical rewrite.

### Transport Review

Retain the working transport override until an authenticated login from a GitHub Actions runner proves native SDK transport is reliable, or a new block requires a replacement. Evaluate dependency and deployment implications before considering `curl_cffi`.

### Future Dashboard Measures

Do not claim source-specific post engagement, impressions, sentiment, demographics or individual audience outcomes without appropriate, privacy-safe source data. Keep separate the dashboard's observed history and historical estimates.

## Standing Decisions

| Decision | Reason |
|---|---|
| Keep state files instead of a database | Current operational scale does not justify a migration. |
| Keep synchronous command execution | No throughput requirement justifies an async rewrite. |
| Change workflow schedules only for observed needs | Current cadence and action caps are safety controls. |
| Retain encoded joke state | Avoid fragile comparisons and indexing raw joke text. |
| Do not integrate HumorAPI | Content use and storage terms are unsuitable. |

## Dependency Exceptions

No deliberate first-party version exceptions are currently recorded. Recheck against upstream releases or Dependabot results at the end of each work batch and document exceptions here before closing it.