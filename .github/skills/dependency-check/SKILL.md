---
name: dependency-check
description: Check and upgrade TheJokeBot first-party Python, npm and GitHub Actions dependencies before implementation or during dependency maintenance.
---

# Dependency check and upgrade

The objective is to update dependencies wherever compatibility and validation
allow, not merely report available versions. Agreement to a dependency check
authorises these upgrades as a separate, validated change; do not ask again
whether to apply routine compatible updates.

- Compare Python manifests, lockfile and local validation tools, npm dependencies,
  dashboard CDN dependencies and first-party Action pins with authoritative stable
  releases. Distinguish CodeQL Action releases from CLI bundle releases.
- Review upstream compatibility and migration notes. Resolve Python updates together
  with pip-compile and retain hashes; never force transitive pins independently.
  Keep Actions pinned to the verified release commit.
- Apply compatible updates, install the resolved dependencies and run the repository's
  required validation, including Sonar. Deliver dependency updates separately from
  the feature that prompted the check, with the required changelog entry.
- Investigate failures before retaining older versions. Record each necessary
  exception in problem-statement.md with current/latest versions, a concrete reason,
  an explicit owner and a review date or named work trigger. Agree deferrals with
  the user; availability alone is not evidence that an upgrade is compatible.
- Exempt documentation-only tasks from dependency audits. Preserve the opening
  dependency-check decision required by the session's repository instructions.
