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

from dataclasses import replace
from typing import Iterable

import unicodedata

from bigness_league_bot.application.services.match_replay_models import (
    MatchReplayGame,
    MatchReplayPlayer,
    MatchReplayReport,
    MatchReplayRosterPlayer,
    MatchReplayTeam,
)
from bigness_league_bot.application.services.match_replay_team_names import (
    match_replay_team_names_match,
    normalize_match_replay_team_name,
)


def resolve_match_replay_report_players(
        report: MatchReplayReport,
        roster_players: Iterable[MatchReplayRosterPlayer],
) -> MatchReplayReport:
    roster_index = _build_roster_player_index(roster_players)
    resolved_games: list[MatchReplayGame] = []
    unresolved_winners: list[str] = []

    for game in report.games:
        resolved_blue = _resolve_match_replay_team(game.blue, roster_index)
        resolved_orange = _resolve_match_replay_team(game.orange, roster_index)
        resolved_games.append(
            MatchReplayGame(
                number=game.number,
                replay_id=game.replay_id,
                replay_url=game.replay_url,
                blue=resolved_blue,
                orange=resolved_orange,
                replay_sha256=game.replay_sha256,
                replay_date=game.replay_date,
            )
        )

    team_one_games = 0
    team_two_games = 0
    normalized_team_one = normalize_match_replay_team_name(report.team_one_name)
    normalized_team_two = normalize_match_replay_team_name(report.team_two_name)
    for game in resolved_games:
        winner = normalize_match_replay_team_name(game.winner_name)
        winner_matches_team_one = match_replay_team_names_match(winner, normalized_team_one)
        winner_matches_team_two = match_replay_team_names_match(winner, normalized_team_two)
        if winner_matches_team_one and not winner_matches_team_two:
            team_one_games += 1
            continue
        if winner_matches_team_two and not winner_matches_team_one:
            team_two_games += 1
            continue
        unresolved_winners.append(f"Game {game.number}: {game.winner_name}")

    return MatchReplayReport(
        division=report.division,
        matchday=report.matchday,
        match_number=report.match_number,
        team_one_name=report.team_one_name,
        team_two_name=report.team_two_name,
        games=tuple(resolved_games),
        team_one_games=team_one_games,
        team_two_games=team_two_games,
        unresolved_winners=tuple(unresolved_winners),
    )


def _resolve_match_replay_team(
        team: MatchReplayTeam,
        roster_index: dict[str, dict[str, MatchReplayRosterPlayer]],
) -> MatchReplayTeam:
    resolved_players: list[MatchReplayPlayer] = []
    team_match_counts: dict[str, int] = {}

    for player in team.players:
        roster_player, method, match_methods, resolution_status = _find_roster_player_match(player, roster_index)
        if roster_player is None:
            resolved_players.append(
                replace(
                    player,
                    match_method=method,
                    match_methods=match_methods,
                    resolution_status=resolution_status,
                )
            )
            continue

        team_match_counts[roster_player.team_name] = (
                team_match_counts.get(roster_player.team_name, 0) + 1
        )
        resolved_players.append(
            replace(
                player,
                official_team_name=roster_player.team_name,
                roster_player_name=roster_player.player_name,
                match_method=method,
                match_methods=match_methods,
                resolution_status=resolution_status,
            )
        )

    official_team_name = _resolve_team_name_from_counts(team_match_counts)
    if official_team_name is None:
        return MatchReplayTeam(
            color=team.color,
            name=team.name,
            goals=team.goals,
            players=tuple(resolved_players),
        )

    return MatchReplayTeam(
        color=team.color,
        name=official_team_name,
        goals=team.goals,
        players=tuple(resolved_players),
    )


def _find_roster_player_match(
        replay_player: MatchReplayPlayer,
        roster_index: dict[str, dict[str, MatchReplayRosterPlayer]],
) -> tuple[MatchReplayRosterPlayer | None, str, tuple[str, ...], str]:
    platform_key = _normalize_platform_lookup(replay_player.platform)
    platform_id_key = _normalize_player_lookup(replay_player.platform_id)
    epic_match = _find_unique_roster_index_match(
        roster_index,
        "epic_name",
        _normalize_player_lookup(replay_player.name),
    )
    if platform_key and platform_id_key:
        platform_pair_match = _find_unique_roster_index_match(
            roster_index,
            "platform_pair",
            f"{platform_key}:{platform_id_key}",
        )
        if platform_pair_match is not None:
            match_methods = ["platform", "platform_id"]
            if epic_match == platform_pair_match:
                match_methods.append("epic_name")
            return (
                platform_pair_match,
                "platform + platform_id",
                tuple(match_methods),
                "matched",
            )

    if epic_match is not None:
        return (
            epic_match,
            "platform + platform_id",
            _collect_partial_match_methods(
                roster_index,
                platform_key=platform_key,
                platform_id_key=platform_id_key,
                epic_match=epic_match,
            ),
            "unmatched",
        )

    match_methods = _collect_partial_match_methods(
        roster_index,
        platform_key=platform_key,
        platform_id_key=platform_id_key,
        epic_match=epic_match,
    )
    return None, "platform + platform_id", match_methods, "unmatched"


