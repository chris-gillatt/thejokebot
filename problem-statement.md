# The Joke Bot – Problem Statement

## 1. Purpose
This document is the project-level operating brief for safe, incremental maintenance.
It should stay concise and current, with focus on active priorities and quality rules.

Detailed implementation history belongs in Git commit history and PRs. The milestone
changelog in this file is intentionally brief.

## 2. Working Principles
- Preserve core runtime behaviour unless a change is explicitly approved.
- Use focused, reversible changes; avoid speculative refactors.
- Keep secrets out of source control.
- Use British English in prose/documentation where practical.
- Use Conventional Commits with commit messages that explain why.
- Before push, sync with remote (`git pull --rebase`) because scheduled workflows can update `main`.
- Before commit/push, run local quality checks (`ruff check`, `ruff format --check`, unit tests, and local CodeQL when available) and fix issues proactively.
- Treat lint and tests as a combined gate for all code changes: do not consider a change validated if only tests ran without lint/format checks.

## 3. Operational Constraints
- The project is automation-first (GitHub Actions + script execution).
- Existing runtime contracts (script entry points, workflow triggers, key env vars) should be treated as stable interfaces.
- Required environment variable names such as `BLUESKY_APP_PASSWORD` (preferred), `BLUESKY_PASSWORD` (fallback), and `BLUESKY_USERNAME` should not change casually.
- Bluesky profile counters and raw follow records can exceed hydrated `get_followers`/`get_follows` results; suspended, deactivated, taken-down, or otherwise hidden accounts may still count in totals without materialising in actionable graph queries.

## 4. Current Active Risks
1. Dependency drift and workflow/runtime skew.
2. Behaviour regressions when touching posting/report/follow flows.
3. Scope creep during multi-file maintenance work.
4. **httpx TLS fingerprint workaround fragility** — all Bluesky API calls currently route through a custom `_RequestsTransport` in `bluesky_common.py` that delegates to `requests`/urllib3. If AWS WAF Bot Control later adds urllib3's JA3/JA4 fingerprint to its block-list, every workflow will break again. Fallback option is `curl_cffi`, which can impersonate a real browser TLS stack.
5. **Session-cache key custody** — cached Bluesky sessions must remain encrypted with `BLUESKY_SESSION_CACHE_KEY`. Rotating that secret invalidates existing cache generations and requires a credential login to seed a replacement.

## 5. Active Backlog

### 5.52 Improve dashboard hierarchy and local preview ✓ Complete
**Priority: Medium**

Separate the public dashboard into Audience and Operations views so visitor-facing
statistics are not presented at the same visual priority as maintainer diagnostics.
Use accessible, deep-linkable tabs; keep operational summaries and alerts visible;
and show complete provider and workflow tables in the Operations view. Clarify
discovery follow success, expose selected date ranges to assistive technology, and
share one GitHub Pages staging path between deployment and local preview.

Acceptance criteria:
- Audience is the default view and Operations is directly addressable by URL hash.
- Tabs support pointer, keyboard, browser-history, focus, and no-script use.
- Date-range controls expose their selected state, and discovery labels describe
  successful follows divided by selected accounts without changing the data schema.
- Operational alerts, summary metrics, provider data, and workflow data remain
  fully visible on desktop and mobile without nested expansion controls.
- Local preview reproduces the deployed artifact layout, including dashboard images.
- Focused tests and desktop/mobile browser checks cover semantics, navigation,
  overflow, chart pixels, asset loading, and expanded operational records.

### 5.35 Publish a GitHub Pages statistics dashboard (Issue #62) ✓ Complete
**Priority: Medium**

Build a static, public dashboard from aggregate Bluesky data collected every six
hours. Public reads use the cached `https://public.api.bsky.app` service without
credentials and retain the existing network retry, pagination, and fail-closed
behaviour. GitHub Actions persists a versioned metrics document and deploys the
site through GitHub Pages.

Acceptance criteria:
- Show the latest successfully posted joke at the top using its persisted
  `post_uri`, enhanced by the official Bluesky embed widget with a local fallback.
- Show current followers, following, profile posts, and received engagement
  totals for original joke posts: likes, replies, reposts, quotes, and bookmarks.
- Chart sampled follower, following, and profile-post totals over time, clearly
  distinguishing collection-time snapshots from reconstructable joke-post and
  unfollow history.
- Chart joke posts and unfollows over time, plus engagement per joke and recent
  top-performing jokes.
- Persist only public aggregate data and public post metadata; never persist
  follower, liker, replier, or other audience DIDs.
- Keep the collector idempotent for a six-hour interval, reject partial API
  pagination, and expose the latest successful collection time to the page.
- Provide responsive, accessible desktop and mobile layouts with a useful
  no-script and embed-failure experience.
- Cover collection, filtering, aggregation, schema handling, and identifier
  exclusion with focused tests, then validate the rendered site locally.

**Resolution:** Added an unauthenticated, fail-closed public metrics collector,
versioned aggregate history, official Bluesky latest-post embed with fallback,
responsive Chart.js views, and a six-hour GitHub Pages workflow. Pages is served
from <https://chris-gillatt.github.io/thejokebot/>. The generated data excludes
audience identifiers and distinguishes sampled account totals from activity
reconstructed from retained bot state.

### 5.36 Dashboard follow-up improvements ✓ Complete
**Priority: Low**

- ✓ Added selectable 7-day, 30-day, and all-time windows for top-performing jokes.
- ✓ Retain normalised six-hour telemetry in UTC monthly JSON partitions while
  keeping the initial dashboard payload to a rolling 30-day window. The all-time
  audience and activity views load derived daily history on demand. Canonical
  records are retained indefinitely; destructive downsampling remains deferred
  until measured repository growth justifies a separate retention decision.
- ✓ Provider engagement averages now require 30 currently visible posts and
  display their sample size with a descriptive-comparison caveat. Hashtag
  provenance is retained on future successful posts without historical
  inference; comparison remains deferred until 30-post cohorts accumulate.

### 5.37 Add dashboard build and run health ✓ Complete
**Priority: Medium**

Extended the public metrics document and dashboard with rolling 30-day GitHub
Actions reliability, stable first-party workflow rows, retained publication mix
by joke provider, average interactions for currently visible provider posts,
cumulative provider fall-throughs, and latest provider health state. GitHub
Actions collection is authenticated in CI, bounded to 20 pages, and covered by
multi-page regression tests. Labels distinguish rolling workflow data, retained
publication history, visible-post engagement, and combined legacy fall-through
reasons.

### 5.38 Correct optional-provider health classification ✓ Complete
**Priority: Medium**

API Ninjas accumulated consecutive health failures because the provider-health
workflow did not pass the existing `API_NINJAS_API_KEY` secret to its state
updater. The provider was therefore never called; missing credentials were
misclassified as an outage even though the health-test step treated that same
condition as expected.

The workflow now supplies the existing secret so API Ninjas receives a real
authenticated health check. Health state also distinguishes an optional provider
that is not configured from a configured provider that failed, resetting false
failure streaks and allowing the dashboard to show "Not configured" instead of
"Attention" when credentials are deliberately absent.

