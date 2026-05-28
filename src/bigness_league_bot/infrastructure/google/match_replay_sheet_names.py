from __future__ import annotations

from bigness_league_bot.application.services.match_replays import MatchReplayDivision


def parse_worksheet_names(raw_value: str) -> tuple[str, ...]:
    names = tuple(
        candidate
        for candidate in (value.strip() for value in raw_value.split(","))
        if candidate
    )
    return names or ("REPLAY STATS",)


def resolve_worksheet_name_for_division(
        worksheet_names: tuple[str, ...],
        *,
        division: MatchReplayDivision,
) -> str:
    if len(worksheet_names) == 1:
        return worksheet_names[0]

    division_name = division.name.casefold()
    division_value = division.value.casefold()
    for worksheet_name in worksheet_names:
        normalized_name = worksheet_name.casefold()
        if division_name in normalized_name or division_value in normalized_name:
            return worksheet_name

    return worksheet_names[0]
