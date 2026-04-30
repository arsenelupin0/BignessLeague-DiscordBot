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

import discord

from bigness_league_bot.application.services.team_profile import TeamProfile, build_team_profile
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.google.team_sheets.blocks import (
    _collect_team_blocks,
    _extract_block_title_cell,
    _find_team_block,
)
from bigness_league_bot.infrastructure.google.team_sheets.cells import (
    _is_free_block_title,
    _normalize_member_lookup_text,
)
from bigness_league_bot.infrastructure.google.team_sheets.client import GoogleSheetsClient
from bigness_league_bot.infrastructure.google.team_sheets.errors import (
    TeamSheetEmptyError,
    TeamSheetLayoutError,
    TeamSheetRowNotFoundError,
)
from bigness_league_bot.infrastructure.google.team_sheets.finders import (
    _find_member_affiliations_by_discord_name_set,
    _find_member_team_matches_by_discord_name_set,
    _find_player_matches_by_discord_name_set,
)
from bigness_league_bot.infrastructure.google.team_sheets.models import (
    TeamMemberSheetAffiliation,
    TeamMemberTeamMatch,
    TeamPlayerMatch,
    TeamRoleSheetMetadata,
)
from bigness_league_bot.infrastructure.google.team_sheets.parser import (
    _parse_players,
    _parse_summary,
    _parse_technical_staff,
)
from bigness_league_bot.infrastructure.google.team_sheets.schema import PLACEHOLDER_MEMBER_NAMES
from bigness_league_bot.infrastructure.i18n.keys import I18N


