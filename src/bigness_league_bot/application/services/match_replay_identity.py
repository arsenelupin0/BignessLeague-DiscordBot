"""Normalization shared by roster verification and replay aggregation."""
from __future__ import annotations

import unicodedata

from bigness_league_bot.application.services.match_replay_models import MatchReplayPlayer


def normalize_replay_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def normalize_replay_platform_id(value: str) -> str:
    # IDs are opaque: removing punctuation can merge different accounts.
    return value.strip().casefold()


def normalize_replay_platform(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return {"ps4": "psn", "ps5": "psn"}.get(normalized, normalized)


def replay_player_identity_key(player: MatchReplayPlayer) -> tuple[str, str]:
    platform_id = normalize_replay_platform_id(player.platform_id)
    if platform_id:
        return normalize_replay_platform(player.platform), platform_id
    return "name", normalize_replay_name(player.name)
