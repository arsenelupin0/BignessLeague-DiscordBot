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

from dataclasses import dataclass
from pathlib import Path

from bigness_league_bot.core.localization import localize
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.google.team_sheets.errors import GoogleSheetsNotConfiguredError
from bigness_league_bot.infrastructure.i18n.keys import I18N

GOOGLE_SHEETS_READ_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
GOOGLE_SHEETS_WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


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
