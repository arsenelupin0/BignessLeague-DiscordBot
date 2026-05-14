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

import unicodedata

from bigness_league_bot.application.services.match_replay_models import (
    MatchReplayPlayer,
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


@dataclass(frozen=True, slots=True)
class MatchReplayUnmatchedPlayer:
    team_name: str
    player_name: str
    platform: str
    platform_id: str
    missing_methods: tuple[str, ...]


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
    method_players: dict[str, set[tuple[str, str]]] = {}
    unique_players: dict[tuple[str, str], bool] = {}
    unmatched_players: dict[tuple[str, str], MatchReplayUnmatchedPlayer] = {}

    for game in report.games:
        for team in (game.blue, game.orange):
            for replay_player in team.players:
                total_appearances += 1
                player_key = _player_identity_key(replay_player)
                match_methods = replay_player.match_methods
                if (
                        not match_methods
                        and replay_player.match_method
                        and replay_player.resolution_status == "matched"
                ):
                    match_methods = (replay_player.match_method,)
                for method in match_methods:
                    method_players.setdefault(method, set()).add(player_key)

                identity_verified = {"platform", "platform_id"} <= set(match_methods)
                unique_players[player_key] = unique_players.get(player_key, False) or identity_verified
                if identity_verified:
                    matched_appearances += 1
                    unmatched_players.pop(player_key, None)
                    continue

                unmatched_players.setdefault(
                    player_key,
                    MatchReplayUnmatchedPlayer(
                        team_name=team.name,
                        player_name=replay_player.name,
                        platform=replay_player.platform,
                        platform_id=replay_player.platform_id,
                        missing_methods=_missing_match_methods(match_methods),
                    ),
                )

    matched_unique_players = sum(1 for matched in unique_players.values() if matched)
    unmatched_unique_players = len(unique_players) - matched_unique_players
    return MatchReplayRosterValidationSummary(
        total_appearances=total_appearances,
        matched_appearances=matched_appearances,
        unmatched_appearances=total_appearances - matched_appearances,
        unique_players=len(unique_players),
        matched_unique_players=matched_unique_players,
        unmatched_unique_players=unmatched_unique_players,
        match_methods=tuple(
            MatchReplayMatchMethodCount(method=method, count=count)
            for method, count in sorted(
                (
                    (method, len(player_keys))
                    for method, player_keys in method_players.items()
                ),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        unmatched_players=tuple(
            sorted(
                unmatched_players.values(),
                key=lambda player: (
                    player.team_name.casefold(),
                    player.player_name.casefold(),
                ),
            )
        ),
        epic_name_unmatched_players=tuple(
            player
            for player in sorted(
                unmatched_players.values(),
                key=lambda player: (
                    player.team_name.casefold(),
                    player.player_name.casefold(),
                ),
            )
            if "epic_name" not in _match_methods_for_unmatched_player(report, player)
        ),
    )


def _match_methods_for_unmatched_player(
        report: MatchReplayReport,
        unmatched_player: MatchReplayUnmatchedPlayer,
) -> tuple[str, ...]:
    target_key = _unmatched_player_key(unmatched_player)
    for game in report.games:
        for team in (game.blue, game.orange):
            for replay_player in team.players:
                if _player_identity_key(replay_player) != target_key:
                    continue
                return replay_player.match_methods or (
                    (replay_player.match_method,) if replay_player.match_method else ()
                )

    return ()


def _unmatched_player_key(player: MatchReplayUnmatchedPlayer) -> tuple[str, str]:
    if player.platform_id:
        return player.platform.casefold(), player.platform_id.casefold()
    return "name", _normalize_player_lookup(player.player_name)


def _missing_match_methods(match_methods: tuple[str, ...]) -> tuple[str, ...]:
    missing: list[str] = []
    if "platform" not in match_methods:
        missing.append("platform")
    if "platform_id" not in match_methods:
        missing.append("platform_id")
    return tuple(missing)


def build_match_replay_player_stat_totals(
        report: MatchReplayReport,
) -> tuple[MatchReplayPlayerStatTotal, ...]:
    totals: dict[tuple[str, str, str], MatchReplayPlayerStatTotal] = {}
    for game in report.games:
        for team in (game.blue, game.orange):
            for replay_player in team.players:
                team_name = replay_player.official_team_name or team.name
                player_name = replay_player.roster_player_name or replay_player.name
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


def _player_identity_key(player: MatchReplayPlayer) -> tuple[str, str]:
    if player.platform_id:
        return player.platform.casefold(), player.platform_id.casefold()
    return "name", _normalize_player_lookup(player.name)


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


def _normalize_player_lookup(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value.casefold())
    return "".join(character for character in normalized if character.isalnum())
