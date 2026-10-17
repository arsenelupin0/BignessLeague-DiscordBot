from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from bigness_league_bot.application.services.match_replays import (
    MatchReplayDivision,
    MatchReplayReport,
)
from bigness_league_bot.application.services.match_standings import (
    MatchGridManualResult,
    MatchStandingRow,
    build_match_grid_manual_result_row_values,
    match_grid_row_number,
)
from bigness_league_bot.application.services.standings_sanctions import SanctionScope, sanction_error
from bigness_league_bot.core.localization import localize
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.google.match_replay_rosters import (
    normalize_worksheet_title,
)
from bigness_league_bot.infrastructure.google.match_replay_sheet_names import (
    parse_worksheet_names,
    resolve_worksheet_name_for_division,
)
from bigness_league_bot.infrastructure.google.match_replay_standings import (
    MatchReplayStandingsGateway,
    report_grid_values,
)
from bigness_league_bot.infrastructure.google.sanctions_sheet import serialized_standings_write
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


@dataclass(frozen=True, slots=True)
class MatchStandingsRefreshResult:
    worksheet_name: str
    rows: tuple[MatchStandingRow, ...]


class GoogleSheetsMatchStandingsRepository:
    def __init__(self, settings: Settings) -> None:
        self.config = TeamSheetLookupConfig.from_settings(settings)
        self.client = GoogleSheetsClient(self.config)
        self.worksheet_names = parse_worksheet_names(
            settings.google_sheets_match_standings_sheet_name
        )
        self.standings_gateway = MatchReplayStandingsGateway(self.config)

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
    ) -> MatchStandingsRefreshResult:
        return await asyncio.to_thread(
            self.sync_report_to_standings_sync,
            report,
            team_names=team_names,
        )

    async def sync_manual_result_to_standings(
            self,
            division: MatchReplayDivision,
            *,
            matchday: int,
            match_number: int,
            result: MatchGridManualResult,
            team_names: tuple[str, ...],
    ) -> MatchStandingsRefreshResult:
        return await asyncio.to_thread(
            self.sync_manual_result_to_standings_sync,
            division,
            matchday=matchday,
            match_number=match_number,
            result=result,
            team_names=team_names,
        )

    @serialized_standings_write
    def refresh_division_standings_report_sync(
            self,
            division: MatchReplayDivision,
            *,
            team_names: tuple[str, ...],
    ) -> MatchStandingsRefreshResult:
        service = self.client.build_service(read_only=False)
        standings_worksheet_name = self.resolve_standings_worksheet(
            service,
            division=division,
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

    @serialized_standings_write
    def sync_report_to_standings_sync(
            self,
            report: MatchReplayReport,
            *,
            team_names: tuple[str, ...],
    ) -> MatchStandingsRefreshResult:
        service = self.client.build_service(read_only=False)
        standings_worksheet_name = self.resolve_standings_worksheet(
            service,
            division=report.division,
        )
        rows = self.standings_gateway.refresh_standings_from_grid(
            service,
            worksheet_name=standings_worksheet_name,
            team_names=team_names,
            replacement_row=report_grid_values(report),
        )
        return MatchStandingsRefreshResult(
            worksheet_name=standings_worksheet_name,
            rows=rows,
        )

    @serialized_standings_write
    def sync_manual_result_to_standings_sync(
            self,
            division: MatchReplayDivision,
            *,
            matchday: int,
            match_number: int,
            result: MatchGridManualResult,
            team_names: tuple[str, ...],
    ) -> MatchStandingsRefreshResult:
        service = self.client.build_service(read_only=False)
        standings_worksheet_name = self.resolve_standings_worksheet(
            service,
            division=division,
        )
        rows = self.standings_gateway.refresh_standings_from_grid(
            service,
            worksheet_name=standings_worksheet_name,
            team_names=team_names,
            replacement_row=(
                match_grid_row_number(matchday=matchday, match_number=match_number),
                build_match_grid_manual_result_row_values(result),
            ),
        )
        return MatchStandingsRefreshResult(
            worksheet_name=standings_worksheet_name,
            rows=rows,
        )

    def resolve_standings_worksheet(
            self,
            service: Any,
            *,
            division: MatchReplayDivision,
    ) -> str:
        worksheet_name = resolve_worksheet_name_for_division(
            self.worksheet_names,
            division=division,
        )
        worksheet_titles = self._list_worksheet_titles(service)
        if worksheet_name in worksheet_titles:
            if SanctionScope.from_worksheet(worksheet_name).division.casefold() != division.value:
                raise sanction_error("scope", sheet_name=worksheet_name)
            return worksheet_name

        normalized_target = normalize_worksheet_title(worksheet_name)
        for title in worksheet_titles:
            if normalize_worksheet_title(title) == normalized_target:
                if SanctionScope.from_worksheet(title).division.casefold() != division.value:
                    raise sanction_error("scope", sheet_name=title)
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
