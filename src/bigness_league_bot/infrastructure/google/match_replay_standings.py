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
    MatchStandingRow,
    MatchStandingGameResult,
    build_match_grid_row_values,
    build_match_grid_standing_games,
    build_match_standings_rows,
    match_grid_row_number,
    match_standings_headers,
    match_standings_sheet_rows,
)
from bigness_league_bot.core.localization import localize
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

        game_scores = []
        for game in report.games:
            score = parse_score(match_replay_game_score(report, game))
            if score is None:
                continue
            game_scores.append(
                MatchGridGameScore(
                    game_number=game.number,
                    team_one_goals=score[0],
                    team_two_goals=score[1],
                )
            )

        row_number = match_grid_row_number(
            matchday=report.matchday,
            match_number=report.match_number,
        )
        values = build_match_grid_row_values(
            team_one_name=report.team_one_name,
            team_two_name=report.team_two_name,
            game_scores=game_scores,
        )
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
    ) -> tuple[MatchStandingRow, ...]:
        games = self.list_match_grid_standing_game_results(
            service,
            worksheet_name=worksheet_name,
        )
        standings = build_match_standings_rows(team_names, games)
        self.write_standings(
            service,
            worksheet_name=worksheet_name,
            rows=match_standings_sheet_rows(standings),
        )
        return tuple(standings[:MATCH_STANDINGS_TEAM_COUNT])


def escape_worksheet_name(worksheet_name: str) -> str:
    return worksheet_name.replace("'", "''")


def parse_score(value: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*-\s*(\d+)", value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))
