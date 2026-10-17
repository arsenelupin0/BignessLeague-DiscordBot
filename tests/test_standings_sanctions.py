from __future__ import annotations

import unittest
from dataclasses import astuple, replace

from bigness_league_bot.application.services.match_standings import (
    MatchStandingGameResult, build_match_grid_manual_result_row_values, MatchGridManualResult,
    build_match_grid_standing_games, build_match_standings_rows,
)
from bigness_league_bot.application.services.standings_sanctions import (
    SanctionScope, StandingsSanction, add_sanction, annul_sanction, sanction_deductions,
    sanction_marker_updates, scope_team_names, validate_sanction,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.google.sanctions_sheet import (
    HEADERS, TABLE_TITLE, ledger_updates, parse_ledger,
)

WORKSHEET = "Clasificación - GOLD DIVISION S4 TEST"
SCOPE = SanctionScope.from_worksheet(WORKSHEET)


def sanction(**overrides) -> StandingsSanction:
    return replace(StandingsSanction(
        "123456789012345678", WORKSHEET, "S4", "GOLD", "Equipo A", 1, "Alineación indebida", "AI", 1, 1,
        "ACTIVA", "2026-10-17T15:00:00+00:00", "Staff (42)",
    ), **overrides)


class StandingsSanctionsTests(unittest.TestCase):
    def test_six_points_become_five_on_every_rebuild_and_eight_after_another_win(self):
        games = [MatchStandingGameResult(day, 1, "Equipo A", "Equipo B", 2, 0)
                 for day in (1, 2) for _ in range(3)]
        deductions = sanction_deductions((sanction(),), SCOPE, ("Equipo A", "Equipo B"))
        for _ in range(3):
            rows = build_match_standings_rows(("Equipo A", "Equipo B"), games, point_deductions=deductions)
            self.assertEqual(rows[0].points, 5)
        games.extend(MatchStandingGameResult(3, 1, "Equipo A", "Equipo B", 2, 0) for _ in range(3))
        self.assertEqual(build_match_standings_rows(("Equipo A", "Equipo B"), games,
                                                    point_deductions=deductions)[0].points, 8)

    def test_sanctions_are_applied_before_ranking_and_allow_negative_points(self):
        games = [MatchStandingGameResult(1, 1, "Equipo A", "Equipo B", 2, 0) for _ in range(3)]
        rows = build_match_standings_rows(("Equipo A", "Equipo B"), games, point_deductions={"Equipo A": 4})
        self.assertEqual([(row.team_name, row.points) for row in rows], [("Equipo B", 0), ("Equipo A", -1)])
        self.assertEqual(rows[1].series_won, 1)
        self.assertEqual(rows[1].goals_for, 6)

    def test_season_division_and_exact_destination_separate_test_and_production(self):
        records = (sanction(), sanction(identifier="old", worksheet=WORKSHEET.replace("S4", "S3"), season="S3"),
                   sanction(identifier="live", worksheet=WORKSHEET.removesuffix(" TEST")),
                   sanction(identifier="silver", worksheet=WORKSHEET.replace("GOLD", "SILVER"), division="SILVER"))
        self.assertEqual(sanction_deductions(records, SCOPE, ("Equipo A",)), {"Equipo A": 1})

    def test_annulment_preserves_original_audit_and_restores_points(self):
        original = sanction()
        record, = annul_sanction((original,), original.identifier, at="now", by="Admin (43)", reason="Recurso estimado")
        self.assertEqual(record.created_at, original.created_at)
        self.assertEqual(record.created_by, original.created_by)
        self.assertEqual(record.reason, original.reason)
        self.assertEqual(record.annulment_reason, "Recurso estimado")
        self.assertFalse(record.active)
        self.assertEqual(sanction_deductions((record,), SCOPE, ("Equipo A",)), {})
        with self.assertRaises(CommandUserError):
            annul_sanction((record,), record.identifier, at="again", by="other", reason="again")

    def test_same_interaction_is_idempotent_and_same_ai_match_cannot_be_duplicated(self):
        record = sanction()
        self.assertEqual(add_sanction((record,), record), (record,))
        for duplicate in (replace(record, identifier="other"), replace(record, points=2)):
            with self.assertRaises(CommandUserError):
                add_sanction((record,), duplicate)
        other_team = replace(record, identifier="other", team_name="Equipo B")
        self.assertEqual(len(add_sanction((record,), other_team)), 2)

    def test_multiple_general_sanctions_and_cancelled_ai_can_be_added(self):
        record = sanction(kind="OTRA", matchday=None, match_number=None)
        records = add_sanction((record,), replace(record, identifier="second", points=2))
        self.assertEqual(sanction_deductions(records, SCOPE, ("Equipo A",)), {"Equipo A": 3})
        cancelled = annul_sanction((sanction(),), sanction().identifier, at="now", by="staff", reason="recurso")
        self.assertEqual(len(add_sanction(cancelled, sanction(identifier="new"))), 2)

    def test_unknown_team_or_invalid_record_is_never_silently_ignored(self):
        with self.assertRaises(CommandUserError):
            sanction_deductions((sanction(),), SCOPE, ("Equipo B",))
        for change in ({"points": -1}, {"points": 0}, {"points": True}, {"reason": " "},
                       {"matchday": None}, {"matchday": 8}, {"match_number": 0},
                       {"season": "S3"}, {"division": "SILVER"}, {"state": "?"},
                       {"state": "ANULADA"}, {"kind": "FW"}):
            with self.subTest(change=change), self.assertRaises(CommandUserError):
                validate_sanction(sanction(**change))

    def test_ai_marks_the_sanctioned_team_without_changing_scores_and_is_removed_on_annulment(self):
        for label in ("3 - 0 (FW)", "0 - 3 (WO)", "NULO"):
            with self.subTest(label=label):
                row = ["J1", *build_match_grid_manual_result_row_values(MatchGridManualResult(
                    "Equipo A", "Equipo B", label))]
                games_before = build_match_grid_standing_games([row])
                updates = sanction_marker_updates([row], (sanction(),), SCOPE)
                self.assertEqual(updates, ((20, 1, "Equipo A (AI)"),))
                row[1] = updates[0][2]
                self.assertEqual(build_match_grid_standing_games([row]), games_before)
                self.assertEqual(sanction_marker_updates([row], (sanction(),), SCOPE), ())
                self.assertEqual(sanction_marker_updates([row], (), SCOPE), ((20, 1, "Equipo A"),))

    def test_both_teams_can_be_marked_and_annulling_one_keeps_the_other(self):
        row = ["J1", "Equipo A (AI)", "2 - 0", "Equipo B (AI)"]
        records = (sanction(), sanction(identifier="b", team_name="Equipo B"))
        self.assertEqual(sanction_marker_updates([row], records, SCOPE), ())
        self.assertEqual(sanction_marker_updates([row], records[1:], SCOPE), ((20, 1, "Equipo A"),))

    def test_wrong_match_is_rejected_and_general_sanctions_need_no_match(self):
        with self.assertRaises(CommandUserError):
            sanction_marker_updates([["J1", "Otro", "", "Equipo B"]], (sanction(),), SCOPE)
        self.assertEqual(sanction_marker_updates([], (sanction(kind="OTRA", matchday=None, match_number=None),), SCOPE),
                         ())

    def test_roster_selection_is_bound_to_season_division_and_environment(self):
        rosters = (("GOLD DIVISION S3 TEST", "Old"), ("GOLD DIVISION S4", "Live"),
                   ("GOLD DIVISION S4 TEST", "Equipo A"), ("SILVER DIVISION S4 TEST", "Silver"))
        self.assertEqual(scope_team_names(SCOPE, rosters), ("Equipo A",))
        with self.assertRaises(CommandUserError):
            scope_team_names(SCOPE, rosters[:2])


class SanctionsLedgerTests(unittest.TestCase):
    def test_legacy_team_bans_are_preserved_and_not_inferred_as_points(self):
        legacy = [["MX2", "", "", "", "", "", "", "Baneado al completo"], ["Jugador", "Discord ID"]]
        legacy.extend([[] for _ in range(34)])
        ledger = parse_ledger(legacy, merged_end_row=36)
        self.assertFalse(ledger.initialized)
        self.assertEqual(ledger.records, ())
        self.assertEqual(ledger.header_row, 40)
        self.assertEqual([u["range"] for u in ledger_updates(ledger, (sanction(),))],
                         ["'Sanciones'!A39", "'Sanciones'!A40:P40", "'Sanciones'!A41:P41"])
        self.assertEqual(legacy[0][0], "MX2")

    def test_parser_round_trip_audit_and_blank_rows(self):
        record = annul_sanction((sanction(),), sanction().identifier, at="now", by="Staff (44)", reason="Recurso")[0]
        values = [[TABLE_TITLE], list(HEADERS), [], ["" if v is None else v for v in astuple(record)]]
        ledger = parse_ledger(values)
        self.assertEqual(ledger.records, (record,))
        self.assertEqual(ledger.record_rows, (4,))
        self.assertEqual(ledger_updates(ledger, ledger.records), [])

    def test_broken_header_duplicate_identifiers_or_malformed_record_fail_closed(self):
        fields = list(astuple(sanction()))
        for values in ([[TABLE_TITLE]], [[HEADERS[0], "bad"]], [list(HEADERS), fields, fields],
                       [list(HEADERS), ["bad"]], [list(HEADERS), [*fields[:5], "-1", *fields[6:]]]):
            with self.subTest(values=values), self.assertRaises(CommandUserError):
                parse_ledger(values)

    def test_manual_duplicate_ai_records_with_different_ids_are_rejected(self):
        with self.assertRaises(CommandUserError):
            parse_ledger([list(HEADERS), list(astuple(sanction())), list(astuple(sanction(identifier="other")))])
