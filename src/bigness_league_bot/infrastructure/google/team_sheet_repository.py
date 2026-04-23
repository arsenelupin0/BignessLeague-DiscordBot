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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import discord
import unicodedata

from bigness_league_bot.application.services.team_profile import (
    TeamProfile,
    TeamProfilePlayer,
    TeamProfileStaffMember,
    build_team_profile,
)
from bigness_league_bot.application.services.team_signing import (
    MAX_TEAM_SIGNING_PLAYERS,
    TeamSigningBatch,
    TeamSigningCapacityError,
    TeamSigningPlayer,
    TeamTechnicalStaffBatch,
    merge_team_signing_players,
    TeamTechnicalStaffMember,
)
from bigness_league_bot.application.services.team_signing import (
    sort_team_signing_players,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.discord.team_role_assignment import PLACEHOLDER_MEMBER_NAMES
from bigness_league_bot.infrastructure.i18n.keys import I18N

GOOGLE_SHEETS_READ_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
GOOGLE_SHEETS_WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TEAM_BLOCK_HEADERS = (
    "Jugador",
    "Discord",
    "Epic Name",
    "Rocket In-Game Name",
    "MMR",
)
TEAM_BLOCK_HEADERS_NORMALIZED = tuple(header.casefold() for header in TEAM_BLOCK_HEADERS)
TEAM_BLOCK_HEADER_ROW_OFFSET = 1
TEAM_BLOCK_PLAYERS_ROW_OFFSET = 2
TEAM_BLOCK_MAX_PLAYERS = 6
TEAM_BLOCK_SUMMARY_ROW_OFFSET = TEAM_BLOCK_PLAYERS_ROW_OFFSET + TEAM_BLOCK_MAX_PLAYERS
TEAM_BLOCK_TECHNICAL_STAFF_ROW_OFFSET = TEAM_BLOCK_SUMMARY_ROW_OFFSET + 1
TEAM_BLOCK_MAX_TECHNICAL_STAFF = 6
TEAM_BLOCK_COLUMN_COUNT = len(TEAM_BLOCK_HEADERS)
TECHNICAL_STAFF_TITLE_NORMALIZED = "staff tecnico"
TECHNICAL_STAFF_HEADERS_NORMALIZED = (
    "rol",
    "discord",
    "epic name",
    "rocket in-game name",
)
PLACEHOLDER_CELL_VALUE = "-"
HYPERLINK_FORMULA_PATTERN = re.compile(
    r'^=HYPERLINK\("((?:[^"]|"")*)"\s*[,;]\s*"((?:[^"]|"")*)"\)$',
    re.IGNORECASE,
)
INTEGER_VALUE_PATTERN = re.compile(r"-?\d+")


class TeamSheetError(CommandUserError):
    """Base error for expected team sheet lookup failures."""


class GoogleSheetsNotConfiguredError(TeamSheetError):
    """Raised when Google Sheets settings are missing."""


class GoogleSheetsDependencyError(TeamSheetError):
    """Raised when Google API dependencies are not installed."""


class TeamSheetEmptyError(TeamSheetError):
    """Raised when the configured sheet is empty."""


class TeamSheetLayoutError(TeamSheetError):
    """Raised when the configured sheet does not match the expected layout."""


class TeamSheetRowNotFoundError(TeamSheetError):
    """Raised when a team block cannot be found for the Discord role."""


class TeamSheetRequestError(TeamSheetError):
    """Raised when Google Sheets rejects the request."""


class TeamSheetDivisionNotFoundError(TeamSheetError):
    """Raised when the requested division sheet cannot be found."""


class TeamSheetNoFreeBlockError(TeamSheetError):
    """Raised when there is no free team block left in the selected sheet."""


class TeamSheetWriteError(TeamSheetError):
    """Raised when Google Sheets rejects a write operation."""


class TeamSheetRosterFullError(TeamSheetError):
    """Raised when the target team block does not have enough free slots."""


class TeamSheetRemainingSigningsExceededError(TeamSheetError):
    """Raised when the requested signings exceed the remaining signing quota."""


class TeamSheetPlayerNotFoundError(TeamSheetError):
    """Raised when a player cannot be found by Discord name."""


class TeamSheetDuplicatePlayerError(TeamSheetError):
    """Raised when more than one player matches the same Discord name."""


class TeamSheetTechnicalStaffRoleNotFoundError(TeamSheetError):
    """Raised when a requested technical staff role does not exist in the block."""


class TeamSheetTechnicalStaffPlayerNotFoundError(TeamSheetError):
    """Raised when staff data cannot be completed from the roster."""


class TeamSheetTechnicalStaffPlayerDuplicateError(TeamSheetError):
    """Raised when staff data completion finds multiple roster players."""


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


@dataclass(frozen=True, slots=True)
class TeamSheetLookupConfig:
    spreadsheet_id: str
    worksheet_names: tuple[str, ...]
    service_account_file: Path

    @classmethod
    def from_settings(cls, settings: Settings) -> "TeamSheetLookupConfig":
        if settings.google_service_account_file is None:
            raise GoogleSheetsNotConfiguredError(
                localize(I18N.errors.team_profile.google_service_account_missing)
            )

        if not settings.google_service_account_file.exists():
            raise GoogleSheetsNotConfiguredError(
                localize(
                    I18N.errors.team_profile.google_service_account_not_found,
                    path=str(settings.google_service_account_file),
                )
            )

        if not settings.google_sheets_spreadsheet_id:
            raise GoogleSheetsNotConfiguredError(
                localize(I18N.errors.team_profile.google_spreadsheet_id_missing)
            )

        return cls(
            spreadsheet_id=settings.google_sheets_spreadsheet_id,
            worksheet_names=_parse_sheet_names(settings.google_sheets_team_sheet_name),
            service_account_file=settings.google_service_account_file,
        )


@dataclass(frozen=True, slots=True)
class SheetCell:
    value: str = ""
    hyperlink: str | None = None
    formula: str | None = None


@dataclass(frozen=True, slots=True)
class TeamBlockAnchor:
    title_row: int
    start_column: int
    title: str


@dataclass(frozen=True, slots=True)
class TeamSigningWriteResult:
    worksheet_title: str
    team_name: str
    inserted_count: int
    total_players: int


@dataclass(frozen=True, slots=True)
class TeamSigningRemovalResult:
    worksheet_title: str
    team_name: str
    discord_name: str
    removed_player_name: str | None = None
    total_players: int | None = None
    removed_staff_role_names: tuple[str, ...] = ()
    remaining_staff_role_names: tuple[str, ...] = ()
    is_player_present_after: bool = False


@dataclass(frozen=True, slots=True)
class TeamPlayerMatch:
    worksheet_title: str
    block: TeamBlockAnchor
    player: TeamProfilePlayer


@dataclass(frozen=True, slots=True)
class TeamTechnicalStaffMatch:
    worksheet_title: str
    block: TeamBlockAnchor
    row_index: int
    member: TeamProfileStaffMember


@dataclass(frozen=True, slots=True)
class TeamTechnicalStaffWriteResult:
    worksheet_title: str
    team_name: str
    updated_count: int


@dataclass(frozen=True, slots=True)
class TeamRoleSheetMetadata:
    worksheet_title: str
    team_name: str
    team_image_url: str | None = None


@dataclass(frozen=True, slots=True)
class TeamMemberSheetAffiliation:
    discord_name: str
    is_player: bool
    staff_role_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TeamMemberTeamMatch:
    worksheet_title: str
    block: TeamBlockAnchor
    affiliation: TeamMemberSheetAffiliation


class GoogleSheetsTeamRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.config = TeamSheetLookupConfig.from_settings(settings)

    async def find_team_profile_for_role(
            self,
            role: discord.Role,
    ) -> TeamProfile:
        return await asyncio.to_thread(self._find_team_profile_for_role_sync, role)

    async def register_team_signings(
            self,
            signing_batch: TeamSigningBatch,
    ) -> TeamSigningWriteResult:
        return await asyncio.to_thread(
            self._register_team_signings_sync,
            signing_batch,
        )

    async def register_team_technical_staff(
            self,
            technical_staff_batch: TeamTechnicalStaffBatch,
    ) -> TeamTechnicalStaffWriteResult:
        return await asyncio.to_thread(
            self._register_team_technical_staff_sync,
            technical_staff_batch,
        )

    async def find_team_sheet_metadata_for_role(
            self,
            role: discord.Role,
    ) -> TeamRoleSheetMetadata:
        return await asyncio.to_thread(
            self._find_team_sheet_metadata_for_role_sync,
            role,
        )

    async def remove_team_player_by_discord(
            self,
            discord_name: str,
    ) -> TeamSigningRemovalResult:
        return await asyncio.to_thread(
            self._remove_team_player_by_discord_sync,
            discord_name,
        )

    async def remove_team_staff_by_discord(
            self,
            discord_name: str,
    ) -> TeamSigningRemovalResult:
        return await asyncio.to_thread(
            self._remove_team_staff_by_discord_sync,
            discord_name,
        )

    async def remove_team_member_by_discord(
            self,
            discord_name: str,
    ) -> TeamSigningRemovalResult:
        return await asyncio.to_thread(
            self._remove_team_member_by_discord_sync,
            discord_name,
        )

    async def find_player_matches_by_discord_names(
            self,
            discord_names: Iterable[str],
    ) -> tuple[TeamPlayerMatch, ...]:
        return await asyncio.to_thread(
            self._find_player_matches_by_discord_names_sync,
            tuple(discord_names),
        )

    async def find_member_affiliations_by_discord_names(
            self,
            discord_names: Iterable[str],
    ) -> dict[str, TeamMemberSheetAffiliation]:
        return await asyncio.to_thread(
            self._find_member_affiliations_by_discord_names_sync,
            tuple(discord_names),
        )

    async def find_member_team_matches_by_discord_names(
            self,
            discord_names: Iterable[str],
    ) -> tuple[TeamMemberTeamMatch, ...]:
        return await asyncio.to_thread(
            self._find_member_team_matches_by_discord_names_sync,
            tuple(discord_names),
        )

    def _find_team_profile_for_role_sync(
            self,
            role: discord.Role,
    ) -> TeamProfile:
        service = self._build_google_sheets_service(read_only=True)
        _, sheet_grids = self._fetch_sheet_grids(service)
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

            team_block = self._find_team_block(role.name, cell_grid)
            if team_block is None:
                continue

            players = self._parse_players(cell_grid, team_block)
            if not players:
                raise TeamSheetLayoutError(
                    localize(
                        I18N.errors.team_profile.team_sheet_layout_invalid,
                        sheet_name=worksheet_title,
                        role_name=role.name,
                    )
                )

            remaining_signings, top_three_average = self._parse_summary(
                cell_grid,
                team_block,
                worksheet_name=worksheet_title,
            )
            technical_staff = self._parse_technical_staff(
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

    def _find_team_sheet_metadata_for_role_sync(
            self,
            role: discord.Role,
    ) -> TeamRoleSheetMetadata:
        service = self._build_google_sheets_service(read_only=True)
        sheet_scope, sheet_grids = self._fetch_sheet_grids(service)
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

            team_block = self._find_team_block(role.name, cell_grid)
            if team_block is None:
                continue

            title_cell = self._extract_block_title_cell(
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

        service = self._build_google_sheets_service(read_only=True)
        _, sheet_grids = self._fetch_sheet_grids(service)
        return self._find_player_matches_by_discord_name_set(
            frozenset(normalized_names),
            sheet_grids,
        )

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

        service = self._build_google_sheets_service(read_only=True)
        _, sheet_grids = self._fetch_sheet_grids(service)
        return self._find_member_affiliations_by_discord_name_set(
            frozenset(normalized_names),
            sheet_grids,
        )

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

        service = self._build_google_sheets_service(read_only=True)
        _, sheet_grids = self._fetch_sheet_grids(service)
        return self._find_member_team_matches_by_discord_name_set(
            frozenset(normalized_names),
            sheet_grids,
        )

    def _register_team_signings_sync(
            self,
            signing_batch: TeamSigningBatch,
    ) -> TeamSigningWriteResult:
        service = self._build_google_sheets_service(read_only=False)
        _, sheet_grids = self._fetch_sheet_grids(service)
        worksheet_title, cell_grid = self._find_division_sheet(
            signing_batch.division_name,
            sheet_grids,
        )
        team_blocks = self._collect_team_blocks(cell_grid)
        if not team_blocks:
            raise TeamSheetLayoutError(
                localize(
                    I18N.errors.team_signing.team_sheet_layout_invalid,
                    sheet_name=worksheet_title,
                )
            )

        target_block = self._resolve_target_team_block(
            signing_batch.team_name,
            team_blocks,
            worksheet_title=worksheet_title,
        )
        is_new_team_block = _is_free_block_title(target_block.title)
        if is_new_team_block:
            existing_players: tuple[TeamSigningPlayer, ...] = ()
        else:
            existing_players = tuple(
                self._to_team_signing_player(player)
                for player in self._parse_players(cell_grid, target_block)
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
                "values": self._build_player_values_grid(merged_players),
            }
        ]
        if is_new_team_block:
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
                    "values": [[signing_batch.team_name]],
                },
            )
        else:
            remaining_signings = self._parse_remaining_signings_count(
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

        return TeamSigningWriteResult(
            worksheet_title=worksheet_title,
            team_name=signing_batch.team_name,
            inserted_count=len(signing_batch.players),
            total_players=len(merged_players),
        )

    def _remove_team_player_by_discord_sync(
            self,
            discord_name: str,
    ) -> TeamSigningRemovalResult:
        return self._remove_team_member_by_discord_sync(
            discord_name,
            remove_player=True,
            remove_staff=False,
        )

    def _remove_team_staff_by_discord_sync(
            self,
            discord_name: str,
    ) -> TeamSigningRemovalResult:
        return self._remove_team_member_by_discord_sync(
            discord_name,
            remove_player=False,
            remove_staff=True,
        )

    def _remove_team_member_by_discord_sync(
            self,
            discord_name: str,
            *,
            remove_player: bool = True,
            remove_staff: bool = True,
    ) -> TeamSigningRemovalResult:
        normalized_discord_name = _normalize_member_lookup_text(discord_name)
        if not normalized_discord_name:
            self._raise_removal_not_found_error(
                discord_name,
                remove_player=remove_player,
                remove_staff=remove_staff,
            )

        service = self._build_google_sheets_service(read_only=False)
        sheet_scope, sheet_grids = self._fetch_sheet_grids(service)
        player_matches = self._find_player_matches(normalized_discord_name, sheet_grids)
        staff_matches = self._find_technical_staff_matches(
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

        if not candidate_contexts:
            self._raise_removal_not_found_error(
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
            self._raise_removal_not_found_error(
                discord_name,
                remove_player=remove_player,
                remove_staff=False,
            )
        if remove_staff and not remove_player and not target_staff_matches:
            self._raise_removal_not_found_error(
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
                self._to_team_signing_player(player)
                for player in self._parse_players(target_sheet_grid, target_block)
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
                    "values": self._build_player_values_grid(sorted_remaining_players),
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
        )

    def _register_team_technical_staff_sync(
            self,
            technical_staff_batch: TeamTechnicalStaffBatch,
    ) -> TeamTechnicalStaffWriteResult:
        service = self._build_google_sheets_service(read_only=False)
        _, sheet_grids = self._fetch_sheet_grids(service)
        worksheet_title, cell_grid = self._find_division_sheet(
            technical_staff_batch.division_name,
            sheet_grids,
        )
        team_blocks = self._collect_team_blocks(cell_grid)
        if not team_blocks:
            raise TeamSheetLayoutError(
                localize(
                    I18N.errors.team_signing.team_sheet_layout_invalid,
                    sheet_name=worksheet_title,
                )
            )

        target_block = self._resolve_target_team_block(
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

        technical_staff_rows = self._collect_technical_staff_rows(
            cell_grid,
            target_block,
            worksheet_name=worksheet_title,
        )
        players_by_discord = self._collect_players_by_discord(
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

            discord_name, epic_name, rocket_name = self._resolve_technical_staff_values(
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

    def _build_google_sheets_service(
            self,
            *,
            read_only: bool,
    ) -> Any:
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleSheetsDependencyError(
                localize(I18N.errors.team_profile.google_dependencies_missing)
            ) from exc

        scopes = [GOOGLE_SHEETS_READ_SCOPE] if read_only else [GOOGLE_SHEETS_WRITE_SCOPE]
        credentials = service_account.Credentials.from_service_account_file(
            str(self.config.service_account_file),
            scopes=scopes,
        )
        return build(
            "sheets",
            "v4",
            credentials=credentials,
            cache_discovery=False,
        )

    def _fetch_sheet_grids(
            self,
            service: Any,
    ) -> tuple[str, tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...]]:
        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GoogleSheetsDependencyError(
                localize(I18N.errors.team_profile.google_dependencies_missing)
            ) from exc

        request_arguments: dict[str, Any] = {
            "spreadsheetId": self.config.spreadsheet_id,
            "includeGridData": True,
            "fields": (
                "sheets(properties(title),"
                "data(startRow,startColumn,rowData(values(formattedValue,hyperlink,userEnteredValue))))"
            ),
        }
        if self.config.worksheet_names:
            request_arguments["ranges"] = list(self.config.worksheet_names)

        try:
            response = service.spreadsheets().get(**request_arguments).execute()
        except HttpError as exc:
            raise TeamSheetRequestError(
                localize(
                    I18N.errors.team_profile.google_request_failed,
                    details=_extract_http_error_message(exc),
                )
            ) from exc

        sheets = response.get("sheets", [])
        if not isinstance(sheets, list) or not sheets:
            raise TeamSheetEmptyError(
                localize(
                    I18N.errors.team_profile.team_sheet_empty,
                    sheet_name=_sheet_scope_label(self.config.worksheet_names),
                )
            )

        grids: list[tuple[str, dict[int, dict[int, SheetCell]]]] = []
        for sheet in sheets:
            if not isinstance(sheet, dict):
                continue

            worksheet_title = _normalize_cell_value(
                sheet.get("properties", {}).get("title")
            )
            if not worksheet_title:
                continue

            if (
                    self.config.worksheet_names
                    and worksheet_title not in self.config.worksheet_names
            ):
                continue

            grids.append((worksheet_title, _build_sheet_grid(sheet)))

        if grids:
            return _sheet_scope_label(self.config.worksheet_names), tuple(grids)

        raise TeamSheetEmptyError(
            localize(
                I18N.errors.team_profile.team_sheet_empty,
                sheet_name=_sheet_scope_label(self.config.worksheet_names),
            )
        )

    @staticmethod
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
                    GoogleSheetsTeamRepository._get_cell_value(
                        cell_grid,
                        row_index + TEAM_BLOCK_HEADER_ROW_OFFSET,
                        start_column + offset,
                    )
                    .casefold()
                    for offset in range(TEAM_BLOCK_COLUMN_COUNT)
                )
                if header_values != TEAM_BLOCK_HEADERS_NORMALIZED:
                    continue

                title = GoogleSheetsTeamRepository._extract_block_title(
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

    @staticmethod
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
                    GoogleSheetsTeamRepository._get_cell_value(
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
                        title=GoogleSheetsTeamRepository._extract_block_title(
                            cell_grid,
                            row_index,
                            start_column,
                        ),
                    )
                )

        return tuple(blocks)

    @staticmethod
    def _find_division_sheet(
            division_name: str,
            sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
    ) -> tuple[str, dict[int, dict[int, SheetCell]]]:
        normalized_division = _normalize_lookup_text(division_name)
        for worksheet_title, cell_grid in sheet_grids:
            if _normalize_lookup_text(worksheet_title) == normalized_division:
                return worksheet_title, cell_grid

        raise TeamSheetDivisionNotFoundError(
            localize(
                I18N.errors.team_signing.division_not_found,
                division_name=division_name,
            )
        )

    @staticmethod
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

    @staticmethod
    def _find_player_matches(
            normalized_discord_name: str,
            sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
    ) -> tuple[TeamPlayerMatch, ...]:
        return GoogleSheetsTeamRepository._find_player_matches_by_discord_name_set(
            frozenset({normalized_discord_name}),
            sheet_grids,
        )

    @staticmethod
    def _find_technical_staff_matches(
            normalized_discord_name: str,
            sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
    ) -> tuple[TeamTechnicalStaffMatch, ...]:
        matches: list[TeamTechnicalStaffMatch] = []
        for worksheet_title, cell_grid in sheet_grids:
            for block in GoogleSheetsTeamRepository._collect_team_blocks(cell_grid):
                if _is_free_block_title(block.title):
                    continue

                start_row = GoogleSheetsTeamRepository._find_technical_staff_start_row(
                    cell_grid,
                    block,
                )
                if start_row is None:
                    continue

                for offset in range(TEAM_BLOCK_MAX_TECHNICAL_STAFF):
                    row_index = start_row + offset
                    role_cell = GoogleSheetsTeamRepository._get_cell(
                        cell_grid,
                        row_index,
                        block.start_column,
                    )
                    discord_cell = GoogleSheetsTeamRepository._get_cell(
                        cell_grid,
                        row_index,
                        block.start_column + 1,
                    )
                    epic_cell = GoogleSheetsTeamRepository._get_cell(
                        cell_grid,
                        row_index,
                        block.start_column + 2,
                    )
                    rocket_cell = GoogleSheetsTeamRepository._get_cell(
                        cell_grid,
                        row_index,
                        block.start_column + 3,
                    )

                    row_values = (
                        role_cell.value,
                        discord_cell.value,
                        epic_cell.value,
                        rocket_cell.value,
                    )
                    if _is_placeholder_row(*row_values):
                        continue

                    if _normalize_member_lookup_text(discord_cell.value) != normalized_discord_name:
                        continue

                    matches.append(
                        TeamTechnicalStaffMatch(
                            worksheet_title=worksheet_title,
                            block=block,
                            row_index=row_index,
                            member=TeamProfileStaffMember(
                                role_name=role_cell.value,
                                discord_name=discord_cell.value,
                                epic_name=epic_cell.value,
                                rocket_name=rocket_cell.value,
                            ),
                        )
                    )

        return tuple(matches)

    @staticmethod
    def _raise_removal_not_found_error(
            discord_name: str,
            *,
            remove_player: bool,
            remove_staff: bool,
    ) -> None:
        if remove_player and remove_staff:
            raise TeamSheetPlayerNotFoundError(
                localize(
                    I18N.errors.team_signing.member_not_found,
                    discord_name=discord_name,
                )
            )

        if remove_staff:
            raise TeamSheetPlayerNotFoundError(
                localize(
                    I18N.errors.team_signing.technical_staff_member_not_found,
                    discord_name=discord_name,
                )
            )

        raise TeamSheetPlayerNotFoundError(
            localize(
                I18N.errors.team_signing.player_not_found,
                discord_name=discord_name,
            )
        )

    @staticmethod
    def _find_player_matches_by_discord_name_set(
            normalized_discord_names: frozenset[str],
            sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
    ) -> tuple[TeamPlayerMatch, ...]:
        matches: list[TeamPlayerMatch] = []
        seen_matches: set[tuple[str, int, int, str, str]] = set()
        for worksheet_title, cell_grid in sheet_grids:
            for block in GoogleSheetsTeamRepository._collect_team_blocks(cell_grid):
                if _is_free_block_title(block.title):
                    continue

                for player in GoogleSheetsTeamRepository._parse_players(cell_grid, block):
                    normalized_player_discord = _normalize_member_lookup_text(
                        player.discord_name
                    )
                    if normalized_player_discord not in normalized_discord_names:
                        continue

                    match_key = (
                        worksheet_title,
                        block.title_row,
                        block.start_column,
                        normalized_player_discord,
                        player.player_name,
                    )
                    if match_key in seen_matches:
                        continue
                    seen_matches.add(match_key)
                    matches.append(
                        TeamPlayerMatch(
                            worksheet_title=worksheet_title,
                            block=block,
                            player=player,
                        )
                    )

        return tuple(matches)

    @staticmethod
    def _find_member_affiliations_by_discord_name_set(
            normalized_discord_names: frozenset[str],
            sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
    ) -> dict[str, TeamMemberSheetAffiliation]:
        player_flags: dict[str, bool] = {}
        staff_role_names: dict[str, set[str]] = {}
        original_names: dict[str, str] = {}

        for _, cell_grid in sheet_grids:
            for block in GoogleSheetsTeamRepository._collect_team_blocks(cell_grid):
                if _is_free_block_title(block.title):
                    continue

                for player in GoogleSheetsTeamRepository._parse_players(cell_grid, block):
                    normalized_player_discord = _normalize_member_lookup_text(
                        player.discord_name
                    )
                    if normalized_player_discord not in normalized_discord_names:
                        continue

                    player_flags[normalized_player_discord] = True
                    original_names.setdefault(
                        normalized_player_discord,
                        player.discord_name,
                    )

                for staff_member in GoogleSheetsTeamRepository._parse_technical_staff(
                        cell_grid,
                        block,
                ):
                    normalized_staff_discord = _normalize_member_lookup_text(
                        staff_member.discord_name
                    )
                    if normalized_staff_discord not in normalized_discord_names:
                        continue

                    original_names.setdefault(
                        normalized_staff_discord,
                        staff_member.discord_name,
                    )
                    normalized_staff_role_name = _normalize_technical_staff_role_name(
                        staff_member.role_name
                    )
                    if not normalized_staff_role_name or normalized_staff_role_name == _normalize_lookup_text(
                            PLACEHOLDER_CELL_VALUE):
                        continue

                    staff_role_names.setdefault(
                        normalized_staff_discord,
                        set(),
                    ).add(staff_member.role_name)

        return {
            normalized_name: TeamMemberSheetAffiliation(
                discord_name=original_names.get(normalized_name, normalized_name),
                is_player=player_flags.get(normalized_name, False),
                staff_role_names=tuple(
                    sorted(staff_role_names.get(normalized_name, set()))
                ),
            )
            for normalized_name in normalized_discord_names
            if player_flags.get(normalized_name, False)
               or staff_role_names.get(normalized_name)
        }

    @staticmethod
    def _find_member_team_matches_by_discord_name_set(
            normalized_discord_names: frozenset[str],
            sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
    ) -> tuple[TeamMemberTeamMatch, ...]:
        matches: list[TeamMemberTeamMatch] = []
        seen_matches: set[tuple[str, int, int, str]] = set()

        for worksheet_title, cell_grid in sheet_grids:
            for block in GoogleSheetsTeamRepository._collect_team_blocks(cell_grid):
                if _is_free_block_title(block.title):
                    continue

                player_flags: dict[str, bool] = {}
                staff_role_names: dict[str, set[str]] = {}
                original_names: dict[str, str] = {}

                for player in GoogleSheetsTeamRepository._parse_players(cell_grid, block):
                    normalized_player_discord = _normalize_member_lookup_text(
                        player.discord_name
                    )
                    if normalized_player_discord not in normalized_discord_names:
                        continue

                    player_flags[normalized_player_discord] = True
                    original_names.setdefault(
                        normalized_player_discord,
                        player.discord_name,
                    )

                for staff_member in GoogleSheetsTeamRepository._parse_technical_staff(
                        cell_grid,
                        block,
                ):
                    normalized_staff_discord = _normalize_member_lookup_text(
                        staff_member.discord_name
                    )
                    if normalized_staff_discord not in normalized_discord_names:
                        continue

                    normalized_staff_role_name = _normalize_technical_staff_role_name(
                        staff_member.role_name
                    )
                    if not normalized_staff_role_name or normalized_staff_role_name == _normalize_lookup_text(
                            PLACEHOLDER_CELL_VALUE):
                        continue

                    original_names.setdefault(
                        normalized_staff_discord,
                        staff_member.discord_name,
                    )
                    staff_role_names.setdefault(
                        normalized_staff_discord,
                        set(),
                    ).add(staff_member.role_name)

                matched_names = sorted(
                    normalized_name
                    for normalized_name in normalized_discord_names
                    if player_flags.get(normalized_name, False)
                    or staff_role_names.get(normalized_name)
                )
                for normalized_name in matched_names:
                    match_key = (
                        worksheet_title,
                        block.title_row,
                        block.start_column,
                        normalized_name,
                    )
                    if match_key in seen_matches:
                        continue

                    seen_matches.add(match_key)
                    matches.append(
                        TeamMemberTeamMatch(
                            worksheet_title=worksheet_title,
                            block=block,
                            affiliation=TeamMemberSheetAffiliation(
                                discord_name=original_names.get(
                                    normalized_name,
                                    normalized_name,
                                ),
                                is_player=player_flags.get(normalized_name, False),
                                staff_role_names=tuple(
                                    sorted(staff_role_names.get(normalized_name, set()))
                                ),
                            ),
                        )
                    )

        return tuple(matches)

    @staticmethod
    def _extract_block_title(
            cell_grid: dict[int, dict[int, SheetCell]],
            row_index: int,
            start_column: int,
    ) -> str:
        return GoogleSheetsTeamRepository._extract_block_title_cell(
            cell_grid,
            row_index,
            start_column,
        ).value

    @staticmethod
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

    @staticmethod
    def _build_player_values_grid(
            players: tuple[TeamSigningPlayer, ...],
    ) -> list[list[str]]:
        rows: list[list[str]] = []
        for player in players:
            rows.append(
                [
                    _build_player_cell_value(player.player_name, player.tracker_url),
                    player.discord_name,
                    player.epic_name,
                    player.rocket_name,
                    player.mmr,
                ]
            )

        while len(rows) < TEAM_BLOCK_MAX_PLAYERS:
            rows.append([PLACEHOLDER_CELL_VALUE] * TEAM_BLOCK_COLUMN_COUNT)

        return rows

    @staticmethod
    def _to_team_signing_player(player: TeamProfilePlayer) -> TeamSigningPlayer:
        return TeamSigningPlayer(
            player_name=player.player_name,
            tracker_url=player.tracker_url or "",
            discord_name=player.discord_name,
            epic_name=player.epic_name,
            rocket_name=player.rocket_name,
            mmr=player.mmr,
        )

    @staticmethod
    def _parse_players(
            cell_grid: dict[int, dict[int, SheetCell]],
            block: TeamBlockAnchor,
    ) -> tuple[TeamProfilePlayer, ...]:
        players: list[TeamProfilePlayer] = []
        for offset in range(TEAM_BLOCK_MAX_PLAYERS):
            row_index = block.title_row + TEAM_BLOCK_PLAYERS_ROW_OFFSET + offset
            player_cell = GoogleSheetsTeamRepository._get_cell(
                cell_grid,
                row_index,
                block.start_column,
            )
            discord_cell = GoogleSheetsTeamRepository._get_cell(
                cell_grid,
                row_index,
                block.start_column + 1,
            )
            epic_cell = GoogleSheetsTeamRepository._get_cell(
                cell_grid,
                row_index,
                block.start_column + 2,
            )
            rocket_cell = GoogleSheetsTeamRepository._get_cell(
                cell_grid,
                row_index,
                block.start_column + 3,
            )
            mmr_cell = GoogleSheetsTeamRepository._get_cell(
                cell_grid,
                row_index,
                block.start_column + 4,
            )

            row_values = (
                player_cell.value,
                discord_cell.value,
                epic_cell.value,
                rocket_cell.value,
                mmr_cell.value,
            )
            if _is_placeholder_row(*row_values):
                continue

            players.append(
                TeamProfilePlayer(
                    position=len(players) + 1,
                    player_name=player_cell.value,
                    discord_name=discord_cell.value,
                    epic_name=epic_cell.value,
                    rocket_name=rocket_cell.value,
                    mmr=mmr_cell.value,
                    tracker_url=player_cell.hyperlink,
                )
            )

        return tuple(players)

    @staticmethod
    def _parse_summary(
            cell_grid: dict[int, dict[int, SheetCell]],
            block: TeamBlockAnchor,
            *,
            worksheet_name: str,
    ) -> tuple[str, str]:
        summary_row = block.title_row + TEAM_BLOCK_SUMMARY_ROW_OFFSET
        remaining_signings = GoogleSheetsTeamRepository._get_cell_value(
            cell_grid,
            summary_row,
            block.start_column,
        )
        top_three_average = GoogleSheetsTeamRepository._get_cell_value(
            cell_grid,
            summary_row,
            block.start_column + 4,
        )
        if not remaining_signings and not top_three_average:
            raise TeamSheetLayoutError(
                localize(
                    I18N.errors.team_profile.team_sheet_layout_invalid,
                    sheet_name=worksheet_name,
                    role_name=block.title,
                )
            )

        return remaining_signings, top_three_average

    @staticmethod
    def _parse_remaining_signings_count(
            cell_grid: dict[int, dict[int, SheetCell]],
            block: TeamBlockAnchor,
            *,
            worksheet_name: str,
    ) -> int:
        summary_row = block.title_row + TEAM_BLOCK_SUMMARY_ROW_OFFSET
        remaining_signings_value = GoogleSheetsTeamRepository._get_cell_value(
            cell_grid,
            summary_row,
            block.start_column,
        )
        return _parse_integer_cell_value(
            remaining_signings_value,
            error_message=localize(
                I18N.errors.team_signing.remaining_signings_invalid,
                team_name=block.title,
                sheet_name=worksheet_name,
            ),
        )

    @staticmethod
    def _parse_technical_staff(
            cell_grid: dict[int, dict[int, SheetCell]],
            block: TeamBlockAnchor,
    ) -> tuple[TeamProfileStaffMember, ...]:
        start_row = GoogleSheetsTeamRepository._find_technical_staff_start_row(
            cell_grid,
            block,
        )
        if start_row is None:
            return ()

        members: list[TeamProfileStaffMember] = []
        for offset in range(TEAM_BLOCK_MAX_TECHNICAL_STAFF):
            row_index = start_row + offset
            role_cell = GoogleSheetsTeamRepository._get_cell(
                cell_grid,
                row_index,
                block.start_column,
            )
            discord_cell = GoogleSheetsTeamRepository._get_cell(
                cell_grid,
                row_index,
                block.start_column + 1,
            )
            epic_cell = GoogleSheetsTeamRepository._get_cell(
                cell_grid,
                row_index,
                block.start_column + 2,
            )
            rocket_cell = GoogleSheetsTeamRepository._get_cell(
                cell_grid,
                row_index,
                block.start_column + 3,
            )

            row_values = (
                role_cell.value,
                discord_cell.value,
                epic_cell.value,
                rocket_cell.value,
            )
            if _is_placeholder_row(*row_values):
                continue

            members.append(
                TeamProfileStaffMember(
                    role_name=role_cell.value,
                    discord_name=discord_cell.value,
                    epic_name=epic_cell.value,
                    rocket_name=rocket_cell.value,
                )
            )

        return tuple(members)

    @staticmethod
    def _find_technical_staff_start_row(
            cell_grid: dict[int, dict[int, SheetCell]],
            block: TeamBlockAnchor,
    ) -> int | None:
        search_start_row = block.title_row + TEAM_BLOCK_TECHNICAL_STAFF_ROW_OFFSET
        search_end_row = search_start_row + TEAM_BLOCK_MAX_TECHNICAL_STAFF + 4
        for row_index in range(search_start_row, search_end_row):
            title_value = _normalize_lookup_text(
                GoogleSheetsTeamRepository._get_cell_value(
                    cell_grid,
                    row_index,
                    block.start_column,
                )
            )
            if title_value != TECHNICAL_STAFF_TITLE_NORMALIZED:
                continue

            headers_row = row_index + 1
            header_values = tuple(
                _normalize_lookup_text(
                    GoogleSheetsTeamRepository._get_cell_value(
                        cell_grid,
                        headers_row,
                        block.start_column + offset,
                    )
                )
                for offset in range(len(TECHNICAL_STAFF_HEADERS_NORMALIZED))
            )
            if header_values == TECHNICAL_STAFF_HEADERS_NORMALIZED:
                return headers_row + 1

            return row_index + 1

        return None

    @staticmethod
    def _find_technical_staff_role_names_by_discord(
            cell_grid: dict[int, dict[int, SheetCell]],
            block: TeamBlockAnchor,
            normalized_discord_name: str,
    ) -> tuple[str, ...]:
        technical_staff = GoogleSheetsTeamRepository._parse_technical_staff(
            cell_grid,
            block,
        )
        return tuple(
            member.role_name
            for member in technical_staff
            if _normalize_member_lookup_text(member.discord_name) == normalized_discord_name
        )

    @staticmethod
    def _collect_players_by_discord(
            cell_grid: dict[int, dict[int, SheetCell]],
            block: TeamBlockAnchor,
    ) -> dict[str, tuple[TeamProfilePlayer, ...]]:
        players_by_discord: dict[str, list[TeamProfilePlayer]] = {}
        for player in GoogleSheetsTeamRepository._parse_players(cell_grid, block):
            normalized_discord_name = _normalize_member_lookup_text(player.discord_name)
            if not normalized_discord_name:
                continue

            players_by_discord.setdefault(normalized_discord_name, []).append(player)

        return {
            discord_name: tuple(players)
            for discord_name, players in players_by_discord.items()
        }

    @staticmethod
    def _resolve_technical_staff_values(
            member: TeamTechnicalStaffMember,
            players_by_discord: dict[str, tuple[TeamProfilePlayer, ...]],
            *,
            team_name: str,
            worksheet_name: str,
    ) -> tuple[str, str, str]:
        if member.epic_name and member.rocket_name:
            return member.discord_name, member.epic_name, member.rocket_name

        normalized_discord_name = _normalize_member_lookup_text(member.discord_name)
        matching_players = players_by_discord.get(normalized_discord_name, ())
        if not matching_players:
            raise TeamSheetTechnicalStaffPlayerNotFoundError(
                localize(
                    I18N.errors.team_signing.technical_staff_player_not_found,
                    discord_name=member.discord_name,
                    role_name=member.role_name,
                    team_name=team_name,
                    sheet_name=worksheet_name,
                )
            )
        if len(matching_players) > 1:
            raise TeamSheetTechnicalStaffPlayerDuplicateError(
                localize(
                    I18N.errors.team_signing.technical_staff_player_duplicate,
                    discord_name=member.discord_name,
                    role_name=member.role_name,
                    team_name=team_name,
                    sheet_name=worksheet_name,
                )
            )

        player = matching_players[0]
        return (
            member.discord_name,
            member.epic_name or player.epic_name,
            member.rocket_name or player.rocket_name,
        )

    @staticmethod
    def _collect_technical_staff_rows(
            cell_grid: dict[int, dict[int, SheetCell]],
            block: TeamBlockAnchor,
            *,
            worksheet_name: str,
    ) -> dict[str, int]:
        start_row = GoogleSheetsTeamRepository._find_technical_staff_start_row(
            cell_grid,
            block,
        )
        if start_row is None:
            raise TeamSheetLayoutError(
                localize(
                    I18N.errors.team_signing.team_sheet_layout_invalid,
                    sheet_name=worksheet_name,
                )
            )

        technical_staff_rows: dict[str, int] = {}
        for offset in range(TEAM_BLOCK_MAX_TECHNICAL_STAFF):
            row_index = start_row + offset
            role_name = GoogleSheetsTeamRepository._get_cell_value(
                cell_grid,
                row_index,
                block.start_column,
            )
            normalized_role_name = _normalize_technical_staff_role_name(role_name)
            if not normalized_role_name or normalized_role_name == _normalize_lookup_text(PLACEHOLDER_CELL_VALUE):
                continue

            technical_staff_rows[normalized_role_name] = row_index

        if not technical_staff_rows:
            raise TeamSheetLayoutError(
                localize(
                    I18N.errors.team_signing.team_sheet_layout_invalid,
                    sheet_name=worksheet_name,
                )
            )

        return technical_staff_rows

    @staticmethod
    def _get_cell(
            cell_grid: dict[int, dict[int, SheetCell]],
            row_index: int,
            column_index: int,
    ) -> SheetCell:
        return cell_grid.get(row_index, {}).get(column_index, SheetCell())

    @staticmethod
    def _get_cell_value(
            cell_grid: dict[int, dict[int, SheetCell]],
            row_index: int,
            column_index: int,
    ) -> str:
        return GoogleSheetsTeamRepository._get_cell(
            cell_grid,
            row_index,
            column_index,
        ).value


def _parse_sheet_names(raw_value: str) -> tuple[str, ...]:
    if not raw_value.strip():
        return ()

    return tuple(
        candidate
        for candidate in (value.strip() for value in raw_value.split(","))
        if candidate
    )


def _sheet_scope_label(worksheet_names: tuple[str, ...]) -> str:
    if not worksheet_names:
        return "todas las hojas"

    return ", ".join(worksheet_names)


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


def _build_a1_range(
        worksheet_title: str,
        start_row: int,
        start_column: int,
        row_count: int,
        column_count: int,
) -> str:
    start_cell = f"{_column_to_letter(start_column)}{start_row + 1}"
    end_cell = (
        f"{_column_to_letter(start_column + column_count - 1)}"
        f"{start_row + row_count}"
    )
    escaped_title = worksheet_title.replace("'", "''")
    return f"'{escaped_title}'!{start_cell}:{end_cell}"


def _column_to_letter(column_index: int) -> str:
    value = column_index + 1
    letters: list[str] = []
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(ord("A") + remainder))

    return "".join(reversed(letters))


def _parse_integer_cell_value(
        value: str,
        *,
        error_message: CommandUserError | Any,
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


def _maybe_wrap_google_http_error(exc: Exception) -> Exception | None:
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        return None

    if isinstance(exc, HttpError):
        return exc

    return None


def _extract_http_error_message(exc: Exception) -> str:
    message = str(exc)
    if not message:
        return "sin detalles"

    return message
