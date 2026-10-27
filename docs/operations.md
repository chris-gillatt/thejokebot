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

The Operations pulse names failed or overdue workflows and reports consecutive completed-run failures. A workflow failure is not necessarily a Python test failure: inspect its GitHub Actions logs to identify the failed step. If a failed run already made changes, its alert includes the run ID; verify saved state against completed actions before retrying. An overdue joke-request checkpoint points to the Follows and likes workflow. Unrecognised alert types are shown explicitly rather than hidden behind a generic warning.

Audience source counts are completed outgoing follows, not incoming follower acquisitions. Follow completion divides completed follows by that source's measured candidates, eligible accounts or selected accounts; these denominators are not interchangeable. The historical JSON fields `acquired` and `success_rate` retain those outgoing-follow meanings for compatibility. Day-30 and day-90 relationship outcomes show how many observed cohort accounts follow the bot, with sample sizes and overdue observations. Follow-back cohorts began as existing followers, so their outcome describes retention rather than new reciprocity. Cohort outcomes are not causal attribution and do not share the rolling activity window. The network-protection duration is rendered from the collected configuration, never a hard-coded day count.

Audience and Operations have independent historical date controls: seven, 30 or 90 days, year to date, all available history, or inclusive custom UTC dates. Today is excluded because it is incomplete. Selected-period summaries compare against the immediately preceding equal-length period. Current counters, current rolling operational cards, source activity, fixed-age cohorts and top-post controls retain their separately labelled scopes.

Audience history uses the compact daily archive plus recent six-hour samples; Operations loads only monthly partitions needed for its selected period, comparison period and baseline day. Missing days remain gaps, not zeroes. Publication/follow period totals require complete daily coverage; partial observations are explicitly labelled subtotals with their covered-day counts and no comparison. Sampled account and visible-engagement changes require observations near both boundaries. A missing comparison or zero baseline never produces an infinite percentage. Availability notes describe loaded observations, not invented earlier measurements.

Historical workflow reliability counts observed successful and failed completed attempts, including retries, and excludes running/cancelled attempts from that denominator. Posting pressure uses runs with explicit provider telemetry. The delivery trend is a sampled rolling seven-day slot-delivery rate, not a daily total; rolling windows are never summed. Recorded unfollow events provide maintenance context; release and schedule changes are not inferred. Archive failures leave previous charts intact with an explicit error and retry instructions.

Comparable-age joke performance uses the existing six-hour collection schedule and complete public author-feed fetch. The first available observation in `[24, 30)` or `[168, 174)` hours is immutable, including when later engagement counts change. The dashboard labels these as age bands, not exact 24-hour or seven-day readings. Missing, hidden or deleted posts cannot supply an observation; a closed window remains missed and is never backfilled. Failed/incomplete fetches abort collection rather than recording partial samples.

Checkpoint receipts are persisted in `state/dashboard_engagement.json` and excluded from Pages. This repository is public: receipts contain only public bot-post URIs, publication/provider metadata, observation times and interaction counts, never audience identifiers or private text. Public metrics contain aggregates and currently visible public top-joke summaries. Previously observed hidden/deleted posts retain their aggregate contribution but are removed from top-joke links. Receipts and derived publishing-month history are retained for 400 days, with the original collection start disclosed.

Each age band compares the most recent 30 complete UTC publishing days whose entire observation windows have closed with the preceding 30 such days. It shows mean, median, observed/eligible sample counts, missed checkpoints, zero-interaction share and observed interaction-type totals. Pre-tracking checkpoints are excluded from the eligible denominator. There is no invented pre-collection checkpoint history. Provider and UTC publishing-hour comparisons use the same mature cohort and require 30 observed posts per group before displaying averages; they are descriptive, not causal evidence or impressions-based engagement rates. Publishing hour is the actual UTC publication hour, not a reconstructed scheduled slot. Existing cumulative visible totals and current-total top-post rankings remain separately labelled.

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

An explicit mention such as `@thejokebot.bsky.social tell me a joke` requests a threaded reply. The two-hourly social workflow sends at most two replies per requester and six replies overall per run. Requests are handled oldest first; those above either limit are discarded when the run advances its checkpoint. Reply jokes come from the bundled jokebook, carry the normal rotating tags, and do not consume the main posting workflow's 730-day uniqueness pool. The workflow excludes reports and checks for an existing bot reply before posting. To report an unsuitable posted joke, reply to the joke with standalone `#report`. The report workflow opens a denylist PR for maintainer review; after merge, a later run removes the approved post.

Starter-pack settings live in `resources/jokebot_starter_pack.json`. Dispatch `bluesky_manage_starter_pack` with `apply_changes=false` to preview; use `apply_changes=true` only for deliberate live changes. When enabled, members of its source list are protected from unfollowing.

For read-only inclusion checks, run `thejokebot-inspect-starter-packs` or dispatch the manual-only `bluesky_inspect_starter_packs` workflow. It checks retained packs discovered through attributed follows; add an explicit canonical AT URI with `--pack-uri` (repeatable locally) or the workflow's `pack_uri` input to test a known pack that has not produced a follow. The JSON report is written to `.agent-tmp/starter_pack_membership.json` locally and printed in workflow logs. It never posts, follows, changes runtime state, or publishes dashboard membership data.

