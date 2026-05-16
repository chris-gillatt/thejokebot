import copy
import json
from pathlib import Path

_CONFIG_PATH = (
    Path(__file__).resolve().parent / "resources" / "jokebot_runtime_config.json"
)

_DEFAULT_CONFIG = {
    "schema_version": 1,
    "posting": {
        "days_limit": 365,
        "max_attempts": 5,
        "max_post_chars": 300,
        "hashtags": ["#jokes", "#dadjoke", "#funny"],
    },
    "follow_fellows": {
        "per_tag_limit": 12,
        "global_follow_limit": 150,
        "search_limit": 100,
        "hashtags": [
            "followback",
            "dadjoke",
            "dadjokes",
            "joke",
            "jokes",
            "humour",
            "humor",
            "humoursky",
            "humorsky",
            "jokesky",
            "momjokes",
            "mumjokes",
            "groan",
            "puns",
            "pun",
            "punny",
            "divertido",
            "funny",
        ],
    },
    "unfollow": {
        "max_actions": 200,
        "batch_size": 50,
        "batch_pause_seconds": 60.0,
        "default_ignorable_handles": [
            "theonion.bsky.social",
            "groandeck.bsky.social",
            "nocontextbritss.bsky.social",
            "dehler55.bsky.social",
        ],
    },
    "reports": {
        "max_pages": 3,
        "page_limit": 100,
    },
    "workflow_schedules": {
        "bluesky_post_joke": "0 0,4,8,12,16,20 * * *",
        "bluesky_follows_and_likes": "0 */2 * * *",
        "bluesky_follow_fellows": "0 0 * * 3,5",
        "bluesky_unfollow": "0 12 1 */3 *",
        "bluesky_process_reports": "*/30 * * * *",
        "bluesky_validate_unfollow_ignore": "0 9 1 * *",
    },
}

_cached_runtime_config = None


def _deep_merge(base, override):
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _ensure_int(value, minimum, field_name):
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer.")
    if value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}.")
    return value


def _ensure_number(value, minimum, field_name):
    if not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number.")
    if value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}.")
    return float(value)


def _ensure_string_list(value, field_name):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty list.")

    result = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field_name}[{index}] must be a string.")
        text = item.strip()
        if not text:
            raise ValueError(f"{field_name}[{index}] must not be empty.")
        result.append(text)
    return result


