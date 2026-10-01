from __future__ import annotations

from dataclasses import replace

from bigness_league_bot.application.services.team_signing import (
    TeamSigningBatch, TeamTechnicalStaffBatch, sort_team_signing_players,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.google.team_sheets.blocks import (
    _collect_team_blocks, _find_division_sheet, _resolve_target_team_block,
)
from bigness_league_bot.infrastructure.google.team_sheets.client import GoogleSheetsClient
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.models import (
    SheetCell, TeamSigningWriteResult, TeamTechnicalStaffWriteResult,
)
from bigness_league_bot.infrastructure.google.team_sheets.player_signing_mutations import (
    prepare_team_signings, write_team_updates,
)
from bigness_league_bot.infrastructure.google.team_sheets.schema import (
    PLACEHOLDER_CELL_VALUE, TEAM_BLOCK_MAX_PLAYERS, TEAM_BLOCK_PLAYERS_ROW_OFFSET,
)
from bigness_league_bot.infrastructure.google.team_sheets.staff_signing_mutations import (
    prepare_team_technical_staff_updates,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N


def register_team_sync(
        client: GoogleSheetsClient,
        config: TeamSheetLookupConfig,
        signing_batch: TeamSigningBatch,
        technical_staff_batch: TeamTechnicalStaffBatch,
) -> tuple[TeamSigningWriteResult, TeamTechnicalStaffWriteResult]:
    service = client.build_service(read_only=False)
    _, sheet_grids = client.fetch_sheet_grids(service)
    player_result, updates = prepare_team_signings(
        signing_batch, sheet_grids, require_new_team_block=True,
    )
    worksheet_title, grid = _find_division_sheet(signing_batch.division_name, sheet_grids)
    staff_title, _ = _find_division_sheet(technical_staff_batch.division_name, sheet_grids)
    if staff_title != worksheet_title or signing_batch.team_name != technical_staff_batch.team_name:
        raise CommandUserError(localize(
            I18N.errors.team_signing.import_payload_mismatch,
            player_division=signing_batch.division_name, player_team=signing_batch.team_name,
            staff_division=technical_staff_batch.division_name, staff_team=technical_staff_batch.team_name,
        ))
    block = _resolve_target_team_block(
        signing_batch.team_name, _collect_team_blocks(grid), worksheet_title=worksheet_title,
    )
    # Validate staff against the future roster without writing anything yet.
    projected_grid = {row: dict(cells) for row, cells in grid.items()}
    players = sort_team_signing_players(signing_batch.players)
    for offset in range(TEAM_BLOCK_MAX_PLAYERS):
        player = players[offset] if offset < len(players) else None
        values = (
            (player.player_name, player.discord_id, player.platform, player.platform_id, player.epic_name, player.mmr)
            if player is not None else (PLACEHOLDER_CELL_VALUE,) * 6
        )
        cells = projected_grid.setdefault(block.title_row + TEAM_BLOCK_PLAYERS_ROW_OFFSET + offset, {})
        cells.update({block.start_column + column: SheetCell(
            value=value, hyperlink=player.tracker_url if player is not None and column == 4 else None,
        ) for column, value in enumerate(values)})
    projected_grid[block.title_row][block.start_column] = SheetCell(value=signing_batch.team_name)
    updates.extend(prepare_team_technical_staff_updates(
        technical_staff_batch, worksheet_title, projected_grid,
        replace(block, title=signing_batch.team_name), reset=True,
    ))
    write_team_updates(service, config, updates)
    return player_result, TeamTechnicalStaffWriteResult(
        worksheet_title, technical_staff_batch.team_name, len(technical_staff_batch.members),
    )
