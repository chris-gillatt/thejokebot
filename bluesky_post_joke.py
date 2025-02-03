import requests
import random
from atproto import Client
import os

# Configuration
JOKE_API_URL = "https://icanhazdadjoke.com"
HEADERS = {
    "Accept": "text/plain",
    "User-Agent": "thejokebot (https://github.com/chris-gillatt/thejokebot)"
}
BLUESKY_USERNAME = "thejokebot.bsky.social"
BLUESKY_PASSWORD = os.getenv("BLUESKY_PASSWORD")

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

try:
    # Fetch joke from API
    response = requests.get(JOKE_API_URL, headers=HEADERS)
    response.raise_for_status()  # Ensure successful response
    joke = response.content.decode("utf-8").strip()
    print(f"Raw joke fetched: {repr(joke)}")  # Debugging raw joke
    print(f"Fetched joke: {joke}")
except requests.exceptions.RequestException as e:
    print(f"Failed to fetch joke: {e}")
    joke = get_fallback_joke()  # Use fallback joke
    print(f"Using fallback joke: {joke}")

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
            {"$type": "app.bsky.richtext.facet#tag", "tag": tag[1:]}  # Remove `#` for the `tag` field
        ],
    })
    current_offset = tag_end + 1  # Add 1 for the space between hashtags

try:
    # Login to Bluesky and post joke
    client = Client()
    client.login(BLUESKY_USERNAME, BLUESKY_PASSWORD)
    print(f"Final joke before posting: {repr(joke_with_tags)}")  # Debugging final joke
    post = client.send_post(text=joke_with_tags, facets=facets)
    print("Joke successfully posted!")
except Exception as e:
    print(f"Failed to post joke: {e}")
