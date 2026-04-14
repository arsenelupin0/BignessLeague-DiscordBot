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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import discord

from bigness_league_bot.application.services.team_profile import (
    TeamProfile,
    TeamProfilePlayer,
    TeamProfileStaffMember,
    build_team_profile,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.i18n.keys import I18N

GOOGLE_SHEETS_READ_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
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


@dataclass(frozen=True, slots=True)
class TeamBlockAnchor:
    title_row: int
    start_column: int
    title: str


class GoogleSheetsTeamRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.config = TeamSheetLookupConfig.from_settings(settings)

    async def find_team_profile_for_role(
            self,
            role: discord.Role,
    ) -> TeamProfile:
        return await asyncio.to_thread(self._find_team_profile_for_role_sync, role)

    def _find_team_profile_for_role_sync(
            self,
            role: discord.Role,
    ) -> TeamProfile:
        sheet_scope, sheet_grids = self._fetch_sheet_grids()
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

    def _fetch_sheet_grids(
            self,
    ) -> tuple[str, tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...]]:
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GoogleSheetsDependencyError(
                localize(I18N.errors.team_profile.google_dependencies_missing)
            ) from exc

        credentials = service_account.Credentials.from_service_account_file(
            str(self.config.service_account_file),
            scopes=[GOOGLE_SHEETS_READ_SCOPE],
        )
        service = build(
            "sheets",
            "v4",
            credentials=credentials,
            cache_discovery=False,
        )
        try:
            response = service.spreadsheets().get(
                spreadsheetId=self.config.spreadsheet_id,
                includeGridData=True,
                fields=(
                    "sheets(properties(title),"
                    "data(startRow,startColumn,rowData(values(formattedValue,hyperlink))))"
                ),
            ).execute()
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

        all_grids: list[tuple[str, dict[int, dict[int, SheetCell]]]] = []
        for sheet in sheets:
            if not isinstance(sheet, dict):
                continue

            worksheet_title = _normalize_cell_value(
                sheet.get("properties", {}).get("title")
            )
            if not worksheet_title:
                continue

            all_grids.append((worksheet_title, _build_sheet_grid(sheet)))

        return _sheet_scope_label(()), tuple(all_grids)

    @staticmethod
    def _find_team_block(
            role_name: str,
            cell_grid: dict[int, dict[int, SheetCell]],
    ) -> TeamBlockAnchor | None:
        normalized_role_name = role_name.casefold()
        for row_index, row_cells in sorted(cell_grid.items()):
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
    def _extract_block_title(
            cell_grid: dict[int, dict[int, SheetCell]],
            row_index: int,
            start_column: int,
    ) -> str:
        title_row = cell_grid.get(row_index, {})
        for column in range(start_column, start_column + TEAM_BLOCK_COLUMN_COUNT):
            value = title_row.get(column, SheetCell()).value
            if value:
                return value

        return ""

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

            if not any(
                    (
                            player_cell.value,
                            discord_cell.value,
                            epic_cell.value,
                            rocket_cell.value,
                            mmr_cell.value,
                    )
            ):
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

            if not any(
                    (
                            role_cell.value,
                            discord_cell.value,
                            epic_cell.value,
                            rocket_cell.value,
                    )
            ):
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
                hyperlink = _normalize_cell_value(raw_cell.get("hyperlink")) or None
                if not value and hyperlink is None:
                    continue

                row_cells[start_column + column_offset] = SheetCell(
                    value=value,
                    hyperlink=hyperlink,
                )

    return grid


def _extract_http_error_message(exc: Exception) -> str:
    message = str(exc)
    if not message:
        return "sin detalles"

    return message