class TeamSheetQueryService:
    def __init__(self, client: GoogleSheetsClient) -> None:
        self.client = client

    def find_team_profile_for_role_sync(
            self,
            role: discord.Role,
    ) -> TeamProfile:
        return self._find_team_profile_for_role_sync(role)

    def _find_team_profile_for_role_sync(
            self,
            role: discord.Role,
    ) -> TeamProfile:
        service = self.client.build_service(read_only=True)
        sheet_scope, sheet_grids = self.client.fetch_sheet_grids(service)
        if not sheet_grids:
            raise TeamSheetEmptyError(
                localize(
                    I18N.errors.team_profile.team_sheet_empty,
                    sheet_name=sheet_scope,
                )
            )

        for worksheet_title, cell_grid in sheet_grids:
            if not cell_grid:
                continue

            team_block = _find_team_block(role.name, cell_grid)
            if team_block is None:
                continue

            players = _parse_players(cell_grid, team_block)
            if not players:
                raise TeamSheetLayoutError(
                    localize(
                        I18N.errors.team_profile.team_sheet_layout_invalid,
                        sheet_name=worksheet_title,
                        role_name=role.name,
                    )
                )

            remaining_signings, top_three_average = _parse_summary(
                cell_grid,
                team_block,
                worksheet_name=worksheet_title,
            )
            technical_staff = _parse_technical_staff(
                cell_grid,
                team_block,
            )

            return build_team_profile(
                team_name=team_block.title,
                division_name=worksheet_title,
                remaining_signings=remaining_signings,
                top_three_average=top_three_average,
                players=players,
                technical_staff=technical_staff,
            )

        raise TeamSheetRowNotFoundError(
            localize(
                I18N.errors.team_profile.team_not_found,
                role_name=role.name,
                sheet_name=sheet_scope,
            )
        )

    def find_team_sheet_metadata_for_role_sync(
            self,
            role: discord.Role,
    ) -> TeamRoleSheetMetadata:
        return self._find_team_sheet_metadata_for_role_sync(role)

    def list_team_sheet_metadata_sync(self) -> tuple[TeamRoleSheetMetadata, ...]:
        service = self.client.build_service(read_only=True)
        sheet_scope, sheet_grids = self.client.fetch_sheet_grids(service)
        if not sheet_grids:
            raise TeamSheetEmptyError(
                localize(
                    I18N.errors.team_profile.team_sheet_empty,
                    sheet_name=sheet_scope,
                )
            )

        metadata: list[TeamRoleSheetMetadata] = []
        for worksheet_title, cell_grid in sheet_grids:
            if not cell_grid:
                continue

            for team_block in _collect_team_blocks(cell_grid):
                if _is_free_block_title(team_block.title):
                    continue

                title_cell = _extract_block_title_cell(
                    cell_grid,
                    team_block.title_row,
                    team_block.start_column,
                )
                metadata.append(
                    TeamRoleSheetMetadata(
                        worksheet_title=worksheet_title,
                        team_name=team_block.title,
                        team_image_url=title_cell.hyperlink,
                    )
                )

        return tuple(metadata)

    def _find_team_sheet_metadata_for_role_sync(
            self,
            role: discord.Role,
    ) -> TeamRoleSheetMetadata:
        service = self.client.build_service(read_only=True)
        sheet_scope, sheet_grids = self.client.fetch_sheet_grids(service)
        if not sheet_grids:
            raise TeamSheetEmptyError(
                localize(
                    I18N.errors.team_profile.team_sheet_empty,
                    sheet_name=sheet_scope,
                )
            )

        for worksheet_title, cell_grid in sheet_grids:
            if not cell_grid:
                continue

            team_block = _find_team_block(role.name, cell_grid)
            if team_block is None:
                continue

            title_cell = _extract_block_title_cell(
                cell_grid,
                team_block.title_row,
                team_block.start_column,
            )
            return TeamRoleSheetMetadata(
                worksheet_title=worksheet_title,
                team_name=team_block.title,
                team_image_url=title_cell.hyperlink,
            )

        raise TeamSheetRowNotFoundError(
            localize(
                I18N.errors.team_profile.team_not_found,
                role_name=role.name,
                sheet_name=sheet_scope,
            )
        )

    def find_player_matches_by_discord_names_sync(
            self,
            discord_names: tuple[str, ...],
    ) -> tuple[TeamPlayerMatch, ...]:
        return self._find_player_matches_by_discord_names_sync(discord_names)

    def _find_player_matches_by_discord_names_sync(
            self,
            discord_names: tuple[str, ...],
    ) -> tuple[TeamPlayerMatch, ...]:
        normalized_names = tuple(
            normalized_name
            for normalized_name in (
                _normalize_member_lookup_text(discord_name)
                for discord_name in discord_names
            )
            if normalized_name not in PLACEHOLDER_MEMBER_NAMES
        )
        if not normalized_names:
            return ()

        service = self.client.build_service(read_only=True)
        _, sheet_grids = self.client.fetch_sheet_grids(service)
        return _find_player_matches_by_discord_name_set(
            frozenset(normalized_names),
            sheet_grids,
        )

    def find_member_affiliations_by_discord_names_sync(
            self,
            discord_names: tuple[str, ...],
    ) -> dict[str, TeamMemberSheetAffiliation]:
        return self._find_member_affiliations_by_discord_names_sync(discord_names)

    def _find_member_affiliations_by_discord_names_sync(
            self,
            discord_names: tuple[str, ...],
    ) -> dict[str, TeamMemberSheetAffiliation]:
        normalized_names = tuple(
            normalized_name
            for normalized_name in (
                _normalize_member_lookup_text(discord_name)
                for discord_name in discord_names
            )
            if normalized_name not in PLACEHOLDER_MEMBER_NAMES
        )
        if not normalized_names:
            return {}

        service = self.client.build_service(read_only=True)
        _, sheet_grids = self.client.fetch_sheet_grids(service)
        return _find_member_affiliations_by_discord_name_set(
            frozenset(normalized_names),
            sheet_grids,
        )

    def find_member_team_matches_by_discord_names_sync(
            self,
            discord_names: tuple[str, ...],
    ) -> tuple[TeamMemberTeamMatch, ...]:
        return self._find_member_team_matches_by_discord_names_sync(discord_names)

    def _find_member_team_matches_by_discord_names_sync(
            self,
            discord_names: tuple[str, ...],
    ) -> tuple[TeamMemberTeamMatch, ...]:
        normalized_names = tuple(
            normalized_name
            for normalized_name in (
                _normalize_member_lookup_text(discord_name)
                for discord_name in discord_names
            )
            if normalized_name not in PLACEHOLDER_MEMBER_NAMES
        )
        if not normalized_names:
            return ()

        service = self.client.build_service(read_only=True)
        _, sheet_grids = self.client.fetch_sheet_grids(service)
        return _find_member_team_matches_by_discord_name_set(
            frozenset(normalized_names),
            sheet_grids,
        )
