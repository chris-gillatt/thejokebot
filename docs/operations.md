# Operations and Configuration

The [README](../README.md) covers the project at a glance. This guide covers local validation, runtime configuration and account maintenance.

## Local Setup and Validation

Use Python 3.12 or newer and follow the README's locked-dependency installation steps. `pyproject.toml` defines the application version and direct dependencies; `requirements.lock` pins the complete environment. An editable install uses `--no-deps` deliberately so it cannot resolve a different set of dependencies.

To regenerate the lock file after a separately reviewed dependency change:

```bash
pip-compile --allow-unsafe --extra=dev --generate-hashes --output-file=requirements.lock --strip-extras pyproject.toml
```

Run `npm ci --ignore-scripts` once to install the locked Pyright quality tool. Before a push, run `./scripts/preflight-local.sh` as a separate command. It checks Ruff lint and format, Pyright, workflow lint, unit tests, application coverage (at least 90% overall and 95% of changed executable Python), and local CodeQL. If CodeQL is unavailable, `BLUESKY_PREFLIGHT_ALLOW_REDUCED_COVERAGE=true ./scripts/preflight-local.sh` explicitly opts into reduced coverage. `./scripts/test-local.sh` runs only the tests.

To sync your checkout, use `git pull --rebase && git submodule update --init --recursive`. The `references/` submodules are read-only upstream resources, not first-party code. Do not refresh them proactively. Validate before syncing and pushing; scheduled workflows may update `main` while local checks run.

Preview the staged GitHub Pages dashboard locally with `./scripts/preview-dashboard.sh` at <http://localhost:8765/>. Set `DASHBOARD_PREVIEW_PORT` to change the port. The dashboard publishes public aggregate metrics every six hours, keeps UTC monthly history, and never exports audience identifiers or raw workflow logs. Its Audience and Operations views distinguish sampled counts from reconstructed activity.

Follower totals are collection-time snapshots; missing historical follower totals remain blank rather than being estimated. Up to 30 days of following and profile-post totals can be reconstructed from aggregate successful-action logs and retained post timestamps, while joke-post, follow and unfollow activity is shown by day. The all-time view loads daily points from monthly history on demand. Audience growth combines follow-backs, interaction-led and discovery follows with source-specific success rates; 30/90-day reciprocity cohorts are reported only when observed. Pending checkpoints keep account hashes in private state and publish aggregate results only.

## Configuration

Copy `.env.example` to the ignored `.env` file for local use. Keep secrets out of `resources/jokebot_runtime_config.json`. Production workflows use `BLUESKY_USERNAME` and `BLUESKY_APP_PASSWORD` with `BLUESKY_PASSWORD_SOURCE=app_password`. Local use of the full account password requires an explicit `BLUESKY_PASSWORD_SOURCE=account_password` and `BLUESKY_PASSWORD`; credentials are never selected automatically. `BLUESKY_SESSION_CACHE_KEY` encrypts cached production sessions. `API_NINJAS_API_KEY` is optional for the backup provider.

The non-secret runtime config contains posting, follow-fellows, follows-and-likes, unfollow, reports and workflow schedule settings. Supported environment variables override these defaults. Validate config and schedule metadata with `thejokebot-validate-runtime-config` (or its installed `.venv/bin/` entry point).

| Control | Use |
|---|---|
| `BLUESKY_DRY_RUN=true` | Log supported social actions without applying them; also preview starter-pack changes. |
| `BLUESKY_ACTION_DELAY_SECONDS` | Delay follow, unfollow and like actions. |
| `BLUESKY_NETWORK_RETRY_ATTEMPTS`, `BLUESKY_NETWORK_RETRY_DELAY_SECONDS`, `BLUESKY_NETWORK_RETRY_BACKOFF_FACTOR` | Bound transient network retries. |
| `BLUESKY_UNFOLLOW_MAX_ACTIONS`, `BLUESKY_UNFOLLOW_BATCH_SIZE`, `BLUESKY_UNFOLLOW_BATCH_PAUSE_SECONDS` | Limit and pace unfollows; `0` removes the action cap. |
| `BLUESKY_UNFOLLOW_IGNORE` | Protect comma-separated fully qualified handles. |
| `BLUESKY_BLOCK_DIDS` | Private repository variable for blocks to restore before social actions. |
| `BLUESKY_JOKE_PROVIDER` | Force a named joke provider instead of normal rotation. |
| `BLUESKY_REPORT_MAX_PAGES`, `BLUESKY_REPORT_PAGE_LIMIT`, `BLUESKY_REPORT_MAX_UNRESOLVED_ATTEMPTS` | Bound report notification processing. |

The full list of settings and defaults is in `.env.example` and `resources/jokebot_runtime_config.json`. The validator rejects unsafe schedule and action-limit combinations. Unfollow normally protects newly followed accounts for 90 days and batches actions with pauses.

## Commands

Installed entry points are available under `.venv/bin/`:

