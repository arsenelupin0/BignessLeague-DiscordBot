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

from typing import Any

from bigness_league_bot.application.services.team_signing import (
    MAX_TEAM_SIGNING_PLAYERS,
    TeamSigningBatch,
    TeamSigningCapacityError,
    merge_team_signing_players,
)
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.google.team_sheets.blocks import (
    _collect_team_blocks,
    _find_division_sheet,
    _resolve_target_team_block,
)
from bigness_league_bot.infrastructure.google.team_sheets.cells import (
    _build_hyperlink_cell_value,
    _is_free_block_title,
    _normalize_member_lookup_text,
)
from bigness_league_bot.infrastructure.google.team_sheets.client import GoogleSheetsClient
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.errors import (
    TeamSheetDuplicatePlayerError,
    TeamSheetLayoutError,
    TeamSheetNewTeamMinimumPlayersError,
    TeamSheetRemainingSigningsExceededError,
    TeamSheetRosterFullError,
    TeamSheetWriteError,
)
from bigness_league_bot.infrastructure.google.team_sheets.finders import _find_player_matches
from bigness_league_bot.infrastructure.google.team_sheets.http_errors import (
    _extract_http_error_message,
    _maybe_wrap_google_http_error,
)
from bigness_league_bot.infrastructure.google.team_sheets.models import TeamSigningWriteResult
from bigness_league_bot.infrastructure.google.team_sheets.parser import (
    _build_player_values_grid,
    _parse_players,
    _parse_remaining_signings_count,
    _to_team_signing_player,
)
from bigness_league_bot.infrastructure.google.team_sheets.ranges import _build_a1_range
from bigness_league_bot.infrastructure.google.team_sheets.schema import (
    TEAM_BLOCK_COLUMN_COUNT,
    TEAM_BLOCK_MAX_PLAYERS,
    TEAM_BLOCK_PLAYERS_ROW_OFFSET,
    TEAM_BLOCK_SUMMARY_ROW_OFFSET,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N


def register_team_signings_sync(
        client: GoogleSheetsClient,
        config: TeamSheetLookupConfig,
        signing_batch: TeamSigningBatch,
) -> TeamSigningWriteResult:
    service = client.build_service(read_only=False)
    _, sheet_grids = client.fetch_sheet_grids(service)
    worksheet_title, cell_grid = _find_division_sheet(
        signing_batch.division_name,
        sheet_grids,
    )
    team_blocks = _collect_team_blocks(cell_grid)
    if not team_blocks:
        raise TeamSheetLayoutError(
            localize(
                I18N.errors.team_signing.team_sheet_layout_invalid,
                sheet_name=worksheet_title,
            )
        )

    target_block = _resolve_target_team_block(
        signing_batch.team_name,
        team_blocks,
        worksheet_title=worksheet_title,
    )
    is_new_team_block = _is_free_block_title(target_block.title)
    if is_new_team_block and len(signing_batch.players) < 3:
        raise TeamSheetNewTeamMinimumPlayersError(
            localize(
                I18N.errors.team_signing.new_team_min_players,
                team_name=signing_batch.team_name,
                player_count=str(len(signing_batch.players)),
            )
        )
    if is_new_team_block:
        _ensure_new_team_players_are_not_already_registered(
            signing_batch,
            sheet_grids,
        )
        existing_players = ()
    else:
        existing_players = tuple(
            _to_team_signing_player(player)
            for player in _parse_players(cell_grid, target_block)
        )

    try:
        merged_players = merge_team_signing_players(
            existing_players,
            signing_batch.players,
            capacity=MAX_TEAM_SIGNING_PLAYERS,
        )
    except TeamSigningCapacityError as exc:
        raise TeamSheetRosterFullError(
            localize(
                I18N.errors.team_signing.team_roster_full,
                team_name=signing_batch.team_name,
                available_slots=str(exc.available_slots),
                requested_slots=str(exc.requested_count),
            )
        ) from exc

    update_data: list[dict[str, Any]] = [
        {
            "range": _build_a1_range(
                worksheet_title,
                target_block.title_row + TEAM_BLOCK_PLAYERS_ROW_OFFSET,
                target_block.start_column,
                TEAM_BLOCK_MAX_PLAYERS,
                TEAM_BLOCK_COLUMN_COUNT,
            ),
            "values": _build_player_values_grid(merged_players),
        }
    ]
    if is_new_team_block or signing_batch.team_logo_url:
        update_data.insert(
            0,
            {
                "range": _build_a1_range(
                    worksheet_title,
                    target_block.title_row,
                    target_block.start_column,
                    1,
                    1,
                ),
                "values": [[
                    _build_hyperlink_cell_value(
                        signing_batch.team_name,
                        signing_batch.team_logo_url,
                    )
                ]],
            },
        )
    else:
        remaining_signings = _parse_remaining_signings_count(
            cell_grid,
            target_block,
            worksheet_name=worksheet_title,
        )
        requested_signings = len(signing_batch.players)
        if requested_signings > remaining_signings:
            raise TeamSheetRemainingSigningsExceededError(
                localize(
                    I18N.errors.team_signing.remaining_signings_exceeded,
                    team_name=signing_batch.team_name,
                    remaining_signings=str(remaining_signings),
                    requested_signings=str(requested_signings),
                )
            )

        update_data.append(
            {
                "range": _build_a1_range(
                    worksheet_title,
                    target_block.title_row + TEAM_BLOCK_SUMMARY_ROW_OFFSET,
                    target_block.start_column,
                    1,
                    1,
                ),
                "values": [[str(remaining_signings - requested_signings)]],
            }
        )

    try:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=config.spreadsheet_id,
            body={
                "valueInputOption": "USER_ENTERED",
                "data": update_data,
            },
        ).execute()
    except Exception as exc:
        http_error = _maybe_wrap_google_http_error(exc)
        if http_error is not None:
            raise TeamSheetWriteError(
                localize(
                    I18N.errors.team_signing.google_write_failed,
                    details=_extract_http_error_message(http_error),
                )
            ) from exc
        raise

    return TeamSigningWriteResult(
        worksheet_title=worksheet_title,
        team_name=signing_batch.team_name,
        inserted_count=len(signing_batch.players),
        total_players=len(merged_players),
        created_team_block=is_new_team_block,
    )


def _ensure_new_team_players_are_not_already_registered(
        signing_batch: TeamSigningBatch,
        sheet_grids: tuple[tuple[str, dict[int, dict[int, Any]]], ...],
) -> None:
    for player in signing_batch.players:
        normalized_discord_name = _normalize_member_lookup_text(player.discord_name)
        if not normalized_discord_name:
            continue

        matches = _find_player_matches(normalized_discord_name, sheet_grids)
        if not matches:
            continue

        locations = ", ".join(
            f"{match.worksheet_title}/{match.block.title}"
            for match in matches
        )
        raise TeamSheetDuplicatePlayerError(
            localize(
                I18N.errors.team_signing.player_already_registered_in_team,
                discord_name=player.discord_name,
                team_name=signing_batch.team_name,
                locations=locations,
            )
        )
