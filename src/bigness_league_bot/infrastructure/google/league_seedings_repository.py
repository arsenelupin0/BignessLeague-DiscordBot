from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from bigness_league_bot.application.services.league_seedings import (
    LeagueDivisionSchedule, LeagueSeedingsDestination, league_fixture_rows,
)
from bigness_league_bot.application.services.match_replays import MatchReplayDivision
from bigness_league_bot.application.services.match_standings import (
    MATCH_GRID_GAME_WIDTH, MATCH_GRID_MAX_GAMES, MATCH_GRID_RANGE,
)
from bigness_league_bot.application.services.team_divisions import worksheet_division_name_parts
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.google.match_replay_rosters import normalize_worksheet_title
from bigness_league_bot.infrastructure.google.match_replay_sheet_names import (
    parse_worksheet_names, resolve_worksheet_name_for_division,
)
from bigness_league_bot.infrastructure.google.match_replay_standings import escape_worksheet_name
from bigness_league_bot.infrastructure.google.team_sheets.client import GoogleSheetsClient
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.errors import TeamSheetRequestError, TeamSheetWriteError
from bigness_league_bot.infrastructure.google.team_sheets.http_errors import extract_http_error_message


@dataclass(frozen=True, slots=True)
class _Worksheet:
    title: str
    sheet_id: int
    row_count: int
    column_count: int
    merges: tuple[dict[str, int], ...]


