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

from dataclasses import dataclass
from enum import StrEnum


class MatchReplayDivision(StrEnum):
    GOLD = "gold"
    SILVER = "silver"

    @property
    def label(self) -> str:
        if self is MatchReplayDivision.GOLD:
            return "GOLD DIVISION S3"
        return "SILVER DIVISION S3"


@dataclass(frozen=True, slots=True)
class MatchReplayPlayer:
    name: str
    platform: str
    platform_id: str
    score: int | None = None
    goals: int | None = None
    assists: int | None = None
    saves: int | None = None
    shots: int | None = None
    official_team_name: str = ""
    roster_player_name: str = ""
    match_method: str = ""
    match_methods: tuple[str, ...] = ()
    resolution_status: str = "unmatched"


@dataclass(frozen=True, slots=True)
class MatchReplayRosterPlayer:
    division_name: str
    team_name: str
    player_name: str
    discord_id: str
    platform: str
    platform_id: str
    epic_name: str
    tracker_url: str | None = None


@dataclass(frozen=True, slots=True)
class MatchReplayTeam:
    color: str
    name: str
    goals: int
    players: tuple[MatchReplayPlayer, ...]


@dataclass(frozen=True, slots=True)
class MatchReplayGame:
    number: int
    replay_id: str
    replay_url: str
    blue: MatchReplayTeam
    orange: MatchReplayTeam
    replay_sha256: str = ""
    replay_date: str = ""

    @property
    def winner_name(self) -> str:
        if self.blue.goals > self.orange.goals:
            return self.blue.name
        if self.orange.goals > self.blue.goals:
            return self.orange.name
        return "Empate"


@dataclass(frozen=True, slots=True)
class MatchReplayReport:
    division: MatchReplayDivision
    matchday: int
    match_number: int
    team_one_name: str
    team_two_name: str
    games: tuple[MatchReplayGame, ...]
    team_one_games: int
    team_two_games: int
    unresolved_winners: tuple[str, ...]

    @property
    def series_score(self) -> str:
        return f"{self.team_one_games} - {self.team_two_games}"
