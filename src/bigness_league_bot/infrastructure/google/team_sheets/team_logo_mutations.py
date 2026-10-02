from __future__ import annotations

from bigness_league_bot.application.services.team_logo import normalize_team_logo_url
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.google.team_sheets.blocks import _find_division_sheet, _find_team_block
from bigness_league_bot.infrastructure.google.team_sheets.cells import _build_hyperlink_cell_value
from bigness_league_bot.infrastructure.google.team_sheets.client import GoogleSheetsClient
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.errors import TeamSheetRowNotFoundError
from bigness_league_bot.infrastructure.google.team_sheets.models import TeamRoleSheetMetadata
from bigness_league_bot.infrastructure.google.team_sheets.player_signing_mutations import write_team_updates
from bigness_league_bot.infrastructure.google.team_sheets.ranges import _build_a1_range
from bigness_league_bot.infrastructure.google.team_sheets.schema import TEAM_BLOCK_COLUMN_COUNT
from bigness_league_bot.infrastructure.i18n.keys import I18N


def update_team_logo_sync(
        client: GoogleSheetsClient, config: TeamSheetLookupConfig,
        division_name: str, team_name: str, logo_url: str,
) -> TeamRoleSheetMetadata:
    try:
        logo_url = normalize_team_logo_url(logo_url)
    except ValueError as exc:
        raise CommandUserError(localize(I18N.errors.team_signing.invalid_logo_url)) from exc
    service = client.build_service(read_only=False)
    _, sheet_grids = client.fetch_sheet_grids(service)
    worksheet_title, grid = _find_division_sheet(division_name, sheet_grids)
    block = _find_team_block(team_name, grid)
    if block is None:
        raise TeamSheetRowNotFoundError(localize(
            I18N.errors.team_profile.team_not_found, role_name=team_name, sheet_name=worksheet_title,
        ))
    # The visible title may be offset inside the team's header (including merged cells).
    title_cells = grid[block.title_row]
    column = next(column for column in range(block.start_column, block.start_column + TEAM_BLOCK_COLUMN_COUNT)
                  if column in title_cells and title_cells[column].value)
    write_team_updates(service, config, [{
        "range": _build_a1_range(worksheet_title, block.title_row, column, 1, 1),
        "values": [[_build_hyperlink_cell_value(title_cells[column].value, logo_url)]],
    }])
    return TeamRoleSheetMetadata(worksheet_title, block.title, logo_url)