### 5.39 Split provider rejection telemetry ✓ Complete
**Priority: Medium**

Posting now records duplicate and over-length candidate rejections separately at
the point where each candidate is evaluated. Network failures and provider-level
errors use their own categories. The existing provider fall-through count and
last-error text remain for compatibility, while new `reason_counts` state starts
from zero rather than attempting to infer historical detail from combined error
messages.

Dashboard schema v2 exposes the reason counters in a dedicated rejected-candidate
column and labels their inception caveat. Producer, migration, aggregation, and
rendering are treated as a single contract under the repository validation rules.

### 5.40 Reconstruct recent account activity history ✓ Complete
**Priority: Medium**

The dashboard collector reads successful follow and unfollow outcomes from up to
30 days of GitHub Actions logs and retains only per-run aggregate counts. It uses
those counts with retained post timestamps to reconstruct following and
profile-post totals before collection-time snapshots began. Historical follower
totals remain unknown rather than being inferred from follow-back activity.

Log ingestion is idempotent across dashboard runs, bounded by compressed and
uncompressed archive limits, and stops reconstruction at the newest unavailable
or unrecognised run. The page exposes follows alongside jokes and unfollows,
marks reconstructed account history, and links to the source repository from
both the header and footer.

### 5.41 Exclude reference submodules from quality analysis ✓ Complete
**Priority: Medium**

All first-party quality tooling now excludes the read-only `references/`
submodules explicitly. Ruff and coverage retain their root exclusions; pytest
declares first-party test discovery; Pylance suppresses reference analysis; and
local plus GitHub CodeQL share one `paths-ignore` configuration. Actionlint was
verified to discover only the root repository's workflow directory.

### 5.42 Clarify dashboard workflow status and ranking ✓ Complete
**Priority: Medium**

Workflow metrics now retain the latest run status independently from its
conclusion. Active runs display as queued, waiting, or in progress instead of
the contradictory "No runs" label, which is reserved for workflows with no
runs in the rolling window. The ranked-joke grid now contains six posts so its
three-column desktop layout fills two complete rows.

### 5.43 Balance monthly follow and unfollow capacity ✓ Complete
**Priority: High**

The default unfollow cap is derived from four weeks of configured follow-fellows
capacity instead of remaining fixed at `200`. With the current `150`-account cap
and twice-weekly schedule, the monthly unfollow run can process up to `1,200`
eligible accounts. Explicit environment and numeric config overrides still take
precedence, while batching, grace periods, protected accounts, deterministic
selection, and throttle detection remain unchanged.

### 5.44 Split runtime state by operational purpose ✓ Complete
**Priority: Medium**

Issue #90 identified that unrelated workflows rewrote one growing state file and
therefore required a shared concurrency group plus offset schedules. Runtime
state is now divided into posting, social, moderation, and provider-health files
under `state/`.
Each writer persists only its owned domain and uses a matching concurrency group;
dashboard collection reads assembled state without serialising unrelated writers.
Legacy `bot_state.json` remains a read fallback for compatibility but is no longer
tracked or written. Provider-health persistence also uses bounded
pull/rebase/push retries.
Domain reads are isolated so one corrupt file cannot discard healthy state from
another domain, and updates refuse to overwrite a selected domain that could not
be read safely.

### 5.45 Restore configured account blocks (Issue #91) ✓ Complete
**Priority: Medium**

Maintain a private DID policy in the `BLUESKY_BLOCK_DIDS` GitHub repository
variable. Before the existing two-hour follow and like processing, compare that
policy with the account's current Bluesky blocks and recreate only missing
records. Never automatically unblock accounts. Rely on Bluesky's block filtering
for search-based discovery rather than adding parallel checks throughout social
scripts.

Acceptance criteria:
- Accept comma/newline-separated DIDs with optional handle comments, while using
  only stable DIDs for identity.
- Reject the complete policy before mutation when any entry is invalid or names
  the bot account itself.
- Page through all current blocks and preserve both configured and unmanaged
  existing blocks.
- Support existing dry-run, delay, masking, and retry controls.
- Backfill every currently blocked account into the private variable before
  enabling enforcement.

**Resolution:** The existing two-hour social workflow now validates the private
DID policy, reads the complete live block set, and recreates only missing blocks
before any follow or like processing. Five existing live blocks were backfilled
to the repository variable without committing or logging their identifiers.

### 5.46 Harden Bluesky session-file persistence ✓ Complete
**Priority: High**

Persist exported session credentials through an owner-only temporary file before
atomically replacing the live cache path. Permission, write, flush, and replace
failures remove temporary token material and leave no newly exposed destination.
Focused tests cover restrictive permissions, failed hardening, and replacement
of an existing session file.

### 5.47 Make provider health monitoring deterministic ✓ Complete
**Priority: Medium**

Keep live provider connectivity in the scheduled health updater and use mocked
provider functions in the ordinary test suite. The workflow now probes each
provider once per run, persists every result, and applies its existing alert
threshold only after two consecutive primary-provider failures. Tests cover
successful responses, exceptions, streak escalation, recovery, and deliberately
unconfigured optional providers without requiring network access.

### 5.48 Add discovery-run performance to the dashboard ✓ Complete
**Priority: Medium**

Fellow-follow discovery now emits an explicit aggregate run summary and reports
successful follows by tag rather than selected candidates. The dashboard retains
30 days of classified run totals and shows accounts considered and added,
completion, typical run size, and zero-result runs. Public metrics contain no
account identifiers, tags, targeting details, or workflow run identifiers, and
older unclassified activity is not presented as discovery history.

### 5.49 Repair dashboard history and expand operational reporting ⏳ Planned
**Priority: High**

The discovery and account-total views need correction before more dashboard
surface area is added. The live metrics document contains successful discovery
runs cached before schema v4, but those records lack their workflow name and
selection totals. The collector treats matching run IDs as complete and never
reprocesses them, leaving discovery activity empty until a new run occurs.
The account chart also splices daily reconstructed values into six-hour sampled
values, combines unrelated absolute scales, and renders profile posts on a
crowded secondary axis. Although the underlying values are labelled by source,
the resulting graph does not communicate meaningful growth.

#### Phase 1: Repair existing views ✓ Complete

- Reprocess only cached `bluesky_follow_fellows` runs that are missing v4
  classification or discovery totals. Use the current GitHub run metadata to
  identify them, then parse their retained logs with the existing legacy and
  explicit-summary parsers. Preserve an honest coverage boundary when logs have
  expired rather than estimating missing outcomes.
- Keep discovery on its own fixed rolling 30-day window. Do not let the account
  chart's 7/30/all selector filter only the discovery graph while leaving its
  summary cards unchanged.
- Replace the combined account-total graph with sampled audience change from the
  first available Bluesky snapshot. Plot follower and following deltas on one
  axis, exclude profile posts, and show absolute totals plus deltas in tooltips.
- Retain reconstructed following and profile-post values in the accessible data
  table, with an explicit sampled/reconstructed source column. Keep the current
  profile-post total and latest change in the metric band.
- Show a useful collecting-history state until at least two sampled audience
  snapshots exist.

Acceptance criteria:
- The next dashboard collection backfills all still-readable discovery runs
  without re-fetching already complete cached runs.
