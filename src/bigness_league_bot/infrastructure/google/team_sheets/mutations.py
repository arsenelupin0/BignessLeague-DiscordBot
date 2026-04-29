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
    TeamSigningBatch,
    TeamTechnicalStaffBatch,
    sort_team_signing_players,
)
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.google.team_sheets.blocks import (
    _collect_team_blocks,
    _find_division_sheet,
    _resolve_target_team_block,
)
from bigness_league_bot.infrastructure.google.team_sheets.cells import (
    _is_free_block_title,
    _normalize_member_lookup_text,
    _normalize_technical_staff_role_name,
)
from bigness_league_bot.infrastructure.google.team_sheets.client import GoogleSheetsClient
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.errors import (
    TeamSheetDuplicatePlayerError,
    TeamSheetLayoutError,
    TeamSheetTechnicalStaffRoleNotFoundError,
    TeamSheetWriteError,
)
from bigness_league_bot.infrastructure.google.team_sheets.finders import (
    _find_player_matches,
    _find_technical_staff_matches,
    _raise_removal_not_found_error,
)
from bigness_league_bot.infrastructure.google.team_sheets.http_errors import (
    _extract_http_error_message,
    _maybe_wrap_google_http_error,
)
from bigness_league_bot.infrastructure.google.team_sheets.models import (
    TeamBlockAnchor,
    TeamSigningRemovalResult,
    TeamSigningWriteResult,
    TeamTechnicalStaffWriteResult,
)
from bigness_league_bot.infrastructure.google.team_sheets.parser import (
    _collect_players_by_discord,
    _collect_technical_staff_rows,
    _parse_players,
    _resolve_technical_staff_values, _to_team_signing_player, _build_player_values_grid,
)
from bigness_league_bot.infrastructure.google.team_sheets.player_signing_mutations import (
    register_team_signings_sync as _register_team_signings_sync,
)
from bigness_league_bot.infrastructure.google.team_sheets.ranges import _build_a1_range
from bigness_league_bot.infrastructure.google.team_sheets.schema import (
    PLACEHOLDER_CELL_VALUE, TEAM_BLOCK_PLAYERS_ROW_OFFSET, TEAM_BLOCK_MAX_PLAYERS, TEAM_BLOCK_COLUMN_COUNT,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N


class TeamSheetMutationService:
    def __init__(self, client: GoogleSheetsClient, config: TeamSheetLookupConfig) -> None:
        self.client = client
        self.config = config

    def register_team_signings_sync(
            self,
            signing_batch: TeamSigningBatch,
    ) -> TeamSigningWriteResult:
        return _register_team_signings_sync(
            self.client,
            self.config,
            signing_batch,
        )

    def remove_team_player_by_discord_sync(
            self,
            discord_name: str,
            *,
            team_name: str | None = None,
    ) -> TeamSigningRemovalResult:
        return self._remove_team_player_by_discord_sync(
            discord_name,
            team_name=team_name,
        )

    def _remove_team_player_by_discord_sync(
            self,
            discord_name: str,
            *,
            team_name: str | None = None,
    ) -> TeamSigningRemovalResult:
        return self._remove_team_member_by_discord_sync(
            discord_name,
            team_name=team_name,
            remove_player=True,
            remove_staff=False,
        )

    def remove_team_staff_by_discord_sync(
            self,
            discord_name: str,
            *,
            team_name: str | None = None,
    ) -> TeamSigningRemovalResult:
        return self._remove_team_staff_by_discord_sync(
            discord_name,
            team_name=team_name,
        )

    def _remove_team_staff_by_discord_sync(
            self,
            discord_name: str,
            *,
            team_name: str | None = None,
    ) -> TeamSigningRemovalResult:
        return self._remove_team_member_by_discord_sync(
            discord_name,
            team_name=team_name,
            remove_player=False,
            remove_staff=True,
        )

    def remove_team_member_by_discord_sync(
            self,
            discord_name: str,
            *,
            team_name: str | None = None,
            remove_player: bool = True,
            remove_staff: bool = True,
    ) -> TeamSigningRemovalResult:
        return self._remove_team_member_by_discord_sync(
            discord_name,
            team_name=team_name,
            remove_player=remove_player,
            remove_staff=remove_staff,
        )

    def _remove_team_member_by_discord_sync(
            self,
            discord_name: str,
            *,
            team_name: str | None = None,
            remove_player: bool = True,
            remove_staff: bool = True,
    ) -> TeamSigningRemovalResult:
        normalized_discord_name = _normalize_member_lookup_text(discord_name)
        normalized_team_name = _normalize_member_lookup_text(team_name)
        if not normalized_discord_name:
            _raise_removal_not_found_error(
                discord_name,
                remove_player=remove_player,
                remove_staff=remove_staff,
            )

        service = self.client.build_service(read_only=False)
        sheet_scope, sheet_grids = self.client.fetch_sheet_grids(service)
        player_matches = _find_player_matches(normalized_discord_name, sheet_grids)
        staff_matches = _find_technical_staff_matches(
            normalized_discord_name,
            sheet_grids,
        )

        candidate_contexts: dict[tuple[str, int, int], TeamBlockAnchor] = {}
        if remove_player:
            for match in player_matches:
                candidate_contexts[
                    (match.worksheet_title, match.block.title_row, match.block.start_column)
                ] = match.block
        if remove_staff:
            for match in staff_matches:
                candidate_contexts[
                    (match.worksheet_title, match.block.title_row, match.block.start_column)
                ] = match.block
        if normalized_team_name:
            candidate_contexts = {
                context_key: block
                for context_key, block in candidate_contexts.items()
                if _normalize_member_lookup_text(block.title) == normalized_team_name
            }

        if not candidate_contexts:
            _raise_removal_not_found_error(
                discord_name,
                remove_player=remove_player,
                remove_staff=remove_staff,
            )

        if len(candidate_contexts) > 1:
            duplicate_locations = ", ".join(
                f"{worksheet_title}/{block.title}"
                for (worksheet_title, _, _), block in candidate_contexts.items()
            )
            raise TeamSheetDuplicatePlayerError(
                localize(
                    I18N.errors.team_signing.member_duplicate,
                    discord_name=discord_name,
                    locations=duplicate_locations,
                )
            )

        (worksheet_title, title_row, start_column), target_block = next(
            iter(candidate_contexts.items())
        )
        target_context_key = (worksheet_title, title_row, start_column)
        target_player_matches = tuple(
            match
            for match in player_matches
            if (match.worksheet_title, match.block.title_row, match.block.start_column)
            == target_context_key
        )
        target_staff_matches = tuple(
            match
            for match in staff_matches
            if (match.worksheet_title, match.block.title_row, match.block.start_column)
            == target_context_key
        )
        if remove_player and len(target_player_matches) > 1:
            duplicate_locations = ", ".join(
                f"{match.worksheet_title}/{match.block.title}"
                for match in target_player_matches
            )
            raise TeamSheetDuplicatePlayerError(
                localize(
                    I18N.errors.team_signing.player_duplicate,
                    discord_name=discord_name,
                    locations=duplicate_locations,
                )
            )
        if remove_player and not remove_staff and not target_player_matches:
            _raise_removal_not_found_error(
                discord_name,
                remove_player=remove_player,
                remove_staff=False,
            )
        if remove_staff and not remove_player and not target_staff_matches:
            _raise_removal_not_found_error(
                discord_name,
                remove_player=False,
                remove_staff=remove_staff,
            )

        target_sheet_grid = next(
            cell_grid
            for worksheet_title, cell_grid in sheet_grids
            if worksheet_title == target_context_key[0]
        )
        update_data: list[dict[str, Any]] = []
        removed_player_name: str | None = None
        total_players: int | None = None
        is_player_present_after = bool(target_player_matches)

        if remove_player and target_player_matches:
            player_match = target_player_matches[0]
            remaining_players = tuple(
                _to_team_signing_player(player)
                for player in _parse_players(target_sheet_grid, target_block)
                if _normalize_member_lookup_text(player.discord_name) != normalized_discord_name
            )
            sorted_remaining_players = sort_team_signing_players(remaining_players)
            removed_player_name = player_match.player.player_name
            total_players = len(sorted_remaining_players)
            is_player_present_after = False
            update_data.append(
                {
                    "range": _build_a1_range(
                        worksheet_title,
                        target_block.title_row + TEAM_BLOCK_PLAYERS_ROW_OFFSET,
                        target_block.start_column,
                        TEAM_BLOCK_MAX_PLAYERS,
                        TEAM_BLOCK_COLUMN_COUNT,
                    ),
                    "values": _build_player_values_grid(sorted_remaining_players),
                }
            )

        removed_staff_role_names: tuple[str, ...] = ()
        remaining_staff_role_names = tuple(match.member.role_name for match in target_staff_matches)
        if remove_staff and target_staff_matches:
            removed_staff_role_names = tuple(match.member.role_name for match in target_staff_matches)
            remaining_staff_role_names = ()
            for staff_match in target_staff_matches:
                update_data.append(
                    {
                        "range": _build_a1_range(
                            staff_match.worksheet_title,
                            staff_match.row_index,
                            staff_match.block.start_column + 1,
                            1,
                            3,
                        ),
                        "values": [[
                            PLACEHOLDER_CELL_VALUE,
                            PLACEHOLDER_CELL_VALUE,
                            PLACEHOLDER_CELL_VALUE,
                        ]],
                    }
                )

        after_player_matches = tuple(
            match
            for match in player_matches
            if (
                    not remove_player
                    or (match.worksheet_title, match.block.title_row, match.block.start_column)
                    != target_context_key
            )
        )
        after_staff_matches = tuple(
            match
            for match in staff_matches
            if (
                    not remove_staff
                    or (match.worksheet_title, match.block.title_row, match.block.start_column)
                    != target_context_key
            )
        )
        after_player_contexts = {
            (match.worksheet_title, match.block.title_row, match.block.start_column)
            for match in after_player_matches
        }
        remaining_staff_role_names_after_any_team = tuple(
            sorted(
                {
                    match.member.role_name
                    for match in after_staff_matches
                    if (
                        _normalize_technical_staff_role_name(match.member.role_name)
                        not in {"capitan", "captain"}
                        or (
                            match.worksheet_title,
                            match.block.title_row,
                            match.block.start_column,
                        ) in after_player_contexts
                )
                }
            )
        )

        try:
            if update_data:
                service.spreadsheets().values().batchUpdate(
                    spreadsheetId=self.config.spreadsheet_id,
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

        return TeamSigningRemovalResult(
            worksheet_title=target_context_key[0],
            team_name=target_block.title,
            discord_name=discord_name,
            removed_player_name=removed_player_name,
            total_players=total_players,
            removed_staff_role_names=removed_staff_role_names,
            remaining_staff_role_names=remaining_staff_role_names,
            is_player_present_after=is_player_present_after,
            is_player_present_after_any_team=bool(after_player_matches),
            remaining_staff_role_names_after_any_team=remaining_staff_role_names_after_any_team,
            has_any_team_affiliation_after=bool(after_player_matches or after_staff_matches),
        )

    def register_team_technical_staff_sync(
            self,
            technical_staff_batch: TeamTechnicalStaffBatch,
    ) -> TeamTechnicalStaffWriteResult:
        return self._register_team_technical_staff_sync(technical_staff_batch)

    def _register_team_technical_staff_sync(
            self,
            technical_staff_batch: TeamTechnicalStaffBatch,
    ) -> TeamTechnicalStaffWriteResult:
        service = self.client.build_service(read_only=False)
        _, sheet_grids = self.client.fetch_sheet_grids(service)
        worksheet_title, cell_grid = _find_division_sheet(
            technical_staff_batch.division_name,
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
            technical_staff_batch.team_name,
            team_blocks,
            worksheet_title=worksheet_title,
        )
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

            discord_name, epic_name, rocket_name = _resolve_technical_staff_values(
                member,
                players_by_discord,
                team_name=technical_staff_batch.team_name,
                worksheet_name=worksheet_title,
            )
            update_data.append(
                {
                    "range": _build_a1_range(
                        worksheet_title,
                        target_row,
                        target_block.start_column + 1,
                        1,
                        3,
                    ),
                    "values": [[
                        discord_name,
                        epic_name,
                        rocket_name,
                    ]],
                }
            )

        try:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=self.config.spreadsheet_id,
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

        return TeamTechnicalStaffWriteResult(
            worksheet_title=worksheet_title,
            team_name=technical_staff_batch.team_name,
            updated_count=len(technical_staff_batch.members),
        )
