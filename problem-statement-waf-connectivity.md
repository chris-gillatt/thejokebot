# The Joke Bot – WAF Connectivity Sub-Problem Statement

**Status:** Active investigation (all workflows disabled as of 2026-05-19)
**Related main-PS items:** Risk #4, backlog item 5.27

---

## 1. Problem Summary

The Joke Bot cannot make authenticated API calls to `bsky.social` from GitHub Actions
runners. Requests are rejected by an AWS WAF (Web Application Firewall) deployed in
front of Bluesky's load balancer, returning an HTML `403 Forbidden` with
`server: awselb/2.0` before the request reaches the Bluesky application layer.

This is a **WAF Bot Control block**, not a Bluesky rate-limit (which would return
`429 Too Many Requests` with a JSON body).

---

## 2. Timeline

| Date (UTC) | Event |
|---|---|
| 2026-05-17T03:42 | Block starts. No code changes in this repo. First suspected cause: runner IP. |
| 2026-05-17 (morning) | Confirmed block is **not** IP-based: curl from CI NordVPN IP → 200 |
| 2026-05-17 (morning) | Confirmed block is **not** User-Agent based: all httpx UA variants → 403 |
| 2026-05-17 (morning) | Confirmed block **is** TLS-fingerprint based: httpx (any config) → 403, requests/urllib3 → 200 |
| 2026-05-17 | Fix shipped: `_RequestsTransport` in `bluesky_common.py`. CI run 25986602247 → `"Joke successfully posted!"` ✅ |
| 2026-05-17 | NordVPN workaround removed (now redundant). |
| 2026-05-18 02:36-05:28 (GMT+8) | Overnight failure wave: multiple scheduled jobs fail with `403 awselb/2.0` at login (`createSession`). |
| 2026-05-18 06:29-07:35 (GMT+8) | Scheduled jobs recover and pass again without a code change. |
| 2026-05-18 07:54 (GMT+8) | Workflows disabled manually in `36d1c83` (`chore(actions): disable all workflows`) to prevent further damage while investigating. |

---

## 3. What We Know

### 3.1 Confirmed facts

- **httpx JA3/JA4 fingerprint is blocked.** AWS WAF Bot Control added Python httpx's
  TLS client-hello to its known-bot signature list on 2026-05-17T03:42 UTC.
- **urllib3 fingerprint was not blocked initially.** Our `_RequestsTransport` fix
  (routes httpx I/O through `requests.Session`) worked for at least one CI run.
- **The block is at the WAF layer.** HTML body + `awselb/2.0` server header = AWS ELB
  WAF blocking before Bluesky application code is reached.
- **curl is never blocked.** libcurl's TLS fingerprint is not on the block-list.
- **Failure windows are intermittent.** We observed an overnight failure wave on
  2026-05-18 (GMT+8), followed by successful scheduled runs before workflows were
  disabled. This suggests dynamic rule/reputation scoring, not a permanent hard block.

### 3.2 Current best hypotheses for the overnight failure wave

One or more of the following:

1. **Dynamic WAF bot scoring / reputation windows.** A temporary block window followed
  by spontaneous recovery is consistent with managed-rule score thresholds and
  periodically refreshed reputation signals.
2. **urllib3 fingerprint now also intermittently penalised.** AWS WAF Bot Control rule
  sets are updated regularly. urllib3 may be newly detected in some windows or at
  certain score thresholds.
3. **Behavioural/volume pattern triggering bot scoring.** AWS WAF Bot Control uses
   heuristics beyond TLS fingerprint — request volume, frequency, lack of browser-like
   behaviour (cookies, JS challenges, etc.). Our request pattern is highly repetitive
   and login-heavy.
4. **Shared runner IP pool reputation.** GitHub Actions runners share Azure IP ranges
   with many other users. If those IPs have a low reputation score at the WAF, all
   bots running on them may be blocked regardless of content.

### 3.3 Request frequency analysis (before disable)

