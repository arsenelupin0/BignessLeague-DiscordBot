from __future__ import annotations

from dataclasses import astuple, dataclass
from functools import wraps
from threading import RLock
from typing import Any

from googleapiclient.errors import HttpError

from bigness_league_bot.application.services.standings_sanctions import (
    StandingsSanction, sanction_error, team_key, validate_sanction,
)
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.http_errors import extract_http_error_message
from bigness_league_bot.infrastructure.i18n.keys import I18N

SHEET_NAME = "Sanciones"
_sheet = I18N.sanctions.sheet
TABLE_TITLE = _sheet.title.default
HEADERS = tuple(key.default for key in (
    _sheet.id, _sheet.worksheet, _sheet.season, _sheet.division, _sheet.team, _sheet.points,
    _sheet.reason, _sheet.kind, _sheet.matchday, _sheet.match_number, _sheet.state,
    _sheet.created_at, _sheet.created_by, _sheet.annulled_at, _sheet.annulled_by, _sheet.annulment_reason,
))
# Serialize read/modify/write operations across repository instances in this bot process.
# Sheets remains authoritative; no cached sanctions survive a refresh.
STANDINGS_WRITE_LOCK = RLock()


def serialized_standings_write(function):
    @wraps(function)
    def locked(*args, **kwargs):
        with STANDINGS_WRITE_LOCK:
            return function(*args, **kwargs)

    return locked


def sheet_range(title: str, area: str) -> str:
    return "'" + title.replace("'", "''") + "'!" + area


def values_update(title: str, area: str, values: list[list[object]]) -> dict[str, object]:
    return {"range": sheet_range(title, area), "values": values}


@dataclass(frozen=True, slots=True)
class SanctionsLedger:
    header_row: int
    records: tuple[StandingsSanction, ...]
    record_rows: tuple[int, ...]
    next_row: int
    initialized: bool


def parse_ledger(values: list[list[object]], *, merged_end_row: int = 0) -> SanctionsLedger:
    headers = [index for index, row in enumerate(values)
               if tuple(row[:len(HEADERS)]) == HEADERS]
    if not headers:
        # Old MX2/NEXUS ban dossiers are deliberately not inferred as point deductions.
        if any(row and (str(row[0]) in (TABLE_TITLE, HEADERS[0])) for row in values):
            raise sanction_error("table")
        header_row = max(len(values), merged_end_row) + 4
        return SanctionsLedger(header_row, (), (), header_row + 1, False)
    if len(headers) != 1:
        raise sanction_error("table")
    header_index = headers[0]
    records: list[StandingsSanction] = []
    rows: list[int] = []
    identifiers: set[str] = set()
    active_ai: set[tuple[str, str, int, int]] = set()
    for index in range(header_index + 1, len(values)):
        row = values[index]
        if not any(str(cell).strip() for cell in row):
            continue
        if len(row) > len(HEADERS) and any(str(cell).strip() for cell in row[len(HEADERS):]):
            raise sanction_error("table")
        fields = [str(value).strip() for value in row[:len(HEADERS)]]
        fields.extend([""] * (len(HEADERS) - len(fields)))
        try:
            fields[5] = int(fields[5])
            fields[8] = int(fields[8]) if fields[8] else None
            fields[9] = int(fields[9]) if fields[9] else None
            record = StandingsSanction(*fields)
            validate_sanction(record)
        except (ValueError, TypeError) as exc:
            raise sanction_error("invalid_record", identifier=f"A{index + 1}:P{index + 1}") from exc
        if record.identifier in identifiers:
            raise sanction_error("duplicate", identifier=record.identifier)
        if record.active and record.kind == "AI":
            key = (team_key(record.worksheet), team_key(record.team_name), record.matchday, record.match_number)
            if key in active_ai:
                raise sanction_error("duplicate", identifier=record.identifier)
            active_ai.add(key)
        identifiers.add(record.identifier)
        records.append(record)
        rows.append(index + 1)
    return SanctionsLedger(header_index + 1, tuple(records), tuple(rows),
                           max(len(values) + 1, header_index + 2), True)


def ledger_updates(ledger: SanctionsLedger, records: tuple[StandingsSanction, ...]) -> list[dict[str, object]]:
    updates = []
    if not ledger.initialized:
        updates.extend([
            values_update(SHEET_NAME, f"A{ledger.header_row - 1}", [[TABLE_TITLE]]),
            values_update(SHEET_NAME, f"A{ledger.header_row}:P{ledger.header_row}", [list(HEADERS)]),
        ])
    old = {record.identifier: (record, row) for record, row in zip(ledger.records, ledger.record_rows)}
    next_row = ledger.next_row
    for record in records:
        previous = old.get(record.identifier)
        if previous and previous[0] == record:
            continue
        if previous:
            row = previous[1]
        else:
            row = next_row
            next_row += 1
        values = ["" if value is None else value for value in astuple(record)]
        updates.append(values_update(SHEET_NAME, f"A{row}:P{row}", [values]))
    return updates


class SanctionsSheetStore:
    def __init__(self, config: TeamSheetLookupConfig) -> None:
        self.config = config

    def read(self, service: Any) -> SanctionsLedger:
        values = self.read_values(service, sheet_range(SHEET_NAME, "A:Z"))
        ledger = parse_ledger(values)
        if not ledger.initialized:
            raise sanction_error("table")
        return ledger

    def read_values(self, service: Any, area: str) -> list[list[object]]:
        try:
            response = service.spreadsheets().values().get(
                spreadsheetId=self.config.spreadsheet_id, range=area,
                valueRenderOption="UNFORMATTED_VALUE",
            ).execute(num_retries=0)
        except HttpError as exc:
            raise sanction_error("request", details=extract_http_error_message(exc)) from exc
        values = response.get("values", [])
        if not isinstance(values, list) or any(not isinstance(row, list) for row in values):
            raise sanction_error("table")
        return values

    def commit(self, service: Any, updates: list[dict[str, object]]) -> None:
        if not updates:
            return
        try:
            # RAW keeps names, reasons and identifiers literal, including leading '='.
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=self.config.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": updates},
            ).execute(num_retries=0)
        except HttpError as exc:
            raise sanction_error("write", details=extract_http_error_message(exc)) from exc
