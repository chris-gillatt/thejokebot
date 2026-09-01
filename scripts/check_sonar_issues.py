"""Fail unless a SonarQube Cloud analysis has no unresolved issues."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_HOST_URL = "https://sonarcloud.io"
UNRESOLVED_STATUSES = "OPEN,CONFIRMED,REOPENED"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-key",
        default=os.getenv("SONAR_PROJECT_KEY", "chris-gillatt_thejokebot"),
    )
    parser.add_argument(
        "--host-url", default=os.getenv("SONAR_HOST_URL", DEFAULT_HOST_URL)
    )
    parser.add_argument("--branch", default=os.getenv("SONAR_BRANCH"))
    parser.add_argument("--pull-request", default=os.getenv("SONAR_PULL_REQUEST"))
    args = parser.parse_args(argv)
    if args.branch and args.pull_request:
        parser.error("--branch and --pull-request are mutually exclusive")
    return args


def _unresolved_issue_total(args: argparse.Namespace, token: str) -> int:
    params = {
        "componentKeys": args.project_key,
        "statuses": UNRESOLVED_STATUSES,
        "ps": 1,
    }
    if args.pull_request:
        params["pullRequest"] = args.pull_request
    elif args.branch:
        params["branch"] = args.branch
    url = f"{args.host_url.rstrip('/')}/api/issues/search?{urllib.parse.urlencode(params)}"
    credentials = base64.b64encode(f"{token}:".encode()).decode()
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {credentials}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    total = payload.get("total")
    if not isinstance(total, int):
        raise ValueError("Sonar issue response did not contain an integer total")
    return total


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    token = os.getenv("SONAR_TOKEN")
    if not token:
        print("ERROR: SONAR_TOKEN is required", file=sys.stderr)
        return 2
    try:
        total = _unresolved_issue_total(args, token)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: Could not query unresolved Sonar issues: {exc}", file=sys.stderr)
        return 2
    if total:
        print(f"ERROR: Sonar reports {total} unresolved issue(s)", file=sys.stderr)
        return 1
    print("Sonar unresolved issue check passed: 0 issues")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
