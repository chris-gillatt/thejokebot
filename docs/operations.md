# Operations and Configuration

The [README](../README.md) covers the project at a glance. This guide covers local validation, runtime configuration and account maintenance.

## Local Setup and Validation

Use standard CPython 3.14.10 for the primary environment and follow the README's
Homebrew and `venv` locked-dependency installation steps. Recreate an existing
virtual environment when changing its interpreter. Python 3.14 is the minimum;
CI installs the hash-locked binary packages and runs the full suite on 3.14.10,
with deprecation warnings visible. Python 3.12 and 3.13 are no longer supported
or tested. Python 3.15 remains blocked by atproto 0.0.73's `<3.15`
constraint; do not bypass dependency metadata to force installation.

Pyright, Ruff's inferred target and Sonar's supported-version setting use Python
3.14. A single 3.14.10 CI job runs the authoritative Sonar analysis and zero-issue
gate. Dependabot merges require the current `tests` check, not the removed 3.12
compatibility check.
`pyproject.toml` defines the application version and direct dependencies;
`requirements.lock` pins the complete environment. An editable install uses
`--no-deps` deliberately so it cannot resolve a different set of dependencies.

To regenerate the lock file after a separately reviewed dependency change:

```bash
pip-compile --upgrade --allow-unsafe --extra=dev --generate-hashes --output-file=requirements.lock --strip-extras pyproject.toml
```

Run `npm ci --ignore-scripts` once to install the locked Pyright quality tool when needed for code validation. Before a non-documentation push, run `./scripts/preflight-local.sh` as a separate command. It checks Ruff lint and format, Pyright, workflow lint, unit tests, application coverage (at least 90% overall and 95% of changed executable Python), and local CodeQL. If CodeQL is unavailable, `BLUESKY_PREFLIGHT_ALLOW_REDUCED_COVERAGE=true ./scripts/preflight-local.sh` explicitly opts into reduced coverage. `./scripts/test-local.sh` runs only the tests.

**Docs-only SDLC exception**

For documentation-only changes, including prose-only agent instructions and
process guidance, do not run tests, preflight, builds, code lint/type checks,
coverage, CodeQL, Sonar or dependency audits. Do not install validation tools,
manually dispatch full CI or wait for full test/analysis gates solely for docs.
Review wording, links and formatting, confirm that only documentation changed,
run `git diff --check`, update the changelog, then rebase and push. Existing
automatic docs-only CI skips are sufficient.

Executable code, runtime configuration, workflows, dependency manifests/locks
and dashboard application assets are not documentation-only changes. Mixed
changes still require their normal relevant validation.

**Changelog completion gate**

