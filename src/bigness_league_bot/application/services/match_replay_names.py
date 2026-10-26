"""Combine names read from a replay with accounts returned by its analyzer."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from bigness_league_bot.application.services.match_replay_identity import (
    normalize_replay_platform, normalize_replay_platform_id, replay_player_identity_key,
)
from bigness_league_bot.application.services.match_replay_models import MatchReplayGame, MatchReplayTeam


@dataclass(frozen=True, slots=True)
class ReplayAccountName:
    """An IGN bound to a platform account, not an Epic Games display name."""

    platform: str
    platform_id: str
    name: str

    @property
    def identity(self) -> tuple[str, str]:
        return normalize_replay_platform(self.platform), normalize_replay_platform_id(self.platform_id)


def apply_replay_account_names(game: MatchReplayGame, names: tuple[ReplayAccountName, ...]) -> MatchReplayGame:
    """Require a unique account on both sides; never join by name or list order."""
    name_counts = Counter(entry.identity for entry in names)
    player_counts = Counter(replay_player_identity_key(player)
                            for team in (game.blue, game.orange) for player in team.players)
    unique = {entry.identity: entry for entry in names
              if all(entry.identity) and name_counts[entry.identity] == 1}

    def enrich(team: MatchReplayTeam) -> MatchReplayTeam:
        players = []
        for player in team.players:
            key = replay_player_identity_key(player)
            entry = unique.get(key)
            if entry is not None and entry.name and player_counts[key] == 1:
                player = replace(
                    player, name=entry.name,
                    ballchasing_name=player.ballchasing_name or player.name,
                    name_source="replay_header",
                )
            players.append(player)
        return replace(team, players=tuple(players))

    return replace(game, blue=enrich(game.blue), orange=enrich(game.orange))
