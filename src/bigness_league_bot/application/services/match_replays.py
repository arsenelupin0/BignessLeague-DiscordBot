#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from bigness_league_bot.application.services.match_replay_models import (
    MatchReplayDivision,
    MatchReplayGame,
    MatchReplayReport,
    MatchReplayRosterPlayer,
    MatchReplayPlayer,
    MatchReplayTeam
)
from bigness_league_bot.application.services.match_replay_team_names import (
    match_replay_team_names_match,
    normalize_match_replay_team_name,
)

MATCH_REPLAY_MIN_FILES = 3
MATCH_REPLAY_MAX_FILES = 5
MATCH_REPLAY_EXTENSION = ".replay"
__all__ = [
    "InvalidReplayCountError",
    "InvalidReplayExtensionError",
    "MATCH_REPLAY_EXTENSION",
    "MATCH_REPLAY_MAX_FILES",
    "MATCH_REPLAY_MIN_FILES",
    "MatchReplayDivision",
    "MatchReplayGame",
    "MatchReplayPlayer",
    "MatchReplayReport",
    "MatchReplayRosterPlayer",
    "MatchReplayTeam",
    "MatchReplayValidationError",
    "build_match_replay_report",
    "build_match_replay_sheet_rows",
    "format_match_replay_game_scores",
    "match_replay_game_score",
    "match_replay_sheet_headers",
    "resolve_match_replay_report_players",
    "sort_match_replay_games_by_replay_date",
    "validate_replay_filenames",
]


class MatchReplayValidationError(ValueError):
    """Raised when a replay upload request cannot be processed."""


class InvalidReplayCountError(MatchReplayValidationError):
    """Raised when the series does not have a BO5-compatible replay count."""


class InvalidReplayExtensionError(MatchReplayValidationError):
    def __init__(self, filenames: tuple[str, ...]) -> None:
        super().__init__(", ".join(filenames))
        self.filenames = filenames


def validate_replay_filenames(
        filenames: Iterable[str],
) -> tuple[str, ...]:
    names = tuple(name.strip() for name in filenames if name.strip())
    if len(names) < MATCH_REPLAY_MIN_FILES or len(names) > MATCH_REPLAY_MAX_FILES:
        raise InvalidReplayCountError()

    invalid_names = tuple(
        name for name in names if not name.lower().endswith(MATCH_REPLAY_EXTENSION)
    )
    if invalid_names:
        raise InvalidReplayExtensionError(invalid_names)

    return names


def build_match_replay_report(
        *,
        division: MatchReplayDivision,
        matchday: int,
        match_number: int,
        team_one_name: str,
        team_two_name: str,
        games: Iterable[MatchReplayGame],
) -> MatchReplayReport:
    ordered_games = tuple(
        MatchReplayGame(
            number=index,
            replay_id=game.replay_id,
            replay_url=game.replay_url,
            blue=game.blue,
            orange=game.orange,
            replay_sha256=game.replay_sha256,
            replay_date=game.replay_date,
        )
        for index, game in enumerate(
            sort_match_replay_games_by_replay_date(games),
            start=1,
        )
    )
    if len(ordered_games) < MATCH_REPLAY_MIN_FILES or len(ordered_games) > MATCH_REPLAY_MAX_FILES:
        raise InvalidReplayCountError()

    team_one_games = 0
    team_two_games = 0
    unresolved_winners: list[str] = []
    normalized_team_one = normalize_match_replay_team_name(team_one_name)
    normalized_team_two = normalize_match_replay_team_name(team_two_name)

    for game in ordered_games:
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
        division=division,
        matchday=matchday,
        match_number=match_number,
        team_one_name=team_one_name,
        team_two_name=team_two_name,
        games=ordered_games,
        team_one_games=team_one_games,
        team_two_games=team_two_games,
        unresolved_winners=tuple(unresolved_winners),
    )


def resolve_match_replay_report_players(
        report: MatchReplayReport,
        roster_players: Iterable[MatchReplayRosterPlayer],
) -> MatchReplayReport:
    from bigness_league_bot.application.services.match_replay_roster_resolution import (
        resolve_match_replay_report_players as resolve_players,
    )

    return resolve_players(report, roster_players)


