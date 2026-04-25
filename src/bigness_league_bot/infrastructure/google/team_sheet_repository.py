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

import asyncio
from typing import Iterable

import discord

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.application.services.team_signing import (
    TeamSigningBatch,
    TeamTechnicalStaffBatch,
)
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.google.team_sheets.client import GoogleSheetsClient
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.errors import (
    GoogleSheetsDependencyError,
    GoogleSheetsNotConfiguredError,
    TeamSheetDivisionNotFoundError,
    TeamSheetDuplicatePlayerError,
    TeamSheetEmptyError,
    TeamSheetError,
    TeamSheetLayoutError,
    TeamSheetNoFreeBlockError,
    TeamSheetPlayerNotFoundError,
    TeamSheetRemainingSigningsExceededError,
    TeamSheetRequestError,
    TeamSheetRosterFullError,
    TeamSheetRowNotFoundError,
    TeamSheetTechnicalStaffPlayerDuplicateError,
    TeamSheetTechnicalStaffPlayerNotFoundError,
    TeamSheetTechnicalStaffRoleNotFoundError,
    TeamSheetWriteError,
)
from bigness_league_bot.infrastructure.google.team_sheets.models import (
    SheetCell,
    TeamBlockAnchor,
    TeamMemberSheetAffiliation,
    TeamMemberTeamMatch,
    TeamPlayerMatch,
    TeamTechnicalStaffMatch,
    TeamRoleSheetMetadata,
    TeamSigningRemovalResult,
    TeamSigningWriteResult,
    TeamTechnicalStaffWriteResult,
)
from bigness_league_bot.infrastructure.google.team_sheets.mutations import TeamSheetMutationService
from bigness_league_bot.infrastructure.google.team_sheets.queries import TeamSheetQueryService


class GoogleSheetsTeamRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.config = TeamSheetLookupConfig.from_settings(settings)
        self.client = GoogleSheetsClient(self.config)
        self.queries = TeamSheetQueryService(self.client)
        self.mutations = TeamSheetMutationService(self.client, self.config)

    async def find_team_profile_for_role(
            self,
            role: discord.Role,
    ) -> TeamProfile:
        return await asyncio.to_thread(self.queries.find_team_profile_for_role_sync, role)

    async def register_team_signings(
            self,
            signing_batch: TeamSigningBatch,
    ) -> TeamSigningWriteResult:
        return await asyncio.to_thread(
            self.mutations.register_team_signings_sync,
            signing_batch,
        )

    async def register_team_technical_staff(
            self,
            technical_staff_batch: TeamTechnicalStaffBatch,
    ) -> TeamTechnicalStaffWriteResult:
        return await asyncio.to_thread(
            self.mutations.register_team_technical_staff_sync,
            technical_staff_batch,
        )

    async def find_team_sheet_metadata_for_role(
            self,
            role: discord.Role,
    ) -> TeamRoleSheetMetadata:
        return await asyncio.to_thread(
            self.queries.find_team_sheet_metadata_for_role_sync,
            role,
        )

    async def remove_team_player_by_discord(
            self,
            discord_name: str,
    ) -> TeamSigningRemovalResult:
        return await asyncio.to_thread(
            self.mutations.remove_team_player_by_discord_sync,
            discord_name,
        )

    async def remove_team_staff_by_discord(
            self,
            discord_name: str,
    ) -> TeamSigningRemovalResult:
        return await asyncio.to_thread(
            self.mutations.remove_team_staff_by_discord_sync,
            discord_name,
        )

    async def remove_team_member_by_discord(
            self,
            discord_name: str,
    ) -> TeamSigningRemovalResult:
        return await asyncio.to_thread(
            self.mutations.remove_team_member_by_discord_sync,
            discord_name,
        )

    async def find_player_matches_by_discord_names(
            self,
            discord_names: Iterable[str],
    ) -> tuple[TeamPlayerMatch, ...]:
        return await asyncio.to_thread(
            self.queries.find_player_matches_by_discord_names_sync,
            tuple(discord_names),
        )

    async def find_member_affiliations_by_discord_names(
            self,
            discord_names: Iterable[str],
    ) -> dict[str, TeamMemberSheetAffiliation]:
        return await asyncio.to_thread(
            self.queries.find_member_affiliations_by_discord_names_sync,
            tuple(discord_names),
        )

    async def find_member_team_matches_by_discord_names(
            self,
            discord_names: Iterable[str],
    ) -> tuple[TeamMemberTeamMatch, ...]:
        return await asyncio.to_thread(
            self.queries.find_member_team_matches_by_discord_names_sync,
            tuple(discord_names),
        )


__all__ = (
    "GoogleSheetsTeamRepository",
    "GoogleSheetsNotConfiguredError",
    "GoogleSheetsDependencyError",
    "TeamSheetError",
    "TeamSheetEmptyError",
    "TeamSheetLayoutError",
    "TeamSheetRowNotFoundError",
    "TeamSheetRequestError",
    "TeamSheetDivisionNotFoundError",
    "TeamSheetNoFreeBlockError",
    "TeamSheetWriteError",
    "TeamSheetRosterFullError",
    "TeamSheetRemainingSigningsExceededError",
    "TeamSheetPlayerNotFoundError",
    "TeamSheetDuplicatePlayerError",
    "TeamSheetTechnicalStaffRoleNotFoundError",
    "TeamSheetTechnicalStaffPlayerNotFoundError",
    "TeamSheetTechnicalStaffPlayerDuplicateError",
    "TeamSheetLookupConfig",
    "SheetCell",
    "TeamBlockAnchor",
    "TeamSigningWriteResult",
    "TeamSigningRemovalResult",
    "TeamPlayerMatch",
    "TeamTechnicalStaffMatch",
    "TeamTechnicalStaffWriteResult",
    "TeamRoleSheetMetadata",
    "TeamMemberSheetAffiliation",
    "TeamMemberTeamMatch",
)
