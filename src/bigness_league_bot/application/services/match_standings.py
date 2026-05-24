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

from dataclasses import dataclass
from typing import Iterable

NULL_MATCH_SCORE = "nulo"
MATCH_SCORE_SUFFIXES = ("fw", "wo")
MATCH_STANDINGS_RANGE = "A3:I11"
MATCH_STANDINGS_TEAM_COUNT = 8
MATCH_STANDINGS_ROW_COUNT = MATCH_STANDINGS_TEAM_COUNT + 1
MATCH_GRID_RANGE = "A20:U47"
MATCH_GRID_START_ROW = 20
MATCH_GRID_MATCHDAYS = 7
MATCH_GRID_MATCHES_PER_MATCHDAY = 4
MATCH_GRID_MAX_GAMES = 5
MATCH_GRID_GAME_WIDTH = 4
MATCH_GRID_FIRST_GAME_COLUMN_INDEX = 1


@dataclass(frozen=True, slots=True)
class MatchStandingGameResult:
    matchday: int
    match_number: int
    team_one_name: str
    team_two_name: str
    team_one_goals: int
    team_two_goals: int
    is_null: bool = False


@dataclass(frozen=True, slots=True)
class MatchGridGameScore:
    game_number: int
    team_one_goals: int
    team_two_goals: int


@dataclass(frozen=True, slots=True)
class MatchStandingRow:
    position: str
    team_name: str
    points: int
    series_played: int
    series_won: int
    games_won: int
    games_lost: int
    goals_for: int
    goals_against: int

    @property
    def game_diff(self) -> int:
        return self.games_won - self.games_lost

    @property
    def goal_diff(self) -> int:
        return self.goals_for - self.goals_against

    @property
    def games_summary(self) -> str:
        diff = self.game_diff
        if diff > 0:
            diff_text = f"+{diff}"
        else:
            diff_text = str(diff)
        return f"{self.games_won} - {self.games_lost} ({diff_text})"


@dataclass(slots=True)
class _MutableStanding:
    team_name: str
    points: int = 0
    series_played: int = 0
    series_won: int = 0
    games_won: int = 0
    games_lost: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def game_diff(self) -> int:
        return self.games_won - self.games_lost

    @property
    def goal_diff(self) -> int:
        return self.goals_for - self.goals_against


@dataclass(slots=True)
class _SeriesAccumulator:
    team_one_name: str
    team_two_name: str
    games: list[MatchStandingGameResult]
    team_one_games: int = 0
    team_two_games: int = 0
    has_null_result: bool = False


def match_standings_headers() -> list[str]:
    return [
        "Pos",
        "Equipo",
        "Pts",
        "S.J.",
        "S.G.",
        "Games (Dif)",
        "GF",
        "GC",
        "DG",
    ]


def build_match_standings_rows(
        team_names: Iterable[str],
        games: Iterable[MatchStandingGameResult],
) -> list[MatchStandingRow]:
    standings = {
        _normalize_team_name(team_name): _MutableStanding(team_name=team_name.strip())
        for team_name in team_names
        if team_name.strip()
    }
    official_team_keys = frozenset(standings)
    series_by_key: dict[tuple[int, int, str, str], _SeriesAccumulator] = {}

    for game in games:
        team_one_key = _normalize_team_name(game.team_one_name)
        team_two_key = _normalize_team_name(game.team_two_name)
        if not team_one_key or not team_two_key or team_one_key == team_two_key:
            continue
        if official_team_keys and (
                team_one_key not in official_team_keys
                or team_two_key not in official_team_keys
        ):
            continue

        standings.setdefault(
            team_one_key,
            _MutableStanding(team_name=game.team_one_name.strip()),
        )
        standings.setdefault(
            team_two_key,
            _MutableStanding(team_name=game.team_two_name.strip()),
        )

        series_key = (
            game.matchday,
            game.match_number,
            team_one_key,
            team_two_key,
        )
        series = series_by_key.setdefault(
            series_key,
            _SeriesAccumulator(
                team_one_name=game.team_one_name.strip(),
                team_two_name=game.team_two_name.strip(),
                games=[],
            ),
        )
        if game.is_null:
            series.has_null_result = True
            continue

        if game.team_one_goals > game.team_two_goals:
            game_winner = "team_one"
        elif game.team_two_goals > game.team_one_goals:
            game_winner = "team_two"
        else:
            game_winner = ""

        series.games.append(game)
        if game_winner == "team_one":
            series.team_one_games += 1
        elif game_winner == "team_two":
            series.team_two_games += 1

    for series in series_by_key.values():
        team_one_key = _normalize_team_name(series.team_one_name)
        team_two_key = _normalize_team_name(series.team_two_name)
        if series.has_null_result:
            standings[team_one_key].series_played += 1
            standings[team_two_key].series_played += 1
            continue

        if max(series.team_one_games, series.team_two_games) < 3:
            continue

        if series.team_one_games == series.team_two_games:
            continue

        team_one = standings[team_one_key]
        team_two = standings[team_two_key]
        for game in series.games:
            team_one.goals_for += game.team_one_goals
            team_one.goals_against += game.team_two_goals
            team_two.goals_for += game.team_two_goals
            team_two.goals_against += game.team_one_goals

            if game.team_one_goals > game.team_two_goals:
                team_one.games_won += 1
                team_two.games_lost += 1
            elif game.team_two_goals > game.team_one_goals:
                team_two.games_won += 1
                team_one.games_lost += 1

        team_one.series_played += 1
        team_two.series_played += 1
        if series.team_one_games > series.team_two_games:
            team_one.series_won += 1
            team_one.points += 3
        else:
            team_two.series_won += 1
            team_two.points += 3

    ordered_rows = sorted(
        standings.values(),
        key=lambda row: (
            -row.points,
            -row.series_won,
            -row.game_diff,
            -row.goal_diff,
            -row.goals_for,
            row.team_name.casefold(),
        ),
    )
    return [
        MatchStandingRow(
            position=f"{index}º",
            team_name=row.team_name,
            points=row.points,
            series_played=row.series_played,
            series_won=row.series_won,
            games_won=row.games_won,
            games_lost=row.games_lost,
            goals_for=row.goals_for,
            goals_against=row.goals_against,
        )
        for index, row in enumerate(ordered_rows, start=1)
    ]