def build_match_replay_sheet_rows(
        report: MatchReplayReport,
        *,
        skip_replay_ids: Iterable[str] = (),
        skip_replay_sha256: Iterable[str] = (),
) -> list[list[object]]:
    rows: list[list[object]] = []
    skipped_replay_ids = {value.casefold() for value in skip_replay_ids if value}
    skipped_replay_sha256 = {value.casefold() for value in skip_replay_sha256 if value}
    for game in report.games:
        if game.replay_id.casefold() in skipped_replay_ids:
            continue
        if game.replay_sha256 and game.replay_sha256.casefold() in skipped_replay_sha256:
            continue

        rows.append(
            _base_row(report, game)
            + [
                "GAME",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                game.replay_sha256,
            ]
        )
        for team in (game.blue, game.orange):
            for player in team.players:
                rows.append(
                    _base_row(report, game)
                    + [
                        "PLAYER",
                        team.name,
                        player.name,
                        player.platform,
                        player.platform_id,
                        _optional_int(player.score),
                        _optional_int(player.goals),
                        _optional_int(player.assists),
                        _optional_int(player.saves),
                        _optional_int(player.shots),
                        player.official_team_name,
                        player.roster_player_name,
                        player.match_method,
                        player.resolution_status,
                        game.replay_sha256,
                    ]
                )

    return rows


def match_replay_sheet_headers() -> list[str]:
    return [
        "Division",
        "Jornada",
        "Partido",
        "Equipo 1",
        "Equipo 2",
        "Marcador serie",
        "Marcador game",
        "Game",
        "Replay ID",
        "Replay URL",
        "Blue team",
        "Blue goals",
        "Orange goals",
        "Orange team",
        "Ganador",
        "Tipo fila",
        "Equipo jugador",
        "Jugador",
        "Plataforma",
        "Platform ID",
        "Score",
        "Goals",
        "Assists",
        "Saves",
        "Shots",
        "Equipo oficial",
        "Jugador roster",
        "Match method",
        "Resolution status",
        "Replay SHA256",
    ]


def format_match_replay_game_scores(report: MatchReplayReport) -> str:
    return " | ".join(
        f"G{game.number}: {match_replay_game_score(report, game)}"
        for game in report.games
    )


def sort_match_replay_games_by_replay_date(
        games: Iterable[MatchReplayGame],
) -> tuple[MatchReplayGame, ...]:
    indexed_games = tuple(enumerate(games))
    return tuple(
        game
        for _, game in sorted(
            indexed_games,
            key=lambda item: (_replay_date_sort_key(item[1].replay_date), item[0]),
        )
    )


def _replay_date_sort_key(value: str) -> tuple[int, float]:
    timestamp = _parse_replay_date_timestamp(value)
    if timestamp is None:
        return 1, 0.0
    return 0, timestamp


def _parse_replay_date_timestamp(value: str) -> float | None:
    normalized_value = value.strip()
    if not normalized_value:
        return None
    if normalized_value.endswith("Z"):
        normalized_value = f"{normalized_value[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized_value).timestamp()
    except ValueError:
        return None


def match_replay_game_score(
        report: MatchReplayReport,
        game: MatchReplayGame,
) -> str:
    team_one_goals = _goals_for_report_team(
        game,
        expected_team_name=report.team_one_name,
    )
    team_two_goals = _goals_for_report_team(
        game,
        expected_team_name=report.team_two_name,
    )
    if team_one_goals is None or team_two_goals is None:
        return f"{game.blue.goals} - {game.orange.goals}"
    return f"{team_one_goals} - {team_two_goals}"


def _base_row(
        report: MatchReplayReport,
        game: MatchReplayGame,
) -> list[object]:
    return [
        report.division.label,
        report.matchday,
        report.match_number,
        report.team_one_name,
        report.team_two_name,
        report.series_score,
        match_replay_game_score(report, game),
        game.number,
        game.replay_id,
        game.replay_url,
        game.blue.name,
        game.blue.goals,
        game.orange.goals,
        game.orange.name,
        game.winner_name,
    ]


def _optional_int(value: int | None) -> int | str:
    if value is None:
        return ""
    return value


def _goals_for_report_team(
        game: MatchReplayGame,
        *,
        expected_team_name: str,
) -> int | None:
    normalized_expected = normalize_match_replay_team_name(expected_team_name)
    blue_matches = match_replay_team_names_match(
        normalize_match_replay_team_name(game.blue.name),
        normalized_expected,
    )
    orange_matches = match_replay_team_names_match(
        normalize_match_replay_team_name(game.orange.name),
        normalized_expected,
    )
    if blue_matches and not orange_matches:
        return game.blue.goals
    if orange_matches and not blue_matches:
        return game.orange.goals
    return None