| Workflow | Schedule | createSession calls/day |
|---|---|---|
| `bluesky_process_reports` | Every 30 minutes | **48** |
| `bluesky_follows_and_likes` | Every 2 hours | 12 |
| `bluesky_post_joke` | Every 4 hours | 6 |
| `provider_health_check` | Daily | 1 |
| `bluesky_follow_fellows` | Wed + Fri | ~0.3 |
| **Total** | | **~67/day** |

Bluesky's documented limit for `createSession` is 300/day (per account). We are within
that limit, but **each of these is a fresh `login()` call that creates a new session**.
The Bluesky bot guide explicitly warns against this pattern and recommends persisting
and resuming sessions.

Importantly, in the captured failures the request is blocked at login with
`403 awselb/2.0` immediately, so session-creation frequency is likely a contributing
signal rather than the sole trigger.

### 3.4 Bot policy compliance review

From https://docs.bsky.app/docs/starter-templates/bots:

> "Automated bots that post to an account on a regular interval are welcome."  ✅

> "If your bot interacts with other users, please only interact (like, repost, reply,
> etc.) if the user has tagged the bot account. It must be an opt-in interaction, or
> else your bot may be taken for spam."

> "As a best practice, bot accounts should identify themselves by adding a self-label
> to their profile." — ✅ **Confirmed enabled by account owner.** This appears to be
> best-practice metadata and is unlikely to be the root cause of a pre-auth WAF block.

Current assessment of `like_replies()`/`follow_interactors()`:
- `like_replies()` is scoped to replies directed at the bot and appears compliant.
- Interactions are sourced from the bot's own engagement feed; this is treated as
  directed engagement for current policy interpretation.
- The account owner reports this behaviour is not running as a broad "like spree".
- Since failures occur before action logic executes (at login), this interaction logic
  is unlikely to be the immediate trigger for the observed 403 events.

---

## 4. What Has Been Tried

| Approach | Outcome |
|---|---|
| NordVPN UK exit node in CI | 403 — same block. Rules out runner IP as sole cause. |
| NordVPN SG exit node in CI | 403 — same block. |
| httpx with custom User-Agent | 403 — UA makes no difference. |
| httpx with HTTP/1.1 forced (no h2 ALPN) | 403 — HTTP version makes no difference. |
| `_RequestsTransport` (urllib3 stack) | ✅ Restored access after first block; later saw an overnight failure wave on 2026-05-18 (GMT+8), then spontaneous recovery before workflows were disabled. |
| Disabling all workflows | ✅ Stopped making things worse while we investigate. |

---

## 5. Investigation and Fix Plan

Work items are ordered by impact-vs-effort and least-to-most disruptive.

### Step 1 — Merge dependabot PR #44 (requests `>=2.34.2`) 🔲

**Why first:** requests 2.34.x ships with an updated urllib3. This may change the TLS
fingerprint our `_RequestsTransport` presents, potentially bypassing any new urllib3
block-list entry at zero implementation cost.

**Action:** Merge PR #44 via `gh pr merge 44 --squash --repo chris-gillatt/thejokebot`.

**Verification:** Run the smoke-test locally:
```python
import requests
r = requests.post("https://bsky.social/xrpc/com.atproto.server.createSession", json={"identifier": "...", "password": "..."})
print(r.status_code, r.headers.get("server"))
```
Expected: `200 None/Cloudfront` (not `403 awselb/2.0`).

---

### Step 2 — Lightweight CI connectivity probe ✅ (implemented, pending execution)

**Why:** Before re-enabling the full bot, confirm the transport layer is actually
passing before committing to further implementation work.

**Implemented:** Added a temporary `bluesky_connectivity_probe.yml` workflow (manual
dispatch only, no schedule) that:
1. Installs deps
2. Runs `python -c "import requests; r = requests.post('https://bsky.social/xrpc/com.atproto.server.createSession', json={...}); print(r.status_code, r.headers.get('server'))"` (with secrets)
3. Runs the atproto login via `login_client()` and prints the result

**Remaining action:** Dispatch this workflow in CI and capture status/header output.
Remove it after recovery stabilises.

---

### Step 3 — Implement session persistence (resumeSession pattern) 🟡 (partially complete)

