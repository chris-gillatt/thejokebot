import os
import time
from pathlib import Path

import atproto_client.exceptions
import httpx
import requests
from atproto import Client
from atproto_client.request import Request as _AtprotoRequest
from dotenv import load_dotenv

DEFAULT_LOGIN_RETRY_ATTEMPTS = 3
DEFAULT_LOGIN_RETRY_DELAY_SECONDS = 2.0
DEFAULT_NETWORK_RETRY_ATTEMPTS = 3
DEFAULT_NETWORK_RETRY_DELAY_SECONDS = 1.0
DEFAULT_NETWORK_RETRY_BACKOFF_FACTOR = 2.0
DEFAULT_SESSION_FILE_PATH = ".agent-tmp/bluesky_session.txt"


def _load_local_env_file():
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)


_load_local_env_file()

# ---------------------------------------------------------------------------
# TLS fingerprint workaround
# ---------------------------------------------------------------------------
# Bluesky's AWS WAF blocks Python httpx by its JA3/JA4 TLS fingerprint.
# requests/urllib3 generates a different fingerprint that is not blocked.
# We bridge the two by providing a custom httpx transport that delegates all
# network I/O to a requests.Session.
# ---------------------------------------------------------------------------
_STRIP_RESP_HEADERS = frozenset(
    ("content-length", "content-encoding", "transfer-encoding")
)


class _RequestsTransport(httpx.BaseTransport):
    """httpx transport that delegates to requests/urllib3.

    Passes a different TLS client-hello fingerprint (JA3/JA4) than the
    default httpx transport, bypassing the AWS WAF Bot Control rule that
    blocks httpx on bsky.social.
    """

    def __init__(self) -> None:
        self._session = requests.Session()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        resp = self._session.request(
            method=request.method,
            url=str(request.url),
            headers=dict(request.headers),
            data=request.content,
            allow_redirects=True,
            timeout=30.0,
        )
        # requests already decompresses the body; strip encoding/length headers
        # so httpx does not attempt to process them a second time.
        headers = [
            (k, v)
            for k, v in resp.headers.items()
            if k.lower() not in _STRIP_RESP_HEADERS
        ]
        return httpx.Response(
            status_code=resp.status_code,
            headers=headers,
            content=resp.content,
            request=request,
        )

    def close(self) -> None:
        self._session.close()


def get_bluesky_password():
    app_password = os.getenv("BLUESKY_APP_PASSWORD")
    if app_password:
        return app_password, "BLUESKY_APP_PASSWORD"

    password = os.getenv("BLUESKY_PASSWORD")
    if password:
        return password, "BLUESKY_PASSWORD"

    raise ValueError(
        "Neither BLUESKY_APP_PASSWORD nor BLUESKY_PASSWORD environment variable is set. "
        "Please configure BLUESKY_APP_PASSWORD (preferred) or BLUESKY_PASSWORD in "
        "GitHub Actions secrets or local .env."
    )


def get_bluesky_credentials(include_source=False):
    username = os.getenv("BLUESKY_USERNAME", "").strip()

    if not username:
        raise ValueError(
            "BLUESKY_USERNAME environment variable is not set. "
            "Please configure it in GitHub Actions variables or local .env."
        )

    password, password_source = get_bluesky_password()

    if include_source:
        return username, password, password_source

    return username, password


def _get_session_file_path():
    raw_path = os.getenv("BLUESKY_SESSION_FILE_PATH", DEFAULT_SESSION_FILE_PATH).strip()
    if not raw_path:
        raw_path = DEFAULT_SESSION_FILE_PATH
    return Path(raw_path)


def _load_session_string_from_file(path):
    try:
        session_string = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not session_string:
        return None
    return session_string


def _persist_session_string_to_file(client, path):
    try:
        session_string = client.export_session_string().strip()
    except Exception as exc:
        print(
            f"Warning: failed to export Bluesky session string for persistence: {type(exc).__name__}: {exc}."
        )
        return False

    if not session_string:
        print(
            "Warning: Bluesky session export returned an empty value; skipping persistence."
        )
        return False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{session_string}\n", encoding="utf-8")
    except OSError as exc:
        print(
            f"Warning: failed to write Bluesky session file at {path}: {type(exc).__name__}: {exc}."
        )
        return False

    return True


def _register_session_persistence_callback(client, path):
    def _on_session_change(*_args, **_kwargs):
        _persist_session_string_to_file(client, path)

    try:
        client.on_session_change(_on_session_change)
    except Exception as exc:
        print(
            f"Warning: failed to register Bluesky session change callback: {type(exc).__name__}: {exc}."
        )
        return False

    return True


