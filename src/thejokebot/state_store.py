"""Generic domain-based state persistence helpers."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Callable, Generator, TypeVar

T = TypeVar("T")
StateReadFailures = dict[str, tuple[str, Exception]]


class StateReadError(RuntimeError):
    """Raised when an update cannot safely read a selected state domain."""

    def __init__(self, failures: StateReadFailures) -> None:
        self.domains = tuple(sorted(failures))
        details = "; ".join(
            f"{domain} ({path}): {error}"
            for domain, (path, error) in sorted(failures.items())
        )
        super().__init__(f"Could not read selected state domain(s): {details}")


def _state_files(state_file: str, state_filenames: dict[str, str]) -> dict[str, str]:
    state_directory = Path(state_file).resolve().parent / "state"
    return {
        domain: str(state_directory / filename)
        for domain, filename in state_filenames.items()
    }


def _lock_files(
    state_file: str,
    state_filenames: dict[str, str],
    lock_dir_name: str,
) -> dict[str, str]:
    lock_directory = Path(state_file).resolve().parent / lock_dir_name
    return {
        domain: str(lock_directory / f"{filename}.lock")
        for domain, filename in state_filenames.items()
    }


def _normalise_domains(
    domains: str | tuple[str, ...],
    state_filenames: dict[str, str],
) -> tuple[str, ...]:
    selected = domains if isinstance(domains, tuple) else (domains,)
    unknown = set(selected) - set(state_filenames)
    if unknown:
        raise ValueError(f"Unknown state domain(s): {', '.join(sorted(unknown))}")
    return selected


@contextmanager
def _state_locks(
    domains: tuple[str, ...],
    exclusive: bool,
    lock_files: dict[str, str],
    fcntl_module: Any,
) -> Generator[None, None, None]:
    if fcntl_module is None:
        yield
        return

    lock_mode = fcntl_module.LOCK_EX if exclusive else fcntl_module.LOCK_SH
    with ExitStack() as stack:
        for domain in sorted(domains):
            lock_path = lock_files[domain]
            Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
            lock_file = stack.enter_context(open(lock_path, "w", encoding="utf-8"))
            fcntl_module.flock(lock_file.fileno(), lock_mode)
            stack.callback(fcntl_module.flock, lock_file.fileno(), fcntl_module.LOCK_UN)
        yield


def _load_state_unlocked(
    *,
    state_file: str,
    state_files: dict[str, str],
    normalise_state: Callable[[dict], dict],
    merge_domain_payload: Callable[[dict, str, dict], None],
) -> tuple[dict, StateReadFailures]:
    legacy_state: dict = {}
    legacy_failure: tuple[str, Exception] | None = None
    if os.path.exists(state_file):
        try:
            with open(state_file, encoding="utf-8") as state_handle:
                legacy_state = json.load(state_handle)
        except (json.JSONDecodeError, OSError) as exc:
            legacy_failure = (state_file, exc)

    state = normalise_state(legacy_state)
    failures: StateReadFailures = {}
    for domain, domain_file_path in state_files.items():
        if not os.path.exists(domain_file_path):
            if legacy_failure is not None:
                failures[domain] = legacy_failure
            continue

        try:
            with open(domain_file_path, encoding="utf-8") as state_handle:
                payload = json.load(state_handle)
        except (json.JSONDecodeError, OSError) as exc:
            failures[domain] = (domain_file_path, exc)
            continue

        merge_domain_payload(state, domain, payload)

    return normalise_state(state), failures


def _warn_state_read_failures(failures: StateReadFailures) -> None:
    for domain, (path, error) in sorted(failures.items()):
        print(f"Warning: could not read {domain} state from {path}: {error}")


def _save_domain_unlocked(
    *,
    state: dict,
    domain: str,
    state_files: dict[str, str],
    normalise_state: Callable[[dict], dict],
    domain_payload: Callable[[dict, str], dict],
) -> None:
    state_file_path = state_files[domain]
    Path(state_file_path).parent.mkdir(parents=True, exist_ok=True)
    temporary_path = state_file_path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as state_handle:
        json.dump(
            domain_payload(normalise_state(state), domain), state_handle, indent=2
        )
        state_handle.write("\n")
    os.replace(temporary_path, state_file_path)


def load_state(
    *,
    state_file: str,
    state_filenames: dict[str, str],
    lock_dir_name: str,
    fcntl_module: Any,
    default_state: Callable[[], dict],
    normalise_state: Callable[[dict], dict],
    merge_domain_payload: Callable[[dict, str, dict], None],
) -> dict:
    domains = tuple(state_filenames)
    try:
        with _state_locks(
            domains,
            exclusive=False,
            lock_files=_lock_files(state_file, state_filenames, lock_dir_name),
            fcntl_module=fcntl_module,
        ):
            state, failures = _load_state_unlocked(
                state_file=state_file,
                state_files=_state_files(state_file, state_filenames),
                normalise_state=normalise_state,
                merge_domain_payload=merge_domain_payload,
            )
    except OSError as exc:
        print(f"Warning: could not read bot state; starting with empty state: {exc}")
        return default_state()

    _warn_state_read_failures(failures)
    return state


def save_state(
    state: dict,
    *,
    domains: str | tuple[str, ...],
    state_file: str,
    state_filenames: dict[str, str],
    lock_dir_name: str,
    fcntl_module: Any,
    normalise_state: Callable[[dict], dict],
    domain_payload: Callable[[dict, str], dict],
) -> None:
    selected = _normalise_domains(domains, state_filenames)
    with _state_locks(
        selected,
        exclusive=True,
        lock_files=_lock_files(state_file, state_filenames, lock_dir_name),
        fcntl_module=fcntl_module,
    ):
        state_files = _state_files(state_file, state_filenames)
        for domain in selected:
            _save_domain_unlocked(
                state=state,
                domain=domain,
                state_files=state_files,
                normalise_state=normalise_state,
                domain_payload=domain_payload,
            )


def update_state(
    mutator: Callable[[dict], T],
    *,
    domains: str | tuple[str, ...],
    state_file: str,
    state_filenames: dict[str, str],
    lock_dir_name: str,
    fcntl_module: Any,
    normalise_state: Callable[[dict], dict],
    merge_domain_payload: Callable[[dict, str, dict], None],
    domain_payload: Callable[[dict, str], dict],
) -> T:
    selected = _normalise_domains(domains, state_filenames)
    with _state_locks(
        selected,
        exclusive=True,
        lock_files=_lock_files(state_file, state_filenames, lock_dir_name),
        fcntl_module=fcntl_module,
    ):
        state_files = _state_files(state_file, state_filenames)
        state, failures = _load_state_unlocked(
            state_file=state_file,
            state_files=state_files,
            normalise_state=normalise_state,
            merge_domain_payload=merge_domain_payload,
        )
        selected_failures = {
            domain: failures[domain] for domain in selected if domain in failures
        }
        if selected_failures:
            raise StateReadError(selected_failures)
        _warn_state_read_failures(failures)

        result = mutator(state)
        for domain in selected:
            _save_domain_unlocked(
                state=state,
                domain=domain,
                state_files=state_files,
                normalise_state=normalise_state,
                domain_payload=domain_payload,
            )
        return result
