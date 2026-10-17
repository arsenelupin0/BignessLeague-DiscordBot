from __future__ import annotations

import copy
import re
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from googleapiclient.errors import HttpError
from httplib2 import Response

from bigness_league_bot.application.services.match_replays import (
    MatchReplayDivision, MatchReplayGame, MatchReplayReport, MatchReplayTeam,
)
from bigness_league_bot.application.services.match_standings import MatchGridManualResult
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.google.match_standings_repository import GoogleSheetsMatchStandingsRepository
from bigness_league_bot.infrastructure.google.sanctions_sheet import HEADERS, TABLE_TITLE, parse_ledger
from bigness_league_bot.infrastructure.google.standings_sanctions_repository import \
    GoogleSheetsStandingsSanctionsRepository
from test_standings_sanctions import WORKSHEET


class FakeSheets:
    """In-memory adapter exercising the real repositories and their read/write boundaries."""

    def __init__(self):
        self.values = {"Sanciones": [["MX2", "", "", "", "", "", "", "Baneado"],
                                     ["NEXUS"], [], [TABLE_TITLE], list(HEADERS)],
                       WORKSHEET: [[] for _ in range(47)],
                       WORKSHEET.replace("GOLD", "SILVER"): [[] for _ in range(47)]}
        for start in (19, 23):
            self.values[WORKSHEET][start] = ["J", "Equipo A", "2 - 0", "Equipo B", "",
                                             "Equipo A", "2 - 0", "Equipo B", "",
                                             "Equipo A", "2 - 0", "Equipo B"]
        self.writes = []
        self.fail_read = None
        self.fail_write = False

    def spreadsheets(self):
        return self

    def execute_result(self, function):
        return SimpleNamespace(execute=lambda **kwargs: function())

    def get(self, **kwargs):
        if "range" not in kwargs:
            return self.execute_result(lambda: {"sheets": [{"properties": {"title": name}}
                                                           for name in self.values]})

        def read():
            area = kwargs["range"]
            if self.fail_read and self.fail_read in area:
                raise HttpError(Response({"status": "403"}), b'{"error":{"message":"Denied"}}')
            title, bounds = area.split("!")
            title = title.strip("'").replace("''", "'")
            data = self.values[title]
            if bounds == "A:Z":
                result = copy.deepcopy(data)
            else:
                start, end = map(int, re.findall(r"\d+", bounds))
                result = copy.deepcopy(data[start - 1:end])
            return {"values": result}

        return self.execute_result(read)

    def batchUpdate(self, **kwargs):
        return self.execute_result(lambda: self.commit(kwargs["body"]["data"]))

    def commit(self, updates):
        if self.fail_write:
            raise HttpError(Response({"status": "403"}), b'{"error":{"message":"Denied"}}')
        self.writes.append(copy.deepcopy(updates))
        for update in updates:
            title, area = update["range"].split("!")
            title = title.strip("'").replace("''", "'")
            column_letters, row = re.match(r"([A-Z]+)(\d+)", area).groups()
            column = 0
            for letter in column_letters:
                column = column * 26 + ord(letter) - 64
            column -= 1
            start = int(row) - 1
            for offset, new in enumerate(update["values"]):
                while len(self.values[title]) <= start + offset:
                    self.values[title].append([])
                target = self.values[title][start + offset]
                target.extend([""] * max(0, column + len(new) - len(target)))
                target[column:column + len(new)] = new
        return {}


class SanctionsRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSheets()
        self.service = SimpleNamespace(spreadsheets=lambda: SimpleNamespace(
            get=self.fake.get, values=lambda: self.fake,
        ))
        settings = Settings(token="unused", google_service_account_file=Path(__file__),
                            google_sheets_spreadsheet_id="test",
                            google_sheets_match_standings_sheet_name=WORKSHEET + "," + WORKSHEET.replace("GOLD",
                                                                                                         "SILVER"))
        self.repository = GoogleSheetsStandingsSanctionsRepository(settings)
        self.standings = GoogleSheetsMatchStandingsRepository(settings)
        for repository in (self.repository.standings, self.standings):
            repository.client = Mock()
            repository.client.build_service.return_value = self.service
        self.kwargs = dict(identifier="123", team_name="Equipo A", points=1, reason="Alineación indebida", kind="AI",
                           matchday=1, match_number=1, actor="Staff (42)",
                           rosters=(("GOLD DIVISION S4 TEST", "Equipo A"), ("GOLD DIVISION S4 TEST", "Equipo B")))

    def add(self, **kwargs):
        return self.repository.add_sync(MatchReplayDivision.GOLD, **{**self.kwargs, **kwargs})

    def points(self, result):
        return next(row.points for row in result.standings if row.team_name == "Equipo A")

    def test_add_refresh_and_annul_write_audit_standings_and_marker_together(self):
        original_legacy = copy.deepcopy(self.fake.values["Sanciones"][:2])
        result = self.add()
        self.assertEqual(self.points(result), 5)
        self.assertEqual(self.fake.values[WORKSHEET][19][1], "Equipo A (AI)")
        self.assertEqual(len(self.fake.writes), 1)
        ranges = [u["range"] for u in self.fake.writes[0]]
        self.assertIn("'Sanciones'!A6:P6", ranges)
        self.assertIn(f"'{WORKSHEET}'!A3:I11", ranges)
        self.assertIn(f"'{WORKSHEET}'!B20", ranges)
        refreshed = self.standings.refresh_division_standings_report_sync(MatchReplayDivision.GOLD,
                                                                          team_names=("Equipo A", "Equipo B"))
        self.assertEqual(refreshed.rows[0].points, 5)
        annulled = self.repository.annul_sync(MatchReplayDivision.GOLD, identifier="123", actor="Admin (43)",
                                              reason="Recurso", rosters=self.kwargs["rosters"])
        self.assertEqual(self.points(annulled), 6)
        self.assertEqual(self.fake.values[WORKSHEET][19][1], "Equipo A")
        self.assertEqual(self.fake.values["Sanciones"][:2], original_legacy)
        record, = parse_ledger(self.fake.values["Sanciones"]).records
        self.assertEqual(record.annulled_by, "Admin (43)")

    def test_replay_upload_overwrites_grid_but_reapplies_active_sanctions_and_ai(self):
        self.add()
        games = tuple(MatchReplayGame(i, str(i), "https://example.test/replay",
                                      MatchReplayTeam("blue", "Equipo A", 3, ()),
                                      MatchReplayTeam("orange", "Equipo B", 1, ())) for i in (1, 2, 3))
        report = MatchReplayReport(MatchReplayDivision.GOLD, 1, 1, "Equipo A", "Equipo B", games, 3, 0, ())
        result = self.standings.sync_report_to_standings_sync(report, team_names=("Equipo A", "Equipo B"))
        self.assertEqual(result.rows[0].points, 5)
        self.assertEqual(self.fake.values[WORKSHEET][19][1], "Equipo A (AI)")
        self.assertEqual(self.fake.values[WORKSHEET][19][2], "3 - 1")
        self.assertEqual(len(parse_ledger(self.fake.values["Sanciones"]).records), 1)

    def test_fw_wo_nulo_recalculations_keep_sanctions_and_markers(self):
        self.add()
        for score, points in (("3 - 0 (FW)", 5), ("0 - 3 (WO)", 2), ("NULO", 2)):
            with self.subTest(score=score):
                result = self.standings.sync_manual_result_to_standings_sync(
                    MatchReplayDivision.GOLD, matchday=1, match_number=1,
                    result=MatchGridManualResult("Equipo A", "Equipo B", score), team_names=("Equipo A", "Equipo B"))
                self.assertEqual(next(row.points for row in result.rows if row.team_name == "Equipo A"), points)
                self.assertEqual(self.fake.values[WORKSHEET][19][1], "Equipo A (AI)")
                self.assertEqual(self.fake.values[WORKSHEET][19][2], score)

    def test_missing_or_corrupt_ledger_never_recalculates_as_zero_sanctions(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                if corrupt:
                    self.fake.values["Sanciones"].append(["invalid"])
                    self.fake.fail_read = None
                else:
                    self.fake.fail_read = "Sanciones"
                with self.assertRaises(CommandUserError):
                    self.standings.refresh_division_standings_report_sync(MatchReplayDivision.GOLD,
                                                                          team_names=("Equipo A", "Equipo B"))
                self.assertEqual(self.fake.writes, [])

    def test_bad_match_or_unknown_team_never_saves_partial_sanction(self):
        for kwargs in ({"team_name": "Other"}, {"match_number": 4}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CommandUserError):
                self.add(**kwargs)
            self.assertEqual(self.fake.writes, [])

    def test_failed_atomic_write_keeps_audit_points_and_markers_unchanged(self):
        original = copy.deepcopy(self.fake.values)
        self.fake.fail_write = True
        with self.assertRaises(CommandUserError):
            self.add()
        self.assertEqual(self.fake.values, original)

    def test_retry_does_not_duplicate_and_simultaneous_ai_requests_are_serialized(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.add, identifier=identifier) for identifier in ("one", "two")]
            results = []
            for future in futures:
                try:
                    results.append(future.result(timeout=5))
                except CommandUserError as exc:
                    self.assertEqual(exc.message.key, "sanctions.errors.duplicate")
        self.assertEqual(len(results), 1)
        self.assertEqual(self.points(self.add(identifier=results[0].sanction.identifier)), 5)
        self.assertEqual(len(parse_ledger(self.fake.values["Sanciones"]).records), 1)

    def test_list_and_annul_are_scoped_to_exact_sheet(self):
        self.add()
        scope, records = self.repository.list_sync(MatchReplayDivision.SILVER)
        self.assertIn("SILVER", scope.worksheet)
        self.assertEqual(records, ())
        writes = len(self.fake.writes)
        with self.assertRaises(CommandUserError):
            self.repository.annul_sync(MatchReplayDivision.SILVER, identifier="123", actor="Admin (43)",
                                       reason="Recurso", rosters=(("SILVER DIVISION S4 TEST", "Equipo A"),))
        self.assertEqual(len(self.fake.writes), writes)

    def test_manual_excel_edit_to_discount_is_picked_up_on_next_refresh(self):
        self.add()
        self.fake.values["Sanciones"][5][5] = 2
        result = self.standings.refresh_division_standings_report_sync(MatchReplayDivision.GOLD,
                                                                       team_names=("Equipo A", "Equipo B"))
        self.assertEqual(result.rows[0].points, 4)

    def test_formula_like_reason_is_written_literally(self):
        result = self.add(reason='=HYPERLINK("https://example.test", "Motivo")')
        self.assertEqual(self.fake.values["Sanciones"][5][6], result.sanction.reason)

    def test_uninitialized_or_deleted_register_never_becomes_zero_sanctions(self):
        self.fake.values["Sanciones"] = [["MX2"], ["NEXUS"]]
        with self.assertRaises(CommandUserError):
            self.standings.refresh_division_standings_report_sync(MatchReplayDivision.GOLD,
                                                                  team_names=("Equipo A", "Equipo B"))
        self.assertEqual(self.fake.writes, [])

    def test_administrative_result_and_classification_are_not_partially_saved_when_ledger_read_fails(self):
        self.add()
        original = copy.deepcopy(self.fake.values)
        self.fake.fail_read = "Sanciones"
        with self.assertRaises(CommandUserError):
            self.standings.sync_manual_result_to_standings_sync(
                MatchReplayDivision.GOLD, matchday=1, match_number=1,
                result=MatchGridManualResult("Equipo A", "Equipo B", "NULO"), team_names=("Equipo A", "Equipo B"))
        self.assertEqual(self.fake.values, original)

    def test_replay_results_and_classification_commit_in_one_request(self):
        self.add()
        games = tuple(MatchReplayGame(i, str(i), "https://example.test/replay",
                                      MatchReplayTeam("blue", "Equipo A", 3, ()),
                                      MatchReplayTeam("orange", "Equipo B", 1, ())) for i in (1, 2, 3))
        report = MatchReplayReport(MatchReplayDivision.GOLD, 1, 1, "Equipo A", "Equipo B", games, 3, 0, ())
        original = copy.deepcopy(self.fake.values)
        self.fake.fail_write = True
        with self.assertRaises(CommandUserError):
            self.standings.sync_report_to_standings_sync(report, team_names=("Equipo A", "Equipo B"))
        self.assertEqual(self.fake.values, original)
        self.fake.fail_write = False
        count = len(self.fake.writes)
        self.standings.sync_report_to_standings_sync(report, team_names=("Equipo A", "Equipo B"))
        self.assertEqual(len(self.fake.writes), count + 1)
        ranges = [u["range"] for u in self.fake.writes[-1]]
        self.assertEqual(ranges, [f"'{WORKSHEET}'!A3:I11", f"'{WORKSHEET}'!B20:U20"])
