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
- `API_NINJAS_API_KEY`: API key for the API Ninjas dad jokes endpoint. Optional unless you want the last-resort backup provider enabled.
- `BLUESKY_DRY_RUN`: `true` or `false`.
- `BLUESKY_ACTION_DELAY_SECONDS`: delay between follow/unfollow actions.
- `BLUESKY_JOKE_PROVIDER`: leave unset to alternate between the primary providers (`icanhazdadjoke`, `jokeapi`). Set to `api_ninjas` only for explicit testing or emergency fallback use.

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
- Backup-only live provider: `api_ninjas`
- Static fallback jokes remain the final safety net if all live providers fail.

The default behaviour alternates between the primary providers and only uses `api_ninjas` if the primaries fail. This is intentional because the API Ninjas dad jokes endpoint has a very small joke pool.

## Scripts

- `bluesky_post_joke.py`: fetch a joke, append hashtags, post to Bluesky, maintain `bot_state.json`.
- `bluesky_follow_back.py`: follow users who follow the bot.
- `bluesky_unfollow.py`: unfollow accounts that do not follow back (except ignore list).
- `bluesky_generate_followers.py`: find hashtag users and follow up to configured limits.
- `bluesky_verify_latest_joke_post.py`: read-only check that a recent joke post exists on the account.

## GitHub workflows

- `bluesky_post_joke.yml`: scheduled post run (`0 0,8,16 * * *`) and manual trigger.
- `bluesky_follow_back.yml`: scheduled every 2 hours and manual trigger.
- `bluesky_generate_followers.yml`: scheduled weekly (Friday) and manual trigger.
- `bluesky_unfollow.yml`: manual trigger.

## State and references

- `bot_state.json`: local JSON state used for deduplication, provider rotation, and provider failure tracking.
- `references/bsky-docs`: local shallow submodule of Bluesky docs.

## Project governance

- Working scope and backlog: `problem-statement.md`.
- Copilot/project rules: `.github/copilot-instructions.md`.
- Temp command workspace: `.agent-tmp/` (kept empty in git except `.gitkeep`).