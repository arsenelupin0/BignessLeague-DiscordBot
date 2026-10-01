from __future__ import annotations

from typing import Any

from bigness_league_bot.application.services.team_signing import (
    TeamTechnicalStaffBatch, TeamTechnicalStaffMember,
)
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.google.team_sheets.blocks import (
    _find_division_sheet, _collect_team_blocks, _resolve_target_team_block,
)
from bigness_league_bot.infrastructure.google.team_sheets.cells import (
    _is_free_block_title, _normalize_technical_staff_role_name,
)
from bigness_league_bot.infrastructure.google.team_sheets.client import GoogleSheetsClient
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.errors import (
    TeamSheetLayoutError, TeamSheetTechnicalStaffRoleNotFoundError,
)
from bigness_league_bot.infrastructure.google.team_sheets.models import (
    SheetCell, TeamBlockAnchor, TeamTechnicalStaffWriteResult,
)
from bigness_league_bot.infrastructure.google.team_sheets.parser import (
    _collect_technical_staff_rows, _collect_players_by_discord,
    _resolve_technical_staff_column_offsets, _resolve_technical_staff_values,
)
from bigness_league_bot.infrastructure.google.team_sheets.player_signing_mutations import write_team_updates
from bigness_league_bot.infrastructure.google.team_sheets.ranges import _build_a1_range
from bigness_league_bot.infrastructure.google.team_sheets.schema import PLACEHOLDER_CELL_VALUE
from bigness_league_bot.infrastructure.i18n.keys import I18N


def register_team_technical_staff_sync(
        client: GoogleSheetsClient, config: TeamSheetLookupConfig,
        technical_staff_batch: TeamTechnicalStaffBatch,
) -> TeamTechnicalStaffWriteResult:
    service = client.build_service(read_only=False)
    _, sheet_grids = client.fetch_sheet_grids(service)
    worksheet_title, cell_grid = _find_division_sheet(technical_staff_batch.division_name, sheet_grids)
    team_blocks = _collect_team_blocks(cell_grid)
    if not team_blocks:
        raise TeamSheetLayoutError(localize(
            I18N.errors.team_signing.team_sheet_layout_invalid, sheet_name=worksheet_title,
        ))
    target_block = _resolve_target_team_block(
        technical_staff_batch.team_name, team_blocks, worksheet_title=worksheet_title,
    )
    updates = prepare_team_technical_staff_updates(
        technical_staff_batch, worksheet_title, cell_grid, target_block,
    )
    write_team_updates(service, config, updates)
    return TeamTechnicalStaffWriteResult(
        worksheet_title, technical_staff_batch.team_name, len(technical_staff_batch.members),
    )


def prepare_team_technical_staff_updates(
        technical_staff_batch: TeamTechnicalStaffBatch,
        worksheet_title: str,
        cell_grid: dict[int, dict[int, SheetCell]],
        target_block: TeamBlockAnchor,
        *, reset: bool = False,
) -> list[dict[str, Any]]:
    update_data: list[dict[str, Any]] = []
    if _is_free_block_title(target_block.title):
        update_data.append(
            {
                "range": _build_a1_range(
                    worksheet_title,
                    target_block.title_row,
                    target_block.start_column,
                    1,
                    1,
                ),
                "values": [[technical_staff_batch.team_name]],
            }
        )

    technical_staff_rows = _collect_technical_staff_rows(
        cell_grid,
        target_block,
        worksheet_name=worksheet_title,
    )
    players_by_discord = _collect_players_by_discord(
        cell_grid,
        target_block,
    )
    _, player_offset, discord_offset, epic_offset = _resolve_technical_staff_column_offsets(
        cell_grid,
        target_block,
    )
    if reset:
        for row in technical_staff_rows.values():
            update_data.extend(_build_technical_staff_value_updates(
                worksheet_title, row, target_block.start_column,
                tuple((offset, PLACEHOLDER_CELL_VALUE) for offset in (player_offset, discord_offset, epic_offset)),
            ))
    for member in technical_staff_batch.members:
        target_row = technical_staff_rows.get(
            _normalize_technical_staff_role_name(member.role_name)
        )
        if target_row is None:
            raise TeamSheetTechnicalStaffRoleNotFoundError(
                localize(
                    I18N.errors.team_signing.technical_staff_role_not_found,
                    team_name=technical_staff_batch.team_name,
                    role_name=member.role_name,
                    sheet_name=worksheet_title,
                )
            )

        if _is_technical_staff_clear_request(member):
            player_name = PLACEHOLDER_CELL_VALUE
            discord_id = PLACEHOLDER_CELL_VALUE
            epic_name = PLACEHOLDER_CELL_VALUE
        else:
            player_name, discord_id, epic_name = _resolve_technical_staff_values(
                member,
                players_by_discord,
                team_name=technical_staff_batch.team_name,
                worksheet_name=worksheet_title,
            )
        update_data.extend(
            _build_technical_staff_value_updates(
                worksheet_title,
                target_row,
                target_block.start_column,
                (
                    (player_offset, player_name),
                    (discord_offset, discord_id),
                    (epic_offset, epic_name),
                ),
            )
        )

    # A reset and a supplied staff entry can address the same cell. Submit its
    # final value once, so the batch contains no overlapping staff updates.
    return list({update["range"]: update for update in update_data}.values())


def _is_technical_staff_clear_request(member: TeamTechnicalStaffMember) -> bool:
    return (
            not member.player_name.strip()
            and not member.discord_id.strip()
            and not member.epic_name.strip()
    )


def _build_technical_staff_value_updates(
        worksheet_title: str,
        row_index: int,
        start_column: int,
        values_by_offset: tuple[tuple[int, str], ...],
) -> list[dict[str, Any]]:
    return [
        {
            "range": _build_a1_range(
                worksheet_title,
                row_index,
                start_column + offset,
                1,
                1,
            ),
            "values": [[value]],
        }
        for offset, value in values_by_offset
    ]