def _collect_partial_match_methods(
        roster_index: dict[str, dict[str, MatchReplayRosterPlayer]],
        *,
        platform_key: str,
        platform_id_key: str,
        epic_match: MatchReplayRosterPlayer | None,
) -> tuple[str, ...]:
    methods: list[str] = []
    if epic_match is not None:
        methods.append("epic_name")
        if platform_key and platform_key == _normalize_platform_lookup(epic_match.platform):
            methods.append("platform")
        if platform_id_key and platform_id_key == _normalize_player_lookup(epic_match.platform_id):
            methods.append("platform_id")
        return tuple(methods)

    platform_id_match = _find_unique_roster_index_match(
        roster_index,
        "platform_id",
        platform_id_key,
    )
    if platform_id_match is not None:
        methods.append("platform_id")
        if platform_key and platform_key == _normalize_platform_lookup(platform_id_match.platform):
            methods.append("platform")
    return tuple(
        method
        for method in methods
        if method
    )


def _build_roster_player_index(
        roster_players: Iterable[MatchReplayRosterPlayer],
) -> dict[str, dict[str, MatchReplayRosterPlayer]]:
    index: dict[str, dict[str, MatchReplayRosterPlayer]] = {
        "platform": {},
        "platform_id": {},
        "platform_pair": {},
        "epic_name": {},
    }
    for roster_player in roster_players:
        platform_key = _normalize_platform_lookup(roster_player.platform)
        platform_id_key = _normalize_player_lookup(roster_player.platform_id)
        if platform_key:
            _add_unique_roster_index_entry(index["platform"], platform_key, roster_player)
        if platform_id_key:
            _add_unique_roster_index_entry(index["platform_id"], platform_id_key, roster_player)
        if platform_key and platform_id_key:
            _add_unique_roster_index_entry(
                index["platform_pair"],
                f"{platform_key}:{platform_id_key}",
                roster_player,
            )
        normalized_epic_name = _normalize_player_lookup(roster_player.epic_name)
        if normalized_epic_name:
            _add_unique_roster_index_entry(index["epic_name"], normalized_epic_name, roster_player)
    return index


def _find_unique_roster_index_match(
        roster_index: dict[str, dict[str, MatchReplayRosterPlayer]],
        method: str,
        key: str,
) -> MatchReplayRosterPlayer | None:
    if not key:
        return None

    roster_player = roster_index.get(method, {}).get(key)
    if roster_player is None or _is_ambiguous_roster_player(roster_player):
        return None
    return roster_player


def _add_unique_roster_index_entry(
        method_index: dict[str, MatchReplayRosterPlayer],
        key: str,
        roster_player: MatchReplayRosterPlayer,
) -> None:
    existing_player = method_index.get(key)
    if existing_player is None:
        method_index[key] = roster_player
        return

    method_index[key] = MatchReplayRosterPlayer(
        division_name="",
        team_name="",
        player_name="",
        discord_id="",
        platform="",
        platform_id="",
        epic_name="",
        tracker_url=None,
    )


def _is_ambiguous_roster_player(roster_player: MatchReplayRosterPlayer) -> bool:
    return not roster_player.team_name and not roster_player.player_name


def _resolve_team_name_from_counts(team_match_counts: dict[str, int]) -> str | None:
    if not team_match_counts:
        return None

    ordered_matches = sorted(
        team_match_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    )
    if len(ordered_matches) > 1 and ordered_matches[0][1] == ordered_matches[1][1]:
        return None
    return ordered_matches[0][0]


def _normalize_player_lookup(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value.casefold())
    return "".join(character for character in normalized if character.isalnum())


def _normalize_platform_lookup(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value.casefold()).strip()
    aliases = {
        "ps4": "psn",
        "ps5": "psn",
    }
    compact = "".join(character for character in normalized if character.isalnum())
    return aliases.get(compact, aliases.get(normalized, normalized))