- Empty, partially expired, legacy, and current discovery caches have focused
  migration tests.
- Audience lines share a zero-based change axis and never join reconstructed
  points to sampled points.
- Tooltips and tables make absolute value, delta, timestamp, and source clear.
- Desktop and mobile screenshots verify empty and populated discovery states,
  sampled audience history, table overflow, chart pixels, and text fit.

#### Phase 2: Operational pulse and posting delivery ✓ Complete

- Add a compact alert strip for stale dashboard collection, overdue core
  workflows, recent failures, and unhealthy configured providers. Classify
  transient upstream failures separately from persistent failures where the
  available run metadata supports that distinction.
- Compare configured posting slots with retained successful post timestamps over
  7 and 30 days. Show expected, delivered, delivery rate, current streak, and
  genuinely missed slots. Use UTC and define one bounded matching window per
  slot so a post cannot satisfy two expected runs.
- Add latest and median workflow duration from GitHub run `created_at` and
  `updated_at` metadata; do not ingest job logs for duration alone.

#### Phase 3: Social funnel and network maintenance ✓ Complete

- Emit one stable aggregate summary from the follows-and-likes workflow covering
  follow-back candidates, protected/history skips, successful additions,
  interaction candidates, interaction additions, failures, and replies liked.
- Retain 30 days of those summaries and render a neutral social-activity funnel.
  Publish counts only; never retain audience identifiers in dashboard data.
- Summarise active response-window entries by broad source and monthly unfollow
  outcomes: eligible, processed, completed, failed, missing records, and early
  throttle stops. Keep wording operational and avoid exposing selection rules.

#### Phase 4: Moderation and engagement momentum ✓ Complete

- Parse the existing report workflow summaries into proposals, acknowledgements,
  approved removals, and unresolved outcomes. Do not treat all processed reply
  notifications as reports.
- Add aggregate report lifecycle timestamps at the producer before calculating
  resolution time; do not infer historical durations from current state.
- Add engagement totals to future six-hour snapshots, then derive observed 7 and
  30-day gains after enough samples accumulate. Label them as snapshot deltas,
  account for removed/hidden posts, and avoid age-normalised claims.

Resolution-time reporting remains deferred until the new aggregate lifecycle
events provide a sufficient observed history; no duration is inferred from
legacy identifier-only state.

#### Phase 5: Provider pressure trends ✓ Complete

- Emit a per-posting-run aggregate summary containing provider attempts,
  successful source, fallback use, and rejection counts by existing category.
- Build rolling provider pressure and fall-through rates only from the new event
  stream. Existing cumulative counters remain lifetime context and must not be
  presented as historical trends.

The dashboard keeps observed 7/30-day posting-run pressure separate from the
existing lifetime publication and failure counters.

Cross-phase rules:
- Increment the dashboard schema only when the persisted contract changes, and
  keep old metrics readable during deployment.
- Treat producer logs, collector parsing, generated JSON, and rendering as one
  tested contract for every new metric.
- Persist aggregate counts, public post metadata, and workflow names only; no
  audience DIDs, report contents, targeting tags, secrets, or raw logs.
- Do not claim discovery follow-back conversion, hashtag effectiveness, or post
  engagement decay without durable cohort or fixed-age observations.
- Deliver each phase as a separate commit/PR-sized change with the full local
  quality gate and desktop/mobile visual verification.

### 5.50 Correct primary-provider rotation and promote Syrsly ✓ Complete
**Priority: High**

Provider telemetry showed that the nominal round-robin rotation was advancing
from the provider that eventually supplied a joke rather than the primary that
was scheduled first. A failed JokeAPI attempt followed by an icanhazdadjoke
success therefore selected JokeAPI again on the next run and could repeatedly
delay GroanDeck.

Track the scheduled primary independently from the successful source and order
the remaining primaries cyclically from that slot. Posting telemetry now records
both values so the dashboard can compare intended starts with publications.
Historical provider summaries remain readable while new observations accumulate.

Syrsly was promoted from backup to the primary rotation after a live sample of
50 dad-joke responses produced 50 unique, short, family-appropriate candidates.
Its known encoded-entity quirk remains covered by the existing multi-pass posting
sanitiser. API Ninjas remains backup-only because its free tier has a small joke
pool and more restrictive usage terms; the bundled jokebook remains the offline
final fallback. Review Syrsly's duplicate rate, fall-throughs, and engagement on
the dashboard and demote it if production evidence identifies a quality issue.

### 5.51 Report starter-pack follow attribution (Issue #96) ✓ Complete
**Priority: Medium**

Track authenticated `follow` notifications that include starter-pack metadata
and publish rolling 30-day counts per pack in the Social activity dashboard.
Bootstrap at most 30 days of available notifications, then scan newest-first
from a timestamp and hashed same-timestamp boundary; paging cursors are not
durable checkpoints.

Persist only aggregate UTC daily counts and public pack metadata. Follower DIDs,
notification URIs, and raw notifications must not enter state or dashboard data.
Ignore `starterpack-joined` notifications because they do not represent follows
attributed to the bot's inclusion in a pack. A scan updates counts and its
checkpoint only after reaching the previous boundary or bootstrap cutoff.

Dashboard schema v9 exposes pack name, creator handle, stable Bluesky link,
coverage timestamps, and per-pack counts. It does not infer a percentage of
overall follower growth because the available account snapshots cannot support
honest event-level attribution.

### 5.26 Retry transient Bluesky response failures ✓ Complete
**Priority: High**

The Python SDK reports upstream HTTP failures such as `504 UpstreamTimeout` as
`RequestException`, which previously bypassed the common network retry helper.
Shared retry classification now covers transport failures, SDK `NetworkError`,
HTTP `5xx`, and HTTP `429`, with exponential delay, jitter, and `Retry-After`
support. Other `4xx` responses still fail immediately.

Paginated graph reads now propagate exhausted failures instead of returning
partial follower/following snapshots, preventing follow decisions from being
made with incomplete account state.

### 5.25 Harden Bluesky session refresh and credential selection ✓ Complete
**Priority: High**

Session credentials are encrypted before GitHub cache storage and shared across
the serialised Bluesky workflows using run-unique cache generations. Invalid or
revoked sessions are removed before credential recovery; transient login failures
receive bounded retries. Session persistence is registered before login so newly
issued credentials survive a later profile-fetch failure.

Credential selection no longer silently falls back from `BLUESKY_APP_PASSWORD`
to the full account password. `BLUESKY_PASSWORD_SOURCE=account_password` is now
required for deliberate local use of `BLUESKY_PASSWORD`; production workflows
explicitly select `app_password`.

### 5.1 Unfollow Re-Engagement Guardrail ✓ Complete
See v1.4 changelog entry.

### 5.2 Logging and Network Guardrails ✓ Complete
See v1.5 changelog entry.

---

### 5.3 Unfollow history not persisted to repo ✓ Complete
See v1.7 changelog entry.

---

### 5.4 BLUESKY_UNFOLLOW_IGNORE undocumented ✓ Complete
See v1.8 changelog entry.

---

### 5.5 Stale `### File:` header comments ✓ Complete
See v1.8 changelog entry.

