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

import logging
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
LOGGER = logging.getLogger("bigness_league_bot.activity")


def _normalize_cell_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_lookup_text(value: str) -> str:
    normalized = _normalize_cell_value(value).casefold()
    without_marks = "".join(
        character
        for character in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.split())


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

    if formula is not None:
        return _extract_hyperlink_from_formula(formula)

    # Sheets leaves `hyperlink` empty for some rich-text cells. Preserve a
    # single unambiguous destination, including links on part of the title.
    inherited_link = None
    for field in ("effectiveFormat", "userEnteredFormat"):
        cell_format = raw_cell.get(field)
        if isinstance(cell_format, dict):
            if link := _extract_text_format_link(cell_format.get("textFormat")):
                inherited_link = link
                break
    links = _extract_rich_text_links(raw_cell, inherited_link)
    if len(links) == 1:
        return next(iter(links))
    if len(links) > 1:
        LOGGER.warning("SHEET_CELL_HYPERLINK_AMBIGUOUS value=%s destinations=%s",
                       raw_cell.get("formattedValue", ""), len(links))
    return None


def _extract_rich_text_links(raw_cell: dict[str, Any], inherited_link: str | None) -> set[str]:
    raw_runs = raw_cell.get("textFormatRuns", [])
    if not isinstance(raw_runs, list):
        raw_runs = []
    runs = sorted((run for run in raw_runs if isinstance(run, dict)
                   and isinstance(run.get("startIndex"), int) and run["startIndex"] >= 0),
                  key=lambda run: run["startIndex"])
    # API indices count UTF-16 code units, rather than Python characters.
    text_length = len(str(raw_cell.get("formattedValue", "")).encode("utf-16-le")) // 2
    links: set[str] = set()
    cursor = 0
    active_link = inherited_link
    for run in runs:
        index = min(run["startIndex"], text_length)
        if index > cursor and active_link:
            links.add(active_link)
        text_format = run.get("format")
        active_link = (_extract_text_format_link(text_format)
                       if isinstance(text_format, dict) and "link" in text_format else inherited_link)
        cursor = index
    if cursor < text_length and active_link:
        links.add(active_link)
    return links


def _extract_text_format_link(text_format: Any) -> str | None:
    if not isinstance(text_format, dict):
        return None
    link = text_format.get("link")
    if not isinstance(link, dict):
        return None
    uri = link.get("uri")
    if isinstance(uri, str):
        return uri.strip() or None
    return None


def _extract_hyperlink_from_formula(formula: str) -> str | None:
    match = HYPERLINK_FORMULA_PATTERN.match(formula.strip())
    if match is None:
        return None

    return _unescape_formula_string(match.group(1))


def _unescape_formula_string(value: str) -> str:
    return value.replace('""', '"')


def _build_player_cell_value(player_name: str) -> str:
    return player_name


def _build_hyperlink_cell_value(label: str, url: str | None) -> str:
    normalized_url = _normalize_cell_value(url)
    if not normalized_url:
        return label

    escaped_url = _escape_formula_string(normalized_url)
    escaped_label = _escape_formula_string(label)
    return f'=HYPERLINK("{escaped_url}";"{escaped_label}")'


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


def is_free_block_title(title: str) -> bool:
    return _is_free_block_title(title)
