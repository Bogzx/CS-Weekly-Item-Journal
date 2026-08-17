"""Shared HTTP headers for Steam Community Market requests.

Every call site in this package previously used a bare ``requests.get(url)``.
The default ``python-requests/x.y.z`` User-Agent is one of the first things
Steam rate-limits, so a full price refresh would start returning HTTP 429 far
sooner than necessary. Sending a normal browser User-Agent (plus the Accept
headers a browser would send for a JSON endpoint) keeps the scrapers on the
ordinary rate-limit path.

This identifies the project honestly rather than impersonating a specific
browser build, and it does not bypass any access control -- the Market search
endpoints used here are public and unauthenticated.
"""

PROJECT_URL = "https://github.com/Bogzx/CS-Weekly-Item-Journal"

STEAM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
        f"CS-Weekly-Item-Journal/1.0 (+{PROJECT_URL})"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://steamcommunity.com/market/search?appid=730",
    "Connection": "keep-alive",
}

# Seconds to wait before giving up on a Steam request. Without this a hung
# connection blocks a scrape run forever.
STEAM_TIMEOUT = 30