---

### 5.6 `posted_jokes.txt` legacy file in repo root ✓ Complete
File was already absent from the repository — no action required.

---

### 5.7 `bluesky_create_report_prs.py` missing from README scripts table ✓ Complete
Script was already present in the README table — no action required.

---

### 5.8 Dual source of truth for provider rotation order ✓ Complete
Single source of truth now lives in `bluesky_state.PROVIDER_ROTATION_ORDER`; `bluesky_joke_providers.PRIMARY_PROVIDERS` is derived from it.

---

### 5.9 Python version: schedule bump from 3.11 to 3.12 ✓ Complete
Updated all Python-running workflows from `python-version: "3.11"` to `"3.12"`.

---

### 5.10 Missing concurrency guards on follow/report workflows ✓ Complete
Added `concurrency` blocks with `cancel-in-progress: false` to:
- `bluesky_follow_fellows.yml`
- `bluesky_process_reports.yml`
- `bluesky_follows_and_likes.yml`

---

### 5.11 Investigate GroanDeck as new primary joke provider ✓ Complete
**Priority: Medium**

GroanDeck (`https://groandeck.com/api/v1/random`) is a free REST API with no
sign-up or API key required (30 req/min on the free tier). Response shape is
`{"setup": "...", "punchline": "..."}` — a clean two-part format that maps
naturally to the existing two-part joke assembly already used for JokeAPI. The
pool is substantial (~800+ jokes across categories). No content-safety parameter,
so review the category list to confirm it matches the bot's family-friendly policy
before adding. Candidate for the primary rotation alongside or in place of JokeAPI.

**Resolution:** All 33 GroanDeck categories confirmed family-friendly (~2,200 total
jokes: puns, animals, food, technology, etc.; no adult or dark-humour content).
Added `fetch_from_groandeck()` in `bluesky_joke_providers.py`, appended `groandeck`
to `bluesky_state.PROVIDER_ROTATION_ORDER` (primary rotation is now
`[icanhazdadjoke, jokeapi, groandeck]`), registered in `PROVIDERS` dict. No API key
required. README updated with provider names in `BLUESKY_JOKE_PROVIDER` doc. 4 new
tests added.

---

### 5.12 Investigate HumorAPI as new backup joke provider ✗ Will Not Do
**Priority: Medium**

HumorAPI (`https://api.humorapi.com/jokes/random`) has an `exclude-tags=nsfw,dark`
parameter and a `max-length` cap (useful for staying within Bluesky's 300-character
post limit). Requires an API key (`api-key` query param). The quota model is
point-based (1 point per request); the free tier should be adequate for the bot's
usage. Fits naturally as a backup provider alongside `api_ninjas`. Assess whether
the joke pool is suitably family-friendly and add `HUMORAPI_API_KEY` env var, a
`fetch_from_humorapi()` function, and README/`.env.example` documentation if it
passes review.

**Decision:** Do not implement HumorAPI integration due to terms-and-conditions
concerns around permitted use/storage of joke content for this endpoint.

---

### 5.13 Enforce post-length preflight before Bluesky send ✓ Complete
**Priority: High**

Posting previously relied on the API call to reject over-limit payloads. Add a
pre-send guard so provider candidates are filtered and retried before posting,
using the effective joke-length budget after hashtags are appended.

**Resolution:** Implemented in `bluesky_post_joke.py` via
`BLUESKY_MAX_POST_CHARS=300`, `_HASHTAG_SUFFIX_LEN`, and `_MAX_JOKE_CHARS`.
`pick_joke()` now skips over-long jokes and retries like duplicate handling;
if all attempts are duplicates/too long it falls through to next provider.
Test coverage added for skip-and-retry and all-too-long failure paths.

---

### 5.14 Use grapheme-aware length checks for post safety ✓ Complete
**Priority: Medium**

Current length preflight uses Python `len()` (code points), while Bluesky limits
are based on visible character units. For composed emoji and combining marks,
code-point counts may diverge from rendered length. Evaluate and, if needed,
switch to grapheme-cluster counting in the preflight check to avoid false
accept/reject edge cases.

**Resolution:** `bluesky_post_joke.py` now uses grapheme-cluster counting via
the `regex` package (`\X`) for preflight length checks. `_MAX_JOKE_CHARS` is
now derived from grapheme-aware hashtag suffix length, and `pick_joke()`
compares joke length in graphemes rather than code points. Added regression
tests covering combining-mark edge cases and updated dependencies.

---

### 5.15 Add operational hygiene for stale unfollow ignore handles ✓ Complete
**Priority: Low**

`BLUESKY_UNFOLLOW_IGNORE` can accumulate handles that no longer resolve
(`Profile not found`), which now degrades gracefully but still adds noisy logs.
Add a lightweight maintenance task/runbook step to periodically validate ignore
handles and prune stale entries in GitHub Actions secrets.

**Resolution:** Added `bluesky_validate_unfollow_ignore.py` to resolve
`BLUESKY_UNFOLLOW_IGNORE` handles and report stale entries with deterministic
output. Added workflow `.github/workflows/bluesky_validate_unfollow_ignore.yml`
for monthly and manual validation runs using existing Bluesky credentials. Script
defaults to failing when stale handles are detected so repository secrets/vars can
be pruned promptly.

---

### 5.16 Add Ruff lint/format checks in CI ✓ Complete
**Priority: Medium**

Add a lightweight code-quality workflow using Ruff for linting and format
validation. Start in non-invasive mode (`ruff check` and `ruff format --check`)
to surface issues in pull requests without broad refactors. Include a minimal
`pyproject.toml` Ruff configuration only if needed for stable rule selection.

**Resolution:** Added `.github/workflows/ruff_quality.yml` with
`pull_request`, `push` (`main`), and manual dispatch triggers. The workflow uses
Python 3.12 and runs non-invasive checks only: `ruff check .` and
`ruff format --check .`. Added matching local validation commands to `README.md`.

---

### 5.17 Add GitHub CodeQL analysis workflow ✓ Complete
**Priority: Medium**

Add a standard GitHub CodeQL workflow for Python to provide free baseline
security/static analysis and code scanning alerts on pull requests and main
branch updates. Keep configuration minimal initially, then tune query packs and
exclusions only if noise is observed.

**Resolution:** Added `.github/workflows/codeql.yml` using GitHub's standard
CodeQL actions for Python (`init`, `autobuild`, `analyze`) with
`pull_request`, `push` (`main`), weekly schedule, and manual dispatch triggers.
Permissions are scoped to `actions: read`, `contents: read`, and
`security-events: write`. README workflow status table updated with CodeQL badge.

---

### 5.18 Add Syrsly as an additional backup provider ✓ Complete
**Priority: Medium**

Issue #8 requested adding Syrsly (`https://www.syrsly.com/joke`) as an
additional provider. Implementation uses `https://www.syrsly.com/joke/dad`
as a family-friendly backup source. Added `fetch_from_syrsly()` and registered
`syrsly` in `PROVIDERS` and `BACKUP_PROVIDERS` (ahead of API Ninjas and the
offline jokebook fallback). Added provider tests and env/README documentation.

