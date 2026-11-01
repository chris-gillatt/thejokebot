"""Baseline or preview starter-pack acknowledgements; publish only an approved preview."""

import argparse
import html
import json
import os

from thejokebot import starter_pack_acknowledgements as acknowledgements
from thejokebot.paths import AGENT_TMP_DIR, DASHBOARD_DIR
from thejokebot.runtime import login_client
from thejokebot.starter_pack_membership import candidate_uris

OUTPUT_PATH = AGENT_TMP_DIR / "starter_pack_acknowledgements.json"
PREVIEW_PATH = AGENT_TMP_DIR / "starter_pack_acknowledgements.html"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _preview_html(report: dict) -> str:
    cards = []
    for proposal in report["proposals"]:
        record = proposal["record"]
        quote = record["embed"]["record"]["uri"]
        url = f"https://bsky.app/profile/{quote.split('/')[2]}/post/{quote.rsplit('/', 1)[-1]}"
        link = record["facets"][1]["features"][0]["uri"]
        cards.append(
            "<article><h2>Proposed thank-you (not published)</h2>"
            f'<p class="draft">{html.escape(record["text"])}</p>'
            f'<p><a href="{html.escape(link, quote=True)}">Open creator starter pack</a></p>'
            f'<p><a href="{html.escape(url, quote=True)}">Open quoted original joke</a></p>'
            f'<iframe title="Original quoted joke" src="https://embed.bsky.app/embed/{html.escape(quote.removeprefix("at://"), quote=True)}"'
            ' loading="lazy" referrerpolicy="no-referrer"></iframe></article>'
        )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Starter-pack acknowledgement preview</title>"
        "<style>body{font:16px system-ui;max-width:650px;margin:24px auto;padding:0 16px}"
        "article{border:1px solid #aaa;border-radius:12px;padding:16px;margin:16px 0}"
        ".draft{white-space:pre-wrap;overflow-wrap:anywhere}iframe{width:100%;height:500px;"
        "border:0}a{overflow-wrap:anywhere}</style>"
        "<h1>Starter-pack acknowledgement preview</h1>"
        "<p>No thank-you has been published. This is a draft with the live original "
        "joke embedded for review, not a screenshot of a published Bluesky quote. "
        "Likes on a future thank-you and its quoted original remain separate.</p>"
        + ("".join(cards) or "<p>No eligible newly observed membership.</p>")
        + "</html>"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("baseline", "preview", "publish"), default="preview"
    )
    parser.add_argument("--pack-uri", action="append", default=[])
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
    client, _ = login_client()
    if args.mode == "baseline":
        report = acknowledgements.baseline_memberships(client, explicit)
    elif args.mode == "publish":
        if not explicit:
            parser.error("Publishing requires an explicitly approved --pack-uri")
        saved = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        proposals = saved["proposals"]
        if len(proposals) != 1 or proposals[0]["pack_uri"] not in explicit:
            parser.error("The saved preview must contain one approved pack")
        report = acknowledgements.publish_acknowledgement(client, proposals[0])
    else:
        metrics = json.loads(
            (DASHBOARD_DIR / "data" / "metrics.json").read_text(encoding="utf-8")
        )
        report = acknowledgements.preview_acknowledgements(client, metrics, explicit)
        _write(PREVIEW_PATH, _preview_html(report))
    if args.mode != "publish":
        _write(OUTPUT_PATH, json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
