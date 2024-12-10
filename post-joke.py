import requests
import random
from atproto import Client

JOKE_API_URL = "https://icanhazdadjoke.com"
HEADERS = {"Accept": "text/plain"}
BLUESKY_USERNAME = "thejokebot.bsky.social"
BLUESKY_PASSWORD = os.getenv("BLUESKY_PASSWORD")

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
    response.raise_for_status()  # Ensure successful
    joke = response.text.strip()  # Strip whitespace
    print(f"Fetched joke: {joke}")
except requests.exceptions.RequestException as e:
    print(f"Failed to fetch joke: {e}")
    joke = get_fallback_joke()  # Use fallback joke
    print(f"Using fallback joke: {joke}")

try:
    # Login to Bluesky and post joke
    client = Client()
    client.login(BLUESKY_USERNAME, BLUESKY_PASSWORD)
    post = client.send_post(joke)
    print("Joke successfully posted!")
except Exception as e:
    print(f"Failed to post joke: {e}")