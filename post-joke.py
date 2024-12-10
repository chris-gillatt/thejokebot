import requests

jokeApi = "https://icanhazdadjoke.com"

headers = {
    "Accept": "text/plain"
}

try:
    # Send GET request with headers
    response = requests.get(jokeApi, headers=headers)
    
    # Check if the request was successful
    response.raise_for_status()
    
    joke = response.text
    
    print(joke)
except requests.exceptions.RequestException as e:
    print(f"An error occurred: {e}")

from atproto import Client

client = Client()
client.login('thejokebot.bsky.social', '<pass>')

post = client.send_post(joke)