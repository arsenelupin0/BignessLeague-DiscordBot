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

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Iterable

MATCH_REPLAY_MIN_FILES = 3
MATCH_REPLAY_MAX_FILES = 5
MATCH_REPLAY_EXTENSION = ".replay"
TEAM_NAME_IGNORED_TOKENS = frozenset(
    {
        "academy",
        "club",
        "esport",
        "esports",
        "fc",
        "gaming",
        "rl",
        "team",
    }
)
TEAM_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


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
    resolution_status: str = "unmatched"


@dataclass(frozen=True, slots=True)
class MatchReplayRosterPlayer:
    division_name: str
    team_name: str
    player_name: str
    discord_name: str
    epic_name: str
    rocket_name: str
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
        )
        for index, game in enumerate(games, start=1)
    )
    if len(ordered_games) < MATCH_REPLAY_MIN_FILES or len(ordered_games) > MATCH_REPLAY_MAX_FILES:
        raise InvalidReplayCountError()

    team_one_games = 0
    team_two_games = 0
    unresolved_winners: list[str] = []
    normalized_team_one = _normalize_team_name(team_one_name)
    normalized_team_two = _normalize_team_name(team_two_name)

    for game in ordered_games:
        winner = _normalize_team_name(game.winner_name)
        winner_matches_team_one = _team_names_match(winner, normalized_team_one)
        winner_matches_team_two = _team_names_match(winner, normalized_team_two)
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
            )
        )

    team_one_games = 0
    team_two_games = 0
    normalized_team_one = _normalize_team_name(report.team_one_name)
    normalized_team_two = _normalize_team_name(report.team_two_name)
    for game in resolved_games:
        winner = _normalize_team_name(game.winner_name)
        winner_matches_team_one = _team_names_match(winner, normalized_team_one)
        winner_matches_team_two = _team_names_match(winner, normalized_team_two)
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
    normalized_expected = _normalize_team_name(expected_team_name)
    blue_matches = _team_names_match(_normalize_team_name(game.blue.name), normalized_expected)
    orange_matches = _team_names_match(_normalize_team_name(game.orange.name), normalized_expected)
    if blue_matches and not orange_matches:
        return game.blue.goals
    if orange_matches and not blue_matches:
        return game.orange.goals
    return None


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


def _resolve_match_replay_team(
        team: MatchReplayTeam,
        roster_index: dict[str, tuple[MatchReplayRosterPlayer, str]],
) -> MatchReplayTeam:
    resolved_players: list[MatchReplayPlayer] = []
    team_match_counts: dict[str, int] = {}

    for player in team.players:
        roster_player, method = _find_roster_player_match(player, roster_index)
        if roster_player is None:
            resolved_players.append(player)
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
                resolution_status="matched",
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
        roster_index: dict[str, tuple[MatchReplayRosterPlayer, str]],
) -> tuple[MatchReplayRosterPlayer | None, str]:
    candidates = (
        ("platform_id", replay_player.platform_id),
        ("ballchasing_name", replay_player.name),
    )
    for method, value in candidates:
        normalized_value = _normalize_player_lookup(value)
        if not normalized_value:
            continue
        match = roster_index.get(normalized_value)
        if match is not None:
            return match[0], match[1] if method == "ballchasing_name" else method
    return None, ""


def _build_roster_player_index(
        roster_players: Iterable[MatchReplayRosterPlayer],
) -> dict[str, tuple[MatchReplayRosterPlayer, str]]:
    index: dict[str, tuple[MatchReplayRosterPlayer, str]] = {}
    for roster_player in roster_players:
        for method, value in (
                ("player_name", roster_player.player_name),
                ("discord_name", roster_player.discord_name),
                ("epic_name", roster_player.epic_name),
                ("rocket_name", roster_player.rocket_name),
        ):
            normalized_value = _normalize_player_lookup(value)
            if not normalized_value:
                continue
            if normalized_value in index:
                continue
            index[normalized_value] = (roster_player, method)
    return index


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
    return "".join(TEAM_TOKEN_PATTERN.findall(value.casefold()))
