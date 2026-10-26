from __future__ import annotations

import unittest

from bigness_league_bot.application.services.match_replay_roster_resolution import resolve_match_replay_report_players
from bigness_league_bot.application.services.match_replay_summaries import build_match_replay_roster_validation_summary
from bigness_league_bot.infrastructure.google.match_replay_rosters import list_division_roster_players_from_grids
from bigness_league_bot.infrastructure.google.team_sheets.models import SheetCell
from test_match_replay_verification import player, report

ACTUAL_ID = "8e669eab3ab2480f8e126ce62d0d67e1"
OLD_ID = "8e669eab3ab248f8e126ce62d0d67e1"
NAME = "ᶠ ᵃ ᵏ ᵉDAVIDツ"


def snapshot(identifier=ACTUAL_ID):
    grid = {}

    def row(number, values, column=0):
        grid.setdefault(number - 1, {}).update({column + i: SheetCell(value=v) for i, v in enumerate(values)})

    headers = ["Jugador", "Discord ID", "Platform", "Platform ID", "Epic Name", "MMR"]
    row(1, ["Goat Esports"])
    row(2, headers)
    row(3, ["Goat", "handle", "epic", "other-account", "Goat", "1200"])
    row(19, ["Astra Drift"])
    row(20, headers)
    row(21, ["Pangourmet", "pansito", "steam", "76561198851538602", "Pangourmet", "1481"])
    row(22, ["chaik0v", "chaik0v", "epic", "82f9c9b6df414a948b181b93ec98b9b0", "chaik0v", "1251"])
    row(23, ["ZkyKrono", "Zkykrono", "psn", "FaZe_IzAn_7", "ZkyKrono", "1211"])
    row(24, ["DAVID", NAME, "epic", identifier, NAME, "1174"])
    row(19, ["Triana CRL"], 7)
    row(20, headers, 7)
    row(21, ["Other", "other-handle", "epic", "different-account", "Other", "1400"], 7)
    return (("SILVER DIVISION S4", grid),)


class ReplayRosterSheetTests(unittest.TestCase):
    def test_astra_c24_d24_e24_are_read_without_column_or_block_shift(self):
        entries = list_division_roster_players_from_grids("SILVER DIVISION S4", snapshot())
        david = next(p for p in entries if p.player_name == "DAVID")
        self.assertEqual((david.team_name, david.platform, david.platform_id, david.epic_name),
                         ("Astra Drift", "epic", ACTUAL_ID, NAME))
        self.assertEqual(len(entries), 6)

    def test_missing_zero_and_corrupt_name_cannot_identify_the_roster_but_do_not_prove_wrong_platform(self):
        entries = list_division_roster_players_from_grids("SILVER DIVISION S4", snapshot(OLD_ID))
        resolved = resolve_match_replay_report_players(report(player(platform_id=ACTUAL_ID)), entries)
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertEqual(summary.matched_unique_players, 0)
        self.assertEqual(summary.unmatched_players[0].missing_methods, ())
        self.assertEqual(summary.unmatched_players[0].unevaluated_methods, ("platform", "platform_id"))

    def test_recovered_unicode_ign_does_not_become_an_epic_lookup_key(self):
        entries = list_division_roster_players_from_grids("SILVER DIVISION S4", snapshot(OLD_ID))
        resolved = resolve_match_replay_report_players(report(player(platform_id=ACTUAL_ID, name=NAME)), entries)
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertEqual(summary.unmatched_players[0].missing_methods, ())
        self.assertEqual(summary.unmatched_players[0].unevaluated_methods, ("platform", "platform_id"))
        self.assertEqual({m.method: m.count for m in summary.match_methods}["platform"], 0)

    def test_corrected_sheet_verifies_account_even_if_analyzer_name_is_corrupted(self):
        entries = list_division_roster_players_from_grids("SILVER DIVISION S4", snapshot())
        resolved = resolve_match_replay_report_players(report(player(platform_id=ACTUAL_ID)), entries)
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertEqual(summary.matched_unique_players, 1)
        self.assertFalse(summary.unmatched_players)

    def test_tracker_hyperlink_locates_the_row_without_overriding_its_platform_id_column(self):
        grids = snapshot(OLD_ID)
        grids[0][1][23][4] = SheetCell(
            value=NAME,
            hyperlink=f"https://rocketleague.tracker.network/rocket-league/profile/epic/{ACTUAL_ID}/overview",
        )
        entries = list_division_roster_players_from_grids("SILVER DIVISION S4", grids)
        resolved = resolve_match_replay_report_players(report(player(platform_id=ACTUAL_ID)), entries)
        actual = resolved.games[0].blue.players[0]
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertEqual(actual.roster_player_name, "DAVID")
        self.assertEqual(actual.registered_platform_id, OLD_ID)
        self.assertEqual(summary.matched_unique_players, 0)
        self.assertEqual(summary.unmatched_players[0].missing_methods, ("platform_id",))
