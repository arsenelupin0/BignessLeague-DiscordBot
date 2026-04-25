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

import re
from typing import Any

import unicodedata

from bigness_league_bot.core.localization import LocalizedText
from bigness_league_bot.infrastructure.google.team_sheets.errors import TeamSheetLayoutError
from bigness_league_bot.infrastructure.google.team_sheets.models import SheetCell
from bigness_league_bot.infrastructure.google.team_sheets.schema import PLACEHOLDER_CELL_VALUE

HYPERLINK_FORMULA_PATTERN = re.compile(
    r'^=HYPERLINK\("((?:[^"]|"")*)"\s*[,;]\s*"((?:[^"]|"")*)"\)$',
    re.IGNORECASE,
)
INTEGER_VALUE_PATTERN = re.compile(r"-?\d+")


def _normalize_cell_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_lookup_text(value: str) -> str:
    normalized = _normalize_cell_value(value).casefold()
    return (
        normalized.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )


def _build_sheet_grid(sheet: dict[str, Any]) -> dict[int, dict[int, SheetCell]]:
    grid: dict[int, dict[int, SheetCell]] = {}
    for data in sheet.get("data", []):
        if not isinstance(data, dict):
            continue

        start_row = int(data.get("startRow", 0))
        start_column = int(data.get("startColumn", 0))
        for row_offset, row_data in enumerate(data.get("rowData", [])):
            if not isinstance(row_data, dict):
                continue

            values = row_data.get("values", [])
            if not isinstance(values, list):
                continue

            target_row = start_row + row_offset
            row_cells = grid.setdefault(target_row, {})
            for column_offset, raw_cell in enumerate(values):
                if not isinstance(raw_cell, dict):
                    continue

                value = _normalize_cell_value(raw_cell.get("formattedValue"))
                formula = _extract_formula_value(raw_cell)
                hyperlink = _extract_hyperlink_value(raw_cell, formula)
                if not value and hyperlink is None and formula is None:
                    continue

                row_cells[start_column + column_offset] = SheetCell(
                    value=value,
                    hyperlink=hyperlink,
                    formula=formula,
                )

    return grid


def _extract_formula_value(raw_cell: dict[str, Any]) -> str | None:
    user_entered_value = raw_cell.get("userEnteredValue")
    if not isinstance(user_entered_value, dict):
        return None

    formula = _normalize_cell_value(user_entered_value.get("formulaValue"))
    return formula or None


def _extract_hyperlink_value(
        raw_cell: dict[str, Any],
        formula: str | None,
) -> str | None:
    hyperlink = _normalize_cell_value(raw_cell.get("hyperlink")) or None
    if hyperlink is not None:
        return hyperlink

    if formula is None:
        return None

    return _extract_hyperlink_from_formula(formula)


def _extract_hyperlink_from_formula(formula: str) -> str | None:
    match = HYPERLINK_FORMULA_PATTERN.match(formula.strip())
    if match is None:
        return None

    return _unescape_formula_string(match.group(1))


def _unescape_formula_string(value: str) -> str:
    return value.replace('""', '"')


def _build_player_cell_value(player_name: str, tracker_url: str) -> str:
    normalized_tracker_url = _normalize_cell_value(tracker_url)
    if not normalized_tracker_url:
        return player_name

    escaped_url = _escape_formula_string(normalized_tracker_url)
    escaped_player_name = _escape_formula_string(player_name)
    return f'=HYPERLINK("{escaped_url}";"{escaped_player_name}")'


def _escape_formula_string(value: str) -> str:
    return value.replace('"', '""')


def _parse_integer_cell_value(
        value: str,
        *,
        error_message: LocalizedText,
) -> int:
    normalized_value = _normalize_cell_value(value)
    match = INTEGER_VALUE_PATTERN.search(normalized_value)
    if match is None:
        raise TeamSheetLayoutError(error_message)

    return int(match.group(0))


def _normalize_member_lookup_text(value: str | None) -> str:
    if value is None:
        return ""

    normalized = " ".join(str(value).split()).strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]

    return unicodedata.normalize("NFKC", normalized).casefold()


def _normalize_technical_staff_role_name(value: str | None) -> str:
    normalized = _normalize_member_lookup_text(value)
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(character)
    )


def _is_placeholder_cell_value(value: str) -> bool:
    normalized = _normalize_cell_value(value)
    return not normalized or normalized == PLACEHOLDER_CELL_VALUE


def _is_placeholder_row(*values: str) -> bool:
    return all(_is_placeholder_cell_value(value) for value in values)


def _is_free_block_title(title: str) -> bool:
    return _is_placeholder_cell_value(title)
