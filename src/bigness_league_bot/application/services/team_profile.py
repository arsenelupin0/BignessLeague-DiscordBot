#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

MAX_TEAM_PROFILE_PLAYERS = 6


def _normalize_value(value: str | None) -> str:
    if value is None:
        return ""

    return " ".join(str(value).split())


def _normalize_optional_value(value: str | None) -> str | None:
    normalized_value = _normalize_value(value)
    return normalized_value or None


@dataclass(frozen=True, slots=True)
class TeamProfilePlayer:
    position: int
    player_name: str
    discord_name: str
    epic_name: str
    rocket_name: str
    mmr: str
    tracker_url: str | None = None

    @property
    def has_content(self) -> bool:
        return any(
            (
                self.player_name,
                self.discord_name,
                self.epic_name,
                self.rocket_name,
                self.mmr,
                self.tracker_url,
            )
        )


@dataclass(frozen=True, slots=True)
class TeamProfile:
    team_name: str
    division_name: str
    remaining_signings: str
    top_three_average: str
    players: tuple[TeamProfilePlayer, ...]


def build_team_profile(
        *,
        team_name: str,
        division_name: str,
        remaining_signings: str,
        top_three_average: str,
        players: Iterable[TeamProfilePlayer],
) -> TeamProfile:
    normalized_players: list[TeamProfilePlayer] = []
    for index, player in enumerate(players, start=1):
        normalized_player = TeamProfilePlayer(
            position=player.position or index,
            player_name=_normalize_value(player.player_name),
            discord_name=_normalize_value(player.discord_name),
            epic_name=_normalize_value(player.epic_name),
            rocket_name=_normalize_value(player.rocket_name),
            mmr=_normalize_value(player.mmr),
            tracker_url=_normalize_optional_value(player.tracker_url),
        )
        if not normalized_player.has_content:
            continue

        normalized_players.append(normalized_player)
        if len(normalized_players) >= MAX_TEAM_PROFILE_PLAYERS:
            break

    return TeamProfile(
        team_name=_normalize_value(team_name),
        division_name=_normalize_value(division_name),
        remaining_signings=_normalize_value(remaining_signings),
        top_three_average=_normalize_value(top_three_average),
        players=tuple(normalized_players),
    )
