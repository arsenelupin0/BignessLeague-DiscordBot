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

from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.google.team_sheets.cells import (
    _is_free_block_title,
    _normalize_lookup_text,
)
from bigness_league_bot.infrastructure.google.team_sheets.errors import (
    TeamSheetDivisionNotFoundError,
    TeamSheetNoFreeBlockError,
)
from bigness_league_bot.infrastructure.google.team_sheets.models import SheetCell, TeamBlockAnchor
from bigness_league_bot.infrastructure.google.team_sheets.schema import (
    TEAM_BLOCK_COLUMN_COUNT,
    TEAM_BLOCK_HEADER_ROW_OFFSET,
    TEAM_BLOCK_HEADERS_NORMALIZED,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N


def _find_team_block(
        role_name: str,
        cell_grid: dict[int, dict[int, SheetCell]],
) -> TeamBlockAnchor | None:
    normalized_role_name = role_name.casefold()
    for row_index, _row_cells in sorted(cell_grid.items()):
        header_row = cell_grid.get(row_index + TEAM_BLOCK_HEADER_ROW_OFFSET)
        if not header_row:
            continue

        candidate_columns = sorted(header_row)
        for start_column in candidate_columns:
            header_values = tuple(
                _get_cell_value(
                    cell_grid,
                    row_index + TEAM_BLOCK_HEADER_ROW_OFFSET,
                    start_column + offset,
                )
                .casefold()
                for offset in range(TEAM_BLOCK_COLUMN_COUNT)
            )
            if header_values != TEAM_BLOCK_HEADERS_NORMALIZED:
                continue

            title = _extract_block_title(
                cell_grid,
                row_index,
                start_column,
            )
            if title.casefold() != normalized_role_name:
                continue

            return TeamBlockAnchor(
                title_row=row_index,
                start_column=start_column,
                title=title,
            )

    return None


def _collect_team_blocks(
        cell_grid: dict[int, dict[int, SheetCell]],
) -> tuple[TeamBlockAnchor, ...]:
    blocks: list[TeamBlockAnchor] = []
    for row_index, row_cells in sorted(cell_grid.items()):
        header_row = cell_grid.get(row_index + TEAM_BLOCK_HEADER_ROW_OFFSET)
        if not header_row:
            continue

        for start_column in sorted(header_row):
            header_values = tuple(
                _get_cell_value(
                    cell_grid,
                    row_index + TEAM_BLOCK_HEADER_ROW_OFFSET,
                    start_column + offset,
                )
                .casefold()
                for offset in range(TEAM_BLOCK_COLUMN_COUNT)
            )
            if header_values != TEAM_BLOCK_HEADERS_NORMALIZED:
                continue

            blocks.append(
                TeamBlockAnchor(
                    title_row=row_index,
                    start_column=start_column,
                    title=_extract_block_title(
                        cell_grid,
                        row_index,
                        start_column,
                    ),
                )
            )

    return tuple(blocks)


def _find_division_sheet(
        division_name: str,
        sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
) -> tuple[str, dict[int, dict[int, SheetCell]]]:
    normalized_division = _normalize_lookup_text(division_name)
    for worksheet_title, cell_grid in sheet_grids:
        if normalized_division in _division_lookup_aliases(worksheet_title):
            return worksheet_title, cell_grid

    raise TeamSheetDivisionNotFoundError(
        localize(
            I18N.errors.team_signing.division_not_found,
            division_name=division_name,
        )
    )


def _division_lookup_aliases(worksheet_title: str) -> frozenset[str]:
    normalized_title = _normalize_lookup_text(worksheet_title)
    aliases = {normalized_title}
    for suffix in (" test", " dev", " development"):
        if normalized_title.endswith(suffix):
            aliases.add(normalized_title.removesuffix(suffix).strip())

    return frozenset(alias for alias in aliases if alias)


def _resolve_target_team_block(
        team_name: str,
        team_blocks: tuple[TeamBlockAnchor, ...],
        *,
        worksheet_title: str,
) -> TeamBlockAnchor:
    normalized_team_name = _normalize_lookup_text(team_name)
    for block in team_blocks:
        if _normalize_lookup_text(block.title) == normalized_team_name:
            return block

    for block in team_blocks:
        if _is_free_block_title(block.title):
            return block

    raise TeamSheetNoFreeBlockError(
        localize(
            I18N.errors.team_signing.no_free_team_block,
            team_name=team_name,
            sheet_name=worksheet_title,
        )
    )


def _extract_block_title(
        cell_grid: dict[int, dict[int, SheetCell]],
        row_index: int,
        start_column: int,
) -> str:
    return _extract_block_title_cell(
        cell_grid,
        row_index,
        start_column,
    ).value


def _extract_block_title_cell(
        cell_grid: dict[int, dict[int, SheetCell]],
        row_index: int,
        start_column: int,
) -> SheetCell:
    title_row = cell_grid.get(row_index, {})
    for column in range(start_column, start_column + TEAM_BLOCK_COLUMN_COUNT):
        cell = title_row.get(column, SheetCell())
        if cell.value:
            return cell

    return SheetCell()


def _get_cell(
        cell_grid: dict[int, dict[int, SheetCell]],
        row_index: int,
        column_index: int,
) -> SheetCell:
    return cell_grid.get(row_index, {}).get(column_index, SheetCell())


def _get_cell_value(
        cell_grid: dict[int, dict[int, SheetCell]],
        row_index: int,
        column_index: int,
) -> str:
    return _get_cell(
        cell_grid,
        row_index,
        column_index,
    ).value