def login_client():
    username, password = get_bluesky_credentials()
    raw_attempts = os.getenv(
        "BLUESKY_LOGIN_RETRY_ATTEMPTS", str(DEFAULT_LOGIN_RETRY_ATTEMPTS)
    )
    try:
        max_attempts = int(raw_attempts.strip())
    except ValueError:
        max_attempts = DEFAULT_LOGIN_RETRY_ATTEMPTS
    max_attempts = max(1, max_attempts)
    retry_delay_seconds = get_float_env(
        "BLUESKY_LOGIN_RETRY_DELAY_SECONDS",
        default=DEFAULT_LOGIN_RETRY_DELAY_SECONDS,
        minimum=0.0,
    )
    session_restore_enabled = get_bool_env(
        "BLUESKY_SESSION_RESTORE_ENABLED", default=False
    )
    session_persist_enabled = get_bool_env(
        "BLUESKY_SESSION_PERSIST_ENABLED", default=False
    )
    session_file_path = _get_session_file_path()

    client = Client(request=_AtprotoRequest(transport=_RequestsTransport()))

    if session_restore_enabled:
        session_string = _load_session_string_from_file(session_file_path)
        if session_string:
            print(f"Attempting Bluesky session restore from {session_file_path}.")
            try:
                client.login(session_string=session_string)
                print("Bluesky session restore succeeded.")
                if session_persist_enabled:
                    _persist_session_string_to_file(client, session_file_path)
                    _register_session_persistence_callback(client, session_file_path)
                return client, username
            except Exception as exc:
                print(
                    "Warning: Bluesky session restore failed; falling back to credential login "
                    f"({type(exc).__name__}: {exc})."
                )

    print("Using configured credentials for Bluesky authentication.")
    for attempt in range(1, max_attempts + 1):
        try:
            client.login(username, password)
            if session_persist_enabled:
                _persist_session_string_to_file(client, session_file_path)
                _register_session_persistence_callback(client, session_file_path)
            return client, username
        except atproto_client.exceptions.NetworkError as exc:
            if attempt >= max_attempts:
                raise
            print(
                f"Warning: transient Bluesky login failure ({attempt}/{max_attempts}): {exc}. "
                f"Retrying in {retry_delay_seconds:.1f}s."
            )
            if retry_delay_seconds > 0:
                time.sleep(retry_delay_seconds)


def retry_network_call(
    operation,
    description,
    max_attempts=None,
    initial_delay_seconds=None,
    backoff_factor=None,
):
    """Run a network operation with bounded retries for transient failures."""
    if max_attempts is None:
        max_attempts = get_int_env(
            "BLUESKY_NETWORK_RETRY_ATTEMPTS",
            default=DEFAULT_NETWORK_RETRY_ATTEMPTS,
            minimum=1,
        )
    if initial_delay_seconds is None:
        initial_delay_seconds = get_float_env(
            "BLUESKY_NETWORK_RETRY_DELAY_SECONDS",
            default=DEFAULT_NETWORK_RETRY_DELAY_SECONDS,
            minimum=0.0,
        )
    if backoff_factor is None:
        backoff_factor = get_float_env(
            "BLUESKY_NETWORK_RETRY_BACKOFF_FACTOR",
            default=DEFAULT_NETWORK_RETRY_BACKOFF_FACTOR,
            minimum=1.0,
        )

    delay_seconds = initial_delay_seconds

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except (
            requests.RequestException,
            TimeoutError,
            atproto_client.exceptions.NetworkError,
        ) as exc:
            if attempt >= max_attempts:
                raise
            print(
                f"Warning: transient failure while {description} ({attempt}/{max_attempts}): {exc}. "
                f"Retrying in {delay_seconds:.1f}s."
            )
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            delay_seconds *= backoff_factor


def get_bool_env(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default

    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def get_int_env(name, default, minimum=1):
    raw = os.getenv(name)
    if raw is None:
        return default

    try:
        value = int(raw.strip())
    except ValueError:
        return default

    if value < minimum:
        return minimum
    return value


def get_float_env(name, default=0.0, minimum=0.0):
    raw = os.getenv(name)
    if raw is None:
        return default

    try:
        value = float(raw.strip())
    except ValueError:
        return default

    if value < minimum:
        return minimum
    return value


def get_runtime_controls():
    return {
        "dry_run": get_bool_env("BLUESKY_DRY_RUN", default=False),
        "action_delay_seconds": get_float_env(
            "BLUESKY_ACTION_DELAY_SECONDS", default=0.0, minimum=0.0
        ),
    }


def mask_sensitive(value, prefix=4, suffix=4):
    """Return a stable masked representation for potentially sensitive values."""
    text = str(value or "").strip()
    if not text:
        return "<redacted>"
    if len(text) <= prefix + suffix:
        return "<redacted>"
    return f"{text[:prefix]}...{text[-suffix:]}"
