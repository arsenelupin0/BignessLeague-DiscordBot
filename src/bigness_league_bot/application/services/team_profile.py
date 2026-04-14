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

import re
from collections.abc import Iterable
from dataclasses import dataclass

MAX_TEAM_PROFILE_PLAYERS = 6
MMR_DIGITS_PATTERN = re.compile(r"\d+")


def _normalize_value(value: str | None) -> str:
    if value is None:
        return ""

    return " ".join(str(value).split())


def _normalize_optional_value(value: str | None) -> str | None:
    normalized_value = _normalize_value(value)
    return normalized_value or None


def _parse_mmr_sort_value(value: str) -> int:
    matches = MMR_DIGITS_PATTERN.findall(value)
    if not matches:
        return -1

    return int("".join(matches))


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
    collected_players: list[TeamProfilePlayer] = []
    for player in players:
        normalized_player = TeamProfilePlayer(
            position=player.position,
            player_name=_normalize_value(player.player_name),
            discord_name=_normalize_value(player.discord_name),
            epic_name=_normalize_value(player.epic_name),
            rocket_name=_normalize_value(player.rocket_name),
            mmr=_normalize_value(player.mmr),
            tracker_url=_normalize_optional_value(player.tracker_url),
        )
        if not normalized_player.has_content:
            continue

        collected_players.append(normalized_player)

    sorted_players = sorted(
        collected_players,
        key=lambda player: (
            _parse_mmr_sort_value(player.mmr),
            player.player_name.casefold(),
        ),
        reverse=True,
    )
    normalized_players = [
        TeamProfilePlayer(
            position=index,
            player_name=player.player_name,
            discord_name=player.discord_name,
            epic_name=player.epic_name,
            rocket_name=player.rocket_name,
            mmr=player.mmr,
            tracker_url=player.tracker_url,
        )
        for index, player in enumerate(
            sorted_players[:MAX_TEAM_PROFILE_PLAYERS],
            start=1,
        )
    ]

    return TeamProfile(
        team_name=_normalize_value(team_name),
        division_name=_normalize_value(division_name),
        remaining_signings=_normalize_value(remaining_signings),
        top_three_average=_normalize_value(top_three_average),
        players=tuple(normalized_players),
    )
