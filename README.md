# The Joke Bot

## Workflow status

| Category | Workflow | Status |
|---|---|---|
| Core posting | `bluesky_post_joke` | [![bluesky_post_joke](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_post_joke.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_post_joke.yml) |
| Engagement | `bluesky_follows_and_likes` | [![bluesky_follows_and_likes](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_follows_and_likes.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_follows_and_likes.yml) |
| Engagement | `bluesky_follow_fellows` | [![bluesky_follow_fellows](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_follow_fellows.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_follow_fellows.yml) |
| Housekeeping | `bluesky_unfollow` | [![bluesky_unfollow](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_unfollow.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_unfollow.yml) |
| Reporting | `bluesky_process_reports` | [![bluesky_process_reports](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_process_reports.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_process_reports.yml) |
| Quality | `ruff_quality` | [![ruff_quality](https://github.com/chris-gillatt/thejokebot/actions/workflows/ruff_quality.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/ruff_quality.yml) |
| Security | `codeql` | [![codeql](https://github.com/chris-gillatt/thejokebot/actions/workflows/codeql.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/codeql.yml) |
| Repository maintenance | `dependabot-auto-merge` | [![dependabot_auto_merge](https://github.com/chris-gillatt/thejokebot/actions/workflows/dependabot-auto-merge.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/dependabot-auto-merge.yml) |

Posts dad jokes to the Bluesky account [thejokebot.bsky.social](https://bsky.app/profile/thejokebot.bsky.social), plus account housekeeping automations.

![joke bot](./images/jokebot-logo.png)

## Functionality

- Posts regular jokes by a schedule.
- Avoids duplicating jokes within a rolling 90-day window.
- Rotates across multiple live joke APIs with a bundled offline fallback.
- Supports follow-back, reply liking, unfollow, and fellow-follow discovery scripts.
- Lets followers report unsuitable jokes via a `#report` reply, which triggers an automated PR to add the joke to a permanent denylist.

## Quick start (local)

1. Install Python 3.11 or newer.
2. Install dependencies:
	- `python -m pip install -r requirements.txt`
3. Copy and set environment values:
	- `cp .env.example .env`
4. Run a script:
	- `python bluesky_post_joke.py`

## Local validation helper

Before commit/push, run the local preflight gate:

- `./scripts/preflight-local.sh`

This runs:

- Ruff lint (`ruff check .`)
- Ruff format check (`ruff format --check .`)
- Unit tests (`pytest tests/ -v --tb=short`)
- Local CodeQL analysis when the `codeql` CLI is installed

If you only want tests after merges (for example Dependabot updates), run:

- `./scripts/test-local.sh`

If you prefer a direct one-liner without the helper script:

- `.venv/bin/python -m pytest tests/ -v --tb=short`

For local code-quality checks aligned with CI:

- `.venv/bin/ruff check .`
- `.venv/bin/ruff format --check .`

## Environment variables

Set these in `.env` (keep values quoted):

| Variable | Required | Description |
|---|---|---|
| `BLUESKY_USERNAME` | No | Account handle. Defaults to `thejokebot.bsky.social`. |
| `BLUESKY_PASSWORD` | Yes | App password for the Bluesky account. |
| `API_NINJAS_API_KEY` | No | API key for the API Ninjas jokes endpoint. Only needed if you want the `api_ninjas` backup provider. |
| `BLUESKY_DRY_RUN` | No | Set to `true` to log actions without applying them (also used by `bluesky_manage_starter_pack.py` for preview mode). |
| `BLUESKY_ACTION_DELAY_SECONDS` | No | Seconds to wait between follow/unfollow actions. |
| `BLUESKY_NETWORK_RETRY_ATTEMPTS` | No | Max attempts for transient network retries across API fetch/follow/like/unfollow/report calls (default `3`). |
| `BLUESKY_NETWORK_RETRY_DELAY_SECONDS` | No | Initial retry delay in seconds for transient network failures (default `1`). |
| `BLUESKY_NETWORK_RETRY_BACKOFF_FACTOR` | No | Multiplier applied to each retry delay step (default `2`). |
| `BLUESKY_UNFOLLOW_MAX_ACTIONS` | No | Safety cap per run for unfollow actions (default `200`; set `0` for no cap). |
| `BLUESKY_UNFOLLOW_BATCH_SIZE` | No | Unfollow batch size before pause (default `50`). |
| `BLUESKY_UNFOLLOW_BATCH_PAUSE_SECONDS` | No | Pause between unfollow batches in seconds (default `60`). |
| `BLUESKY_UNFOLLOW_IGNORE` | No | Comma-separated fully-qualified handles to protect from unfollowing (e.g. `theonion.bsky.social`). |
| `BLUESKY_JOKE_PROVIDER` | No | Force a specific provider by name (`icanhazdadjoke`, `jokeapi`, `groandeck`, `syrsly`, `api_ninjas`, `jokebot_jokebook`). Leave unset for normal rotation. |
| `BLUESKY_REPORT_MAX_PAGES` | No | Max notification pages to fetch per report run (default `3`). |
| `BLUESKY_REPORT_PAGE_LIMIT` | No | Notifications per page when polling for reports (default `100`). |

## Runtime safety controls

- **Dry run:** set `BLUESKY_DRY_RUN='true'` to log actions without applying them. Applies to `bluesky_follows_and_likes.py`, `bluesky_unfollow.py`, and `bluesky_follow_fellows.py`.
- **Throttling:** set `BLUESKY_ACTION_DELAY_SECONDS='1.5'` (example) to slow follow/unfollow/like loops.
- **Network retries:** set `BLUESKY_NETWORK_RETRY_ATTEMPTS`, `BLUESKY_NETWORK_RETRY_DELAY_SECONDS`, and `BLUESKY_NETWORK_RETRY_BACKOFF_FACTOR` to tune bounded retries for transient network/API failures.
- **Unfollow batching:** `bluesky_unfollow.py` is capped and batched by default (`BLUESKY_UNFOLLOW_MAX_ACTIONS=200`, `BLUESKY_UNFOLLOW_BATCH_SIZE=50`, `BLUESKY_UNFOLLOW_BATCH_PAUSE_SECONDS=60`) to reduce throttle risk on large clean-ups.
- **Starter-pack/list protection:** if `resources/jokebot_starter_pack.json` is enabled and points to a valid source list URI, all members of that list are automatically protected from unfollowing (unioned with `BLUESKY_UNFOLLOW_IGNORE`).
- **Post length preflight:** `bluesky_post_joke.py` skips over-long jokes and retries provider fetches before posting, using grapheme-aware length checks so posts stay within Bluesky's 300-character limit after hashtags are appended.

Bluesky rate-limit context (as documented):
- Repository write budget is point-based per account: `5000` points/hour and `35000` points/day; delete operations cost `1` point each.
- Hosted PDS API requests are also rate-limited by IP (`3000` requests per `5` minutes).
- This repo defaults to conservative unfollow batches so multi-thousand clean-ups can be done over repeated runs instead of one aggressive burst.

## Reporting a joke (#report)

If a posted joke is unsuitable, any Bluesky user can flag it:

1. Reply to the joke post with the hashtag `#report` (case-insensitive, standalone — e.g. `#report this is offensive`).
2. That's it. The bot picks up the reply automatically within 30 minutes.

The report triggers an automated PR adding the joke to the denylist. Once a maintainer merges the PR, the joke will never be posted again and the original post is deleted from the account on the next report run.

## Scripts

| Script | Purpose |
|---|---|
| `bluesky_post_joke.py` | Fetch a joke, append hashtags, post to Bluesky, maintain `bot_state.json`. |
| `bluesky_follows_and_likes.py` | Follow back new followers and like replies to the bot's posts. |
| `bluesky_unfollow.py` | Unfollow accounts that do not follow back (respects an ignore list). |
| `bluesky_follow_fellows.py` | Find hashtag users and follow up to configured limits. |
| `bluesky_verify_latest_joke_post.py` | Read-only check that a recent joke post exists on the account. |
| `bluesky_manage_starter_pack.py` | Convert/synchronise a starter pack from a configured Bluesky list and optionally follow missing list members. |
| `bluesky_process_reports.py` | Poll reply notifications for `#report`, map replies to posted jokes, delete approved denylist posts, and write PR proposals. |
| `bluesky_create_report_prs.py` | Open one denylist PR per new report proposal. |

## Starter pack workflow

Starter-pack operations are manual and safe by default.

Configuration lives in `resources/jokebot_starter_pack.json`:

- `enabled`: master switch for all starter-pack/list behaviour.
- `source_list_uri`: source list used for protection and starter-pack sync.
- `starter_pack_uri`: preferred update target URI (set after first live creation).
- `record_key`: optional TID rkey for explicit updates.
- `sync.follow_list_members`: when enabled, manager script follows list members not already followed.
- `sync.upsert_record`: when enabled, manager script updates the starter-pack record.

Run it via workflow dispatch: `bluesky_manage_starter_pack`.

- Leave `apply_changes=false` for dry-run preview.
- Set `apply_changes=true` to perform live follow/record mutations.

## Report workflow (technical detail)

The report pipeline runs every 30 minutes via `bluesky_process_reports`.

1. It scans replies for `#report`, maps each report to a posted joke, and ignores duplicates.
2. It writes proposals to `.agent-tmp/report_proposals.json` and opens denylist PRs via `bluesky_create_report_prs.py`.
3. It updates state in `bot_state.json` so notifications and deletions are not reprocessed.

## State

| File | Purpose |
|---|---|
| `bot_state.json` | Runtime state: posted joke history (b64, deduplication), provider rotation, report notification checkpoints, deleted post URIs, liked reply URIs. |
| `resources/jokebot_denylist.json` | Repository-backed denylist. Jokes added here are permanently excluded from posting. |
| `resources/jokebot_jokebook.json` | Bundled offline joke pool (446 jokes). Used as final fallback when all live APIs are unavailable. |

## Security

For vulnerability reporting and security handling expectations, see [SECURITY.md](SECURITY.md).

## Credits

Joke content is sourced from these third-party APIs:

- [icanhazdadjoke](https://icanhazdadjoke.com/api) — free dad jokes API
- [JokeAPI](https://jokeapi.dev) — multi-category joke API
- [GroanDeck](https://groandeck.com/api/v1/random) — free two-part groan-worthy jokes API
- [Syrsly Jokes API](https://www.syrsly.com/joke) — text dad-joke endpoint used as a backup provider
- [API Ninjas Jokes](https://api-ninjas.com/api/jokes) — supplementary backup provider

