"""Check native SDK transport without public or local state writes."""

import json
import sys
from importlib.metadata import version
from typing import TypedDict

import httpx
from atproto import Client
from atproto_client import exceptions
from atproto_client.request import Request

from thejokebot import runtime

PROFILE_READS = 3


class ProbeResult(TypedDict):
    transport: str
    success: bool
    phase: str
    profile_reads: int
    error: str | None
    http_status: int | None


def probe_transport(request: Request, username: str, password: str) -> ProbeResult:
    result: ProbeResult = {
        "transport": "native",
        "success": False,
        "phase": "login",
        "profile_reads": 0,
        "error": None,
        "http_status": None,
    }
    try:
        client = Client(request=request)
        profile = client.login(username, password)
        if profile is None or not profile.did.startswith("did:"):
            raise ValueError("Login did not return an authenticated profile")
        result["phase"] = "session"
        session = client.com.atproto.server.get_session()
        if session.did != profile.did:
            raise ValueError("Authenticated session identity differs from profile")
        result["phase"] = "profile"
        for _ in range(PROFILE_READS):
            if client.get_profile(profile.did).did != session.did:
                raise ValueError("Profile identity changed during transport probe")
            result["profile_reads"] += 1
        result["success"] = True
        result["phase"] = "complete"
    except (
        exceptions.AtProtocolError,
        httpx.HTTPError,
        ValueError,
    ) as exc:
        result["error"] = type(exc).__name__
        if isinstance(exc, exceptions.RequestErrorBase) and exc.response is not None:
            result["http_status"] = exc.response.status_code
    finally:
        request.close()
    return result


def main() -> int:
    try:
        username, password = runtime.get_bluesky_credentials()
    except ValueError:
        print(
            "ERROR: Missing or invalid Bluesky credential configuration.",
            file=sys.stderr,
        )
        return 2
    result = probe_transport(Request(timeout=30.0), username, password)
    successful = result["success"]
    print(
        json.dumps(
            {
                "schema_version": 1,
                "versions": {
                    name: version(name) for name in ("atproto", "httpx", "requests")
                },
                "results": [result],
                "decision": "native_passed" if successful else "native_failed",
            },
            sort_keys=True,
        )
    )
    if not successful:
        print(
            "ERROR: Native transport check failed; investigate before further account actions.",
            file=sys.stderr,
        )
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
