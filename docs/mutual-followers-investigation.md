# Mutual-follower context and related Bluesky API options

Investigation for [#156](https://github.com/chris-gillatt/thejokebot/issues/156),
17 November 2026. Recommendation: begin with a separately approved read-only
measurement pilot; keep existing follow-back, discovery and protection rules.

## What the notification means

The screenshot's “13 mutual followers” comes from the notification author's
`viewer.knownFollowers.count`. The current client explicitly describes this as
the number of people the viewer follows who also follow that author. For TJB
viewing account A, it means accounts X where **TJB follows X and X follows A**.
It does not establish X follows TJB, A follows X, friendship, endorsement or
the source of A's decision to follow TJB.

This is different from a reciprocal relationship between TJB and A: that needs
both `following` and `followedBy`. The shared third-party accounts are contextual
social proof, not causal acquisition attribution like an explicitly attributed
starter-pack follow notification.

The [notification UI](https://github.com/bluesky-social/social-app/blob/8a7a54a4178035534cff5b8f718150623328ce77/src/screens/Notifications/components/NotificationItem/Item/profile.tsx)
uses this field for the displayed count and shows up to three avatars. The
[shared profile component](https://github.com/bluesky-social/social-app/blob/8a7a54a4178035534cff5b8f718150623328ce77/src/components/KnownFollowers.tsx)
warns that the count includes blocked accounts while the returned profiles do
not. Do not use the count to infer hidden identities or equate it to the number
of visible, actionable profiles.

## API and SDK support

| Capability | Verified contract | Implication for TJB |
|---|---|---|
| `author.viewer.knownFollowers` / profile viewer state | Optional and populated only in selected cases. Contains `count` and a preview of at most five profiles. | Reuse it when present; missing is unknown, not zero. Never count the preview array as the full overlap. |
| `app.bsky.graph.getKnownFollowers` | Returns followers of the subject whom the authenticated viewer follows; `limit` 1–100, default 50, cursor pagination. | Use the bot's authenticated client for targeted inspection. No viewer parameter can make an anonymous request act as TJB. |
| `app.bsky.graph.getRelationships` | Public relationship lookup between one actor and at most 30 others; includes directional follow and block fields. | Useful for a bounded relationship check, not a replacement for complete graph reads or existing protections. |
| `app.bsky.graph.getSuggestedFollowsByActor` | Returns accounts similar to an actor, intended as suggestions after following someone. | A possible candidate source for manual review; it does not classify humour or establish suitability. |

Sources: [viewer/known-follower schema](https://github.com/bluesky-social/bsky/blob/5a591310e18f053f6015ee5b94a188bf9f0464b8/lexicons/app/bsky/actor/defs.json),
[known-followers schema](https://github.com/bluesky-social/bsky/blob/5a591310e18f053f6015ee5b94a188bf9f0464b8/lexicons/app/bsky/graph/getKnownFollowers.json),
[relationship query](https://github.com/bluesky-social/bsky/blob/5a591310e18f053f6015ee5b94a188bf9f0464b8/lexicons/app/bsky/graph/getRelationships.json),
[relationship fields](https://github.com/bluesky-social/bsky/blob/5a591310e18f053f6015ee5b94a188bf9f0464b8/lexicons/app/bsky/graph/defs.json),
and [suggested-follows documentation](https://docs.bsky.app/docs/api/app-bsky-graph-get-suggested-follows-by-actor).

An unauthenticated read-only probe of `getKnownFollowers` on the public AppView
returned HTTP 401 `AuthMissing`. Authenticated requests should use the account's
PDS/service proxy through its SDK, following the
[official routing guidance](https://bsky.network/docs/api-directory).
The installed Python SDK already exposes `known_followers`, its `count` and
`followers`, and the known-followers query's actor/limit/cursor parameters.
No SDK upgrade is needed just to explore these fields.

Counts are observations at read time, affected by viewer identity, graph changes,
visibility and hydration. Fetching an old notification today does not reconstruct
the count at the original follow time. Deduplicate returned DIDs within an
inspection; report incomplete pages and unavailable reads. Missing fields,
blocked views and request failures cannot establish zero overlap.

## What could be useful

| Option | Value | Recommendation |
|---|---|---|
| Aggregate context for newly observed followers | Shows how connected incoming followers are to accounts TJB already follows. | Best initial pilot. Describe it as known-follower overlap observed at collection time. |
| Context in a human review preview | Helps the maintainer inspect a suggested follow or creator. | Optional supporting detail; keep humour/content review and existing block checks. |
| Ranking discovery candidates | Could put some socially connected candidates earlier in a bounded review queue. | Experiment only after measurement and explicit policy approval; do not infer safety or trust. |
| Automatic follow eligibility threshold | Would exclude some less-connected/new users. | Not recommended: current follow-back already covers every actionable follower, and the signal is easy to game and favours established networks. |
| Permanent unfollow protection | Could retain connected accounts regardless of interaction. | Not justified by this signal; preserve existing grace and creator protections. |

The current behaviour is implemented in
[`follow_back.py`](../src/thejokebot/commands/follow_back.py),
[`follow_interactors.py`](../src/thejokebot/commands/follow_interactors.py) and
[`content_creators.py`](../src/thejokebot/content_creators.py).
Follow-back completely reads current followers/following and reconciles their
difference. Creator protections derive from actual likes/reposts. Adding an
overlap threshold would change product policy rather than repair a missing check.

### Suggested read-only pilot

Propose a manual, disabled-by-default inspection of at most 20 new follow
notifications, with one page of at most 100 notifications and no extra graph
requests initially. Reuse hydrated counts; report unavailable counts explicitly.
This is a bounded recent sample, not a claim to cover every new follower.

Record aggregate buckets (for example 0, 1–4, 5–19, 20+, and unknown), sampled
event count, observation time, coverage and count-field availability. Bucket
boundaries are a proposal, not accepted thresholds. Do not publish follower
handles, DIDs, avatars or per-person graph counts. Hashing a DID does not make
its linked social graph anonymous. All tracked state files in this public
repository must be treated as public when choosing what to retain.

Keep any exploratory identities in memory. A repeatable cohort/time-series
feature needs an explicit checkpoint/deduplication and privacy design before
persistence; summing repeated snapshots would double-count people. Counts summed
across subjects also do not represent unique shared accounts. Explain that TJB's
follow-back policy changes its own following graph and therefore the metric.

Before a public dashboard feature, agree the observation window, labels, retention,
small-cohort handling and completeness denominator. Compare measured availability
and useful variation first; do not claim causal audience growth from overlap.
Any later relationship drill-down needs its own page/request budget and privacy
review. No pilot, schedule or public metric has been implemented by this investigation.

## Other current API capabilities worth considering

- **Notification reason filters:** `listNotifications.reasons` supports bounded
  source-specific reads. TJB already uses these in follow interactions, reports
  and starter-pack attribution, so there is no missing optimisation to add here.
  Keep checkpoints aligned to the filtered stream. The canonical schema marks
  `priority` ignored and the request `seenAt` unsupported/erroring; current bot
  call sites do not pass them. See the
  [notification schema](https://github.com/bluesky-social/bsky/blob/5a591310e18f053f6015ee5b94a188bf9f0464b8/lexicons/app/bsky/notification/listNotifications.json).
- **Scoped mutes:** viewer state distinguishes full mutes, repost-only mutes and
  quote-post-only mutes. Future review/discovery features should preserve those
  meanings instead of treating `muted == false` as absence of every scoped mute.
  These describe the viewer's mute preferences. No new mute policy is proposed here.
- **Starter-pack attribution:** the notification's `starterPack` is explicitly
  attached to follows originating from a pack. Existing
  [`starter_pack_attribution.py`](../src/thejokebot/commands/starter_pack_attribution.py)
  uses that stronger attribution signal. Known-follower overlap cannot replace
  it, detect inclusion dates or solve global reverse pack-membership discovery.
- **Relationship and suggestion endpoints:** the bounded APIs above could support
  fresher checks or manual candidate previews. Preserve full-read, block-list,
  grace, idempotency and action-cap rules; unknown or partial relationships must
  never authorise an unfollow or bypass protection.

These are verified current schema/client capabilities. Their individual first
release dates and deployment across every PDS/AppView were not established.

## Outcome and next decision

The investigation is complete. No account actions, bot behaviour, dashboard
assets, state schema or dependencies were changed. The next optional decision
belongs to `chris-gillatt`: approve or decline the bounded aggregate-only pilot
when choosing the next audience-analytics task. Any pilot or follow-policy
implementation should be scoped separately from this research issue.
