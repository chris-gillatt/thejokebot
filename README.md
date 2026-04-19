# The Joke Bot

[![post-joke](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_post_joke.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_post_joke.yml)
[![bluesky_follow_back](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_follow_back.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_follow_back.yml)
[![bluesky_unfollow](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_unfollow.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_unfollow.yml)
[![bluesky_generate_followers](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_generate_followers.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_generate_followers.yml)

Posts dad jokes to the Bluesky account [thejokebot.bsky.social](https://bsky.app/profile/thejokebot.bsky.social), and runs optional follower automation.

![joke bot](./images/jokebot-logo.png)

## What this repo does

- Posts a joke on a schedule.
- Avoids reposting the same joke within a rolling 90-day window.
- Supports follow-back, unfollow, and follower-generation scripts.

## Quick start (local)

1. Install Python 3.11 or newer.
2. Install dependencies:
	- `python -m pip install -r requirements.txt`
3. Copy and set environment values:
	- `cp .env.example .env`
4. Run a script:
	- `python bluesky_post_joke.py`

## Environment variables

Set these in `.env` (keep values quoted):

- `BLUESKY_USERNAME`: account handle (defaults to `thejokebot.bsky.social` if omitted).
- `BLUESKY_PASSWORD`: app password for Bluesky.
- `API_NINJAS_API_KEY`: API key for the API Ninjas dad jokes endpoint. Optional unless you want the `api_ninjas` backup provider enabled.
- `BLUESKY_DRY_RUN`: `true` or `false`.
- `BLUESKY_ACTION_DELAY_SECONDS`: delay between follow/unfollow actions.
- `BLUESKY_JOKE_PROVIDER`: leave unset to alternate between the primary providers (`icanhazdadjoke`, `jokeapi`). Set to a specific provider name only for explicit testing or emergency use.
- `BLUESKY_REPORT_MAX_PAGES`: optional cap for report notification paging (default `3`).
- `BLUESKY_REPORT_PAGE_LIMIT`: optional page size for report notifications (default `100`).

## Runtime safety controls

- Dry run:
  - Set `BLUESKY_DRY_RUN='true'` to log actions without applying them.
- Throttling:
  - Set `BLUESKY_ACTION_DELAY_SECONDS='1.5'` (example) to slow follow/unfollow loops.

These controls apply to:

- `bluesky_follow_back.py`
- `bluesky_unfollow.py`
- `bluesky_generate_followers.py`

## Joke providers

- Primary providers: `icanhazdadjoke`, `jokeapi`
- Backup live provider: `api_ninjas` (small joke pool — used after primaries fail)
- Offline final resort: `official_jokes` — 446 jokes bundled in `resources/official_jokes.json`, b64-encoded. No network access or API key required; always available.

The default behaviour alternates between the primary providers, tries `api_ninjas` if both fail, and falls back to `official_jokes` as a last resort. The offline provider means a joke post should always succeed even if every live API is unavailable.

## Scripts

- `bluesky_post_joke.py`: fetch a joke, append hashtags, post to Bluesky, maintain `bot_state.json`.
- `bluesky_follow_back.py`: follow users who follow the bot.
- `bluesky_unfollow.py`: unfollow accounts that do not follow back (except ignore list).
- `bluesky_generate_followers.py`: find hashtag users and follow up to configured limits.
- `bluesky_verify_latest_joke_post.py`: read-only check that a recent joke post exists on the account.
- `bluesky_process_reports.py`: poll Bluesky reply notifications for `#report`, map replies to posted jokes, and emit denylist proposals.
- `bluesky_create_report_prs.py`: create one denylist PR per report proposal.

## GitHub workflows

- `bluesky_post_joke.yml`: scheduled post run (`0 0,8,16 * * *`) and manual trigger.
- `bluesky_follow_back.yml`: scheduled every 2 hours and manual trigger.
- `bluesky_generate_followers.yml`: scheduled weekly (Friday) and manual trigger.
- `bluesky_unfollow.yml`: manual trigger.
- `bluesky_process_reports.yml`: scheduled every 30 minutes and manual trigger. Ingests `#report` replies, updates report checkpoints in `bot_state.json`, and opens one denylist PR per newly reported joke.

## State and references

- `bot_state.json`: local JSON state used for deduplication, provider rotation, and provider failure tracking.
- `resources/joke_denylist.json`: repository-backed denylist. Jokes added here are excluded from future posting.
- `references/bsky-docs`: local shallow submodule of Bluesky docs.

## User reporting flow

1. A user replies to a joke post with `#report`.
2. The report workflow reads reply notifications and maps the reply parent URI back to the posted joke state.
3. For each newly reported joke, the workflow opens one PR that adds the joke b64 to `resources/joke_denylist.json`.
4. Maintainers review and merge approved PRs.
5. Merged denylist entries are excluded from future posts automatically.

## Project governance

- Working scope and backlog: `problem-statement.md`.
- Copilot/project rules: `.github/copilot-instructions.md`.
- Temp command workspace: `.agent-tmp/` (kept empty in git except `.gitkeep`).