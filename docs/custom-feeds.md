# Custom Feeds Strategy

## Objective
Improve discoverability of The Joke Bot posts using Bluesky custom feeds while
remaining compliant with platform anti-spam guidance.

## Compliance Guardrails
The bot must not perform promotional spam behaviours:
- No auto-like campaigns
- No auto-reply campaigns
- No mass-follow workflows for growth
- No DM automation

The integration in this repository is currently read-only and observational:
- optional hashtag rotation at posting time (bounded and configurable)
- feed visibility checks against configured feed URIs

## Recommended Approach
Start with existing feed integration before building a dedicated feed generator.

Why:
- lower complexity and maintenance
- no always-on service required
- faster to validate whether discovery improves

## Current Implementation (Phase 1/2)
1. Config file: `resources/jokebot_custom_feeds.json`
2. Optional bounded hashtag rotation in `bluesky_post_joke.py`
3. Read-only feed visibility checker: `bluesky_check_custom_feeds.py`
4. Scheduled GitHub Actions workflow: `.github/workflows/bluesky_audit_custom_feeds.yml`

All features are disabled by default.

Runtime rule: keep `target_feeds` empty until you have real feed URIs. Do not
keep placeholder values in `resources/jokebot_custom_feeds.json`.

This discovery path is temporary. It exists only to gather evidence before the
project decides whether to remove it or replace it with an owned feed generator.

## Configuration
Example from `resources/jokebot_custom_feeds.json`:

```json
{
  "custom_feeds": {
    "enabled": false,
    "mode": "existing",
    "target_feeds": [
      {
        "name": "Real Target Feed",
        "uri": "at://did:plc:your-feed-generator-did/app.bsky.feed.generator/your-feed-key"
      }
    ],
    "hashtags": {
      "enabled": false,
      "max_per_post": 2,
      "rotate": ["#joke", "#dadjokes", "#pun", "#puns", "#cleanhumour"]
    }
  }
}
```

## Operational Guidance
- Keep `max_per_post` low (recommended: 1-2)
- Prefer clean humour tags and avoid engagement-bait tags
- Periodically review configured target feeds for activity and relevance
- Keep this feature disabled by default unless intentionally testing/discovering

## Evidence Storage
- The scheduled workflow `.github/workflows/bluesky_audit_custom_feeds.yml` runs the audit automatically in GitHub Actions.
- Each run writes a JSON summary to `.agent-tmp/custom_feed_audit_latest.json` inside the runner.
- The workflow uploads that JSON as a GitHub Actions artifact for later review.
- The workflow also writes a concise human-readable summary into the GitHub Actions job summary.
- If the script is run locally, results only persist when `--out-json` is provided.

## Temporary Lifecycle And Housekeeping
This discovery tooling is not intended to be permanent. At the scheduled review:

- review the GitHub Actions artifacts and job summaries
- decide whether to keep, rollback, or replace the discovery path
- prune stale feed URIs from `resources/jokebot_custom_feeds.json`
- remove `bluesky_check_custom_feeds.py`, `.github/workflows/bluesky_audit_custom_feeds.yml`, and related documentation if the discovery track is no longer needed
- remove optional hashtag-rotation logic if it was only supporting this evaluation

## Future Phase (Optional)
If existing feeds do not provide sufficient visibility, evaluate a dedicated
feed-generator service as a separate scoped project.