Update [CHANGELOG.md](../CHANGELOG.md) in the same substantive commit as each
meaningful feature, fix, configuration, workflow, dependency, documentation or
project-process change. Before committing, check that its entry describes the
delivered effect and any breaking change; before completing work, confirm the
log is current alongside the applicable validation and remote-check results.
Group delivered changes by actual commit date, newest first; never create or
restore an `Unreleased` section. Preserve the retrospective pre-1.0.0 milestone
numbers, explicitly distinguished from original release tags and package
metadata; use verified package versions for actual releases. Follow the
[repository changelog policy](../.github/copilot-instructions.md#changelog-policy)
for grouping and automation exclusions.

For a retrospective audit, start with your authored commits:

```bash
git --no-pager log --author="$(git config user.name)" --date=short --format='%h %ad %s'
```

Also check meaningful agent and Dependabot commits. Omit routine automated
state/dashboard-data refreshes and issue-link-only commits. Backfill using actual
commit dates and stable commit links, not a bullet for every automation run.

Ruff's rule selection and file inclusion are explicit so a tool upgrade does not silently broaden the established lint policy. Keep runtime packages hash-locked, GitHub Actions SHA-pinned, and the dashboard's Chart.js version and integrity hash in sync.

To sync your checkout, use `git pull --rebase && git submodule update --init --recursive`. The `references/` submodules are read-only upstream resources, not runtime, build or dashboard dependencies. Dependabot checks their upstream default branches weekly on Monday at 06:30 Europe/London and groups available pin updates into a PR. The existing merge workflow accepts only the three registered reference paths and merges the checked head after its checks pass. Reference-only PRs skip Python tests, coverage and Sonar; lint, runtime-configuration and CodeQL checks still apply. Mixed reference/dependency/workflow changes retain the full checks, including Sonar. Nested submodules follow their parent's committed pins rather than receiving independent updates. Do not edit upstream content locally. Apply the relevant code-validation or docs-only review before syncing and pushing; scheduled workflows may update `main` while work is in progress.

Preview the staged GitHub Pages dashboard locally with `./scripts/preview-dashboard.sh` at <http://localhost:8765/>. Set `DASHBOARD_PREVIEW_PORT` to change the port. The dashboard publishes public aggregate metrics every six hours, keeps UTC monthly history, and never exports audience identifiers or raw workflow logs. Its Audience and Operations views distinguish sampled counts from reconstructed activity.

The Operations pulse names failed or overdue workflows and reports consecutive completed-run failures. A workflow failure is not necessarily a Python test failure: inspect its GitHub Actions logs to identify the failed step. If a failed attempt reports completed changes, its alert includes the run ID and attempt; verify saved state against completed actions before retrying. This warns of uncertain persistence, not proven lost state. A later successful retry does not erase the earlier observation within the alert's 24-hour window. An overdue joke-request checkpoint points to the Follows and likes workflow. Unrecognised alert types are shown explicitly rather than hidden behind a generic warning.

Activity collection reads recognised telemetry from completed successful and failed production attempts using attempt-specific log downloads. Cached and archived records retain workflow, run ID and attempt separately, with the observed conclusion when available. Queued and running attempts do not supply completed outcomes. Missing, expired or malformed logs remain unavailable evidence; planned follows without a completion summary do not establish failed-attempt activity. Legacy archives retain their known aggregates without invented conclusions or counters.

Measured posting outcomes contribute to provider supply even when the workflow later fails; they never turn that attempt into a successful workflow or an extra scheduled slot. Other measured action counters include failed attempts as completed attempts, not successful runs or distinct-account counts. Daily follows sum observed completed actions; daily unfollows use the greater of summed attempt counters and saved receipts, rather than adding receipts again. Daily joke-post totals remain backed by posting receipts, so a failed checkpoint can leave a confirmed provider publication without a matching daily posting receipt.

Audience source counts are completed outgoing follows, not incoming follower acquisitions. Follow completion divides completed follows by that source's measured candidates, eligible accounts or selected accounts; these denominators are not interchangeable. The historical JSON fields `acquired` and `success_rate` retain those outgoing-follow meanings for compatibility. Day-30 and day-90 relationship outcomes show how many observed cohort accounts follow the bot, with sample sizes and overdue observations. Follow-back cohorts began as existing followers, so their outcome describes retention rather than new reciprocity. Cohort outcomes are not causal attribution and do not share the rolling activity window. The network-protection duration is rendered from the collected configuration, never a hard-coded day count.

Audience and Operations have independent historical date controls: seven, 30 or 90 days, year to date, all available history, or inclusive custom UTC dates. Today is excluded because it is incomplete. Selected-period summaries compare against the immediately preceding equal-length period. Current counters, current rolling operational cards, source activity, fixed-age cohorts and top-post controls retain their separately labelled scopes.

Audience history uses the compact daily archive plus recent six-hour samples; Operations loads only monthly partitions needed for its selected period, comparison period and baseline day. Missing days remain gaps, not zeroes. Publication/follow period totals require complete daily coverage; partial observations are explicitly labelled subtotals with their covered-day counts and no comparison. Sampled account and visible-engagement changes require observations near both boundaries. A missing comparison or zero baseline never produces an infinite percentage. Availability notes describe loaded observations, not invented earlier measurements.

Historical workflow reliability counts observed successful and failed completed attempts, including retries, and excludes running/cancelled attempts from that denominator. Posting pressure uses runs with explicit provider telemetry. The delivery trend is a sampled rolling seven-day slot-delivery rate, not a daily total; rolling windows are never summed. Recorded unfollow events provide maintenance context; release and schedule changes are not inferred. Archive failures leave previous charts intact with an explicit error and retry instructions.

Operations leads with observed delivery slots, joke-request checkpoint time and the last observed moderation remainder. Production and CI alerts are separate: a CI failure does not prove an operational failure, and passing CI does not prove a post was delivered. Component rows show source observation times and the last successful workflow separately from dashboard regeneration. Cached social/moderation/maintenance summaries use their recorded run times; provider availability uses each recorded health-check time. Existing workflow cadence plus two hours defines overdue source observations; the existing eight-hour page-level collection warning is unchanged.

The selected Operations period includes failed workflow episodes grouped until the next observed successful workflow. Incident ordering and period membership use completion/update timestamps, falling back to recorded creation times for older receipts; a retry does not recover an incident at its original run creation time. Recovery describes workflow success, not proven recovery of posting, social actions or saved state. Running, queued and cancelled attempts do not establish recovery. Exact run/attempt links and available failed-step names support investigation. The collector fetches paginated jobs for failed run attempts, reuses successful metadata receipts from monthly history, and retries unavailable metadata on later collections. API/validation failures are reported as warnings and missing step detail, not fabricated step names or healthy outcomes. Only explicitly named first-party workflow steps are allowlisted; default command text, arbitrary API strings, raw logs and private identifiers are never exported.

Closed-slot exceptions list actual scheduled UTC times and single-use publication matches over the retained recent 30 days, independently of the historical selector. The keyboard inspection button focuses the labelled scroll region without adding a non-interactive element to the static tab order. A delayed slot is more than 30 minutes late within the existing two-hour match window; missed means no matching publication within that window. Open slots are excluded. The maintenance remainder is the sum of unreviewed candidates across historical runs, not a currently observed queue, and can count repeated accounts.

Provider supply follows the selected Operations period, not the cumulative retained-joke table. Publication shares count only confirmed published run outcomes; selecting a provider before a failed publication does not add to its share. Retries and manual runs count as separate workflow attempts, not scheduled delivery slots. The concentration index is the sum of squared publication shares: 1 means a single observed source; lower values indicate a more distributed mix. Daily gaps are absent observations, never zero concentration.

New `Provider candidates` log summaries contain only allowlisted provider names and integer counters. They distinguish provider visits, candidate fetch calls, returned candidates, successful selections, confirmed publications, duplicate/length rejections, exhausted visits and network/provider errors. Rejections before an eventual successful selection are retained. Internal transport retries are not separate candidate calls. Content rejection divides duplicate/length rejects by returned candidates; fetch error rate divides failed fetch calls by all candidate calls. Reaching the candidate limit is exhaustion, not endpoint failure. Availability checks measure endpoint or local-source access, not fresh-candidate supply.

Historical aggregate-only runs still contribute known publication outcomes but never invented candidate counters. Tables disclose both outcome and detailed-telemetry sample counts, and previous-period rejection changes and daily provider trends use only measured candidate samples. Static fallback appears in publication contribution without fabricated candidate-fetch data. These changes are descriptive, not new advisory thresholds or automatic provider-rotation changes. Equal-age engagement comparisons remain in Audience.

Comparable-age joke performance uses the existing six-hour collection schedule and complete public author-feed fetch. The first available observation in `[24, 30)` or `[168, 174)` hours is immutable, including when later engagement counts change. The dashboard labels these as age bands, not exact 24-hour or seven-day readings. Missing, hidden or deleted posts cannot supply an observation; a closed window remains missed and is never backfilled. Failed/incomplete fetches abort collection rather than recording partial samples.

Checkpoint receipts are persisted in `state/dashboard_engagement.json` and excluded from Pages. This repository is public: receipts contain only public bot-post URIs, publication/provider metadata, observation times and interaction counts, never audience identifiers or private text. Public metrics contain aggregates and currently visible public top-joke summaries. Previously observed hidden/deleted posts retain their aggregate contribution but are removed from top-joke links. Receipts and derived publishing-month history are retained for 400 days, with the original collection start disclosed.

Each age band compares the most recent 30 complete UTC publishing days whose entire observation windows have closed with the preceding 30 such days. It shows mean, median, observed/eligible sample counts, missed checkpoints, zero-interaction share and observed interaction-type totals. Pre-tracking checkpoints are excluded from the eligible denominator. There is no invented pre-collection checkpoint history. Provider and UTC publishing-hour comparisons use the same mature cohort and require 30 observed posts per group before displaying averages; they are descriptive, not causal evidence or impressions-based engagement rates. Publishing hour is the actual UTC publication hour, not a reconstructed scheduled slot. Existing cumulative visible totals and current-total top-post rankings remain separately labelled.

Follower totals are collection-time snapshots; missing historical follower totals remain blank rather than being estimated. Up to 30 days of following and profile-post totals can be reconstructed from aggregate successful-action logs and retained post timestamps, while joke-post, follow and unfollow activity is shown by day. The all-time view loads daily points from monthly history on demand. Audience growth combines follow-backs, interaction-led and discovery follows with source-specific success rates; 30/90-day reciprocity cohorts are reported only when observed. Pending checkpoints keep account hashes in private state and publish aggregate results only.

## Configuration

Copy `.env.example` to the ignored `.env` file for local use. Keep secrets out of `resources/jokebot_runtime_config.json`. Production workflows use `BLUESKY_USERNAME` and `BLUESKY_APP_PASSWORD` with `BLUESKY_PASSWORD_SOURCE=app_password`. Local use of the full account password requires an explicit `BLUESKY_PASSWORD_SOURCE=account_password` and `BLUESKY_PASSWORD`; credentials are never selected automatically. `BLUESKY_SESSION_CACHE_KEY` encrypts cached production sessions. `API_NINJAS_API_KEY` is optional for the backup provider.

When session restore is enabled, the authenticated session DID is checked against
the configured DID or the DID currently resolved from the configured handle
before the client is returned to a command. The profile is loaded only for that
verified DID. A mismatch removes the cached session and falls back to the
configured credentials. Transient identity-read failures use the bounded login
retry setting; if identity remains unverified, login fails rather than allowing
account actions. Workflow session caches are not account-namespaced, so this
runtime check is required when the configured account changes.

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
| `thejokebot-follows-and-likes` | Follow back, respond to interactions and explicit tagged joke requests, like replies and follow liked/reposted content creators. |
| `thejokebot-follow-fellows` | Discover accounts through rotating search tags. |
| `thejokebot-unfollow` | Remove non-reciprocal follows subject to grace and protection rules. |
| `thejokebot-process-reports`, `thejokebot-create-report-prs` | Process `#report` replies and propose denylist changes. |
| `thejokebot-collect-dashboard-metrics` | Collect public aggregate dashboard data. |
| `thejokebot-manage-starter-pack` | Preview or synchronise the configured list and starter pack. |
| `thejokebot-acknowledge-starter-packs` | Baseline known memberships or preview a popular-joke thank-you; publishing requires explicit approval. |
| `thejokebot-validate-runtime-config`, `thejokebot-validate-unfollow-ignore` | Validate configuration and protected unfollow handles. |
| `thejokebot-verify-latest-joke-post` | Check read-only for a recent post. |

## Account Maintenance

### Read-only transport review

Production uses the SDK's native httpx transport with a 30-second timeout.
The former requests/urllib3 adapter was removed after two independent
GitHub-hosted comparisons and a local comparison passed on 2 November 2026.

Dispatch `bluesky_check_transport` on `main` for a native SDK check from a
GitHub-hosted runner. It makes one fresh credential-login attempt, verifies the
authenticated session and performs three profile reads with identity checks.
Requests use a 30-second timeout; the job is capped at ten minutes. The probe
does not retry, post, follow, delete, save state or read/write cached sessions.
It creates authentication sessions but does not publish their tokens.

Logs contain package versions, completed phases, read counts, exception class
names and HTTP status codes only, not response bodies, identities or credentials.
Failure exits non-zero, with no automatic fallback or production changes.
Success establishes current read-only connectivity, not permanent availability
or verified posting. A new block needs investigation and a separately validated
transport change, not automatic installation of a browser-compatible client.
A 403 alone does not establish which firewall rule or TLS property caused it.

### Social and report actions

An explicit mention such as `@thejokebot.bsky.social tell me a joke` requests a threaded reply. The two-hourly social workflow sends at most two replies per requester and six replies overall per run. Requests are handled oldest first; those above either limit are discarded when the run advances its checkpoint. Reply jokes come from the bundled jokebook, carry the normal rotating tags, and do not consume the main posting workflow's 730-day uniqueness pool. The workflow excludes reports and checks for an existing bot reply before posting. To report an unsuitable posted joke, reply to the joke with standalone `#report`. The report workflow opens a denylist PR for maintainer review; after merge, a later run removes the approved post.

Starter-pack settings live in `resources/jokebot_starter_pack.json`. Dispatch
`bluesky_manage_starter_pack` with `apply_changes=false` to preview; use
`apply_changes=true` only for deliberate live changes. When enabled, members
of its source list are protected from unfollowing.

The unfollow command resolves every configured protected handle and completely
reads the enabled source list before preparing candidates. Missing or malformed
member data, lookup failures and incomplete pagination stop the run with a
non-zero status before state reconciliation or unfollow actions. A missing
config file or explicit `enabled: false` disables list-based protection; a
valid empty list is allowed.

For read-only inclusion checks, run `thejokebot-inspect-starter-packs` or dispatch the manual-only `bluesky_inspect_starter_packs` workflow. It checks retained packs discovered through attributed follows; add an explicit canonical AT URI with `--pack-uri` (repeatable locally) or the workflow's `pack_uri` input to test a known pack that has not produced a follow. The JSON report is written to `.agent-tmp/starter_pack_membership.json` locally and printed in workflow logs. It never posts, follows, changes runtime state, or publishes dashboard membership data.

The prototype checks at most 20 candidate packs, 10 list pages per pack and 100 members per page, with a 60-second request budget. In-flight requests may finish later, but another request or retry cannot start after that budget expires. A matching member is positive evidence; `not_member` means no match was found in a complete list traversal. Failed, mismatched or incomplete reads are `unknown`; candidate caps and runtime exhaustion report unchecked packs explicitly. Individual list-member identifiers are not included in the report. This is partial candidate verification, not a complete list of packs containing TJB, and it cannot establish when inclusion occurred. A successful workflow means a diagnostic report was produced, not that every pack was discovered or classified.

Current canonical schemas are maintained in [bluesky-social/bsky](https://github.com/bluesky-social/bsky/tree/main/lexicons/app/bsky/graph). [`getStarterPacksWithMembership`](https://github.com/bluesky-social/bsky/blob/main/lexicons/app/bsky/graph/getStarterPacksWithMembership.json) enumerates packs created by the session user, so it cannot provide a global reverse lookup. Known-candidate verification uses [`getStarterPack`](https://github.com/bluesky-social/bsky/blob/main/lexicons/app/bsky/graph/getStarterPack.json) and its underlying list.

### Starter-pack acknowledgement pilot (#115)

The pilot uses retained attributed-follow packs and explicit pack URIs only.
First run `thejokebot-acknowledge-starter-packs --mode baseline`: every candidate
must be classified, existing memberships are permanently baselined without a
thank-you, and already-initialised baselines cannot be reset by rerunning it.
Candidates observed absent can become eligible later; newly discovered members
are newly *observed*, not proof of a recent inclusion date.

The default `--mode preview` is read-only. It proposes at most one thank-you per
run: a current creator mention, one random eligible original from the dashboard's
top six by combined engagement, and a starter-pack link. Metrics must be no more
than 48 hours old. Original author, current URI/CID, local posting history and
moderation exclusions are rechecked. Missing, deleted, quoted, reply or moderated
posts are not selected. The message says “popular”, not “most liked”.

Review `.agent-tmp/starter_pack_acknowledgements.json` and the accompanying
`.html` draft. The HTML embeds the live original joke, but is not a published
Bluesky thank-you. Likes on a thank-you and the original remain distinct.
The manual `bluesky_acknowledge_starter_packs` workflow supports only baseline
and preview; it has no schedule or publish mode and prints the proposed JSON.

After explicit approval, local
`thejokebot-acknowledge-starter-packs --mode publish --pack-uri <approved-at-uri>`
uses that exact saved preview. **This performs a live public action.** Keep it
disabled until review; use a test account to verify actual quote rendering.
`BLUESKY_DRY_RUN=true` forbids both publishing and baseline writes.

The permanent `starter_pack_acknowledgements` ledger lives in social state and
is never age-pruned. Baseline/published packs remain ineligible after removal and
re-addition. Publish saves an immutable pending intent before the network write,
uses a deterministic record key and a repository commit compare-and-swap, and
confirms the exact record before marking it published. Uncertain writes are
never blindly retried: the next attempt reads that key first. Read errors,
changed creator handles/CIDs, mismatched records and unverified membership
withhold publication with an explicit error. Preserve pending entries for
investigation; never delete them merely to retry. Commit and push social state
even after a local publish failure before running any further account actions.

Automated activation, live thank-you rendering approval, broader discovery and
dashboard membership publication remain separate follow-up work under #115.

Fellow discovery reads TJB's saved custom feeds from its Bluesky preferences before searching the configured hashtags. No separate feed list is needed: saving or removing a custom feed in Bluesky changes the discovery sources. Built-in timelines and saved lists are excluded. Current saved-feed preferences take precedence over the legacy format, including when the current list is empty.

Each run samples one page of up to `follow_fellows.search_limit` posts (at most 100) from up to 10 saved custom feeds. When there are more than 10, a persisted offset rotates through the saved feeds after each successful live scan, even if it finds no accounts to follow. Failed reads and dry runs do not advance that offset. Candidates are the original post authors, including when a feed entry is a repost; blocked or muted authors are excluded. Feeds and hashtags share the existing `global_follow_limit` (currently 150), per-source initial allocation (`per_tag_limit`, currently 12), duplicate filtering, unfollow-history exclusions, follow grace and action pacing. Saved feeds are allocated first; this does not increase the run's total follow allowance or its schedule.

Discovery requires a complete following-list read and successful saved-preference/feed reads before following anyone. A failed or truncated prerequisite read aborts the run without follow actions. No saved custom feeds is a valid result and leaves hashtag discovery active. Dispatch `bluesky_follow_fellows` with `dry_run=true` to preview candidates without following accounts or changing social state; local runs can use `BLUESKY_DRY_RUN=true`.

Both social and unfollow runs completely read the authenticated account's
`app.bsky.feed.like` and `app.bsky.feed.repost` repository collections. This
covers manual actions in Bluesky as well as automated actions, including
existing records on the first scan. Creator DIDs are retained permanently in
`follow_tracking.content_creator_dids` in social state, independently of the
90-day follow grace period. Unliking/removing a repost later does not remove a
recorded protection. Historical interactions deleted before the first scan
cannot be reconstructed. Quote posts are not repost records and are not
included in this feature.

After reply liking, each two-hour social run follows at most
`follows_and_likes.content_follow_max_actions` creators (currently **10**).
The cap applies to this additional phase only; follow-back and incoming
interaction processing retain their existing behaviour. Already-followed,
blocked, muted and unavailable accounts are skipped. Explicit unfollow-history
exclusions (including `manual_block`) remain authoritative; an earlier automatic
`not_following_back` unfollow does not prevent a creator follow. New follows use
the existing deterministic record intents, action pacing, grace and checkpoints.
Creator follows contribute to the existing interaction-led aggregate counters
and cohorts; no creator identifiers are added to public dashboard metrics.

Each collection is bounded to 100 pages of 100 records, with a shared
120-second scan budget checked before each request/retry and after each
response. Invalid records, repeated cursors, API errors or incomplete reads
fail the scan rather than treating missing creators as unprotected. Neither
collection is checkpointed unless both reads complete. Unfollow runs refresh
these protections before selecting any candidate and fail without unfollowing
if that refresh fails. Dry runs preview the same protections and follow cap
without state writes or account actions. These are full scans, not timestamp
watermarks: automated likes have deterministic keys that need not sort by
creation time.

Unfollow runs commit grace reconciliation and candidate selection against fresh social state in a locked transaction before making changes to Bluesky. Each confirmed unfollow is checkpointed immediately in a fresh transaction; a later failure or throttle cannot discard earlier confirmed history or overwrite newer unrelated social fields. A checkpoint persistence failure stops the run. The workflow attempts to publish valid checkpoint JSON even when the command fails; invalid JSON is never committed by that step. Dry runs preview reconciliation without saving social state. Existing workflow concurrency still serialises social jobs; local file locks do not replace that control.

Social processing checkpoints explicit operations against fresh state rather than saving its whole working snapshot. Follow acquisitions, completed starter-pack scans, each page of confirmed likes, and joke-request receipts are saved independently. Joke-request scan checkpoints never move backwards, and equal-time boundaries are merged. If starter-pack attribution changes during a scan, that scan is rejected for a fresh retry instead of risking duplicate counts. Joke replies retain their single send attempt and live-thread duplicate verification; confirmed reply receipts update posting and social state together under their locks. The workflow attempts to publish valid checkpoint JSON after command failures. Dispatch `bluesky_follows_and_likes` with `dry_run=true` for a preview without account actions or state writes.

Report processing checkpoints confirmed deletions immediately and replays notification-resolution operations against fresh moderation state. Only completed scans advance the last-successful-poll timestamp. Pending acknowledgements retain the minimal reply/root references needed for retry even after a notification is marked processed; confirmed or permanently rejected acknowledgements clear the queue. Before a single acknowledgement send attempt, the bot verifies the report thread and looks for its exact existing acknowledgement, allowing recovery after an ambiguous write without a second post. Proposal output is written atomically before recording its scan checkpoint. Valid moderation checkpoints are published after command failures. Dispatch `bluesky_process_reports` with `dry_run=true` to preview collection without deletions, acknowledgements, checkpoint writes or PR creation.

Report proposals enter a durable moderation outbox in the same transaction that marks their notifications processed. Delivery retries that outbox even if the temporary proposals file is absent or empty. Pending entries retain the encoded joke, provider, source links and reason; reporter identifiers and reply text are not copied into the outbox. A matching same-repository review PR targeting `main`, whether open, closed or merged, is required before clearing the entry. Closed reviews are respected without reopening or recreating them. If a report branch exists without a PR, its changed files and content are checked against the original branch base before creating the missing review PR; unrelated or mismatched changes require investigation. API and delivery failures retain the proposal and fail the workflow visibly. Verified delivery receipts are saved even after another proposal fails, with a `main` branch check preventing an unapproved report branch from being pushed as state. Delivery receipts retain the latest 5,000 proposal keys; older reports still check PR history before creating anything.

Jokebook-origin report reviews propose both removal from the bundled jokebook
and a denylist instruction for the reported source post. Neither resource change
is approved merely by opening or closing the PR: deletion uses only the approved
resources on `main`. Once merged, the next report run deletes the source post
through the normal checkpointed deletion path, and the denylist suppresses the
same joke from every provider. Existing exclusions for other source posts are
preserved. If one resource change is already present, the review proposes only
the remaining work; if both are present but no matching review can be verified,
delivery stops for investigation rather than inventing approval. Orphan recovery
requires the exact remaining resource changes and rejects altered or extra files.

Approved-post removal timing is prospective. A newly persisted valid report proposal
starts one timer per source post; a successful approved deletion finishes it in
the same locked transaction as its deletion receipt. Retries preserve the start
time. Permanent deletion failures retain their existing deduplication behaviour
but do not produce timing samples. Existing notifications, outbox entries and
identifier-only receipts are not backfilled. Moderation state retains pending
timers keyed by a post-URI hash and the latest 5,000 anonymous completed samples.
The dashboard publishes only a 30-day completion count, coverage start and median
duration; the median remains `Collecting` below three samples. Timing includes
review and polling delays, excludes closed reviews without removal, and does not
measure all report outcomes or a live queue. Dry runs do not start timers. A
backwards clock omits the affected sample with a warning without losing the
deletion checkpoint.

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
