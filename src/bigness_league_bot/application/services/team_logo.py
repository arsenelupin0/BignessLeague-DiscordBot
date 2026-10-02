from __future__ import annotations

from urllib.parse import urlsplit


def normalize_team_logo_url(value: str) -> str:
    url = value.strip()
    if not url or len(url) > 2000 or any(char.isspace() or ord(char) < 32 for char in url):
        raise ValueError("Invalid logo URL")
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in ("http", "https") and bool(parsed.hostname)
        parsed.port  # Reject malformed ports as well as malformed hosts.
    except ValueError as exc:
        raise ValueError("Invalid logo URL") from exc
    if not valid:
        raise ValueError("Invalid logo URL")
    return url
