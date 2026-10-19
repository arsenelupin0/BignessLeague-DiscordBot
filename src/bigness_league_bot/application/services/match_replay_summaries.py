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
from typing import Iterable

from bigness_league_bot.application.services.match_replay_identity import (
    replay_player_identity_key as _player_identity_key,
)
from bigness_league_bot.application.services.match_replay_models import (
    MatchReplayReport,
    MatchReplayRosterPlayer,
)
from bigness_league_bot.application.services.match_replay_team_names import (
    match_replay_team_names_match,
    normalize_match_replay_team_name,
)


@dataclass(frozen=True, slots=True)
class MatchReplayMatchMethodCount:
    method: str
    count: int
    evaluated_count: int | None = None


@dataclass(frozen=True, slots=True)
class MatchReplayUnmatchedPlayer:
    team_name: str
    player_name: str
    platform: str
    platform_id: str
    missing_methods: tuple[str, ...]
    registered_platform: str = ""
    registered_platform_id: str = ""
    registered_epic_name: str = ""
    resolution_status: str = "unmatched"
    unevaluated_methods: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchReplayRosterValidationSummary:
    total_appearances: int
    matched_appearances: int
    unmatched_appearances: int
    unique_players: int
    matched_unique_players: int
    unmatched_unique_players: int
    match_methods: tuple[MatchReplayMatchMethodCount, ...]
    unmatched_players: tuple[MatchReplayUnmatchedPlayer, ...]
    epic_name_unmatched_players: tuple[MatchReplayUnmatchedPlayer, ...]


@dataclass(frozen=True, slots=True)
class MatchReplayPlayerStatTotal:
    team_name: str
    player_name: str
    games_played: int
    score: int
    goals: int
    assists: int
    saves: int
    shots: int
    platform: str
    platform_id: str
    official_team_name: str
    roster_player_name: str
    match_method: str
    resolution_status: str


@dataclass(frozen=True, slots=True)
class MatchReplayTeamLogo:
    team_name: str
    logo_url: str | None


