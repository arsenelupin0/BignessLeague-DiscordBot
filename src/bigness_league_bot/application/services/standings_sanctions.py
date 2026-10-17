from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable

import unicodedata

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize


def sanction_error(code: str, **params: object) -> CommandUserError:
    return CommandUserError(localize(f"sanctions.errors.{code}", **params))


def team_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def unmarked_team_name(value: str) -> str:
    return re.sub(r"\s*\(AI\)\s*$", "", value, flags=re.IGNORECASE).strip()


@dataclass(frozen=True, slots=True)
class SanctionScope:
    worksheet: str
    season: str
    division: str

    @classmethod
    def from_worksheet(cls, worksheet: str) -> SanctionScope:
        seasons = re.findall(r"\bS\d+\b", worksheet, re.IGNORECASE)
        divisions = re.findall(r"\b(GOLD|SILVER)\b", worksheet, re.IGNORECASE)
        if len(seasons) != 1 or len(divisions) != 1:
            raise sanction_error("scope", sheet_name=worksheet)
        return cls(worksheet, seasons[0].upper(), divisions[0].upper())


@dataclass(frozen=True, slots=True)
class StandingsSanction:
    identifier: str
    worksheet: str
    season: str
    division: str
    team_name: str
    points: int
    reason: str
    kind: str
    matchday: int | None
    match_number: int | None
    state: str
    created_at: str
    created_by: str
    annulled_at: str = ""
    annulled_by: str = ""
    annulment_reason: str = ""

    @property
    def active(self) -> bool:
        return self.state == "ACTIVA"

    def belongs_to(self, scope: SanctionScope) -> bool:
        return team_key(self.worksheet) == team_key(scope.worksheet)


def validate_sanction(sanction: StandingsSanction) -> None:
    scope = SanctionScope.from_worksheet(sanction.worksheet)
    if (sanction.season, sanction.division) != (scope.season, scope.division):
        raise sanction_error("scope", sheet_name=sanction.worksheet)
    if (not sanction.identifier.strip() or not sanction.team_name.strip() or not sanction.reason.strip()
            or len(sanction.reason) > 500 or type(sanction.points) is not int or sanction.points < 1
            or sanction.kind not in ("AI", "OTRA") or sanction.state not in ("ACTIVA", "ANULADA")
            or not sanction.created_at.strip() or not sanction.created_by.strip()):
        raise sanction_error("invalid_record", identifier=sanction.identifier)
    if (sanction.matchday is None) != (sanction.match_number is None):
        raise sanction_error("match_required")
    if sanction.kind == "AI" and sanction.matchday is None:
        raise sanction_error("match_required")
    if sanction.matchday is not None and (
            type(sanction.matchday) is not int or not 1 <= sanction.matchday <= 7
            or type(sanction.match_number) is not int or not 1 <= sanction.match_number <= 4):
        raise sanction_error("match_required")
    if not sanction.active and not all((sanction.annulled_at, sanction.annulled_by, sanction.annulment_reason)):
        raise sanction_error("invalid_record", identifier=sanction.identifier)


def active_sanctions(
        sanctions: Iterable[StandingsSanction], scope: SanctionScope,
) -> tuple[StandingsSanction, ...]:
    return tuple(s for s in sanctions if s.active and s.belongs_to(scope))


def scope_team_names(scope: SanctionScope, rosters: Iterable[tuple[str, str]]) -> tuple[str, ...]:
    """Select the configured season and environment without falling back to older rosters."""
    selected: list[tuple[str, str]] = []
    suffix = re.search(r"\b(TEST|DEV|DEVELOPMENT)$", scope.worksheet, re.IGNORECASE)
    environment = suffix[0].upper() if suffix else ""
    for title, name in rosters:
        roster_scope = SanctionScope.from_worksheet(title)
        roster_suffix = re.search(r"\b(TEST|DEV|DEVELOPMENT)$", title, re.IGNORECASE)
        roster_environment = roster_suffix[0].upper() if roster_suffix else ""
        if ((roster_scope.season, roster_scope.division, roster_environment)
                == (scope.season, scope.division, environment)):
            selected.append((title, name))
    names = tuple(name for _, name in selected)
    if (not names or len({title for title, _ in selected}) != 1
            or any(not name.strip() for name in names) or len({team_key(name) for name in names}) != len(names)):
        raise sanction_error("scope", sheet_name=scope.worksheet)
    return names