def match_standings_sheet_rows(rows: Iterable[MatchStandingRow]) -> list[list[object]]:
    return [
        [
            row.position,
            row.team_name,
            row.points,
            row.series_played,
            row.series_won,
            row.games_summary,
            row.goals_for,
            row.goals_against,
            row.goal_diff,
        ]
        for row in rows
    ]


def match_grid_row_number(*, matchday: int, match_number: int) -> int:
    if matchday < 1 or matchday > MATCH_GRID_MATCHDAYS:
        raise ValueError("matchday fuera del rango soportado por la tabla.")
    if match_number < 1 or match_number > MATCH_GRID_MATCHES_PER_MATCHDAY:
        raise ValueError("match_number fuera del rango soportado por la tabla.")
    return MATCH_GRID_START_ROW + ((matchday - 1) * MATCH_GRID_MATCHES_PER_MATCHDAY) + (match_number - 1)


def build_match_grid_row_values(
        *,
        team_one_name: str,
        team_two_name: str,
        game_scores: Iterable[MatchGridGameScore],
) -> list[object]:
    scores_by_game = {
        score.game_number: score
        for score in game_scores
        if 1 <= score.game_number <= MATCH_GRID_MAX_GAMES
    }
    values: list[object] = []
    for game_number in range(1, MATCH_GRID_MAX_GAMES + 1):
        score = scores_by_game.get(game_number)
        if score is None:
            values.extend(["", "", "", ""])
            continue

        values.extend(
            [
                team_one_name,
                f"{score.team_one_goals} - {score.team_two_goals}",
                team_two_name,
                "",
            ]
        )
    return values


def build_match_grid_standing_games(
        rows: Iterable[Iterable[object]],
) -> tuple[MatchStandingGameResult, ...]:
    games: list[MatchStandingGameResult] = []
    for row_index, row_values in enumerate(rows):
        row = tuple(_string_cell(value) for value in row_values)
        matchday = (row_index // MATCH_GRID_MATCHES_PER_MATCHDAY) + 1
        match_number = (row_index % MATCH_GRID_MATCHES_PER_MATCHDAY) + 1
        if matchday > MATCH_GRID_MATCHDAYS:
            break

        for game_index in range(MATCH_GRID_MAX_GAMES):
            base_index = MATCH_GRID_FIRST_GAME_COLUMN_INDEX + (game_index * MATCH_GRID_GAME_WIDTH)
            team_one_name = _cell_at(row, base_index)
            score_cell = _cell_at(row, base_index + 1)
            score = _parse_score(score_cell)
            team_two_name = _cell_at(row, base_index + 2)
            if not team_one_name or not team_two_name:
                continue
            if score is None and not _is_null_score(score_cell):
                continue

            games.append(
                MatchStandingGameResult(
                    matchday=matchday,
                    match_number=match_number,
                    team_one_name=team_one_name,
                    team_two_name=team_two_name,
                    team_one_goals=score[0] if score is not None else 0,
                    team_two_goals=score[1] if score is not None else 0,
                    is_null=score is None,
                )
            )
    return tuple(games)


def _normalize_team_name(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _cell_at(row: tuple[str, ...], index: int) -> str:
    if index >= len(row):
        return ""
    return row[index]


def _string_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int | float | bool):
        return str(value).strip()
    return ""


def _parse_score(value: str) -> tuple[int, int] | None:
    score_text = _strip_score_suffix(value)
    parts = score_text.split("-", maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return None


def _strip_score_suffix(value: str) -> str:
    score_text = value.strip()
    normalized_suffixes = tuple(f"({suffix})" for suffix in MATCH_SCORE_SUFFIXES)
    normalized_score_text = "".join(score_text.casefold().split())
    for suffix in normalized_suffixes:
        if normalized_score_text.endswith(suffix):
            return score_text[: -len(suffix)].strip()
    return score_text


def _is_null_score(value: str) -> bool:
    return " ".join(value.casefold().strip().split()) == NULL_MATCH_SCORE
