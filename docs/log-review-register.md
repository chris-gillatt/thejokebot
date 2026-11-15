# Runner-log review register

This is the decision record for recurring log observations. Read it before
presenting findings or proposing fixes. Decisions below were recorded on
15 November 2026 from the maintainer's discussion and the completed reviews;
they are not a fresh audit of upstream releases.

Accepted observations remain visible in the original logs. This register does
not disable checks, suppress messages, establish that unknown activity was zero,
or accept unrelated warnings from the same tool.

## How to use the register

Match the workflow, source, message and surrounding behaviour, not just a keyword.
Each entry records its disposition, reason, evidence, owner and review trigger.

- **Expected behaviour:** omit unchanged occurrences from the main findings and
  improvement backlog. Mention them only when they explain another finding.
- **Waiting for upstream:** keep a concise watch item with the upstream link and
  review trigger. Do not repeatedly propose the unavailable fix or suppress the
  warning. Check any announced deadline before claiming future compatibility.
- **Accepted access limitation:** record the restricted capability and its impact;
  do not repeatedly ask to change access or treat unavailable tooling as a fault
  in the bot. Revisit when access or the required capability changes.
- **Unresolved observation:** preserve uncertainty. Neither a keyword nor a
  successful workflow establishes its cause, harmlessness or security impact.
- **Fixed:** retain the repair reference. A matching observation from a commit
  before the repair is historical; recurrence on code containing the repair needs
  investigation.

Lead reviews with new actionable findings, changed impact, regressions and due
watch items. Summarise unchanged watch items/limitations once in a small section
or link here. Do not reframe expected behaviour as an optimisation opportunity.
Always report material coverage gaps, including capped or unavailable evidence.

Every requested use of the runner-log-review skill must read and update this
register. Maintain a latest-review summary with its timestamp, scope, coverage
and limitations; refresh entry evidence/last-observed dates and record new
observations, changed impact, triggered watch items and verified repairs. Keep
stable LR identifiers and avoid duplicate entries or repeated unchanged prose.
Distinguish not observed in the sample from not assessed or resolved. Invoking
the skill authorises this documentation maintenance and its docs-only delivery.

Do not infer maintainer acceptance for a new observation. Record it as unresolved
or actionable as supported, with an owner and concrete review trigger. Preserve
existing decisions unless the maintainer explicitly changes them; record new
explicit decisions with their date and rationale. Register maintenance does not
authorise fixes, account changes or automatic issue creation. Any security or
operational change outside an entry's scope needs its own assessment.

## LR-001 — Duplicate joke candidates

**Status:** Expected behaviour; explicitly accepted by the maintainer on
15 November 2026. **Owner:** `chris-gillatt`, as bot maintainer.

Providers can return previously used jokes. Rejecting duplicates, trying further
candidates and falling through to another provider is how the bot is designed
to operate. Duplicate counts, provider candidate exhaustion and successful
fall-through are not concerns by themselves. Do not suggest provider rotation,
extra caching or reduced retries merely because duplicates occurred.

