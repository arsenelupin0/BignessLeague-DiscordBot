"""Prepare the points-sanctions register below existing ban dossiers, without migrating bans.

Preview by default. Use --apply to write the title and header only, then verify the preserved archive.
"""
from __future__ import annotations

import argparse
import json
import socket

from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.google.sanctions_sheet import (
    HEADERS, SHEET_NAME, TABLE_TITLE, SanctionsSheetStore, parse_ledger, sheet_range,
)
from bigness_league_bot.infrastructure.google.team_sheets.client import GoogleSheetsClient
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write the empty register after verifying the legacy area.")
    args = parser.parse_args()
    socket.setdefaulttimeout(20)
    config = TeamSheetLookupConfig.from_settings(Settings.from_env())
    service = GoogleSheetsClient(config).build_service(read_only=not args.apply)
    store = SanctionsSheetStore(config)
    metadata = service.spreadsheets().get(
        spreadsheetId=config.spreadsheet_id, ranges=[SHEET_NAME],
        fields="sheets(properties(sheetId,title,gridProperties),merges)",
    ).execute(num_retries=0)["sheets"][0]
    properties = metadata["properties"]
    assert properties["title"] == SHEET_NAME
    before = service.spreadsheets().values().get(
        spreadsheetId=config.spreadsheet_id, range=sheet_range(SHEET_NAME, "A:Z"), valueRenderOption="FORMULA",
    ).execute(num_retries=0).get("values", [])
    merged_end = max((merge.get("endRowIndex", 0) for merge in metadata.get("merges", [])), default=0)
    ledger = parse_ledger(store.read_values(service, sheet_range(SHEET_NAME, "A:Z")), merged_end_row=merged_end)
    if ledger.initialized:
        print(json.dumps({"initialized": True, "header_row": ledger.header_row, "records": len(ledger.records)}))
        return
    title_row = ledger.header_row - 2  # API indices are zero-based.
    header_row = ledger.header_row - 1
    if properties["gridProperties"]["rowCount"] <= ledger.header_row or properties["gridProperties"][
        "columnCount"] < 16:
        raise ValueError("The sheet needs at least 16 columns and one blank row after the header.")
    summary = {"apply": args.apply, "preserved_rows": len(before),
               "title_range": f"A{title_row + 1}:P{title_row + 1}",
               "header_range": f"A{ledger.header_row}:P{ledger.header_row}", "records": 0}
    if not args.apply:
        print(json.dumps(summary))
        return
    sheet_id = properties["sheetId"]
    title_area = {"sheetId": sheet_id, "startRowIndex": title_row, "endRowIndex": title_row + 1,
                  "startColumnIndex": 0, "endColumnIndex": 16}
    header_area = {**title_area, "startRowIndex": header_row, "endRowIndex": header_row + 1}
    requests = [
        {"updateCells": {"start": {"sheetId": sheet_id, "rowIndex": title_row, "columnIndex": 0},
                         "rows": [{"values": [{"userEnteredValue": {"stringValue": TABLE_TITLE}}]},
                                  {"values": [{"userEnteredValue": {"stringValue": name}} for name in HEADERS]}],
                         "fields": "userEnteredValue"}},
        {"mergeCells": {"range": title_area, "mergeType": "MERGE_ROWS"}},
        {"repeatCell": {"range": title_area, "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.8, "green": 0, "blue": 0}, "horizontalAlignment": "CENTER",
            "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        }}, "fields": "userEnteredFormat"}},
        {"repeatCell": {"range": header_area, "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.93, "green": 0.93, "blue": 0.93}, "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP", "textFormat": {"bold": True, "fontSize": 10},
        }}, "fields": "userEnteredFormat"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS",
                                                 "startIndex": header_row, "endIndex": header_row + 1},
                                       "properties": {"pixelSize": 56}, "fields": "pixelSize"}},
    ]
    for column, choices in ((7, ("AI", "OTRA")), (10, ("ACTIVA", "ANULADA"))):
        requests.append({"setDataValidation": {
            "range": {"sheetId": sheet_id, "startRowIndex": header_row + 1,
                      "endRowIndex": properties["gridProperties"]["rowCount"],
                      "startColumnIndex": column, "endColumnIndex": column + 1},
            "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": value} for value in choices]},
                     "strict": True, "showCustomUi": True},
        }})
    # Recheck the inputs immediately before the one mutation. Other editors should avoid this area during preparation.
    current = service.spreadsheets().values().get(
        spreadsheetId=config.spreadsheet_id, range=sheet_range(SHEET_NAME, "A:Z"), valueRenderOption="FORMULA",
    ).execute(num_retries=0).get("values", [])
    if current != before:
        raise ValueError("Sanciones changed during preparation; no changes were written.")
    service.spreadsheets().batchUpdate(spreadsheetId=config.spreadsheet_id,
                                       body={"requests": requests}).execute(num_retries=0)
    after = service.spreadsheets().values().get(
        spreadsheetId=config.spreadsheet_id, range=sheet_range(SHEET_NAME, "A:Z"), valueRenderOption="FORMULA",
    ).execute(num_retries=0).get("values", [])
    if after[:len(before)] != before:
        raise ValueError("Legacy preservation verification failed.")
    actual = store.read(service)
    assert actual.initialized and actual.header_row == ledger.header_row and not actual.records
    print(json.dumps({**summary, "initialized": True, "legacy_values_and_formulas_preserved": True}))


if __name__ == "__main__":
    main()