def collect_match_replay_standings_team_names(
        *,
        roster_players: Iterable[MatchReplayRosterPlayer],
        fallback_team_names: tuple[str, ...],
) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for player in roster_players:
        team_name = player.team_name
        normalized = " ".join(team_name.casefold().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(team_name)

    for team_name in fallback_team_names:
        normalized = " ".join(team_name.casefold().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(team_name)
    return tuple(names)


def build_match_replay_roster_validation_summary(
        report: MatchReplayReport,
) -> MatchReplayRosterValidationSummary:
    total_appearances = 0
    matched_appearances = 0
    methods_by_player: dict[tuple[str, str], set[str]] = {}
    evaluated_by_player: dict[tuple[str, str], set[str]] = {}
    verified_by_player: dict[tuple[str, str], bool] = {}
    unmatched_players: dict[tuple[str, str], MatchReplayUnmatchedPlayer] = {}
    name_warnings: dict[tuple[str, str], MatchReplayUnmatchedPlayer] = {}

    for game in report.games:
        for team in (game.blue, game.orange):
            for player in team.players:
                total_appearances += 1
                key = _player_identity_key(player)
                methods = set(player.match_methods)
                if not methods and player.resolution_status == "matched":
                    methods = set(player.match_method.split(" + "))
                evaluated = set(player.evaluated_methods if player.evaluated_methods is not None
                                else ("platform", "platform_id"))
                if player.registered_epic_name or "epic_name" in methods:
                    evaluated.add("epic_name")
                identity_verified = (
                        player.resolution_status == "matched"
                        and {"platform", "platform_id"} <= methods
                )
                matched_appearances += int(identity_verified)
                # A failed appearance must not disappear depending on game order.
                verified_by_player[key] = verified_by_player.get(key, True) and identity_verified
                if key not in methods_by_player:
                    methods_by_player[key] = methods
                    evaluated_by_player[key] = evaluated
                else:
                    methods_by_player[key] &= methods
                    evaluated_by_player[key] &= evaluated
                detail = MatchReplayUnmatchedPlayer(
                    team_name=team.name,
                    player_name=player.name,
                    platform=player.platform,
                    platform_id=player.platform_id,
                    missing_methods=tuple(
                        method for method in ("platform", "platform_id") if
                        method in evaluated and method not in methods
                    ),
                    registered_platform=player.registered_platform,
                    registered_platform_id=player.registered_platform_id,
                    registered_epic_name=player.registered_epic_name,
                    resolution_status=player.resolution_status,
                    unevaluated_methods=tuple(
                        method for method in ("platform", "platform_id") if method not in evaluated),
                )
                if not identity_verified:
                    unmatched_players.setdefault(key, detail)
                if "epic_name" not in methods:
                    name_warnings.setdefault(key, detail)

    sort_key = lambda player: (player.team_name.casefold(), player.player_name.casefold())
    matched_unique_players = sum(verified_by_player.values())
    return MatchReplayRosterValidationSummary(
        total_appearances=total_appearances,
        matched_appearances=matched_appearances,
        unmatched_appearances=total_appearances - matched_appearances,
        unique_players=len(verified_by_player),
        matched_unique_players=matched_unique_players,
        unmatched_unique_players=len(verified_by_player) - matched_unique_players,
        match_methods=tuple(
            MatchReplayMatchMethodCount(
                method=method,
                count=sum(method in methods for methods in methods_by_player.values()),
                evaluated_count=sum(method in evaluated for evaluated in evaluated_by_player.values()),
            )
            for method in ("platform", "platform_id", "epic_name")
        ),
        unmatched_players=tuple(sorted(unmatched_players.values(), key=sort_key)),
        epic_name_unmatched_players=tuple(sorted(name_warnings.values(), key=sort_key)),
    )


def build_match_replay_player_stat_totals(
        report: MatchReplayReport,
) -> tuple[MatchReplayPlayerStatTotal, ...]:
    totals: dict[tuple[str, str, str], MatchReplayPlayerStatTotal] = {}
    for game in report.games:
        for team in (game.blue, game.orange):
            for replay_player in team.players:
                team_name = replay_player.official_team_name or team.name
                player_name = replay_player.name
                platform, player_identity = _player_identity_key(replay_player)
                key: tuple[str, str, str] = (
                    normalize_match_replay_team_name(team_name),
                    platform,
                    player_identity,
                )
                current = totals.get(key)
                if current is None:
                    totals[key] = MatchReplayPlayerStatTotal(
                        team_name=team_name,
                        player_name=player_name,
                        games_played=1,
                        score=_optional_stat(replay_player.score),
                        goals=_optional_stat(replay_player.goals),
                        assists=_optional_stat(replay_player.assists),
                        saves=_optional_stat(replay_player.saves),
                        shots=_optional_stat(replay_player.shots),
                        platform=replay_player.platform,
                        platform_id=replay_player.platform_id,
                        official_team_name=replay_player.official_team_name,
                        roster_player_name=replay_player.roster_player_name,
                        match_method=replay_player.match_method,
                        resolution_status=replay_player.resolution_status,
                    )
                    continue

                totals[key] = MatchReplayPlayerStatTotal(
                    team_name=current.team_name,
                    player_name=current.player_name,
                    games_played=current.games_played + 1,
                    score=current.score + _optional_stat(replay_player.score),
                    goals=current.goals + _optional_stat(replay_player.goals),
                    assists=current.assists + _optional_stat(replay_player.assists),
                    saves=current.saves + _optional_stat(replay_player.saves),
                    shots=current.shots + _optional_stat(replay_player.shots),
                    platform=current.platform,
                    platform_id=current.platform_id,
                    official_team_name=current.official_team_name,
                    roster_player_name=current.roster_player_name,
                    match_method=current.match_method,
                    resolution_status=(
                        "matched"
                        if current.resolution_status == "matched"
                           or replay_player.resolution_status == "matched"
                        else current.resolution_status
                    ),
                )

    return tuple(
        sorted(
            totals.values(),
            key=lambda total: (
                _team_sort_index(report, total.team_name),
                total.team_name.casefold(),
                -total.goals,
                -total.score,
                total.player_name.casefold(),
            ),
        )
    )


def _optional_stat(value: int | None) -> int:
    if value is None:
        return 0
    return value


def _team_sort_index(report: MatchReplayReport, team_name: str) -> int:
    normalized_team = normalize_match_replay_team_name(team_name)
    if match_replay_team_names_match(
            normalized_team,
            normalize_match_replay_team_name(report.team_one_name),
    ):
        return 0
    if match_replay_team_names_match(
            normalized_team,
            normalize_match_replay_team_name(report.team_two_name),
    ):
        return 1
    return 2