**Why:** The Bluesky bot guide explicitly recommends persisting and resuming sessions
rather than calling `login()` on every run. We currently call `login_client()` (which
calls `createSession`) on every workflow invocation — up to 67 times/day. Each fresh
login is a fresh TLS handshake + `createSession` API call that looks bot-like. A
persistent session would reduce this to 1-2 logins/day (only when tokens expire).

**How atproto supports this:**
```python
# Export session after login:
session_string = client.export_session_string()

# Restore in next run:
client = Client()
client.login(session_string=session_string)
```
The SDK also provides `client.on_session_change(callback)`, which can be used to
persist refreshed tokens whenever the client rotates them.

The session string should be stored outside git-tracked files. On restore failure
(expired/invalid refresh token), fall back to full `login(login=..., password=...)`.

**Risk:** `bot_state.json` is committed to the repo. **The session string contains
JWT tokens and must NOT be committed.** It must be stored as a GitHub Actions secret
or written to a file that is gitignored, then uploaded/downloaded as a workflow
artifact or Actions cache. Evaluate options carefully before implementing.

**Alternative storage options:**
- GitHub Actions secret: secure but awkward to update each refresh (requires API/CLI write).
- GitHub Actions artifact: simple for per-run handoff but less convenient for long-lived state.
- GitHub Actions cache: practical for persisted state between scheduled runs.
- Private external store: possible but out of scope for this repo.
- **Recommended approach:** cache-backed session file plus `on_session_change` write-back,
  with automatic fallback to full login on cache miss/invalid session.

**Implemented so far:**
- `login_client()` now supports optional restore-first auth with fallback to
  credential login.
- Session export/persist hooks are implemented, including
  `client.on_session_change(...)` write-back.
- Session handling is feature-flagged to preserve safe rollout defaults:
  `BLUESKY_SESSION_RESTORE_ENABLED`, `BLUESKY_SESSION_PERSIST_ENABLED`, and
  `BLUESKY_SESSION_FILE_PATH`.
- Disabled Bluesky workflows now include cache restore/save wiring for
  `.agent-tmp/bluesky_session.txt` to support cross-run reuse.

**Remaining action:** validate this end-to-end through manual probe + staged re-enable
before promoting from implementation-ready to operationally proven.

---

### Step 4 — Reduce `bluesky_process_reports` frequency ✅ (implemented)

**Why:** Running every 30 minutes (48×/day) is the single largest contributor to our
API call volume and login frequency. Reports are user-generated content and do not
require a sub-hour response time. Even hourly is fast for a small bot.

**Action:** Change `*/30 * * * *` to `0 */4 * * *` (every 4 hours, matching
`bluesky_post_joke`). This reduces report-workflow logins from 48 to 6 per day.

**Implemented:** cadence updated in central runtime config and the disabled reports
workflow so re-enable inherits the lower-frequency schedule.

**Impact:** Total daily logins drop from ~67 to ~25, a 63% reduction in login volume.

---

### Step 5 — Switch to `curl_cffi` transport 🔲

**Why:** `curl_cffi` can impersonate a specific browser's TLS client-hello exactly
(Chrome 120, Firefox 120, etc.). Unlike urllib3 (which simply happens to present a
different fingerprint), `curl_cffi` actively mimics a real browser and is the
industry standard for bypassing WAF bot detection. It is harder for WAF to block
without also blocking legitimate browser traffic.

**API:**
```python
import curl_cffi.requests as cffi_requests

session = cffi_requests.Session(impersonate="chrome120")
resp = session.post("https://bsky.social/xrpc/com.atproto.server.createSession", json={...})
```

**Integration:** Replace `_RequestsTransport` in `bluesky_common.py` with a
`_CurlCffiTransport` that delegates to `curl_cffi.requests.Session(impersonate="chrome120")`.
The interface is compatible with `requests.Session`, so the change is minimal.

**Dependency:** Add `curl-cffi>=0.7,<1` to `requirements.txt`.

**Note:** `curl_cffi` uses a compiled Rust/C extension and is more complex to install
than pure-Python `requests`. Verify it installs cleanly on ubuntu-24.04 before
committing.

---

### Step 6 — Route read-only calls to `public.api.bsky.app` 🔲

