---
name: sonar-quality
description: 'Run, diagnose, configure, or remediate SonarQube Cloud and SonarScanner analysis for The Joke Bot. Use when working on Sonar findings, quality-gate failures, coverage import, scanner scope, security hotspots, vulnerabilities, or the python_tests Sonar integration.'
argument-hint: 'Run or diagnose Sonar analysis'
---

# Sonar Quality

Use this workflow for SonarQube Cloud analysis and remediation in The Joke Bot.

## Invariants

- Treat `sonar-project.properties` as the scanner configuration source of truth.
- Analyse first-party code only. Never remove the `references/**` exclusion or analyse reference submodules.
- Keep Sonar automatic analysis disabled; CI analysis is authoritative.
- Never print, commit, or pass `SONAR_TOKEN` as a command-line property.
- Keep dashboard code in static analysis. Exclude it only from coverage until JavaScript coverage exists.
- Preserve the Python coverage floor and Sonar quality-gate thresholds unless the user explicitly changes policy.
- Do not replace deterministic, non-security pseudorandom behaviour merely to silence a security rule.

## Local Analysis

1. Confirm `sonar-scanner` is installed. On macOS, use `brew install sonar-scanner` if needed.
2. Ensure the ignored `.env` contains `SONAR_TOKEN` without revealing its value.
3. Generate a fresh Cobertura report from the repository root:

   ```shell
   PYTHONPATH=. .venv/bin/python -m pytest tests/ -q \
     --cov=. \
     --cov-report=xml:coverage.xml \
     --cov-fail-under=75
   ```

4. Verify `/coverage/sources/source` in `coverage.xml` is non-empty. An empty source causes Sonar to report Python coverage as 0% even when pytest reports coverage.
5. Load the environment and run the scanner:

   ```shell
   set -a
   source .env
   set +a
   SONAR_HOST_URL=https://sonarcloud.io sonar-scanner \
     -Dsonar.qualitygate.wait=true \
     -Dsonar.qualitygate.timeout=300
   unset SONAR_TOKEN
   ```

6. Require scanner exit 0 before declaring the gate successful. Exit 3 commonly means upload succeeded but the quality gate failed.

## Diagnose A Failed Gate

- Read the scanner output first and distinguish upload failure from gate failure.
- Inspect the failed quality-gate condition in SonarQube Cloud rather than guessing from the overall status.
- If coverage is 0%, check in this order:
  1. `coverage.xml` exists and is fresh.
  2. Its `<source>` is non-empty and resolves in the current checkout.
  3. `sonar.python.coverage.reportPaths` points to that file.
  4. File-level Sonar measures show imported coverage.
- Query Sonar APIs only with the token supplied through the environment or Basic authentication. Filter output through `jq` and never display authentication data.
- After each scan, confirm both the gate status and unresolved issue count; one does not imply the other.

## Remediate Findings

1. Group findings by rule and owning file.
2. Fix application behaviour at the controlling code path.
3. For workflow findings, keep third-party actions SHA-pinned, install Python dependencies from `requirements.lock` with hashes and wheels, and use immutable identity fields at privileged trust boundaries.
4. Validate browser-provided URLs before assigning them to resource attributes; retain only allowlisted HTTPS origins.
5. Use cryptographically secure selection for genuinely unpredictable choices.
6. For intentional deterministic pseudorandom ordering, preserve reproducibility. Use a narrow `NOSONAR` comment only when the operation is not security-sensitive, place it on the exact flagged expression, and include a concise justification.
7. Run the focused test immediately after each behaviour change.
8. Before finishing, run `./scripts/preflight-local.sh`, then regenerate coverage and rerun Sonar.

## CI Contract

`.github/workflows/python_tests.yml` owns CI analysis. It must:

- install `requirements.lock` with hash checking and binary wheels;
- generate `coverage.xml` with `--cov=.`;
- enforce the 75% pytest coverage floor;
- invoke the SHA-pinned SonarQube scan action;
- wait for the quality gate;
- avoid exposing repository secrets to fork pull requests.

Repository Actions and Dependabot secret stores both need `SONAR_TOKEN` when Dependabot pull requests should run analysis.