The prototype checks at most 20 candidate packs, 10 list pages per pack and 100 members per page, with a 60-second request budget. In-flight requests may finish later, but another request or retry cannot start after that budget expires. A matching member is positive evidence; `not_member` means no match was found in a complete list traversal. Failed, mismatched or incomplete reads are `unknown`; candidate caps and runtime exhaustion report unchecked packs explicitly. Individual list-member identifiers are not included in the report. This is partial candidate verification, not a complete list of packs containing TJB, and it cannot establish when inclusion occurred. A successful workflow means a diagnostic report was produced, not that every pack was discovered or classified.

Current canonical schemas are maintained in [bluesky-social/bsky](https://github.com/bluesky-social/bsky/tree/main/lexicons/app/bsky/graph). [`getStarterPacksWithMembership`](https://github.com/bluesky-social/bsky/blob/main/lexicons/app/bsky/graph/getStarterPacksWithMembership.json) enumerates packs created by the session user, so it cannot provide the global reverse lookup needed by issue #115. The prototype instead reads each known pack with [`getStarterPack`](https://github.com/bluesky-social/bsky/blob/main/lexicons/app/bsky/graph/getStarterPack.json) and traverses its underlying list. Public thank-you posts, permanent once-per-pack receipts and any dashboard presentation remain separate work under #115.

Fellow discovery reads TJB's saved custom feeds from its Bluesky preferences before searching the configured hashtags. No separate feed list is needed: saving or removing a custom feed in Bluesky changes the discovery sources. Built-in timelines and saved lists are excluded. Current saved-feed preferences take precedence over the legacy format, including when the current list is empty.

Each run samples one page of up to `follow_fellows.search_limit` posts (at most 100) from up to 10 saved custom feeds. When there are more than 10, a persisted offset rotates through the saved feeds after each successful live scan, even if it finds no accounts to follow. Failed reads and dry runs do not advance that offset. Candidates are the original post authors, including when a feed entry is a repost; blocked or muted authors are excluded. Feeds and hashtags share the existing `global_follow_limit` (currently 150), per-source initial allocation (`per_tag_limit`, currently 12), duplicate filtering, unfollow-history exclusions, follow grace and action pacing. Saved feeds are allocated first; this does not increase the run's total follow allowance or its schedule.

Discovery requires a complete following-list read and successful saved-preference/feed reads before following anyone. A failed or truncated prerequisite read aborts the run without follow actions. No saved custom feeds is a valid result and leaves hashtag discovery active. Dispatch `bluesky_follow_fellows` with `dry_run=true` to preview candidates without following accounts or changing social state; local runs can use `BLUESKY_DRY_RUN=true`.

Unfollow runs commit grace reconciliation and candidate selection against fresh social state in a locked transaction before making changes to Bluesky. Each confirmed unfollow is checkpointed immediately in a fresh transaction; a later failure or throttle cannot discard earlier confirmed history or overwrite newer unrelated social fields. A checkpoint persistence failure stops the run. The workflow attempts to publish valid checkpoint JSON even when the command fails; invalid JSON is never committed by that step. Dry runs preview reconciliation without saving social state. Existing workflow concurrency still serialises social jobs; local file locks do not replace that control.

Social processing checkpoints explicit operations against fresh state rather than saving its whole working snapshot. Follow acquisitions, completed starter-pack scans, each page of confirmed likes, and joke-request receipts are saved independently. Joke-request scan checkpoints never move backwards, and equal-time boundaries are merged. If starter-pack attribution changes during a scan, that scan is rejected for a fresh retry instead of risking duplicate counts. Joke replies retain their single send attempt and live-thread duplicate verification; confirmed reply receipts update posting and social state together under their locks. The workflow attempts to publish valid checkpoint JSON after command failures. Dispatch `bluesky_follows_and_likes` with `dry_run=true` for a preview without account actions or state writes.

Report processing checkpoints confirmed deletions immediately and replays notification-resolution operations against fresh moderation state. Only completed scans advance the last-successful-poll timestamp. Pending acknowledgements retain the minimal reply/root references needed for retry even after a notification is marked processed; confirmed or permanently rejected acknowledgements clear the queue. Before a single acknowledgement send attempt, the bot verifies the report thread and looks for its exact existing acknowledgement, allowing recovery after an ambiguous write without a second post. Proposal output is written atomically before recording its scan checkpoint. Valid moderation checkpoints are published after command failures. Dispatch `bluesky_process_reports` with `dry_run=true` to preview collection without deletions, acknowledgements, checkpoint writes or PR creation.

Report proposals enter a durable moderation outbox in the same transaction that marks their notifications processed. Delivery retries that outbox even if the temporary proposals file is absent or empty. Pending entries retain the encoded joke, provider, source links and reason; reporter identifiers and reply text are not copied into the outbox. A matching same-repository review PR targeting `main`, whether open, closed or merged, is required before clearing the entry. Closed reviews are respected without reopening or recreating them. If a report branch exists without a PR, its changed files and content are checked against the original branch base before creating the missing review PR; unrelated or mismatched changes require investigation. API and delivery failures retain the proposal and fail the workflow visibly. Verified delivery receipts are saved even after another proposal fails, with a `main` branch check preventing an unapproved report branch from being pushed as state. Delivery receipts retain the latest 5,000 proposal keys; older reports still check PR history before creating anything.

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
