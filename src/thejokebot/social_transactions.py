"""Checkpoint explicit social operations without writing stale domain snapshots."""

from collections.abc import Callable

from thejokebot import state as bot_state


class CheckpointError(RuntimeError):
    """A persistence failure that must not be treated as a recoverable API error."""


def apply(
    state: dict,
    operation: Callable[[dict], object],
    *,
    domains: str | tuple[str, ...] = "social",
) -> None:
    """Commit against fresh state before updating the caller's working snapshot."""
    try:
        bot_state.update_state(operation, domains=domains)
    except ValueError as exc:
        raise CheckpointError(f"Could not checkpoint social state: {exc}") from exc
    operation(state)
