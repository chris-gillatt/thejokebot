"""Validate BLUESKY_UNFOLLOW_IGNORE handles and report stale entries."""

from __future__ import annotations

import os

import atproto_client.exceptions
import requests

from bluesky_common import (
    get_bool_env,
    login_client,
    mask_sensitive,
    retry_network_call,
)

DEFAULT_IGNORABLE_HANDLES = ("theonion.bsky.social",)
_STALE_ERROR_MARKERS = (
    "profile not found",
    "not found",
    "invalid identifier",
    "could not resolve",
)


def parse_ignore_handles(
    raw_value: str, default_handles=DEFAULT_IGNORABLE_HANDLES
) -> list[str]:
    """Return a deterministic unique ignore-handle list."""
    parsed = [h.strip().lower() for h in (raw_value or "").split(",") if h.strip()]
    combined = list(default_handles) + parsed
    return sorted(set(combined))


def extract_profile_did(profile) -> str | None:
    did = getattr(profile, "did", None)
    if not did and isinstance(profile, dict):
        did = profile.get("did")
    return did


def is_stale_resolution_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _STALE_ERROR_MARKERS)


def resolve_handles(
    client, handles: list[str]
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Resolve handles to DIDs, returning (valid, stale, transient)."""
    valid: dict[str, str] = {}
    stale: dict[str, str] = {}
    transient: dict[str, str] = {}

    for handle in handles:
        try:
            profile = retry_network_call(
                lambda h=handle: client.get_profile(h),
                description=f"resolving ignore handle {handle}",
            )
            did = extract_profile_did(profile)
            if did:
                valid[handle] = did
            else:
                stale[handle] = "resolved profile contained no DID"
        except atproto_client.exceptions.BadRequestError as exc:
            if is_stale_resolution_error(exc):
                stale[handle] = str(exc)
            else:
                transient[handle] = str(exc)
        except (
            requests.RequestException,
            TimeoutError,
            atproto_client.exceptions.NetworkError,
        ) as exc:
            transient[handle] = str(exc)

    return valid, stale, transient


def main() -> int:
    raw_handles = os.getenv("BLUESKY_UNFOLLOW_IGNORE", "")
    fail_on_stale = get_bool_env("BLUESKY_FAIL_ON_STALE_IGNORE", default=True)

    handles = parse_ignore_handles(raw_handles)
    print(f"Validating {len(handles)} ignore handle(s)...")

    client, username = login_client()
    print("Logged in successfully.")

    valid, stale, transient = resolve_handles(client, handles)

    for handle, did in valid.items():
        print(f"OK: {mask_sensitive(handle)} -> {mask_sensitive(did)}")
    for handle, reason in stale.items():
        print(f"STALE: {mask_sensitive(handle)} ({reason})")
    for handle, reason in transient.items():
        print(f"WARN (transient): {mask_sensitive(handle)} ({reason})")

    print(
        f"Summary: valid={len(valid)}, stale={len(stale)}, transient={len(transient)}"
    )

    if stale and fail_on_stale:
        print(
            "Failing due to stale ignore handles. Prune BLUESKY_UNFOLLOW_IGNORE entries."
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
