from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

import unicodedata

from bigness_league_bot.application.services.match_standings import match_grid_row_number
from bigness_league_bot.application.services.team_divisions import (
    division_name_parts, worksheet_division_name_parts,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize

TEAMS_PER_DIVISION = 8
MATCHDAYS_PER_DIVISION = TEAMS_PER_DIVISION - 1
MATCHES_PER_MATCHDAY = TEAMS_PER_DIVISION // 2


class LeagueDivision(Enum):
    GOLD = "Gold Division"
    SILVER = "Silver Division"


@dataclass(frozen=True, slots=True)
class LeagueTeam:
    worksheet_title: str
    team_name: str


@dataclass(frozen=True, slots=True)
class LeagueMatch:
    home: str
    away: str


@dataclass(frozen=True, slots=True)
class LeagueMatchday:
    number: int
    matches: tuple[LeagueMatch, ...]


@dataclass(frozen=True, slots=True)
class LeagueDivisionSchedule:
    division: LeagueDivision
    worksheet_title: str
    matchdays: tuple[LeagueMatchday, ...]


@dataclass(frozen=True, slots=True)
class LeagueFixtureRow:
    row_number: int
    home: str
    away: str


@dataclass(frozen=True, slots=True)
class LeagueSeedingsDestination:
    division: LeagueDivision
    worksheet_title: str
    worksheet_url: str
    ranges: tuple[str, ...]


def league_fixture_rows(schedule: LeagueDivisionSchedule) -> tuple[LeagueFixtureRow, ...]:
    """Use the same matchday/match coordinates as replay result uploads."""
    return tuple(LeagueFixtureRow(
        match_grid_row_number(matchday=day.number, match_number=number), match.home, match.away,
    ) for day in schedule.matchdays for number, match in enumerate(day.matches, 1))


def generate_league_seedings(
        teams: Iterable[LeagueTeam], *, rng: random.Random | None = None,
) -> tuple[LeagueDivisionSchedule, ...]:
    """Draw independent, single round robins after validating both divisions.

    Names are preserved for spreadsheet export. Only the normalized comparison
    is used to recognize divisions and detect duplicate teams.
    """
    teams = tuple(teams)
    division_teams = tuple(_division_teams(teams, division) for division in LeagueDivision)
    seasons = {worksheet_division_name_parts(title)[1] for title, _ in division_teams}
    if len(seasons - {None}) > 1:
        raise CommandUserError(localize("errors.league_seedings.season_mismatch"))

    randomizer = rng if rng is not None else random.SystemRandom()
    return tuple(
        _draw_division(division, title, names, randomizer)
        for division, (title, names) in zip(LeagueDivision, division_teams)
    )


def _division_teams(
        teams: tuple[LeagueTeam, ...], division: LeagueDivision,
) -> tuple[str, tuple[str, ...]]:
    expected_name = division_name_parts(division.value)[0]
    selected = tuple(team for team in teams
                     if worksheet_division_name_parts(team.worksheet_title)[0] == expected_name)
    titles = {team.worksheet_title for team in selected}
    if len(titles) > 1:
        raise CommandUserError(localize(
            "errors.league_seedings.ambiguous_division", division=division.value,
        ))

    seen: set[str] = set()
    for team in selected:
        name = team.team_name
        if not name.strip() or any(unicodedata.category(c) == "Cc" or c in "\u2028\u2029" for c in name):
            raise CommandUserError(localize(
                "errors.league_seedings.invalid_team_name", division=division.value,
            ))
        normalized = " ".join(unicodedata.normalize("NFKC", name).casefold().split())
        if normalized in seen:
            raise CommandUserError(localize(
                "errors.league_seedings.duplicate_team", division=division.value,
            ))
        seen.add(normalized)

    if len(selected) != TEAMS_PER_DIVISION:
        raise CommandUserError(localize(
            "errors.league_seedings.team_count", division=division.value,
            expected=TEAMS_PER_DIVISION, actual=len(selected),
        ))
    return selected[0].worksheet_title, tuple(team.team_name for team in selected)


def _draw_division(
        division: LeagueDivision, worksheet_title: str, names: tuple[str, ...], rng: random.Random,
) -> LeagueDivisionSchedule:
    shuffled_names = list(names)
    rng.shuffle(shuffled_names)
    rotation = list(range(TEAMS_PER_DIVISION))
    rounds: list[tuple[LeagueMatch, ...]] = []
    for _ in range(MATCHDAYS_PER_DIVISION):
        matches: list[LeagueMatch] = []
        for index in range(MATCHES_PER_MATCHDAY):
            left, right = rotation[index], rotation[-index - 1]
            # Orient the cyclic edges so each team hosts three matches, plus
            # at most its opposite team: exactly three or four home matches.
            distance = (right - left) % TEAMS_PER_DIVISION
            left_hosts = distance < MATCHES_PER_MATCHDAY or (
                    distance == MATCHES_PER_MATCHDAY and left < right
            )
            home, away = (left, right) if left_hosts else (right, left)
            matches.append(LeagueMatch(shuffled_names[home], shuffled_names[away]))
        rng.shuffle(matches)
        rounds.append(tuple(matches))
        # Circle method: keep one team fixed and rotate the other seven.
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    rng.shuffle(rounds)
    return LeagueDivisionSchedule(
        division, worksheet_title,
        tuple(LeagueMatchday(number, matches) for number, matches in enumerate(rounds, 1)),
    )