def sanction_deductions(
        sanctions: Iterable[StandingsSanction], scope: SanctionScope, team_names: Iterable[str],
) -> dict[str, int]:
    names = {team_key(name): name for name in team_names}
    deductions: dict[str, int] = {}
    for sanction in active_sanctions(sanctions, scope):
        key = team_key(sanction.team_name)
        if key not in names:
            raise sanction_error("unknown_team", team=sanction.team_name)
        name = names[key]
        deductions[name] = deductions.get(name, 0) + sanction.points
    return deductions


def add_sanction(
        sanctions: tuple[StandingsSanction, ...], sanction: StandingsSanction,
) -> tuple[StandingsSanction, ...]:
    validate_sanction(sanction)
    for existing in sanctions:
        if existing.identifier == sanction.identifier:
            if existing == sanction:
                return sanctions
            raise sanction_error("duplicate", identifier=sanction.identifier)
        if (sanction.active and existing.active and existing.belongs_to(
                SanctionScope.from_worksheet(sanction.worksheet))
                and team_key(existing.team_name) == team_key(sanction.team_name)
                and existing.kind == sanction.kind == "AI"
                and (existing.matchday, existing.match_number) == (sanction.matchday, sanction.match_number)):
            raise sanction_error("duplicate", identifier=existing.identifier)
    return (*sanctions, sanction)


def annul_sanction(
        sanctions: tuple[StandingsSanction, ...], identifier: str, *,
        at: str, by: str, reason: str,
) -> tuple[StandingsSanction, ...]:
    if not reason.strip() or len(reason) > 500:
        raise sanction_error("reason")
    for index, sanction in enumerate(sanctions):
        if sanction.identifier != identifier:
            continue
        if not sanction.active:
            raise sanction_error("already_annulled", identifier=identifier)
        annulled = replace(sanction, state="ANULADA", annulled_at=at, annulled_by=by,
                           annulment_reason=reason.strip())
        validate_sanction(annulled)
        return (*sanctions[:index], annulled, *sanctions[index + 1:])
    raise sanction_error("not_found", identifier=identifier)


def sanction_marker_updates(
        grid: list[list[object]], sanctions: Iterable[StandingsSanction], scope: SanctionScope,
) -> tuple[tuple[int, int, str], ...]:
    """Annotate team cells only; scores (including FW/WO/NULO) retain their meaning."""
    targets: set[tuple[int, str]] = set()
    for sanction in active_sanctions(sanctions, scope):
        if sanction.matchday is None:
            continue
        row_index = (sanction.matchday - 1) * 4 + sanction.match_number - 1
        row = grid[row_index] if row_index < len(grid) else []
        names = [unmarked_team_name(str(row[column])) for column in (1, 3) if column < len(row)]
        if team_key(sanction.team_name) not in {team_key(name) for name in names}:
            raise sanction_error("match_team", team=sanction.team_name,
                                 matchday=sanction.matchday, match_number=sanction.match_number)
        if sanction.kind == "AI":
            targets.add((row_index, team_key(sanction.team_name)))
    updates: list[tuple[int, int, str]] = []
    for row_index, row in enumerate(grid[:28]):
        for game_index in range(5):
            for column in (1 + game_index * 4, 3 + game_index * 4):
                if column >= len(row) or not isinstance(row[column], str):
                    continue
                old = row[column]
                name = unmarked_team_name(old)
                new = f"{name} (AI)" if game_index == 0 and (row_index, team_key(name)) in targets else name
                if new != old:
                    updates.append((row_index + 20, column, new))
    return tuple(updates)