Because the endpoint can return BOM-prefixed and HTML-escaped text, posting
sanitisation now strips leading UTF-8 BOM markers before final normalisation.

---

### 5.19 Create a starter pack from the Funnies list ✓ Complete
**Priority: Medium**

Issue #14 requested converting The Joke Bot's existing Bluesky list ("Funnies")
into a starter pack, plus operational guardrails so list accounts are followed and
not accidentally removed by unfollow automation.



**Resolution:** Added `resources/jokebot_starter_pack.json` and a new script
`bluesky_manage_starter_pack.py` with hybrid operation (one-time setup and manual
sync). Script can upsert the `app.bsky.graph.starterpack` record from the source
list and optionally follow missing list members.

Added workflow `.github/workflows/bluesky_manage_starter_pack.yml` with manual
dispatch and dry-run default (`apply_changes=false`) for safe roll-out.

`bluesky_unfollow.py` now loads source list members from
`resources/jokebot_starter_pack.json` when enabled and unions those DIDs with
`BLUESKY_UNFOLLOW_IGNORE` protection, preventing accidental removals.

### 5.22 Pull starter-pack metadata from Bluesky ✓ Complete
**Priority: Medium**

Issue #19 identified that the live starter-pack name/description on Bluesky had
diverged from `resources/jokebot_starter_pack.json`, creating a risk that the
existing setup/sync path would overwrite manual live edits on the next run.
Bluesky should remain the source of truth for starter-pack metadata.

**Resolution:** Added `pull_starter_pack_record()` and
`write_starter_pack_config_updates()` to `bluesky_manage_starter_pack.py`.
The new `--mode pull` path fetches the live starter-pack record, shows an
actual dry-run preview of changed fields, and optionally writes those changes
back to `resources/jokebot_starter_pack.json` without touching follows or
source-list membership. The workflow now exposes `pull` mode and commits pulled
config updates back to the branch only when `apply_changes=true`.

---

### 5.24 Similar jokes with different punctuation bypass deduplication ✓ Complete
**Priority: Medium**

Near-identical jokes from different providers can currently slip through the
duplicate filter when the wording is unchanged but punctuation differs
(for example `?` versus `.`, or a missing apostrophe/quote mark). That creates
repetitive posts even though the joke content is effectively the same.

**Resolution:** `bluesky_post_joke.py` now performs duplicate checks against a
punctuation-insensitive normal form at comparison time, while still storing the
original posted joke `b64` unchanged for report handling and state/history
lookups. Added regression tests covering skip-and-retry behaviour and all-
duplicate failure when punctuation is the only difference.

---

### 5.25 Follow users who interact with the bot's posts ✓ Complete
**Priority: Medium**

Users who reply to, repost, or like the bot's posts are engaged with the content
and represent natural candidates to follow. The bot should follow them (if not
already doing so) and apply the same 90-day grace window used for all outbound
follows, so they are not unfollowed immediately if they do not follow back.

Guard rules to prevent churn:
- Only look at interactions from the last 24 hours (matching the existing window
  used by `like_replies()`).
- Skip any DID already being followed, still within the follow-grace window, or
  present in the unfollow history (to avoid repeated follow/unfollow cycles).

**Resolution:** Added `follow_interactors()` to `bluesky_follows_and_likes.py`.
It fetches reply, repost, and like notifications from the last 24 hours, collects
unique author DIDs, applies the three-way exclusion guard, then follows and
records new follows in `follow_grace` with `source="interaction"`. Called from
`main()` between `follow_back()` and `like_replies()`. 9 new focused tests added;
suite at 167 passing.

---

### 5.30 Rotate hashtags used in joke posts ✓ Complete
**Priority: Medium**

Issue #50 requested broader hashtag rotation for joke posts so discovery does not
rely on the same fixed trio every run.

**Resolution:** `bluesky_post_joke.py` now builds a deterministic rotating post-tag
window from a resolved posting pool with explicit precedence
(`posting.tag_pool` → `follow_fellows.hashtags` → `posting.hashtags`), tracks
progression in posting state via a dedicated `posting.tag_offset`, and
advances offset after successful posts. Post-length preflight now calculates the
joke budget per post from the selected hashtags (grapheme-aware), reducing
avoidable rejections while preserving Bluesky 300-character safety checks. Added
focused regression tests for posting offset backfill/wraparound, rotated hashtag
selection, and dynamic length budget behaviour.

---

### 5.31 Finish state transaction migration ⏳ Deferred
**Priority: Medium**

`bluesky_state.update_state()` supports domain-scoped locked read-modify-write
persistence, and the posting, follow-fellows, and provider-health writers use it.
Remaining direct `save_state()` workflows (`bluesky_process_reports.py`,
`bluesky_follows_and_likes.py`, and `bluesky_unfollow.py`) now write only their
owned domain, but still need careful transaction migration because state changes
are interleaved with network-side actions.

---

### 5.27 Review and revert httpx WAF workaround when safe to do so ⏳ Deferred
**Priority: Low**

**Timeline:**
- 2026-05-17T03:42 UTC: AWS WAF Bot Control began blocking Python httpx's TLS fingerprint (JA3/JA4)
- 2026-05-17 (same day): Workaround implemented and shipped — `_RequestsTransport` in `bluesky_common.py` routes all httpx I/O through `requests.Session` (urllib3 stack)
- 2026-05-17 to 2026-05-19: Validated in production through staged workflow rollout (stages 1–5); all workflows passing with cached session tokens

