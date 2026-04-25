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

from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.google.team_sheets.cells import _build_sheet_grid, _normalize_cell_value
from bigness_league_bot.infrastructure.google.team_sheets.config import (
    GOOGLE_SHEETS_READ_SCOPE,
    GOOGLE_SHEETS_WRITE_SCOPE,
    TeamSheetLookupConfig,
    _sheet_scope_label,
)
from bigness_league_bot.infrastructure.google.team_sheets.errors import (
    GoogleSheetsDependencyError,
    TeamSheetEmptyError,
    TeamSheetRequestError,
)
from bigness_league_bot.infrastructure.google.team_sheets.http_errors import _extract_http_error_message
from bigness_league_bot.infrastructure.google.team_sheets.models import SheetCell
from bigness_league_bot.infrastructure.i18n.keys import I18N


class GoogleSheetsClient:
    def __init__(self, config: TeamSheetLookupConfig) -> None:
        self.config = config

    def build_service(
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

    def fetch_sheet_grids(
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
