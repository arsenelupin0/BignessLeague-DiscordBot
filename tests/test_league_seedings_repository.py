from __future__ import annotations

import json
import random
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from googleapiclient.errors import HttpError
from httplib2 import Response

from bigness_league_bot.application.services.league_seedings import (
    LeagueTeam, generate_league_seedings, league_fixture_rows,
)
from bigness_league_bot.application.services.match_standings import match_grid_row_number
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.google.league_seedings_repository import GoogleSheetsLeagueSeedingsRepository
from bigness_league_bot.infrastructure.google.team_sheets.errors import TeamSheetRequestError, TeamSheetWriteError
from bigness_league_bot.infrastructure.i18n.service import LocalizationService


class LeagueSeedingsRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            token="unused-test-token", google_service_account_file=Path(__file__),
            google_sheets_spreadsheet_id="test-spreadsheet",
            google_sheets_match_standings_sheet_name=(
                "Clasificación - GOLD DIVISION S4 TEST,Clasificación - SILVER DIVISION S4 TEST"
            ),
        )
        self.schedules = generate_league_seedings(tuple(
            LeagueTeam(f"{division} DIVISION S4 TEST", f"{division} Equipo {index}")
            for division in ("GOLD", "SILVER") for index in range(1, 9)
        ), rng=random.Random(1))
        self.repository = GoogleSheetsLeagueSeedingsRepository(self.settings)
        self.service = Mock()
        self.repository.client = Mock()
        self.repository.client.build_service.return_value = self.service
        self.sheet_titles = tuple(self.settings.google_sheets_match_standings_sheet_name.split(","))
        self.metadata = {"sheets": [{
            "properties": {"sheetId": sheet_id, "title": title,
                           "gridProperties": {"rowCount": 100, "columnCount": 30}},
            # Header and J labels are merged, outside fixture cells.
            "merges": [{"startRowIndex": 18, "endRowIndex": 19,
                        "startColumnIndex": 1, "endColumnIndex": 4},
                       {"startRowIndex": 19, "endRowIndex": 23,
                        "startColumnIndex": 0, "endColumnIndex": 1}],
        } for sheet_id, title in zip((101, 202), self.sheet_titles)]}
        self.service.spreadsheets.return_value.get.return_value.execute.return_value = self.metadata
        self.grids = [{"values": []}, {"values": []}]
        self.service.spreadsheets.return_value.values.return_value.batchGet.return_value.execute.return_value = {
            "valueRanges": self.grids,
        }

    def assert_rejected_without_write(self, key: str) -> None:
        with self.assertRaises(CommandUserError) as caught:
            self.repository.write_seedings_sync(self.schedules)
        self.assertEqual(caught.exception.message.key, f"errors.league_seedings.{key}")
        self.service.spreadsheets.return_value.batchUpdate.assert_not_called()
        localizer = LocalizationService.from_directory(
            directory=Path(__file__).resolve().parents[1] / "aa_resources/locales", default_locale="es-ES",
        )
        for locale in ("es-ES", "en-US"):
            text = localizer.render(caught.exception.message, locale=locale)
            self.assertNotIn("errors.league_seedings", text)
            self.assertNotIn("{", text)

    def test_one_atomic_batch_writes_only_game_one_of_both_configured_divisions(self) -> None:
        destinations = self.repository.write_seedings_sync(self.schedules)
        self.repository.client.build_service.assert_called_once_with(read_only=False)
        self.assertEqual([destination.worksheet_title for destination in destinations], list(self.sheet_titles))
        self.assertEqual([destination.ranges for destination in destinations], [("B20:D47",)] * 2)
        self.assertTrue(destinations[0].worksheet_url.endswith("#gid=101"))
        self.service.spreadsheets.return_value.values.return_value.batchGet.assert_called_once_with(
            spreadsheetId="test-spreadsheet",
            ranges=[f"'{title}'!A20:U47" for title in self.sheet_titles], valueRenderOption="FORMULA",
        )
        write = self.service.spreadsheets.return_value.batchUpdate
        write.assert_called_once()
        requests = write.call_args.kwargs["body"]["requests"]
        self.assertEqual(len(requests), 2)
        for request, schedule, sheet_id in zip(requests, self.schedules, (101, 202)):
            update = request["updateCells"]
            self.assertEqual(update["range"], {"sheetId": sheet_id, "startRowIndex": 19, "endRowIndex": 47,
                                               "startColumnIndex": 1, "endColumnIndex": 4})
            self.assertEqual(update["fields"], "userEnteredValue")
            self.assertEqual(len(update["rows"]), 28)
            for actual, planned in zip(update["rows"], league_fixture_rows(schedule)):
                self.assertEqual(actual["values"], [{"userEnteredValue": {"stringValue": planned.home}}, {},
                                                    {"userEnteredValue": {"stringValue": planned.away}}])
            for day in schedule.matchdays:
                for number, match in enumerate(day.matches, 1):
                    row = match_grid_row_number(matchday=day.number, match_number=number)
                    self.assertEqual(update["rows"][row - 20]["values"][0]["userEnteredValue"]["stringValue"],
                                     match.home)

    def test_formula_like_unicode_team_names_are_written_as_literal_strings(self) -> None:
        teams = tuple(LeagueTeam(f"{division} Division S4 TEST", f"{division} Equipo {index}")
                      for division in ("Gold", "Silver") for index in range(1, 9))
        name = '=HYPERLINK("url","Águilas 🇪🇸")'
        self.schedules = generate_league_seedings((replace(teams[0], team_name=name), *teams[1:]))
        self.repository.write_seedings_sync(self.schedules)
        payload = self.service.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        strings = [cell.get("userEnteredValue", {}).get("stringValue")
                   for request in payload["requests"] for row in request["updateCells"]["rows"]
                   for cell in row["values"]]
        self.assertEqual(strings.count(name), 7)
        self.assertNotIn("formulaValue", json.dumps(payload))

    def test_occupied_silver_prevents_gold_write_including_zero_or_empty_formula(self) -> None:
        for column, value in ((1, "Equipo"), (2, "0 - 0"), (5, "Otro GAME"), (18, "3 - 0 (FW)"),
                              (2, 0), (2, False), (1, '=IF(TRUE,"","")')):
            with self.subTest(column=column, value=value):
                # The read range starts at A, so account for J labels in column A.
                row = [""] * 21
                row[column] = value
                self.grids[1]["values"] = [row]
                self.assert_rejected_without_write("calendar_occupied")

    def test_matchday_labels_and_game_separator_cells_do_not_block_initial_seedings(self) -> None:
        self.grids[0]["values"] = [["J1", "", "", "", "separator"]]
        self.repository.write_seedings_sync(self.schedules)
        self.service.spreadsheets.return_value.batchUpdate.assert_called_once()

    def test_reading_failure_never_writes(self) -> None:
        self.service.spreadsheets.return_value.values.return_value.batchGet.return_value.execute.side_effect = HttpError(
            Response({"status": "403"}), b'{"error":{"message":"Missing access"}}',
        )
        with self.assertRaises(TeamSheetRequestError):
            self.repository.write_seedings_sync(self.schedules)
        self.service.spreadsheets.return_value.batchUpdate.assert_not_called()

    def test_google_write_rejection_is_localized_and_never_retries_a_division_separately(self) -> None:
        self.service.spreadsheets.return_value.batchUpdate.return_value.execute.side_effect = HttpError(
            Response({"status": "403"}), b'{"error":{"message":"Permission denied"}}',
        )
        with self.assertRaises(TeamSheetWriteError) as caught:
            self.repository.write_seedings_sync(self.schedules)
        self.assertEqual(caught.exception.message.key, "errors.league_seedings.google_write_failed")
        self.service.spreadsheets.return_value.batchUpdate.assert_called_once()

    def test_missing_silver_destination_is_rejected_without_writing_gold(self) -> None:
        self.metadata["sheets"].pop()
        self.assert_rejected_without_write("destination_not_found")

    def test_one_shared_destination_or_fallback_to_same_sheet_is_rejected(self) -> None:
        self.repository.worksheet_names = (self.sheet_titles[0],)
        self.assert_rejected_without_write("destination_configuration")
        self.repository.worksheet_names = (self.sheet_titles[0], "Unrelated")
        self.assert_rejected_without_write("destination_configuration")

    def test_destination_season_must_match_roster_season(self) -> None:
        title = self.sheet_titles[1].replace("S4", "S3")
        self.repository.worksheet_names = (self.sheet_titles[0], title)
        self.metadata["sheets"][1]["properties"]["title"] = title
        self.assert_rejected_without_write("destination_season_mismatch")

    def test_merged_cells_in_silver_fixture_area_or_short_grid_reject_both(self) -> None:
        self.metadata["sheets"][1]["merges"].append({
            "startRowIndex": 19, "endRowIndex": 20, "startColumnIndex": 1, "endColumnIndex": 3,
        })
        self.assert_rejected_without_write("invalid_grid")
        self.metadata["sheets"][1]["merges"].pop()
        self.metadata["sheets"][1]["properties"]["gridProperties"]["rowCount"] = 46
        self.assert_rejected_without_write("invalid_grid")

    def test_incomplete_read_of_two_calendars_rejects_all_writes(self) -> None:
        self.grids.pop()
        self.assert_rejected_without_write("grid_read_failed")

    def test_existing_destination_normalization_and_a1_escaping_are_reused(self) -> None:
        title = "Clasificacion - Gold Division S4 Test 'League'"
        self.repository.worksheet_names = (title.upper(), self.sheet_titles[1])
        self.metadata["sheets"][0]["properties"]["title"] = title
        destinations = self.repository.write_seedings_sync(self.schedules)
        self.assertEqual(destinations[0].worksheet_title, title)
        ranges = self.service.spreadsheets.return_value.values.return_value.batchGet.call_args.kwargs["ranges"]
        self.assertEqual(ranges[0], "'Clasificacion - Gold Division S4 Test ''League'''!A20:U47")


if __name__ == "__main__":
    unittest.main()
