"""
Update provider health check state in bot_state.json.

This script is called by the provider_health_check.yml workflow after running
health tests. It records check results (success/failure) and tracks consecutive
failures to detect provider outages.
"""

import sys
import time

import bluesky_joke_providers
import bluesky_state

# All providers to monitor: primary, backup, and fallback.
ALL_PROVIDERS = (
    list(bluesky_state.PROVIDER_ROTATION_ORDER)
    + bluesky_joke_providers.BACKUP_PROVIDERS
)


def check_provider_health(provider_name: str) -> dict:
    """
    Check if a provider is responding correctly.

    Returns:
        {"success": bool, "error": str | None, "check_at": int}
    """
    check_at = int(time.time())
    fetch_fn = bluesky_joke_providers.PROVIDERS.get(provider_name)
    if not fetch_fn:
        return {
            "success": False,
            "error": f"Provider '{provider_name}' not found in PROVIDERS",
            "check_at": check_at,
        }

    try:
        joke = fetch_fn()
        if not joke or not isinstance(joke, str):
            return {
                "success": False,
                "error": f"Provider returned invalid response: {type(joke)}",
                "check_at": check_at,
            }
        return {"success": True, "error": None, "check_at": check_at}
    except Exception as e:
        return {
            "success": False,
            "error": f"{type(e).__name__}: {str(e)[:100]}",
            "check_at": check_at,
        }


def main():
    """Run health checks and update bot_state.json."""
    state = bluesky_state.load_state()
    health_checks = state.get("provider", {}).get("health_checks", {})

    print(f"Running health checks for {len(ALL_PROVIDERS)} providers...")

    for provider_name in ALL_PROVIDERS:
        result = check_provider_health(provider_name)
        check_record = health_checks.get(provider_name, {})

        if result["success"]:
            check_record["last_check_success"] = True
            check_record["consecutive_failures"] = 0
            print(f"✓ {provider_name}: OK")
        else:
            check_record["last_check_success"] = False
            check_record["consecutive_failures"] = (
                check_record.get("consecutive_failures", 0) + 1
            )
            print(
                f"✗ {provider_name}: FAILED ({check_record['consecutive_failures']} consecutive) — {result['error']}"
            )

        check_record["last_check_at"] = result["check_at"]
        health_checks[provider_name] = check_record

    state.setdefault("provider", {})["health_checks"] = health_checks
    bluesky_state.save_state(state)
    print("Health check state saved.")

    # Check for critical failures (primary providers failing consistently).
    critical_failures = [
        (p, health_checks[p]["consecutive_failures"])
        for p in bluesky_state.PROVIDER_ROTATION_ORDER
        if health_checks.get(p, {}).get("consecutive_failures", 0) >= 2
    ]

    if critical_failures:
        print("\n⚠️  ALERT: Primary provider(s) failing consistently:")
        for provider, count in critical_failures:
            print(f"  • {provider}: {count} consecutive failures")
        sys.exit(1)  # Fail the job to trigger GitHub notification

    print("\nAll health checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
