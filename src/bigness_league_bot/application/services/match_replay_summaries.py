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

from bigness_league_bot.application.services.match_replays import (
    MatchReplayPlayer,
    MatchReplayReport,
    MatchReplayRosterPlayer,
    TEAM_NAME_IGNORED_TOKENS,
    TEAM_TOKEN_PATTERN,
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
    method_counts: dict[str, int] = {}
    unique_players: dict[tuple[str, str], bool] = {}
    unmatched_players: dict[tuple[str, str], MatchReplayUnmatchedPlayer] = {}

    for game in report.games:
        for team in (game.blue, game.orange):
            for replay_player in team.players:
                total_appearances += 1
                player_key = _player_identity_key(replay_player)
                matched = replay_player.resolution_status == "matched"
                unique_players[player_key] = unique_players.get(player_key, False) or matched
                if matched:
                    matched_appearances += 1
                    method = replay_player.match_method or "unknown"
                    method_counts[method] = method_counts.get(method, 0) + 1
                    continue

                unmatched_players.setdefault(
                    player_key,
                    MatchReplayUnmatchedPlayer(
                        team_name=team.name,
                        player_name=replay_player.name,
                        platform=replay_player.platform,
                        platform_id=replay_player.platform_id,
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
                method_counts.items(),
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
    )


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
                    _normalize_team_name(team_name),
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
    normalized_team = _normalize_team_name(team_name)
    if _team_names_match(normalized_team, _normalize_team_name(report.team_one_name)):
        return 0
    if _team_names_match(normalized_team, _normalize_team_name(report.team_two_name)):
        return 1
    return 2


def _normalize_team_name(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _team_names_match(candidate: str, expected: str) -> bool:
    if candidate == expected:
        return True

    if candidate and expected and (candidate in expected or expected in candidate):
        return True

    candidate_tokens = set(_team_identity_tokens(candidate))
    expected_tokens = set(_team_identity_tokens(expected))
    if not candidate_tokens or not expected_tokens:
        return False

    return candidate_tokens <= expected_tokens or expected_tokens <= candidate_tokens


def _team_identity_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in TEAM_TOKEN_PATTERN.findall(_normalize_team_name(value))
        if token not in TEAM_NAME_IGNORED_TOKENS
    )


def _normalize_player_lookup(value: str) -> str:
    return "".join(TEAM_TOKEN_PATTERN.findall(value.casefold()))