Evidence: [posting run 43675281234, attempt 1](https://github.com/chris-gillatt/thejokebot/actions/runs/43675281234)
at `12563cb93e77fe30fd63949e80733ef7148ebcea` rejected ten duplicate candidates
and published from another provider. A later sampled posting run also recovered
through normal fall-through.

**Revisit only if:** publication fails after all permitted fallbacks, a duplicate
is actually published, configured attempt/request limits are breached, or a
separate network/provider error appears. Assess that new behaviour, not the
duplicate count alone.

## LR-002 — Pages Action punycode deprecation

**Status:** Waiting for upstream; accepted as a watch item on 15 November 2026.
**Owner:** the implementing agent performing the next dependency check.

`actions/deploy-pages` emits Node `DEP0040` for its bundled use of `punycode`.
The last verified stable version was v5.0.1, pinned at
`368f82528645a54fb793d4d04e342629a3f51346`. The sampled deployment succeeded;
no deployment defect or vulnerability was established from this warning.

Evidence: [deployment job 132727352638](https://github.com/chris-gillatt/thejokebot/actions/runs/43686211254/job/132727352638)
in run 43686211254/1 at `7b22e6c4d4a5988b930fded05c58fb6b9deef0b1`.
Track [actions/deploy-pages#434](https://github.com/actions/deploy-pages/issues/434).
Keep the warning; do not substitute an unreleased Action or disable warnings.

**Review trigger:** the dependency check due 29 November 2026, or an announced
stable upstream fix or applicable removal deadline, whichever comes first.
If impact changes or a deployment starts failing, investigate immediately.

## LR-003 — GitHub Copilot review internet access

**Status:** Accepted access limitation, acknowledged by the maintainer on
15 November 2026. **Owner:** `chris-gillatt`.

This concerns GitHub.com Copilot code review in a hosted runner, not local
Copilot or Codex. Its firewall reported blocked access to `api.github.com`.
The available supported configuration API did not expose the firewall allowlist;
no setting was changed. The review completed and posted four findings, which
does not prove unrestricted access or exhaustive review coverage.

Evidence: [review run 43420637746/1](https://github.com/chris-gillatt/thejokebot/actions/runs/43420637746)
at `3a170b3ae4cd950ede58e9374dd3914e4963c6f5`, and its review on
[PR #147](https://github.com/chris-gillatt/thejokebot/pull/147).
The [investigation in the operating brief](../problem-statement.md#log-review-follow-ups--15-november-2026)
records the verified context and GitHub configuration guidance.

**Revisit when:** the maintainer changes access policy, a supported configuration
API becomes available, or a review requires live API context and cannot obtain
it. Do not repeatedly propose disabling the firewall or call this a bot fault.

## LR-004 — Copilot exclusion-policy lookup returning 404

**Status:** Unresolved observation; no confirmed adverse impact.
**Owner:** `chris-gillatt`.

The same Copilot run as LR-003 reported an exclusion-policy lookup failure and
continued without exclusions. Neither the configured exclusion policy nor the
reason for the 404 was established. It is not an accepted exclusion bypass and
does not establish that files were exposed. Keep this distinct from the firewall
warning; do not claim that changing the allowlist fixes it.

**Review trigger:** an expected exclusion policy becomes known, policy settings
become accessible, excluded content appears in a review, or the message/impact
changes. Until then, retain the uncertainty without inventing a configuration fix.

## LR-005 — Historical activity and telemetry gaps

**Status:** Known evidence limitation, not assumed zero activity.
**Owner:** the agent performing the next requested log review.

Older failed social runs 43535674399/1 and 42673807093/1 lacked recognised
activity summaries. The first showed an upstream login timeout followed by a
handle-resolution failure; the second lacked sufficient job/log detail.
Older test logs can also contain synthetic shutdown summaries from before the
LR-008 repair. Missing observations remain unknown; do not retrospectively mark
these runs successful or fabricate activity counts.

**Revisit when:** the same gap appears in a new run expected to emit the relevant
summary, on code containing the applicable repair, or an authorised historical
investigation obtains additional evidence. Coverage limits still belong in the
review even when no new issue is proposed.

## LR-006 — Other managed-tool messages

**Status:** Observed, with no first-party defect established; not blanket acceptance.
**Owner:** the agent performing the next requested log review.

Sampled GitHub-managed Dependabot jobs reported a registries-proxy parse message
and certificate-rehash warning while succeeding. Sonar installation emitted GPG
trust-model wording. CodeQL printed schemas describing deprecated options.
These messages alone do not establish registry/TLS failure, invalid signatures,
vulnerabilities or actual use of a deprecated option.

**Revisit when:** message context changes, registry/dependency retrieval fails,
signature verification fails, a certificate problem is demonstrated, or an
actually used option acquires a removal deadline. Verify the precise source and
impact before promoting a message to an actionable finding.

## LR-007 — Review evidence crowded out by routine telemetry

**Status:** Fixed in `7e01b45ec7603aca9f6318287f1be025e2fd939d` on
15 November 2026. **Owner:** the implementing agent for log-review maintenance.

Successful structured API telemetry previously filled the excerpt allowance.
The collector now excludes routine telemetry, prioritises errors/warnings and
unknown formats, and preserves omission counts. Replaying the affected archive
retained 14 signals with none omitted instead of truncating 366 later matches.

**Revisit when:** routine success records again crowd out meaningful evidence on
the repaired collector. Remaining keyword false positives still require review;
the collector is not a diagnostic classifier.

## LR-008 — Synthetic shutdown telemetry and capped usage inventory

**Status:** Fixed in `1fd1205df0d7e37c2ec1ccfa42202226ebd30795` on
15 November 2026. **Owner:** the implementing agent for usage-report maintenance.

Telemetry opt-out now applies at interpreter exit, preventing orphan synthetic
test summaries. Strict workflow identity validation remains intact. Oversized
usage-inventory searches now split within the existing query budget, deduplicate
boundaries and retain parent totals. The live reporter persisted a complete
1,059-run inventory; API-history coverage remains separately reported.

**Revisit when:** a repaired test run emits foreign telemetry, or inventory is
truncated despite fitting the query budget and timestamp bounds. Legitimate
budget exhaustion must still be reported as incomplete, not silenced.

## Related records

Continue reading the [CodeQL baseline](../problem-statement.md#codeql-baseline)
and [dependency exceptions](../problem-statement.md#dependency-exceptions) for
their existing scoped decisions. This register does not replace their owners,
review triggers or validation requirements.

An unavailable browser automation host is a tooling limitation of that session,
not a persistent dashboard defect. Record an unavailable check in the task's
validation notes; do not carry it forward as a product finding without evidence
of a product fault.