**Why:** Bluesky's docs state:
> "The `public.api.bsky.app` endpoint is cached, and we request developers use that
> for 'public web' use cases."

Read-only operations (fetching notifications, followers, profile lookups) do not need
authenticated sessions and can go to the public endpoint. This reduces authenticated
traffic to `bsky.social` further. Unauthenticated calls to `public.api.bsky.app`
do not go through the same WAF Bot Control rules.

**Scope:** Audit each script for API calls that don't require write access and
redirect those to `public.api.bsky.app`.

---

### Step 7 — Audit and confirm bot self-labeling 🔲

**Why:** Keep a verifiable record of policy alignment and avoid rechecking assumptions.

**Current state:** Account owner reports the `bot` self-label is already enabled.

**Action:** Keep a one-off verification command in the runbook:
```python
profile = client.get_profile(actor=username)
print(profile.labels)
```
If absent, add it using `client.upsert_profile()` with
`com.atproto.label.defs#selfLabels`.

---

### Step 8 — Review `follow_interactors()` policy compliance 🔲

**Why:** Keep this as a secondary policy-risk check, not a primary WAF hypothesis.

**Current assessment:** This is unlikely to explain current failures because the
403 occurs during login before any follow/like action code runs.

**Action:** Optionally add a mode switch
`BLUESKY_FOLLOW_INTERACTORS_MODE=replies_only|all|off` to tighten behaviour if
future policy guidance requires it.

---

### Step 9 — Re-enable workflows incrementally 🔲

**Readiness update:** prerequisites for first re-enable gate are now in place:
- Manual connectivity probe workflow exists and is ready to dispatch.
- Session restore/persist code path is implemented behind feature flags.
- Session cache restore/save wiring is in disabled Bluesky workflows.
- `bluesky_process_reports` cadence has been reduced to every 4 hours.

**Order:**
1. `bluesky_post_joke` only (core function, lowest frequency)
2. Confirm it posts successfully for 24 hours
3. Re-enable `bluesky_follows_and_likes`
4. Re-enable `bluesky_process_reports` (at reduced frequency from Step 4)
5. Re-enable `bluesky_follow_fellows`, `provider_health_check`, and non-Bluesky
   CI workflows (`python_tests`, `ruff_quality`, `codeql`, `validate_runtime_config`)

---

## 6. Completion Criteria

The issue is resolved when:
- [ ] `bluesky_post_joke` runs successfully on schedule (automated, no manual dispatch)
  for 7 consecutive days without a 403
- [ ] All other Bluesky workflows are re-enabled and passing
- [ ] Session persistence or `curl_cffi` transport is in place (not relying on urllib3
  "happening not to be blocked")
- [ ] `process_reports` is running at a reduced cadence
- [ ] Bot self-label is confirmed

---

## 7. Constraints and Non-Goals

- **No external runners.** All automation runs on GitHub Actions hosted runners.
- **No hardcoded credentials.** Session tokens are never committed to the repo.
- **Preserve all existing bot behaviours** unless a specific behaviour is identified
  as causing the WAF block.
- Do not migrate away from the atproto Python SDK unless all other options are
  exhausted.

---

## 8. Dependency Update Checklist

| Package | Current | Available | Notes |
|---|---|---|---|
| `requests` | `>=2.33.1,<3` | `>=2.34.2` | Dependabot PR #44 open — merge first |
| `atproto` | `0.0.65` | `0.0.65` | Latest. Watch for 0.0.66+ releases |
| `curl-cffi` | not installed | `0.7.x` | New dep if Step 5 is implemented |

---

## 9. Reference Links

- [Bluesky bot guide](https://docs.bsky.app/docs/starter-templates/bots)
- [Bluesky rate limits](https://docs.bsky.app/docs/advanced-guides/rate-limits)
- [atproto Python SDK on PyPI](https://pypi.org/project/atproto/)
- [atproto SDK source](https://github.com/MarshalX/atproto)
- [curl_cffi on PyPI](https://pypi.org/project/curl-cffi/)
- [AWS WAF Bot Control managed rule group](https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-bot.html)
