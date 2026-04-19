# The Joke Bot

[![post-joke](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_post_joke.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_post_joke.yml)
[![bluesky_follow_back](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_follow_back.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_follow_back.yml)
[![bluesky_unfollow](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_unfollow.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_unfollow.yml)
[![bluesky_generate_followers](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_generate_followers.yml/badge.svg)](https://github.com/chris-gillatt/thejokebot/actions/workflows/bluesky_generate_followers.yml)

Posts dad jokes to the Bluesky account [thejokebot.bsky.social](https://bsky.app/profile/thejokebot.bsky.social), and runs optional follower automation.

![joke bot](./images/jokebot-logo.png)

## What this repo does

- Posts a joke three times per day on a schedule.
- Avoids reposting the same joke within a rolling 90-day window.
- Rotates across multiple live joke APIs with a bundled offline fallback.
- Supports follow-back, unfollow, and follower-generation scripts.
- Lets followers report unsuitable jokes via a `#report` reply, which triggers an automated PR to add the joke to a permanent denylist.

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

| Variable | Required | Description |
|---|---|---|
| `BLUESKY_USERNAME` | No | Account handle. Defaults to `thejokebot.bsky.social`. |
| `BLUESKY_PASSWORD` | Yes | App password for the Bluesky account. |
| `API_NINJAS_API_KEY` | No | API key for the API Ninjas jokes endpoint. Only needed if you want the `api_ninjas` backup provider. |
| `BLUESKY_DRY_RUN` | No | Set to `true` to log actions without applying them. |
| `BLUESKY_ACTION_DELAY_SECONDS` | No | Seconds to wait between follow/unfollow actions. |
| `BLUESKY_JOKE_PROVIDER` | No | Force a specific provider by name. Leave unset for normal rotation. |
| `BLUESKY_REPORT_MAX_PAGES` | No | Max notification pages to fetch per report run (default `3`). |
| `BLUESKY_REPORT_PAGE_LIMIT` | No | Notifications per page when polling for reports (default `100`). |

## Runtime safety controls

- **Dry run:** set `BLUESKY_DRY_RUN='true'` to log actions without applying them. Applies to `bluesky_follow_back.py`, `bluesky_unfollow.py`, and `bluesky_generate_followers.py`.
- **Throttling:** set `BLUESKY_ACTION_DELAY_SECONDS='1.5'` (example) to slow follow/unfollow loops.

## Reporting a joke (#report)

If a posted joke is unsuitable, any Bluesky user can flag it:

1. Reply to the joke post with the hashtag `#report` (case-insensitive, standalone — e.g. `#report this is offensive`).
2. That's it. The bot picks up the reply automatically within 30 minutes.

The report triggers an automated PR adding the joke to the denylist. Once a maintainer merges the PR, the joke will never be posted again and the original post is deleted from the account on the next report run.

## Scripts

| Script | Purpose |
|---|---|
| `bluesky_post_joke.py` | Fetch a joke, append hashtags, post to Bluesky, maintain `bot_state.json`. |
| `bluesky_follow_back.py` | Follow back users who follow the bot. |
| `bluesky_unfollow.py` | Unfollow accounts that do not follow back (respects an ignore list). |
| `bluesky_generate_followers.py` | Find hashtag users and follow up to configured limits. |
| `bluesky_verify_latest_joke_post.py` | Read-only check that a recent joke post exists on the account. |
| `bluesky_process_reports.py` | Poll reply notifications for `#report`, map replies to posted jokes, delete approved denylist posts, and write PR proposals. |
| `bluesky_create_report_prs.py` | Open one denylist PR per new report proposal. |

## Report workflow (technical detail)

The report pipeline runs every 30 minutes via the `bluesky_process_reports` workflow. Each run:

1. **Deletes approved posts.** Reads `resources/joke_denylist.json` for entries with a `source_post_uri` and deletes those Bluesky posts if not already deleted. Deleted URIs are recorded in `bot_state.json` so the attempt is not retried.
2. **Scans reply notifications.** Fetches the most recent reply notifications (up to `BLUESKY_REPORT_MAX_PAGES` × `BLUESKY_REPORT_PAGE_LIMIT` entries). Already-processed notification URIs are stored in `bot_state.json` and skipped.
3. **Identifies `#report` replies.** A notification qualifies if it is a reply and its text contains `#report` as a standalone hashtag.
4. **Resolves the reported joke.** The reply's parent URI is looked up in the post URI index in `bot_state.json`. If not found there (e.g. state was reset), the post text is fetched live from the Bluesky API and encoded.
5. **Skips duplicates.** Jokes already in the denylist, or reported more than once in the same run, produce only one proposal.
6. **Emits proposals.** New proposals are written to `.agent-tmp/report_proposals.json`.
7. **Opens PRs.** `bluesky_create_report_prs.py` reads the proposals file and opens one pull request per new report. Each PR adds the joke's base64 value and evidence (post URI, reply URI, reporter DID) to `resources/joke_denylist.json`. Branches are named `chore/report-denylist-<sha1-prefix>` and skip creation if a matching remote branch or open PR already exists.
8. **Updates checkpoint state.** Processed notification URIs and the deletion record are saved back to `bot_state.json` and committed to `main` by the workflow.

## State

| File | Purpose |
|---|---|
| `bot_state.json` | Runtime state: posted joke history (b64, deduplication), provider rotation, report notification checkpoints, deleted post URIs. |
| `resources/joke_denylist.json` | Repository-backed denylist. Jokes added here are permanently excluded from posting. |
| `resources/official_jokes.json` | Bundled offline joke pool (446 jokes). Used as final fallback when all live APIs are unavailable. |

## Credits

Joke content is sourced from these third-party APIs:

- [icanhazdadjoke](https://icanhazdadjoke.com/api) — free dad jokes API
- [JokeAPI](https://jokeapi.dev) — multi-category joke API
- [API Ninjas Jokes](https://api-ninjas.com/api/jokes) — supplementary backup provider

