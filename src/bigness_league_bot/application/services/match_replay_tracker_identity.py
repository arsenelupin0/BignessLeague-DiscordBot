"""Read an exact account reference from a registered Tracker profile URL."""
from __future__ import annotations

from urllib.parse import unquote, urlsplit

from bigness_league_bot.application.services.match_replay_identity import (
    normalize_replay_platform,
    normalize_replay_platform_id,
)


def tracker_account_key(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname != "rocketleague.tracker.network":
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) not in (4, 5) or parts[:2] != ["rocket-league", "profile"]:
        return None
    if len(parts) == 5 and parts[4] != "overview":
        return None
    platform = normalize_replay_platform(parts[2])
    decoded_id = unquote(parts[3])
    if any(ord(character) < 32 or character in "/\\" for character in decoded_id):
        return None
    account_id = normalize_replay_platform_id(decoded_id)
    if platform not in {"epic", "steam", "psn", "xbl", "switch"} or not account_id:
        return None
    return f"{platform}:{account_id}"