class GoogleSheetsLeagueSeedingsRepository:
    """Validate both calendars, then write only fixture cells in one atomic batch."""

    def __init__(self, settings: Settings) -> None:
        self.config = TeamSheetLookupConfig.from_settings(settings)
        self.client = GoogleSheetsClient(self.config)
        self.worksheet_names = parse_worksheet_names(settings.google_sheets_match_standings_sheet_name)

    async def write_seedings(
            self, schedules: tuple[LeagueDivisionSchedule, ...],
    ) -> tuple[LeagueSeedingsDestination, ...]:
        return await asyncio.to_thread(self.write_seedings_sync, schedules)

    def write_seedings_sync(
            self, schedules: tuple[LeagueDivisionSchedule, ...],
    ) -> tuple[LeagueSeedingsDestination, ...]:
        from googleapiclient.errors import HttpError

        if len(schedules) != 2 or len({schedule.division for schedule in schedules}) != 2:
            raise ValueError("Both division schedules are required.")
        if len(set(self.worksheet_names)) < 2:
            raise CommandUserError(localize("errors.league_seedings.destination_configuration"))
        service = self.client.build_service(read_only=False)
        try:
            worksheets = self._resolve_worksheets(service, schedules)
            for schedule, worksheet in zip(schedules, worksheets):
                rows = league_fixture_rows(schedule)
                self._check_layout(worksheet, rows[0].row_number - 1, rows[-1].row_number, 1, 4)
            self._check_empty_calendars(service, worksheets)
        except HttpError as exc:
            raise TeamSheetRequestError(localize(
                "errors.league_seedings.google_read_failed", details=extract_http_error_message(exc),
            )) from exc

        requests = []
        destinations = []
        for schedule, worksheet in zip(schedules, worksheets):
            rows = league_fixture_rows(schedule)
            start_row, end_row = rows[0].row_number - 1, rows[-1].row_number
            # GAME 1: home in B, empty result in C, away in D.
            requests.append({"updateCells": {
                "range": {"sheetId": worksheet.sheet_id, "startRowIndex": start_row,
                          "endRowIndex": end_row, "startColumnIndex": 1, "endColumnIndex": 4},
                "rows": [{"values": [
                    {"userEnteredValue": {"stringValue": row.home}}, {},
                    {"userEnteredValue": {"stringValue": row.away}},
                ]} for row in rows],
                "fields": "userEnteredValue",
            }})
            destinations.append(LeagueSeedingsDestination(
                schedule.division, worksheet.title,
                f"https://docs.google.com/spreadsheets/d/{self.config.spreadsheet_id}/edit#gid={worksheet.sheet_id}",
                (f"B{start_row + 1}:D{end_row}",),
            ))
        try:
            # updateCells writes literal names and preserves formatting, labels and other cells.
            service.spreadsheets().batchUpdate(
                spreadsheetId=self.config.spreadsheet_id, body={"requests": requests},
            ).execute()
        except HttpError as exc:
            raise TeamSheetWriteError(localize(
                "errors.league_seedings.google_write_failed", details=extract_http_error_message(exc),
            )) from exc
        return tuple(destinations)

    def _resolve_worksheets(
            self, service: Any, schedules: tuple[LeagueDivisionSchedule, ...],
    ) -> tuple[_Worksheet, ...]:
        response = service.spreadsheets().get(
            spreadsheetId=self.config.spreadsheet_id,
            fields="sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)),merges)",
        ).execute()
        available = response.get("sheets", [])
        worksheets = []
        for schedule in schedules:
            target = resolve_worksheet_name_for_division(
                self.worksheet_names, division=MatchReplayDivision(schedule.division.name.casefold()),
            )
            matches = [sheet for sheet in available if
                       normalize_worksheet_title(sheet.get("properties", {}).get("title", ""))
                       == normalize_worksheet_title(target)]
            exact = [sheet for sheet in matches if sheet["properties"]["title"] == target]
            matches = exact or matches
            if len(matches) != 1:
                raise CommandUserError(localize(
                    "errors.league_seedings.destination_not_found", division=schedule.division.value,
                    sheet_name=target,
                ))
            properties = matches[0]["properties"]
            source_season = worksheet_division_name_parts(schedule.worksheet_title)[1]
            target_season = worksheet_division_name_parts(properties["title"])[1]
            if source_season is not None and target_season is not None and source_season != target_season:
                raise CommandUserError(localize(
                    "errors.league_seedings.destination_season_mismatch", sheet_name=properties["title"],
                ))
            grid = properties.get("gridProperties", {})
            worksheets.append(_Worksheet(
                properties["title"], properties["sheetId"], grid.get("rowCount", 0),
                grid.get("columnCount", 0), tuple(matches[0].get("merges", [])),
            ))
        if len({sheet.sheet_id for sheet in worksheets}) != 2:
            raise CommandUserError(localize("errors.league_seedings.destination_configuration"))
        return tuple(worksheets)

    def _check_empty_calendars(self, service: Any, worksheets: tuple[_Worksheet, ...]) -> None:
        response = service.spreadsheets().values().batchGet(
            spreadsheetId=self.config.spreadsheet_id,
            ranges=[f"'{escape_worksheet_name(sheet.title)}'!{MATCH_GRID_RANGE}" for sheet in worksheets],
            valueRenderOption="FORMULA",
        ).execute()
        grids = response.get("valueRanges", [])
        if len(grids) != len(worksheets):
            raise CommandUserError(localize("errors.league_seedings.grid_read_failed"))
        for sheet, grid in zip(worksheets, grids):
            for row in grid.get("values", []):
                # MATCH_GRID_RANGE includes the J1–J7 labels in column A.
                for column, value in enumerate(row[1:]):
                    # Ignore the separator column after each game's three cells.
                    if column >= MATCH_GRID_GAME_WIDTH * MATCH_GRID_MAX_GAMES or column % MATCH_GRID_GAME_WIDTH == 3:
                        continue
                    if value is not None and str(value).strip():
                        raise CommandUserError(localize(
                            "errors.league_seedings.calendar_occupied", sheet_name=sheet.title,
                        ))

    @staticmethod
    def _check_layout(sheet: _Worksheet, start_row: int, end_row: int, start_column: int, end_column: int) -> None:
        if sheet.row_count < end_row or sheet.column_count < end_column:
            raise CommandUserError(localize("errors.league_seedings.invalid_grid", sheet_name=sheet.title))
        for merged in sheet.merges:
            if (merged.get("startRowIndex", 0) < end_row and merged.get("endRowIndex", sheet.row_count) > start_row
                    and merged.get("startColumnIndex", 0) < end_column
                    and merged.get("endColumnIndex", sheet.column_count) > start_column):
                raise CommandUserError(localize("errors.league_seedings.invalid_grid", sheet_name=sheet.title))
