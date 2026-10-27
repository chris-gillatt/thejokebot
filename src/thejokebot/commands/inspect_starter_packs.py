"""Inspect candidate starter-pack membership without account actions or state writes."""

import argparse
import json
import os
from pathlib import Path

from thejokebot import state as bot_state
from thejokebot.paths import AGENT_TMP_DIR
from thejokebot.runtime import login_client
from thejokebot.starter_pack_membership import candidate_uris, inspect_membership


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-uri", action="append", default=[])
    parser.add_argument(
        "--output", type=Path, default=AGENT_TMP_DIR / "starter_pack_membership.json"
    )
    args = parser.parse_args()
    explicit = args.pack_uri + (
        [os.environ["BLUESKY_INSPECT_PACK_URI"]]
        if os.getenv("BLUESKY_INSPECT_PACK_URI")
        else []
    )
    try:
        candidate_uris({}, explicit)
    except ValueError as exc:
        parser.error(str(exc))
    state = bot_state.load_state()
    client, _ = login_client()
    report = inspect_membership(client, state, explicit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
