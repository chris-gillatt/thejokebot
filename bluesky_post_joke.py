import requests
import random
from atproto import Client
import os
import time
import base64

# Configuration
JOKE_API_URL = "https://icanhazdadjoke.com"
HEADERS = {
    "Accept": "text/plain",
    "User-Agent": "thejokebot (https://github.com/chris-gillatt/thejokebot)"
}
BLUESKY_USERNAME = "thejokebot.bsky.social"
BLUESKY_PASSWORD = os.getenv("BLUESKY_PASSWORD")
POSTED_JOKES_FILE = "posted_jokes.txt"
DAYS_LIMIT = 90
MAX_ATTEMPTS = 5

# Hashtags
HASHTAGS = ["#jokes", "#dadjoke", "#funny"]

# Check password presence
if not BLUESKY_PASSWORD:
    raise ValueError("BLUESKY_PASSWORD environment variable is not set. Please configure it in your GitHub Actions secrets.")

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
    filtered = [
        line for line in lines
        if line.strip() and float(line.split()[0]) > cutoff
    ]
    with open(POSTED_JOKES_FILE, "w", encoding="utf-8") as f:
        f.writelines(filtered)

# Load recent jokes
recent_jokes = load_recent_jokes()
joke = None

# Try to find a fresh joke
for attempt in range(MAX_ATTEMPTS):
    try:
        response = requests.get(JOKE_API_URL, headers=HEADERS)
        response.raise_for_status()
        candidate = response.content.decode("utf-8").strip()
        encoded = base64.b64encode(candidate.encode("utf-8")).decode()
        if encoded not in recent_jokes:
            joke = candidate
            save_joke(joke)
            break
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch joke: {e}")
        joke = get_fallback_joke()
        break

# Fallback if we didn't get a fresh one
if not joke:
    joke = get_fallback_joke()

# Combine joke and hashtags
hashtags_string = " ".join(HASHTAGS)
joke_with_tags = f"{joke}\n\n{hashtags_string}"

# Calculate facets for hashtags
joke_bytes = joke_with_tags.encode("UTF-8")
facets = []
current_offset = len(joke.encode("UTF-8")) + 2  # Offset starts after joke + 2 newlines

for tag in HASHTAGS:
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
    current_offset = tag_end + 1  # Add 1 for space

try:
    client = Client()
    client.login(BLUESKY_USERNAME, BLUESKY_PASSWORD)
    print(f"Final joke before posting: {repr(joke_with_tags)}")
    post = client.send_post(text=joke_with_tags, facets=facets)
    print("Joke successfully posted!")
except Exception as e:
    print(f"Failed to post joke: {e}")

# Clear old jokes from file
clear_old_jokes()
