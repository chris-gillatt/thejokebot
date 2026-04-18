import requests
import random
import os
import time
import base64
from bluesky_common import login_client

# Configuration
JOKE_API_URL = "https://icanhazdadjoke.com"
HEADERS = {
    "Accept": "text/plain",
    "User-Agent": "thejokebot (https://github.com/chris-gillatt/thejokebot)"
}
POSTED_JOKES_FILE = "posted_jokes.txt"
DAYS_LIMIT = 90
MAX_ATTEMPTS = 5
JOKE_TIMEOUT_SECONDS = 15

# Hashtags
HASHTAGS = ["#jokes", "#dadjoke", "#funny"]

def get_fallback_joke():
    """Return a static self-deprecating joke when something goes wrong."""
    fallback_jokes = [
        "Why did this script fail? Because it has too much byte and not enough bark.",
        "If this script were a programmer, it would still be debugging hello world.",
        "Looks like this script is throwing exceptions faster than I throw tantrums."
    ]
    return random.choice(fallback_jokes)

def get_current_epoch():
    return int(time.time())

def load_recent_jokes():
    recent = set()
    cutoff = get_current_epoch() - (DAYS_LIMIT * 86400)
    if not os.path.exists(POSTED_JOKES_FILE):
        return recent
    with open(POSTED_JOKES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                ts_str, b64 = line.strip().split(" ", 1)
                if float(ts_str) > cutoff:
                    recent.add(b64)
            except ValueError:
                continue
    return recent

def save_joke(joke_text):
    encoded = base64.b64encode(joke_text.strip().encode("utf-8")).decode()
    with open(POSTED_JOKES_FILE, "a", encoding="utf-8") as f:
        f.write(f"{get_current_epoch()} {encoded}\n")

def clear_old_jokes():
    cutoff = get_current_epoch() - (DAYS_LIMIT * 86400)
    if not os.path.exists(POSTED_JOKES_FILE):
        return
    with open(POSTED_JOKES_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    filtered = []
    for line in lines:
        if not line.strip():
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            timestamp = float(parts[0])
        except ValueError:
            continue
        if timestamp > cutoff:
            filtered.append(line)
    with open(POSTED_JOKES_FILE, "w", encoding="utf-8") as f:
        f.writelines(filtered)

def pick_joke(recent_jokes):
    joke = None
    for _ in range(MAX_ATTEMPTS):
        try:
            response = requests.get(JOKE_API_URL, headers=HEADERS, timeout=JOKE_TIMEOUT_SECONDS)
            response.raise_for_status()
            candidate = response.content.decode("utf-8").strip()
            encoded = base64.b64encode(candidate.encode("utf-8")).decode()
            if encoded not in recent_jokes:
                joke = candidate
                save_joke(joke)
                break
        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch joke: {e}")
            return get_fallback_joke()

    if not joke:
        return get_fallback_joke()
    return joke


def build_hashtag_facets(joke_text, hashtags):
    facets = []
    current_offset = len(joke_text.encode("UTF-8")) + 2

    for tag in hashtags:
        tag_bytes = tag.encode("UTF-8")
        tag_start = current_offset
        tag_end = tag_start + len(tag_bytes)
        facets.append({
            "index": {
                "byteStart": tag_start,
                "byteEnd": tag_end,
            },
            "features": [
                {"$type": "app.bsky.richtext.facet#tag", "tag": tag[1:]}
            ],
        })
        current_offset = tag_end + 1

    return facets


def main():
    recent_jokes = load_recent_jokes()
    joke = pick_joke(recent_jokes)

    hashtags_string = " ".join(HASHTAGS)
    joke_with_tags = f"{joke}\n\n{hashtags_string}"
    facets = build_hashtag_facets(joke, HASHTAGS)

    try:
        client, username = login_client()
        print(f"Posting as {username}: {repr(joke_with_tags)}")
        client.send_post(text=joke_with_tags, facets=facets)
        print("Joke successfully posted!")
    except Exception as e:
        print(f"Failed to post joke: {e}")
    finally:
        clear_old_jokes()


if __name__ == "__main__":
    main()