| Command | Purpose |
|---|---|
| `thejokebot-post-joke` | Post a joke using provider rotation, duplicate checks and hashtag rotation. |
| `thejokebot-follows-and-likes` | Follow back, respond to interactions and explicit tagged joke requests, and like replies. |
| `thejokebot-follow-fellows` | Discover accounts through rotating search tags. |
| `thejokebot-unfollow` | Remove non-reciprocal follows subject to grace and protection rules. |
| `thejokebot-process-reports`, `thejokebot-create-report-prs` | Process `#report` replies and propose denylist changes. |
| `thejokebot-collect-dashboard-metrics` | Collect public aggregate dashboard data. |
| `thejokebot-manage-starter-pack` | Preview or synchronise the configured list and starter pack. |
| `thejokebot-validate-runtime-config`, `thejokebot-validate-unfollow-ignore` | Validate configuration and protected unfollow handles. |
| `thejokebot-verify-latest-joke-post` | Check read-only for a recent post. |

## Account Maintenance

An explicit mention such as `@thejokebot.bsky.social tell me a joke` requests a threaded reply. The social workflow caps replies per run, excludes reports, and checkpoints processed requests. To report an unsuitable posted joke, reply to the joke with standalone `#report`. The report workflow opens a denylist PR for maintainer review; after merge, a later run removes the approved post.

Starter-pack settings live in `resources/jokebot_starter_pack.json`. Dispatch `bluesky_manage_starter_pack` with `apply_changes=false` to preview; use `apply_changes=true` only for deliberate live changes. When enabled, members of its source list are protected from unfollowing.

To enforce account blocks, set private repository variable `BLUESKY_BLOCK_DIDS` to one stable DID per line, optionally followed by a handle comment. The social workflow restores missing blocks but never unblocks anyone. Removing a DID from the variable stops enforcing it; unblock manually on Bluesky if appropriate.

To prevent future automatic follows of an account, use its stable DID in `unfollow_history`, not a handle-based list. Do not edit state during a concurrent scheduled write:

1. Resolve the handle to its DID (replace the example handle):

	```bash
	curl -fsS --get --data-urlencode 'handle=example.bsky.social' 'https://bsky.social/xrpc/com.atproto.identity.resolveHandle'
	```

2. Unfollow the account on Bluesky if it is currently followed. Editing state alone does not perform a live unfollow.
3. Add an entry to `unfollow_history.entries` in `state/social_state.json` using the resolved DID and the current Unix timestamp:

	```json
	{"did": "did:plc:example", "unfollowed_at": 1786064785, "reason": "manual_block"}
	```

4. Remove any matching entry from `follow_grace.entries`, then validate the JSON and run `./scripts/preflight-local.sh` before committing the state change. Handles can change; the guard compares DIDs.

## State and Quality Analysis

| Location | Purpose |
|---|---|
| `state/posting_state.json` | Posting history and provider/tag rotation. |
| `state/social_state.json` | Interaction checkpoints, follow grace and unfollow history. |
| `state/moderation_state.json` | Report and deletion checkpoints. |
| `state/provider_health_state.json` | Provider health counters. |
| `resources/jokebot_denylist.json` | Permanent joke exclusions. |
| `resources/jokebot_jokebook.json` | Offline joke fallback. |

The `python_tests` workflow generates `coverage.xml` and submits analysis to SonarQube Cloud. For a local scan, install `sonar-scanner` (on macOS, `brew install sonar-scanner`) and put the Sonar project identity values from `.env.example` and `SONAR_TOKEN` in the ignored `.env`. Keep Sonar automatic analysis disabled; CI analysis is authoritative. From the repository root, generate fresh application coverage:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q --cov=. --cov-report=xml:coverage.xml --cov-fail-under=90
```

Check that `coverage.xml` has a non-empty `<source>` path; otherwise Sonar can report 0% Python coverage. Load the environment and run the scanner with the project identity settings:

```bash
set -a
source .env
set +a
sonar-scanner \
	-Dsonar.organization="$SONAR_ORGANIZATION" \
	-Dsonar.projectKey="$SONAR_PROJECT_KEY" \
	-Dsonar.projectName="$SONAR_PROJECT_NAME" \
	-Dsonar.host.url="$SONAR_HOST_URL" \
	-Dsonar.qualitygate.wait=true \
	-Dsonar.qualitygate.timeout=300
```

If the scanner exits successfully, check unresolved issues for the default-branch analysis before clearing the token:

```bash
.venv/bin/python scripts/check_sonar_issues.py
unset SONAR_TOKEN
```

Both the quality gate and zero unresolved issues must pass. A scanner exit code of 3 usually means the report uploaded but the gate failed. Never pass the token as a command-line property or print it. `sonar-project.properties` defines the first-party analysis scope and coverage report path; the dashboard is analysed but excluded from Python coverage. See the [Sonar quality workflow](../.github/skills/sonar-quality/SKILL.md) for diagnosis and remediation.