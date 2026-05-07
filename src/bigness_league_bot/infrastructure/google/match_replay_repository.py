#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from bigness_league_bot.application.services.match_replay_summaries import (
    MatchReplayTeamLogo,
)
from bigness_league_bot.application.services.match_replays import (
    MatchReplayDivision,
    MatchReplayReport,
    MatchReplayRosterPlayer,
    build_match_replay_sheet_rows,
    match_replay_sheet_headers,
)
from bigness_league_bot.application.services.match_standings import MatchStandingRow
from bigness_league_bot.core.localization import localize
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.google.match_replay_rosters import (
    list_division_team_logos_from_grids,
    list_division_roster_players_from_grids,
    normalize_worksheet_title,
)
from bigness_league_bot.infrastructure.google.match_replay_standings import (
    MatchReplayStandingsGateway,
    escape_worksheet_name,
)
from bigness_league_bot.infrastructure.google.team_sheets.client import GoogleSheetsClient
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.errors import (
    GoogleSheetsDependencyError,
    TeamSheetRequestError,
    TeamSheetWriteError,
)
from bigness_league_bot.infrastructure.google.team_sheets.http_errors import (
    extract_http_error_message,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

REPLAY_ID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
SHA256_PATTERN = re.compile(r"\b[0-9a-fA-F]{64}\b")


@dataclass(frozen=True, slots=True)
class ExistingMatchReplayEntry:
    replay_id: str = ""
    replay_sha256: str = ""


@dataclass(frozen=True, slots=True)
class MatchReplayAppendResult:
    worksheet_name: str
    appended_games: int
    skipped_replay_ids: tuple[str, ...]
    skipped_replay_sha256: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MatchStandingsRefreshResult:
    worksheet_name: str
    rows: tuple[MatchStandingRow, ...]


@dataclass(frozen=True, slots=True)
class MatchReplayDivisionRosterData:
    roster_players: tuple[MatchReplayRosterPlayer, ...]
    team_logos: tuple[MatchReplayTeamLogo, ...]


class GoogleSheetsMatchReplayRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.config = TeamSheetLookupConfig.from_settings(settings)
        self.client = GoogleSheetsClient(self.config)
        self.worksheet_names = _parse_worksheet_names(
            settings.google_sheets_match_replays_sheet_name
        )
        self.standings_worksheet_names = _parse_worksheet_names(
            settings.google_sheets_match_standings_sheet_name
        )
        self.standings_gateway = MatchReplayStandingsGateway(self.config)

    async def append_report(
            self,
            report: MatchReplayReport,
    ) -> MatchReplayAppendResult:
        return await asyncio.to_thread(self.append_report_sync, report)

    async def list_existing_replay_entries(
            self,
            division: MatchReplayDivision,
    ) -> tuple[ExistingMatchReplayEntry, ...]:
        return await asyncio.to_thread(
            self.list_existing_replay_entries_sync,
            division,
        )

    async def list_division_roster_players(
            self,
            division_name: str,
    ) -> tuple[MatchReplayRosterPlayer, ...]:
        return await asyncio.to_thread(
            self.list_division_roster_players_sync,
            division_name,
        )

    async def list_division_roster_data(
            self,
            division_name: str,
    ) -> MatchReplayDivisionRosterData:
        return await asyncio.to_thread(
            self.list_division_roster_data_sync,
            division_name,
        )

    async def list_division_team_logos(
            self,
            division_name: str,
    ) -> tuple[MatchReplayTeamLogo, ...]:
        return await asyncio.to_thread(
            self.list_division_team_logos_sync,
            division_name,
        )

    async def refresh_division_standings(
            self,
            division: MatchReplayDivision,
            *,
            team_names: tuple[str, ...],
    ) -> str:
        result = await self.refresh_division_standings_report(
            division,
            team_names=team_names,
        )
        return result.worksheet_name

    async def refresh_division_standings_report(
            self,
            division: MatchReplayDivision,
            *,
            team_names: tuple[str, ...],
    ) -> MatchStandingsRefreshResult:
        return await asyncio.to_thread(
            self.refresh_division_standings_report_sync,
            division,
            team_names=team_names,
        )

    async def sync_report_to_standings(
            self,
            report: MatchReplayReport,
            *,
            team_names: tuple[str, ...],
    ) -> str:
        return await asyncio.to_thread(
            self.sync_report_to_standings_sync,
            report,
            team_names=team_names,
        )

    def list_division_roster_players_sync(
            self,
            division_name: str,
    ) -> tuple[MatchReplayRosterPlayer, ...]:
        service = self.client.build_service(read_only=True)
        _, sheet_grids = self.client.fetch_sheet_grids(service)
        return list_division_roster_players_from_grids(division_name, sheet_grids)

    def list_division_roster_data_sync(
            self,
            division_name: str,
    ) -> MatchReplayDivisionRosterData:
        service = self.client.build_service(read_only=True)
        _, sheet_grids = self.client.fetch_sheet_grids(service)
        return MatchReplayDivisionRosterData(
            roster_players=list_division_roster_players_from_grids(
                division_name,
                sheet_grids,
            ),
            team_logos=list_division_team_logos_from_grids(
                division_name,
                sheet_grids,
            ),
        )

    def list_division_team_logos_sync(
            self,
            division_name: str,
    ) -> tuple[MatchReplayTeamLogo, ...]:
        service = self.client.build_service(read_only=True)
        _, sheet_grids = self.client.fetch_sheet_grids(service)
        return list_division_team_logos_from_grids(division_name, sheet_grids)

    def list_existing_replay_entries_sync(
            self,
            division: MatchReplayDivision,
    ) -> tuple[ExistingMatchReplayEntry, ...]:
        worksheet_name = _resolve_worksheet_name_for_division(
            self.worksheet_names,
            division=division,
        )
        service = self.client.build_service(read_only=True)
        worksheet_name = self._resolve_existing_worksheet_name(
            service,
            worksheet_name=worksheet_name,
        )
        return self._list_existing_replay_entries(
            service,
            worksheet_name=worksheet_name,
        )

    def refresh_division_standings_sync(
            self,
            division: MatchReplayDivision,
            *,
            team_names: tuple[str, ...],
    ) -> str:
        return self.refresh_division_standings_report_sync(
            division,
            team_names=team_names,
        ).worksheet_name

    def refresh_division_standings_report_sync(
            self,
            division: MatchReplayDivision,
            *,
            team_names: tuple[str, ...],
    ) -> MatchStandingsRefreshResult:
        service = self.client.build_service(read_only=False)
        standings_worksheet_name = _resolve_worksheet_name_for_division(
            self.standings_worksheet_names,
            division=division,
        )
        standings_worksheet_name = self._resolve_existing_worksheet_name(
            service,
            worksheet_name=standings_worksheet_name,
        )
        rows = self.standings_gateway.refresh_standings_from_grid(
            service,
            worksheet_name=standings_worksheet_name,
            team_names=team_names,
        )
        return MatchStandingsRefreshResult(
            worksheet_name=standings_worksheet_name,
            rows=rows,
        )

    def sync_report_to_standings_sync(
            self,
            report: MatchReplayReport,
            *,
            team_names: tuple[str, ...],
    ) -> str:
        service = self.client.build_service(read_only=False)
        standings_worksheet_name = _resolve_worksheet_name_for_division(
            self.standings_worksheet_names,
            division=report.division,
        )
        standings_worksheet_name = self._resolve_existing_worksheet_name(
            service,
            worksheet_name=standings_worksheet_name,
        )
        self.standings_gateway.write_match_grid_report(
            service,
            worksheet_name=standings_worksheet_name,
            report=report,
        )
        self.standings_gateway.refresh_standings_from_grid(
            service,
            worksheet_name=standings_worksheet_name,
            team_names=team_names,
        )
        return standings_worksheet_name

    def append_report_sync(
            self,
            report: MatchReplayReport,
    ) -> MatchReplayAppendResult:
        worksheet_name = _resolve_worksheet_name(
            self.worksheet_names,
            report=report,
        )
        service = self.client.build_service(read_only=False)
        worksheet_name = self._resolve_existing_worksheet_name(
            service,
            worksheet_name=worksheet_name,
        )
        self._ensure_headers(service, worksheet_name=worksheet_name)
        existing_entries = self._list_existing_replay_entries(
            service,
            worksheet_name=worksheet_name,
        )
        existing_replay_ids = {
            entry.replay_id.casefold() for entry in existing_entries if entry.replay_id
        }
        existing_replay_sha256 = {
            entry.replay_sha256.casefold() for entry in existing_entries if entry.replay_sha256
        }
        skipped_replay_ids = tuple(
            game.replay_id
            for game in report.games
            if game.replay_id.casefold() in existing_replay_ids
        )
        skipped_replay_sha256 = tuple(
            game.replay_sha256
            for game in report.games
            if game.replay_sha256 and game.replay_sha256.casefold() in existing_replay_sha256
        )
        rows = build_match_replay_sheet_rows(
            report,
            skip_replay_ids=existing_replay_ids,
            skip_replay_sha256=existing_replay_sha256,
        )
        skipped_game_count = sum(
            1
            for game in report.games
            if game.replay_id.casefold() in existing_replay_ids
            or bool(game.replay_sha256 and game.replay_sha256.casefold() in existing_replay_sha256)
        )
        if not rows:
            return MatchReplayAppendResult(
                worksheet_name=worksheet_name,
                appended_games=0,
                skipped_replay_ids=skipped_replay_ids,
                skipped_replay_sha256=skipped_replay_sha256,
            )

        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GoogleSheetsDependencyError(
                localize(I18N.errors.team_profile.google_dependencies_missing)
            ) from exc

        try:
            service.spreadsheets().values().append(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"'{escape_worksheet_name(worksheet_name)}'!A1",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            ).execute()
        except HttpError as exc:
            raise TeamSheetWriteError(
                localize(
                    I18N.errors.match_replays.google_write_failed,
                    details=extract_http_error_message(exc),
                )
            ) from exc
        return MatchReplayAppendResult(
            worksheet_name=worksheet_name,
            appended_games=len(report.games) - skipped_game_count,
            skipped_replay_ids=skipped_replay_ids,
            skipped_replay_sha256=skipped_replay_sha256,
        )

    def _resolve_existing_worksheet_name(
            self,
            service: Any,
            *,
            worksheet_name: str,
    ) -> str:
        worksheet_titles = self._list_worksheet_titles(service)
        if worksheet_name in worksheet_titles:
            return worksheet_name

        normalized_target = normalize_worksheet_title(worksheet_name)
        for title in worksheet_titles:
            if normalize_worksheet_title(title) == normalized_target:
                return title

        raise TeamSheetWriteError(
            localize(
                I18N.errors.match_replays.worksheet_not_found,
                sheet_name=worksheet_name,
                available_sheets=", ".join(worksheet_titles) or "-",
            )
        )

    def _list_worksheet_titles(
            self,
            service: Any,
    ) -> tuple[str, ...]:
        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GoogleSheetsDependencyError(
                localize(I18N.errors.team_profile.google_dependencies_missing)
            ) from exc

        try:
            response = service.spreadsheets().get(
                spreadsheetId=self.config.spreadsheet_id,
                fields="sheets(properties(title))",
            ).execute()
        except HttpError as exc:
            raise TeamSheetRequestError(
                localize(
                    I18N.errors.match_replays.google_write_failed,
                    details=extract_http_error_message(exc),
                )
            ) from exc

        sheets = response.get("sheets", [])
        if not isinstance(sheets, list):
            return ()

        titles: list[str] = []
        for sheet in sheets:
            if not isinstance(sheet, dict):
                continue
            properties = sheet.get("properties")
            if not isinstance(properties, dict):
                continue
            title = properties.get("title")
            if isinstance(title, str) and title.strip():
                titles.append(title.strip())
        return tuple(titles)

    def _ensure_headers(
            self,
            service: Any,
            *,
            worksheet_name: str,
    ) -> None:
        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GoogleSheetsDependencyError(
                localize(I18N.errors.team_profile.google_dependencies_missing)
            ) from exc

        header_range = f"'{escape_worksheet_name(worksheet_name)}'!A1:AD1"
        try:
            response = service.spreadsheets().values().get(
                spreadsheetId=self.config.spreadsheet_id,
                range=header_range,
            ).execute()
            values = response.get("values", [])
            expected_headers = match_replay_sheet_headers()
            if isinstance(values, list) and values and values[0] == expected_headers:
                return

            service.spreadsheets().values().update(
                spreadsheetId=self.config.spreadsheet_id,
                range=header_range,
                valueInputOption="USER_ENTERED",
                body={"values": [expected_headers]},
            ).execute()
        except HttpError as exc:
            raise TeamSheetRequestError(
                localize(
                    I18N.errors.match_replays.google_write_failed,
                    details=extract_http_error_message(exc),
                )
            ) from exc

    def _list_existing_replay_entries(
            self,
            service: Any,
            *,
            worksheet_name: str,
    ) -> tuple[ExistingMatchReplayEntry, ...]:
        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GoogleSheetsDependencyError(
                localize(I18N.errors.team_profile.google_dependencies_missing)
            ) from exc

        try:
            response = service.spreadsheets().values().get(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"'{escape_worksheet_name(worksheet_name)}'!A1:AD",
            ).execute()
        except HttpError as exc:
            raise TeamSheetRequestError(
                localize(
                    I18N.errors.match_replays.google_write_failed,
                    details=extract_http_error_message(exc),
                )
            ) from exc

        values = response.get("values", [])
        if not isinstance(values, list) or len(values) < 2:
            return ()

        header = values[0]
        if not isinstance(header, list):
            return ()

        replay_id_index = _find_header_index(header, "Replay ID")
        replay_sha256_index = _find_header_index(header, "Replay SHA256")
        entries: list[ExistingMatchReplayEntry] = []
        seen: set[tuple[str, str]] = set()
        for row in values[1:]:
            if not isinstance(row, list):
                continue
            replay_id = _cell_at(row, replay_id_index)
            replay_sha256 = _cell_at(row, replay_sha256_index)
            if not replay_id:
                replay_id = _find_first_pattern_value(row, REPLAY_ID_PATTERN)
            if not replay_sha256:
                replay_sha256 = _find_first_pattern_value(row, SHA256_PATTERN)
            if not replay_id and not replay_sha256:
                continue
            key = (replay_id, replay_sha256)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                ExistingMatchReplayEntry(
                    replay_id=replay_id,
                    replay_sha256=replay_sha256,
                )
            )
        return tuple(entries)


