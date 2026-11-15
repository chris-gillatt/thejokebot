"""Credential-free observations of HTTP attempts made by first-party clients."""

import atexit
import json
import os
import re
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import requests
from requests.adapters import HTTPAdapter

PREFIX = "API_USAGE "
RATE_HEADERS = (
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "ratelimit-policy",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-used",
    "x-ratelimit-reset",
    "x-ratelimit-resource",
    "retry-after",
)
_recorder = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _emit(event: dict) -> None:
    print(
        PREFIX + json.dumps(event, separators=(",", ":"), allow_nan=False), flush=True
    )


def _endpoint(url: str, native: bool) -> tuple[str, str, str] | None:
    parsed = urlsplit(url)
    if native or parsed.hostname in {"api.bsky.app", "public.api.bsky.app"}:
        endpoint = parsed.path.removeprefix("/xrpc/")
        if not re.fullmatch(
            r"[a-zA-Z][a-zA-Z0-9]*(?:\.[a-zA-Z][a-zA-Z0-9]*){2,}", endpoint
        ):
            endpoint = "other"
        group = (
            "appview"
            if parsed.hostname in {"api.bsky.app", "public.api.bsky.app"}
            else "pds"
            if parsed.hostname == "bsky.social"
            or (parsed.hostname and parsed.hostname.endswith(".bsky.network"))
            else "other_pds"
        )
        return "bluesky", endpoint, group
    if parsed.hostname == "api.github.com":
        return "github", "actions" if "/actions/" in parsed.path else "other", "rest"
    return None


def _write_points(endpoint: str, content: bytes) -> int | None:
    fixed = {
        "com.atproto.repo.createRecord": 3,
        "com.atproto.repo.putRecord": 3,
        "com.atproto.repo.deleteRecord": 1,
    }
    if endpoint in fixed:
        return fixed[endpoint]
    if endpoint != "com.atproto.repo.applyWrites":
        return 0
    payload = json.loads(content)
    writes = payload.get("writes") if isinstance(payload, dict) else None
    if not isinstance(writes, list):
        return None
    weights = {"create": 3, "update": 2, "delete": 1}
    kinds = [item.get("$type") if isinstance(item, dict) else None for item in writes]
    actions = [kind.split("#")[-1] if isinstance(kind, str) else "" for kind in kinds]
    return (
        sum(weights[action] for action in actions)
        if all(action in weights for action in actions)
        else None
    )


class Recorder:
    def __init__(self, emit=_emit):
        self.emit = emit
        self.source = uuid.uuid4().hex
        self.context = {
            "version": 1,
            "source": self.source,
            "run": os.getenv("GITHUB_RUN_ID"),
            "attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1"),
            "job": os.getenv("GITHUB_JOB"),
            "command": Path(sys.argv[0]).name,
        }
        self.started = _now()
        self.requests = 0
        self.events = []
        self.lock = threading.RLock()
        self.event("start")

    def event(self, kind: str, **fields) -> None:
        event = {**self.context, "kind": kind, "at": _now(), **fields}
        self.events.append(event)
        self.emit(event)

    def begin(self, method: str, url: str, *, native=False, content=b"") -> str | None:
        endpoint = _endpoint(url, native)
        if endpoint is None:
            return None
        service, name, group = endpoint
        points = 0
        if native and method == "POST":
            try:
                points = _write_points(name, content)
            except json.JSONDecodeError, UnicodeDecodeError:
                points = None
            if points is None:
                print(
                    f"Warning: write-point estimate unavailable for {name}.",
                    file=sys.stderr,
                )
        with self.lock:
            identity = uuid.uuid4().hex
            self.requests += 1
            self.event(
                "request",
                request=identity,
                service=service,
                endpoint=name,
                group=group,
                method=method,
                write_points_upper_bound=points,
            )
            return identity

    def finish(
        self, identity: str | None, status: int | None, headers, *, error=None
    ) -> None:
        if identity is None:
            return
        observed = {
            name: str(headers[name])[:200] for name in RATE_HEADERS if name in headers
        }
        with self.lock:
            self.event(
                "response",
                request=identity,
                status=status,
                headers=observed,
                error=error,
            )

    def summary(self) -> None:
        with self.lock:
            self.event("summary", requests=self.requests, started_at=self.started)

    def native_request(self, request: httpx.Request) -> None:
        content = b""
        if request.url.path == "/xrpc/com.atproto.repo.applyWrites":
            try:
                content = request.content
            except httpx.RequestNotRead:
                print(
                    "Warning: streamed write-point estimate unavailable.",
                    file=sys.stderr,
                )
        request.extensions["thejokebot_usage"] = self.begin(
            request.method,
            str(request.url),
            native=True,
            content=content,
        )

    def native_response(self, response: httpx.Response) -> None:
        self.finish(
            response.request.extensions.get("thejokebot_usage"),
            response.status_code,
            response.headers,
        )


def get_recorder() -> Recorder | None:
    global _recorder
    enabled = os.getenv("THEJOKEBOT_API_USAGE_ENABLED", "true").casefold()
    if enabled not in {"true", "false"}:
        raise ValueError("THEJOKEBOT_API_USAGE_ENABLED must be true or false")
    if enabled == "false":
        return None
    if _recorder is None:
        _recorder = Recorder()
    return _recorder


def native_hooks() -> dict:
    recorder = get_recorder()
    return (
        {"request": [recorder.native_request], "response": [recorder.native_response]}
        if recorder
        else {}
    )


def _finish() -> None:
    if (
        _recorder is not None
        and os.getenv("THEJOKEBOT_API_USAGE_ENABLED", "true").casefold() == "true"
    ):
        _recorder.summary()


atexit.register(_finish)


class UsageAdapter(HTTPAdapter):
    def send(
        self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None
    ):
        if request.method is None or request.url is None:
            raise ValueError("Prepared usage request is missing its method or URL")
        recorder = get_recorder()
        identity = recorder.begin(request.method, request.url) if recorder else None
        try:
            response = super().send(
                request,
                stream=stream,
                timeout=timeout,
                verify=verify,
                cert=cert,
                proxies=proxies,
            )
        except requests.RequestException as exc:
            if recorder:
                recorder.finish(identity, None, {}, error=type(exc).__name__)
            raise
        if recorder:
            recorder.finish(identity, response.status_code, response.headers)
        return response


def session() -> requests.Session:
    client = requests.Session()
    client.mount("https://", UsageAdapter())
    client.mount("http://", UsageAdapter())
    return client