**Final Resolution (2026-05-19):**
The `_RequestsTransport` workaround is stable and proven. It uses a different TLS fingerprint (urllib3 instead of httpx's native stack) to bypass WAF Bot Control. Simultaneously, we implemented session persistence and caching, which reduced login frequency from ~67/day to ~1/day (96% reduction), providing defence-in-depth: even if urllib3 fingerprint is later added to WAF's block-list, the cached sessions mean we'd only be affected every ~60 days (refresh token TTL) rather than on every workflow run.

**Why we keep the workaround:** It is low-complexity, battle-tested, and non-invasive. Reverting to plain httpx now leaves us with no fallback if the block resumes. If urllib3 is blocked in future, the planned upgrade path is to `curl_cffi` (browser-spoofing transport), which is a more sophisticated solution but requires a compiled dependency.

**When to revisit:** Periodically (e.g. after a new atproto SDK release, after any Bluesky infrastructure announcement, or if WAF blocks urllib3), test whether a plain `Client()` login succeeds from a GitHub Actions runner without the transport override.

**Quick smoke-test:** add a temporary workflow step that runs
`python -c "from atproto import Client; c = Client(); c.login('$U', '$P'); print('Success')"`
with real credentials and checks for success output (not a 403 response) before considering removal of the workaround.

**Alternative future paths (if urllib3 is blocked):**
- Evaluate `curl_cffi>=0.7,<1` with `impersonate="chrome120"` mode (most resilient but requires compiled dependency; verify it builds on ubuntu-24.04 first)
- Investigate whether Bluesky offers an alternative API endpoint not subject to WAF Bot Control rules

---

### 5.26 Centralised runtime config foundation (Issue #38) ✓ Complete
**Priority: Medium**

Issue #38 requests centralised, safer configuration for cadence and operational
controls. Initial implementation creates a shared, versioned runtime config file
for non-secret defaults and starts migrating script defaults to consume it while
preserving existing environment-variable overrides.

Guard-rail intent for this phase:
- Keep behavioural drift minimal by preserving current defaults.
- Keep secrets out of central config.
- Keep env overrides operational for emergency adjustments.
- Add schema validation for core numeric/list fields.

**Resolution:** All scripts with operational defaults now consume from
`resources/jokebot_runtime_config.json` via `bluesky_config.py`. The config
schema covers `posting`, `follow_fellows`, `follows_and_likes`, `unfollow`,
`reports`, and `workflow_schedules`. `bluesky_follows_and_likes.py` now derives
its four page/limit constants from the new `follows_and_likes` config section.
`bluesky_verify_latest_joke_post.py` derives its hashtag list from
`posting.hashtags`. Schema validation, deep-merge with built-in defaults, and
a safe fallback-to-defaults path are all implemented.

---

### 5.33 Stagger state-writer workflow schedules ✓ Complete
**Priority: High**

Recent `bluesky_post_joke` scheduled runs were cancelled before any job started
because several workflows sharing the `bot_state_writer` concurrency group were
scheduled at the same minute. GitHub Actions keeps at most one running and one
pending run per concurrency group, so same-minute state-writer bursts can evict
the pending joke-posting run even with `cancel-in-progress: false`.

**Resolution:** Kept `bluesky_post_joke` on its existing cadence and staggered
the other scheduled `bot_state_writer` workflows away from minute zero. Updated
the central runtime schedule metadata to match the workflow YAML so validation
continues to catch drift.

---

### 5.34 Separate reactive follow-back from proactive follow policy ✓ Complete
**Priority: High**

Unfollow history prevents proactive discovery and interaction paths from
restarting follow/unfollow churn. It must not suppress a follow-back after an
account actively follows the bot again. Permanent exclusions belong in the
configured block policy rather than unfollow history.

**Resolution:** `bluesky_follows_and_likes.follow_back()` follows every current
actionable follower regardless of unfollow history. Proactive follow paths still
honour history, while configured blocks are reconciled before follow-back.

---

### 5.35 Make follow-back converge and soften unfollow eligibility ✓ Complete
**Priority: High**

Issues #101 and #103 showed that a single partial or stale graph snapshot could
leave followers outstanding while the workflow still reported success. Issue
#105 extended the requested response grace from one month to three months.

**Resolution:** Follow-back now requires complete follower and following graph
pagination, performs bounded fetch-act-verify reconciliation, and fails the run
if a final snapshot still contains actionable followers. Unfollow graph reads
also require complete snapshots before any destructive action. The state-backed
response grace is now 90 days, with the existing monthly unfollow cadence kept
to spread eligible clean-up without extra API pressure.

## 6. Explicit "Will Not Do" Decisions
Do not revisit these without a concrete operational reason.

| Item | Decision | Reason |
|---|---|---|
| Migrate joke history to a database | Will not do | Current state-file approach is sufficient for operational scale. |
| Rewrite scripts as async | Will not do | No throughput requirement justifies complexity increase. |
| Redesign workflow schedules by default | Will not do | Current cadence works; change only for observed operational need. |
| Remove base64 encoding from state payloads | Will not do | Prevents fragile comparisons and avoids indexing raw joke text. |
| Integrate HumorAPI provider | Will not do | Terms-and-conditions concerns around permitted use/storage of joke content for this endpoint. |

## 7. Completed Milestones (Condensed)
- Multi-provider joke chain implemented with offline last resort (`jokebot_jokebook`).
- Workflow hardening completed (concurrency controls, safer state persistence, retry on push races).
- Security/stability hardening completed (exception narrowing, file locking, safer retries).
- Report pipeline improvements completed (`#report` acknowledgement, like/report rules, jokebook-aware report handling).
- Follow script renamed to `bluesky_follow_fellows.py` to reflect conservative behaviour and reduce misleading framing.
- Unfollow automation now applies safety-first batching controls (per-run cap, inter-batch pause, and throttle-aware early stop).
- Unfollow schedule runs monthly with a state-backed 90-day response grace and safety-first batching controls.
- Re-engagement guardrail implemented: proactive follow paths exclude unfollow history, while current followers remain eligible for reactive follow-back.

## 8. Changelog (Milestones)
- v0.1: Initial governance draft.
- v0.7: Multi-provider chain complete.
- v0.8: Workflow hardening complete.
- v0.9: Security/stability hardening complete.
- v1.0: Error-handling improvements complete.
- v1.1: Low-priority quality hardening complete.
- v1.2: Jokebook report handling fix complete.
- v1.3: Unfollow batching safeguards added (rate-aware stop, per-run action cap, configurable batch pause) to support cautious large clean-ups.
- v1.4: Re-engagement guardrail (5.1) implemented. `unfollow_history` section added to `bot_state.json`. Each live unfollow is recorded. `bluesky_follow_fellows.py` excludes all previously-unfollowed DIDs. `bluesky_follows_and_likes.py` logs re-engagements when a previously-unfollowed DID is detected in the current followers list. 5 new state-layer tests added; suite at 68 passing.
- v1.5: Logging and network guardrails (5.2) complete. Narrowed remaining bare `except Exception` handlers in `bluesky_follower_utils.py`, `bluesky_follow_fellows.py`, and `bluesky_follows_and_likes.py` to `(requests.RequestException, TimeoutError)`. Non-network defensive catches (`extract_text`, base64 decode, SDK attribute access) left as-is — they wrap arbitrary data, not network calls. Suite remains at 68 passing.
- v1.6: Unfollow schedule changed to daily at 12:00 UTC to clear ~4,400 non-follower backlog (200 per run). Also fixed `atproto_client.exceptions.NetworkError` not being caught by narrowed exception handlers, and corrected bare username `theonion` → `theonion.bsky.social` for AT identifier validity.
- v1.7: Fixed `bluesky_unfollow.yml` missing `contents: write` permission and state-persist step. Unfollow history was silently lost at the end of every CI run, making the re-engagement guardrail ineffective. Added push-retry step matching the pattern in `bluesky_post_joke.yml`.
- v1.8: Low-priority housekeeping batch. Documented `BLUESKY_UNFOLLOW_IGNORE` in `.env.example` and README (5.4). Removed stale `### File:` header lines from `bluesky_state.py`, `bluesky_follower_utils.py`, and `bluesky_joke_providers.py` (5.5). Confirmed `posted_jokes.txt` and `bluesky_create_report_prs.py` README row already resolved (5.6, 5.7).
- v1.9: Resolved provider-rotation dual source of truth (5.8). `bluesky_joke_providers.PRIMARY_PROVIDERS` now derives from `bluesky_state.PROVIDER_ROTATION_ORDER`, with a test guard to keep them aligned.
- v1.10: Completed Python runtime maintenance bump (5.9). All workflows running project scripts now use `python-version: "3.12"`.
- v1.11: Added missing workflow concurrency guards (5.10) to follow-fellows, follows-and-likes, and process-reports using the same `cancel-in-progress: false` safety model as post-joke.
- v1.12: Added GroanDeck as a third primary provider (5.11). `fetch_from_groandeck()` added, all 33 categories reviewed and confirmed family-friendly. Primary rotation extended to `[icanhazdadjoke, jokeapi, groandeck]`.
- v1.13: Added pre-post length guard (5.13). `pick_joke()` now skips over-long jokes before API send, retries within provider attempts, and falls through provider chain when necessary.
- v1.14: Added Syrsly as a backup provider (5.18) using the dad-joke endpoint, plus BOM sanitisation hardening for provider text normalisation.
- v1.15: Hardened starter-pack update path (5.19 follow-on): full AT URI validation with DID and collection enforcement; removed misleading slug default for `record_key`; shared list-member DID helpers moved to `bluesky_follower_utils`; 5 new regression tests. Prompt file added for reusable code review. Suite at 105 passing.
- v1.16: Added Ruff code-quality CI checks (5.16) via `.github/workflows/ruff_quality.yml` with non-invasive lint/format validation (`ruff check .`, `ruff format --check .`) on pull requests and `main` updates. README local validation guidance updated to match.
- v1.17: Completed repo-wide Ruff formatting pass and switched `ruff_quality` format validation to strict enforcement (removed advisory mode), so formatting drift now fails CI.
- v1.18: Added baseline GitHub CodeQL scanning (5.17) via `.github/workflows/codeql.yml` for Python on pull requests, `main` updates, weekly schedule, and manual dispatch.
- v1.19: Completed grapheme-aware post-length preflight (5.14) in `bluesky_post_joke.py` using `regex` grapheme-cluster counting so composed characters are measured by visible units instead of code points.
- v1.20: Marked HumorAPI integration (5.12) as will-not-do due to terms-and-conditions concerns around content use/storage for that endpoint.
- v1.21: Completed stale ignore-handle hygiene (5.15) by adding a dedicated validator script and monthly/manual workflow to surface and prune unresolved `BLUESKY_UNFOLLOW_IGNORE` entries.
- v1.22: Completed starter-pack metadata pull support (5.22). `bluesky_manage_starter_pack.py` now supports `--mode pull` to preview and optionally persist live Bluesky name/description changes back into `resources/jokebot_starter_pack.json`, and the workflow can commit those updates back to the branch. Suite at 144 passing.
- v1.23: Code-review follow-ups and quality hardening. Fixed loop lambda closures in `bluesky_follow_fellows.py` (CS-8) to use default-argument pattern. Made `get_int_env()` public and removed duplication in `bluesky_unfollow.py` (CS-3, CR-1). Added explicit `permissions: contents: read` to `bluesky_follow_fellows.yml` (CS-2). Added `BLUESKY_USERNAME` env var to `bluesky_follows_and_likes.yml` (CS-4). Fixed `STATE_FILE` path resolution to use `__file__`-relative path (CS-7). Improved error diagnostics in `bluesky_create_report_prs.py` (CS-6). Added test coverage for `collect_report_proposals()` notification paging and filtering (CS-9). Suite now at 140 passing (formatter-affected count update).
- v1.24: Tightened joke deduplication (5.24) so punctuation-only variants now compare as duplicates during provider retry checks, while preserving the original stored `b64` for state and denylist/report flows. Added focused regression coverage for punctuation-only duplicate variants.
- v1.25: Added interaction-follow feature (5.25). `follow_interactors()` added to `bluesky_follows_and_likes.py`. Fetches reply, repost, and like notifications from the last 24 hours and follows unique author DIDs not already being followed, in the grace window, or in the unfollow history. Followed DIDs recorded in `follow_grace` with `source="interaction"` so the standard grace period applies before any unfollow. 9 new focused tests added; suite at 167 passing.
- v1.26: Started centralised config implementation for issue #38 (5.26). Added `resources/jokebot_runtime_config.json` and `bluesky_config.py` schema/loader with validation and safe fallback-to-defaults on invalid file data. Wired `bluesky_post_joke.py`, `bluesky_follow_fellows.py`, and `bluesky_unfollow.py` to consume central config defaults while retaining env-based runtime override behaviour.
- v1.27: Extended centralised config rollout (5.26). `bluesky_process_reports.py` now consumes report default limits from central config, and new validator `bluesky_validate_runtime_config.py` enforces schema + workflow schedule metadata alignment in CI via `.github/workflows/validate_runtime_config.yml`.
- v1.28: Added cadence-aware runtime guard rails to `bluesky_validate_runtime_config.py` (5.26 follow-on). Validator now fails fast when risky schedule/frequency changes are paired with aggressive report/unfollow/follow control values, reducing accidental high-blast-radius configuration drift.
- v1.29: Completed centralised config rollout (5.26). Added `follows_and_likes` config section to `bluesky_config.py` and `resources/jokebot_runtime_config.json`. Wired `bluesky_follows_and_likes.py` to consume page/limit constants from config instead of hardcoding them. Wired `bluesky_verify_latest_joke_post.py` to derive its hashtag list from `posting.hashtags`. All scripts with operational defaults now consume from central config. Closes #38.
- v1.31: Completed hashtag-rotation rollout for issue #50. `bluesky_post_joke.py` now rotates post hashtags deterministically from the configured pool, tracks posting tag offset in state, and computes per-post grapheme-aware length budget from selected tags before accepting joke candidates. Added focused tests and documentation updates.
- v1.30: Completed configuration tuning for issue #52. Extended joke deduplication window from 365 to 730 days (`posting.days_limit`), reduced follow grace from 90 to 30 days (`FOLLOW_RESPONSE_GRACE_PERIOD_DAYS`), and moved unfollow cadence from quarterly to monthly (`0 12 1 * *`) to smooth clean-up volume. Updated runtime config defaults, unfollow workflow schedule, docs, and tests.
- v1.32: Fixed posting hashtag diversity regression for issue #76 by introducing explicit posting-pool precedence (`posting.tag_pool`, then `follow_fellows.hashtags`, then `posting.hashtags`) and restoring a broad default posting tag pool. Added regression tests for precedence and varied hashtag selection across posting offsets.
- v1.33: Staggered state-writer workflow schedules so `bluesky_post_joke` is no longer cancelled by same-minute `bot_state_writer` queue contention. Runtime schedule metadata remains aligned with the workflow YAML.
- v1.34: Fixed issue #87 by using the existing DID-based `unfollow_history` model. `follow_back()` now skips previously unfollowed DIDs, and `wt5here.bsky.social` is recorded as a manual block in state rather than introducing a parallel handle-based block list.
- v1.35: Published the issue #62 statistics dashboard through GitHub Pages, with six-hour public Bluesky snapshots, an official latest-joke embed, account and activity trends, aggregate engagement, and identifier-safe generated data.

## 9. Code Review: Issues Resolved

Conducted 1 May 2026 against HEAD (`19f0c1c`). All findings have since been addressed. This section documents the review for completeness and as a record of the analysis process.

---

### 🟢 Resolved Issues (v1.23)

#### CR-1 — `bluesky_process_reports.py`: bare `int()` coercions of env vars ✓ Fixed
**File:** `bluesky_process_reports.py`, lines 255–256.

**Status:** Fixed in v1.23. `get_int_env()` is now public (previously private `_get_int_env`), and both `BLUESKY_REPORT_PAGE_LIMIT` and `BLUESKY_REPORT_MAX_PAGES` use safe parsing with defaults.

### 🟢 Resolved Suggestions (v1.23)

#### CS-1 — `bluesky_follow_fellows.py`: module-level `client`/`username` globals
**Status:** Not addressed — remains future optimisation candidate. Function arguments pattern now used consistently throughout. Does not block operations.

#### CS-2 — `bluesky_follow_fellows.yml`: no `permissions` block ✓ Fixed
**File:** `.github/workflows/bluesky_follow_fellows.yml`, line 12.

**Status:** Fixed in v1.23. Workflow now explicitly declares `permissions: contents: read`.

#### CS-3 — `bluesky_unfollow.py`: duplicates `_get_int_env`/`_get_float_env` ✓ Fixed
**File:** `bluesky_unfollow.py` and `bluesky_common.py`.

**Status:** Fixed in v1.23. `_get_int_env` renamed to `get_int_env` (public), and `bluesky_unfollow.py` now imports and reuses it with `minimum=0` argument.

#### CS-4 — `bluesky_follows_and_likes.yml`: missing `BLUESKY_USERNAME` env var ✓ Fixed
**File:** `.github/workflows/bluesky_follows_and_likes.yml`, line 38.

**Status:** Fixed in v1.23. Workflow now explicitly passes `BLUESKY_USERNAME: ${{ vars.BLUESKY_USERNAME }}` to the script.

#### CS-5 — `bluesky_manage_starter_pack.py`: `_build_starter_pack_record` overwrites `createdAt` ✓ Fixed
**File:** `bluesky_manage_starter_pack.py`, lines 110 and 183–198.

**Status:** Fixed in v1.22. `_build_starter_pack_record()` now preserves the original `createdAt` timestamp when updating an existing record, fetching it from the live record if needed.

#### CS-6 — `bluesky_create_report_prs.py`: stderr suppressed on git/gh command failures ✓ Fixed
**File:** `bluesky_create_report_prs.py`, lines 21–26.

**Status:** Fixed in v1.23. `run_command()` now prints stderr on failure for better debugging.

#### CS-7 — `bluesky_state.py`: `STATE_FILE` is CWD-relative ✓ Fixed
**File:** `bluesky_state.py`, line 28.

**Status:** Fixed in v1.23. `STATE_FILE` now uses `Path(__file__).resolve().parent` for deterministic path resolution.
```python
def _build_starter_pack_record(starter_cfg, source_list_uri, created_at=None):
    return {
        ...
        "createdAt": created_at or dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
```

#### CS-6 — `bluesky_create_report_prs.py`: stderr suppressed on git/gh command failures
**File:** `bluesky_create_report_prs.py`, `run_command()`.

**Problem:** `subprocess.run(..., capture_output=True)` captures both stdout and stderr but neither is printed on failure. When `git checkout -b`, `git push`, or `gh pr create` fails, the raised `CalledProcessError` carries no human-readable diagnostic. Debugging CI failures requires digging into raw exception tracebacks.

**Fix:**
```python
#### CS-6 — `bluesky_create_report_prs.py`: stderr suppressed on git/gh command failures ✓ Fixed
**File:** `bluesky_create_report_prs.py`, lines 21–26.

**Status:** Fixed in v1.23. `run_command()` now prints stderr on failure for better debugging.

#### CS-7 — `bluesky_state.py`: `STATE_FILE` is CWD-relative ✓ Fixed
**File:** `bluesky_state.py`, line 28.

**Status:** Fixed in v1.23. `STATE_FILE` now uses `Path(__file__).resolve().parent` for deterministic path resolution.

#### CS-8 — Loop lambda closures: inconsistent late-binding pattern ✓ Complete
**File:** `bluesky_follows_and_likes.py` (`follow_back`), `bluesky_follow_fellows.py` (`follow`).

**Problem:** Several loop lambdas capture the loop variable by reference rather than by value, e.g.:
```python
lambda: client.follow(did)
```
Because `retry_network_call` is synchronous this is safe today, but it is inconsistent with `bluesky_manage_starter_pack.py` which correctly uses:
```python
lambda current_did=did: client.follow(current_did)
```
The default-argument pattern is the idiomatic Python fix and removes the implicit dependency on synchronous execution order.

**Resolution:** Fixed `bluesky_follow_fellows.py` line 59 to use the default-argument pattern. `bluesky_follows_and_likes.py` line 73 already uses the correct pattern.

#### CS-9 — Test coverage gaps ✓ Complete
The following significant paths are now covered:

| Area | Status |
|---|---|
| `bluesky_manage_starter_pack.ensure_following_list_members()` | ✓ Covered (follow-sync path added in v1.22 tests). |
| `bluesky_process_reports.collect_report_proposals()` | ✓ Covered (notification collection tests added; max-pages limit, empty cursor, already-processed skipping, non-reply marking). |
| `bluesky_process_reports.delete_approved_report_posts()` | ✓ Covered (delete, skip-already-deleted, missing-URI, invalid-URI tests). |
| `bluesky_state.load_state()` / `save_state()` with locking | ✓ Covered (round-trip file-locking test added). |
| `bluesky_follow_fellows.main()` | ✓ Covered (smoke tests for re-engagement exclusion and unfollowed DID filtering). |

All items now have unit test coverage. Suite remains at 140 passing tests.

---

### ✅ Good Practices

- **Atomic state writes** via `os.replace()` from a temp file prevent partial-write corruption on interruption — consistent across `bluesky_state.py`, `bluesky_denylist.py`, and `bluesky_create_report_prs.py`.
- **File-level locking** (`fcntl.flock`) on Unix guards against concurrent read/write races in `bluesky_state.py`.
- **Defensive pagination**: cursor deduplication, page-count cap, and wall-clock runtime guard in `bluesky_follower_utils.fetch_paginated_data`.
- **Dry-run default** on all mutating operations. Workflows default `apply_changes=false`; state-mutating scripts check `BLUESKY_DRY_RUN`.
- **Retry wrappers** with configurable exponential backoff (`retry_network_call`) applied consistently across all network calls.
- **Exception narrowing**: no bare `except Exception` in network paths; exceptions are narrowed to `(requests.RequestException, TimeoutError, atproto_client.exceptions.NetworkError)`.
- **Shared helpers** in `bluesky_follower_utils` (pagination, list-member DID extraction) eliminate duplication across scripts.
- **AT URI validation** with DID match and collection enforcement in `bluesky_manage_starter_pack` guards against inadvertent writes to wrong records.
- **Concurrency guards** (`cancel-in-progress: false`) on all workflow files prevent overlapping runs.
- **Dependabot auto-merge** gated behind a full test run and restricted to patch/minor semver updates only.
- **Single source of truth** for provider rotation in `bluesky_state.PROVIDER_ROTATION_ORDER`; `bluesky_joke_providers.PRIMARY_PROVIDERS` is derived from it, backed by a test guard.
- **Report pipeline idempotency**: processed/acknowledged/deleted URIs are tracked in state to prevent duplicate actions across runs.