def _validate_config(payload):
    if not isinstance(payload, dict):
        raise ValueError("Runtime config must be a JSON object.")

    cfg = copy.deepcopy(payload)
    cfg["schema_version"] = _ensure_int(
        cfg.get("schema_version", 1), minimum=1, field_name="schema_version"
    )

    posting = cfg.get("posting", {})
    posting["days_limit"] = _ensure_int(
        posting.get("days_limit", 365), minimum=1, field_name="posting.days_limit"
    )
    posting["max_attempts"] = _ensure_int(
        posting.get("max_attempts", 5), minimum=1, field_name="posting.max_attempts"
    )
    posting["max_post_chars"] = _ensure_int(
        posting.get("max_post_chars", 300),
        minimum=100,
        field_name="posting.max_post_chars",
    )
    posting_hashtags = _ensure_string_list(
        posting.get("hashtags", []), "posting.hashtags"
    )
    for index, hashtag in enumerate(posting_hashtags):
        if not hashtag.startswith("#"):
            raise ValueError(f"posting.hashtags[{index}] must start with '#'.")
    posting["hashtags"] = posting_hashtags
    cfg["posting"] = posting

    follow_fellows = cfg.get("follow_fellows", {})
    follow_fellows["per_tag_limit"] = _ensure_int(
        follow_fellows.get("per_tag_limit", 12),
        minimum=1,
        field_name="follow_fellows.per_tag_limit",
    )
    follow_fellows["global_follow_limit"] = _ensure_int(
        follow_fellows.get("global_follow_limit", 150),
        minimum=1,
        field_name="follow_fellows.global_follow_limit",
    )
    follow_fellows["search_limit"] = _ensure_int(
        follow_fellows.get("search_limit", 100),
        minimum=1,
        field_name="follow_fellows.search_limit",
    )
    if follow_fellows["search_limit"] > 100:
        raise ValueError("follow_fellows.search_limit must be <= 100.")

    follow_hashtags = _ensure_string_list(
        follow_fellows.get("hashtags", []), "follow_fellows.hashtags"
    )
    normalised_follow_hashtags = []
    for tag in follow_hashtags:
        normalised_follow_hashtags.append(tag.lstrip("#"))
    follow_fellows["hashtags"] = normalised_follow_hashtags
    cfg["follow_fellows"] = follow_fellows

    unfollow = cfg.get("unfollow", {})
    unfollow["max_actions"] = _ensure_int(
        unfollow.get("max_actions", 200), minimum=0, field_name="unfollow.max_actions"
    )
    unfollow["batch_size"] = _ensure_int(
        unfollow.get("batch_size", 50), minimum=1, field_name="unfollow.batch_size"
    )
    unfollow["batch_pause_seconds"] = _ensure_number(
        unfollow.get("batch_pause_seconds", 60.0),
        minimum=0.0,
        field_name="unfollow.batch_pause_seconds",
    )
    unfollow["default_ignorable_handles"] = _ensure_string_list(
        unfollow.get("default_ignorable_handles", []),
        "unfollow.default_ignorable_handles",
    )
    cfg["unfollow"] = unfollow

    reports = cfg.get("reports", {})
    reports["max_pages"] = _ensure_int(
        reports.get("max_pages", 3), minimum=1, field_name="reports.max_pages"
    )
    reports["page_limit"] = _ensure_int(
        reports.get("page_limit", 100), minimum=1, field_name="reports.page_limit"
    )
    if reports["page_limit"] > 100:
        raise ValueError("reports.page_limit must be <= 100.")
    cfg["reports"] = reports

    workflow_schedules = cfg.get("workflow_schedules", {})
    if not isinstance(workflow_schedules, dict):
        raise ValueError("workflow_schedules must be an object.")
    cfg["workflow_schedules"] = {
        str(key).strip(): str(value).strip()
        for key, value in workflow_schedules.items()
        if str(key).strip() and str(value).strip()
    }

    return cfg


def _load_from_file(config_path):
    if not config_path.exists():
        return copy.deepcopy(_DEFAULT_CONFIG)

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(
            f"Warning: failed to read runtime config at {config_path}: {exc}. "
            "Using built-in defaults."
        )
        return copy.deepcopy(_DEFAULT_CONFIG)

    merged = _deep_merge(_DEFAULT_CONFIG, payload)
    try:
        return _validate_config(merged)
    except ValueError as exc:
        print(
            f"Warning: invalid runtime config at {config_path}: {exc}. "
            "Using built-in defaults."
        )
        return copy.deepcopy(_DEFAULT_CONFIG)


def load_runtime_config(config_path=None, strict=False):
    path = config_path or _CONFIG_PATH
    path = Path(path)

    if not path.exists():
        if strict:
            raise FileNotFoundError(f"Runtime config file not found: {path}")
        return copy.deepcopy(_DEFAULT_CONFIG)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if strict:
            raise ValueError(f"Failed to read runtime config at {path}: {exc}") from exc
        print(
            f"Warning: failed to read runtime config at {path}: {exc}. "
            "Using built-in defaults."
        )
        return copy.deepcopy(_DEFAULT_CONFIG)

    merged = _deep_merge(_DEFAULT_CONFIG, payload)
    try:
        return _validate_config(merged)
    except ValueError as exc:
        if strict:
            raise ValueError(f"Invalid runtime config at {path}: {exc}") from exc
        print(
            f"Warning: invalid runtime config at {path}: {exc}. "
            "Using built-in defaults."
        )
        return copy.deepcopy(_DEFAULT_CONFIG)


def clear_runtime_config_cache():
    global _cached_runtime_config
    _cached_runtime_config = None


def get_runtime_config():
    global _cached_runtime_config
    if _cached_runtime_config is None:
        _cached_runtime_config = load_runtime_config(strict=False)
    return copy.deepcopy(_cached_runtime_config)


def get_posting_config():
    return get_runtime_config()["posting"]


def get_follow_fellows_config():
    return get_runtime_config()["follow_fellows"]


def get_unfollow_config():
    return get_runtime_config()["unfollow"]


def get_reports_config():
    return get_runtime_config()["reports"]


def get_workflow_schedule_config():
    return get_runtime_config()["workflow_schedules"]
