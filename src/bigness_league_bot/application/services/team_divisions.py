from __future__ import annotations

import re

import unicodedata


def division_name_parts(value: str) -> tuple[str, str | None]:
    normalized = " ".join("".join(
        character for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    ).split())
    match = re.fullmatch(r"(.+?)\s+(s\d+)", normalized)
    return (match.group(1), match.group(2)) if match else (normalized, None)


def division_names_match(left: str, right: str) -> bool:
    left_name, left_season = division_name_parts(left)
    right_name, right_season = division_name_parts(right)
    return left_name == right_name and (
            left_season is None or right_season is None or left_season == right_season
    )
