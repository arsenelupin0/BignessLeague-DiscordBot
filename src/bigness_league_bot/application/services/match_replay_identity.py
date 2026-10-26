"""Normalization shared by roster verification and replay aggregation."""
from __future__ import annotations

import unicodedata

from bigness_league_bot.application.services.match_replay_models import MatchReplayPlayer

PLAYSTATION_PLATFORMS = frozenset({"ps4", "ps5", "psn"})


def normalize_replay_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def normalize_epic_display_name(value: str) -> str:
    """Compare actual Epic display names, preserving punctuation and spaces."""
    normalized = unicodedata.normalize("NFC", value).strip().casefold()
    return normalized if normalized != "-" else ""


def normalize_replay_platform_id(value: str) -> str:
    # IDs are opaque: removing punctuation can merge different accounts.
    return value.strip().casefold()


def normalize_replay_platform(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return "psn" if normalized in PLAYSTATION_PLATFORMS else normalized


def replay_player_identity_key(player: MatchReplayPlayer) -> tuple[str, str]:
    platform_id = normalize_replay_platform_id(player.platform_id)
    if platform_id:
        return normalize_replay_platform(player.platform), platform_id
    return "name", normalize_replay_name(player.name)
