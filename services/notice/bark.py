"""Bark notification client."""

import os

import requests
from dotenv import load_dotenv

DEFAULT_BARK_URL = "https://api.day.app"


def send_notice(title: str, message: str) -> bool:
    """Send a Bark notification.

    Returns ``False`` when Bark is not configured. Network and API errors are
    raised so callers can decide whether they should be fatal.
    """
    load_dotenv()
    bark_key = os.getenv("BARK_KEY", "").strip()
    if not bark_key:
        return False

    base_url = os.getenv("BARK_URL", DEFAULT_BARK_URL).rstrip("/")
    response = requests.post(
        f"{base_url}/{bark_key}",
        json={"title": title, "body": message},
        timeout=10,
    )
    response.raise_for_status()
    return True