__all__ = (
    "ExistingMatchReplayEntry",
    "MatchReplayDivisionRosterData",
    "GoogleSheetsMatchReplayRepository",
    "MatchReplayAppendResult",
    "MatchStandingsRefreshResult",
)


def _parse_worksheet_names(raw_value: str) -> tuple[str, ...]:
    names = tuple(
        candidate
        for candidate in (value.strip() for value in raw_value.split(","))
        if candidate
    )
    return names or ("REPLAY STATS",)


def _resolve_worksheet_name(
        worksheet_names: tuple[str, ...],
        *,
        report: MatchReplayReport,
) -> str:
    return _resolve_worksheet_name_for_division(
        worksheet_names,
        division=report.division,
    )


def _resolve_worksheet_name_for_division(
        worksheet_names: tuple[str, ...],
        *,
        division: MatchReplayDivision,
) -> str:
    if len(worksheet_names) == 1:
        return worksheet_names[0]

    division_name = division.name.casefold()
    division_value = division.value.casefold()
    for worksheet_name in worksheet_names:
        normalized_name = worksheet_name.casefold()
        if division_name in normalized_name or division_value in normalized_name:
            return worksheet_name

    return worksheet_names[0]


def _find_header_index(header: list[Any], expected_name: str) -> int | None:
    normalized_expected = normalize_worksheet_title(expected_name)
    for index, value in enumerate(header):
        if isinstance(value, str) and normalize_worksheet_title(value) == normalized_expected:
            return index
    return None


def _cell_at(row: list[Any], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    value = row[index]
    if value is None:
        return ""
    return str(value).strip()


def _find_first_pattern_value(row: list[Any], pattern: re.Pattern[str]) -> str:
    for value in row:
        if value is None:
            continue
        match = pattern.search(str(value))
        if match is not None:
            return match.group(0).casefold()
    return ""
