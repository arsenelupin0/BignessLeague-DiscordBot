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

import re
from typing import Any

from bigness_league_bot.application.services.match_replays import (
    MatchReplayReport,
    match_replay_game_score,
)
from bigness_league_bot.application.services.match_standings import (
    MATCH_GRID_RANGE,
    MATCH_STANDINGS_RANGE,
    MATCH_STANDINGS_ROW_COUNT,
    MATCH_STANDINGS_TEAM_COUNT,
    MatchGridGameScore,
    MatchGridManualResult,
    MatchStandingRow,
    MatchStandingGameResult,
    build_match_grid_manual_result_row_values,
    build_match_grid_row_values,
    build_match_grid_standing_games,
    build_match_standings_rows,
    match_grid_row_number,
    match_standings_headers,
    match_standings_sheet_rows,
)
from bigness_league_bot.application.services.standings_sanctions import (
    SanctionScope, StandingsSanction, sanction_deductions, sanction_marker_updates,
)
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.google.sanctions_sheet import (
    SanctionsSheetStore, sheet_range, values_update, STANDINGS_WRITE_LOCK,
)
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


class MatchReplayStandingsGateway:
    def __init__(self, config: TeamSheetLookupConfig) -> None:
        self.config = config

    def list_match_grid_standing_game_results(
            self,
            service: Any,
            *,
            worksheet_name: str,
    ) -> tuple[MatchStandingGameResult, ...]:
        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GoogleSheetsDependencyError(
                localize(I18N.errors.team_profile.google_dependencies_missing)
            ) from exc

        try:
            response = service.spreadsheets().values().get(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"'{escape_worksheet_name(worksheet_name)}'!{MATCH_GRID_RANGE}",
            ).execute()
        except HttpError as exc:
            raise TeamSheetRequestError(
                localize(
                    I18N.errors.match_replays.google_write_failed,
                    details=extract_http_error_message(exc),
                )
            ) from exc

        values = response.get("values", [])
        if not isinstance(values, list):
            return ()
        return build_match_grid_standing_games(
            row for row in values if isinstance(row, list)
        )

    def write_match_grid_report(
            self,
            service: Any,
            *,
            worksheet_name: str,
            report: MatchReplayReport,
    ) -> None:
        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GoogleSheetsDependencyError(
                localize(I18N.errors.team_profile.google_dependencies_missing)
            ) from exc

        row_number, values = report_grid_values(report)
        try:
            service.spreadsheets().values().update(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"'{escape_worksheet_name(worksheet_name)}'!B{row_number}:U{row_number}",
                valueInputOption="USER_ENTERED",
                body={"values": [values]},
            ).execute()
        except HttpError as exc:
            raise TeamSheetWriteError(
                localize(
                    I18N.errors.match_replays.google_write_failed,
                    details=extract_http_error_message(exc),
                )
            ) from exc

    def write_match_grid_manual_result(
            self,
            service: Any,
            *,
            worksheet_name: str,
            matchday: int,
            match_number: int,
            result: MatchGridManualResult,
    ) -> None:
        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GoogleSheetsDependencyError(
                localize(I18N.errors.team_profile.google_dependencies_missing)
            ) from exc

        row_number = match_grid_row_number(
            matchday=matchday,
            match_number=match_number,
        )
        values = build_match_grid_manual_result_row_values(result)
        try:
            service.spreadsheets().values().update(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"'{escape_worksheet_name(worksheet_name)}'!B{row_number}:U{row_number}",
                valueInputOption="USER_ENTERED",
                body={"values": [values]},
            ).execute()
        except HttpError as exc:
            raise TeamSheetWriteError(
                localize(
                    I18N.errors.match_replays.google_write_failed,
                    details=extract_http_error_message(exc),
                )
            ) from exc

    def write_standings(
            self,
            service: Any,
            *,
            worksheet_name: str,
            rows: list[list[object]],
    ) -> None:
        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise GoogleSheetsDependencyError(
                localize(I18N.errors.team_profile.google_dependencies_missing)
            ) from exc

        values = [match_standings_headers(), *rows[:MATCH_STANDINGS_TEAM_COUNT]]
        while len(values) < MATCH_STANDINGS_ROW_COUNT:
            values.append([""] * len(match_standings_headers()))
        try:
            service.spreadsheets().values().update(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"'{escape_worksheet_name(worksheet_name)}'!{MATCH_STANDINGS_RANGE}",
                valueInputOption="USER_ENTERED",
                body={"values": values},
            ).execute()
        except HttpError as exc:
            raise TeamSheetWriteError(
                localize(
                    I18N.errors.match_replays.google_write_failed,
                    details=extract_http_error_message(exc),
                )
            ) from exc

    def refresh_standings_from_grid(
            self,
            service: Any,
            *,
            worksheet_name: str,
            team_names: tuple[str, ...],
            sanctions: tuple[StandingsSanction, ...] | None = None,
            extra_updates: list[dict[str, object]] | None = None,
            replacement_row: tuple[int, list[object]] | None = None,
    ) -> tuple[MatchStandingRow, ...]:
        with STANDINGS_WRITE_LOCK:
            store = SanctionsSheetStore(self.config)
            if sanctions is None:
                sanctions = store.read(service).records
            scope = SanctionScope.from_worksheet(worksheet_name)
            deductions = sanction_deductions(sanctions, scope, team_names)
            grid = store.read_values(service, sheet_range(worksheet_name, MATCH_GRID_RANGE))
            if replacement_row is not None:
                row_number, row_values = replacement_row
                while len(grid) <= row_number - 20:
                    grid.append([])
                row = grid[row_number - 20]
                row.extend([""] * max(0, 21 - len(row)))
                row[1:21] = row_values
            markers = sanction_marker_updates(grid, sanctions, scope)
            standings = build_match_standings_rows(
                team_names, build_match_grid_standing_games(grid), point_deductions=deductions,
            )
            values = [match_standings_headers(), *match_standings_sheet_rows(standings)[:MATCH_STANDINGS_TEAM_COUNT]]
            while len(values) < MATCH_STANDINGS_ROW_COUNT:
                values.append([""] * len(match_standings_headers()))
            updates = list(extra_updates or ())
            updates.append(values_update(worksheet_name, MATCH_STANDINGS_RANGE, values))
            for row, column, name in markers:
                if replacement_row is not None and replacement_row[0] == row:
                    grid[row - 20][column] = name
                else:
                    updates.append(values_update(worksheet_name, f"{chr(65 + column)}{row}", [[name]]))
            if replacement_row is not None:
                row_number = replacement_row[0]
                updates.append(values_update(worksheet_name, f"B{row_number}:U{row_number}",
                                             [grid[row_number - 20][1:21]]))
            store.commit(service, updates)
            return tuple(standings[:MATCH_STANDINGS_TEAM_COUNT])


def escape_worksheet_name(worksheet_name: str) -> str:
    return worksheet_name.replace("'", "''")


def parse_score(value: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*-\s*(\d+)", value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def report_grid_values(report: MatchReplayReport) -> tuple[int, list[object]]:
    scores = []
    for game in report.games:
        score = parse_score(match_replay_game_score(report, game))
        if score is not None:
            scores.append(MatchGridGameScore(game.number, *score))
    return (
        match_grid_row_number(matchday=report.matchday, match_number=report.match_number),
        build_match_grid_row_values(team_one_name=report.team_one_name, team_two_name=report.team_two_name,
                                    game_scores=scores),
    )
