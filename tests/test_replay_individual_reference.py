from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from bigness_league_bot.application.services.match_replay_models import (
    MatchReplayDivision, MatchReplayGame, MatchReplayPlayer, MatchReplayReport,
    MatchReplayRosterPlayer, MatchReplayTeam,
)
from bigness_league_bot.application.services.match_replay_roster_resolution import resolve_match_replay_report_players
from bigness_league_bot.application.services.match_replay_summaries import build_match_replay_roster_validation_summary
from bigness_league_bot.infrastructure.discord.match_replay_messages import format_match_replay_roster_validation
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

# Read-only snapshot: GOLD DIVISION S4 and Replay Stats rows 233:260,
# 2026-10-26. The first replay binary SHA256 is
# 380d4b60187077148052e5e076570a25733fe8fc6d116209b321bd481815672c.
ASMA = "Asmathicks"
ELYGIO = "Elygio Esports academy"
CASES = (
    (ASMA, "Unique", "UniqueR321", "epic", "a40a7449e6da4d5fa7cb311cc29de448"),
    (ASMA, "KIMYOX", "Pol Gasly", "steam", "76561199027792393"),
    (ASMA, "Coes", "COES66", "epic", "a31364b7cde346cbb547872f093199dc"),
    (ELYGIO, "Elygio G14n", "Elygio G14N", "epic", "4dc97ccb65ac42e29c991698797fc6b9"),
    (ELYGIO, "lisalucchetta08", "LisaLucchetta08", "epic", "f1ea077d35684ba3996620464523f31a"),
    (ELYGIO, "pablo slave", "pablo slave", "epic", "1d2aed071d8b4f6687a1a7621326fa13"),
)


def registered(team, name, platform, identifier, epic=""):
    return MatchReplayRosterPlayer("GOLD DIVISION S4", team, name, "", platform, identifier, epic)


def fixture():
    entries = tuple(registered(team, name, platform, identifier) for team, name, _, platform, identifier in CASES)
    entries += (
        registered(ASMA, "Vives", "epic", "c34962d235fe40429e0c65a29e81fd8e", "Viveeeesss"),
        registered(ASMA, "yaago", "epic", "e1a6790c583948868f55ba93ab03fc58", "yaago."),
        registered(ASMA, "Oliver", "steam", "76561198048219993", "oliver_Twisted"),
        registered(ELYGIO, "nagi shishiroooo", "epic", "8ea06bd174a94acb97eb024a3ac3ccb0"),
    )
    players = tuple(MatchReplayPlayer(ign, platform, identifier) for _, _, ign, platform, identifier in CASES)
    unknown = MatchReplayPlayer("Viveesss", "ps4", "Viveesss")
    ids = ("e322677c-2334-463b-b3e3-001225c85f65", "7b7e25bb-a700-4ed1-89a7-0b2641303952",
           "dd872f31-0c5f-4cb2-aae3-842d23446de7", "28cef906-5877-4d9a-9e31-4c1beca78216")
    games = tuple(MatchReplayGame(
        number, replay_id, "https://ballchasing.com/replay/" + replay_id,
        MatchReplayTeam("blue", ASMA, goals[0], (unknown, players[0], players[1 if number < 3 else 2])),
        MatchReplayTeam("orange", ELYGIO, goals[1], players[3:]),
    ) for number, (replay_id, goals) in enumerate(zip(ids, ((4, 5), (1, 3), (2, 1), (2, 3))), 1))
    return MatchReplayReport(MatchReplayDivision.GOLD, 3, 3, ASMA, ELYGIO, games, 1, 3, ()), entries


class ReplayIndividualReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.localizer = LocalizationService.from_directory(
            directory=Path(__file__).resolve().parents[1] / "aa_resources/locales", default_locale="es-ES")

    def render(self, resolved):
        return format_match_replay_roster_validation(
            localizer=self.localizer, locale="es-ES",
            summary=build_match_replay_roster_validation_summary(resolved))

    def test_previous_resolution_never_overrides_the_current_excel_registration(self):
        report, entries = fixture()
        previously_registered = resolve_match_replay_report_players(report, (
            *entries, registered(ASMA, "Vives", "psn", "Viveesss")))
        resolved = resolve_match_replay_report_players(previously_registered, entries)
        actual = resolved.games[0].blue.players[0]
        self.assertEqual(actual.resolution_status, "name_candidate")
        self.assertEqual(actual.roster_player_name, "Vives")
        self.assertEqual(actual.registered_platform, "epic")
        self.assertEqual(actual.registered_platform_id, "c34962d235fe40429e0c65a29e81fd8e")
        self.assertEqual(build_match_replay_roster_validation_summary(resolved).matched_unique_players, 6)

    def test_pending_accounts_do_not_hide_an_individually_proven_platform_mismatch(self):
        report, entries = fixture()
        entries = (replace(entries[0], platform="steam"), *entries[1:])
        resolved = resolve_match_replay_report_players(report, entries)
        text = self.render(resolved)
        self.assertIn("Plataforma: **5/7** ❌", text)
        self.assertIn("**Plataforma · ❌ No coincide**", text)
        self.assertIn("**Excel:** `steam`", text)

    def test_team_platforms_are_never_presented_as_an_individual_excel_reference(self):
        report, entries = fixture()
        resolved = resolve_match_replay_report_players(report, entries)
        summary = build_match_replay_roster_validation_summary(resolved)
        issue, = summary.unmatched_players
        self.assertEqual((summary.unique_players, summary.matched_unique_players), (7, 6))
        self.assertEqual((issue.registered_platform, issue.registered_platform_id),
                         ("epic", "c34962d235fe40429e0c65a29e81fd8e"))
        self.assertNotIn("plataformas registradas", self.render(resolved))
        self.assertNotIn("`epic`, `steam`", self.render(resolved))

    def test_real_four_game_case_compares_both_fields_against_the_same_candidate(self):
        report, entries = fixture()
        resolved = resolve_match_replay_report_players(report, iter(entries))
        summary = build_match_replay_roster_validation_summary(resolved)
        issue, = summary.unmatched_players
        self.assertEqual((summary.total_appearances, summary.matched_appearances), (24, 20))
        self.assertEqual(issue.resolution_status, "name_candidate")
        self.assertEqual(issue.registered_player_name, "Vives")
        self.assertEqual(issue.registered_epic_name, "Viveeeesss")
        self.assertEqual(issue.missing_methods, ("platform", "platform_id"))
        self.assertFalse(issue.unevaluated_methods)
        self.assertFalse(summary.epic_name_unmatched_players)
        text = self.render(resolved)
        for expected in (
                "Jugadores verificados: **6/7** ❌", "Plataforma: **6/7** ❌", "Platform ID: **6/7** ❌",
                "**⚠️ Ficha candidata por similitud de nombre**",
                "**Replay (nombre en el juego):** `Viveesss`", "**Excel (Jugador):** `Vives`",
                "**Excel (Epic Name, como referencia):** `Viveeeesss`",
                "**Plataforma · ❌ No coincide**\n- **Replay:** `psn`\n- **Excel:** `epic`",
                "**Platform ID · ❌ No coincide**\n- **Replay:** `Viveesss`\n- **Excel:** `c34962d235fe40429e0c65a29e81fd8e`",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("sin ficha vinculada", text)
        self.assertNotIn("Avisos de Epic Name", text)
        for game in resolved.games:
            actual = next(player for player in game.blue.players if player.name == "Viveesss")
            self.assertEqual(actual.match_method, "name_similarity")
            self.assertEqual(actual.resolution_status, "name_candidate")
            self.assertIsNone(actual.epic_name)

    def test_playstation_aliases_still_agree_with_a_psn_candidate_while_the_id_differs(self):
        report, entries = fixture()
        entries = tuple(replace(entry, platform="psn", platform_id="registered-psn-id")
                        if entry.player_name == "Vives" else entry for entry in entries)
        for alias in ("ps4", "ps5", "psn"):
            with self.subTest(platform=alias):
                first = report.games[0]
                original = first.blue.players[0]
                game = replace(first, blue=replace(first.blue,
                                                   players=(replace(original, platform=alias),
                                                            *first.blue.players[1:])))
                resolved = resolve_match_replay_report_players(replace(report, games=(game,)), entries)
                summary = build_match_replay_roster_validation_summary(resolved)
                issue, = summary.unmatched_players
                self.assertEqual(issue.resolution_status, "name_candidate")
                self.assertEqual(issue.missing_methods, ("platform_id",))
                self.assertEqual(summary.matched_unique_players, 5)
                self.assertNotIn("**Plataforma · ❌ No coincide**", self.render(resolved))
                self.assertNotIn("equivalencia", self.render(resolved))

    def test_name_candidate_notice_is_localized_in_english(self):
        report, entries = fixture()
        summary = build_match_replay_roster_validation_summary(resolve_match_replay_report_players(report, entries))
        text = format_match_replay_roster_validation(localizer=self.localizer, locale="en-US", summary=summary)
        self.assertIn("Candidate roster entry based on name similarity", text)
        self.assertIn("**Excel (Player):** `Vives`", text)
        self.assertNotIn("Ficha candidata", text)

    def test_existing_id_or_tracker_resolution_has_priority_over_similar_names(self):
        report, entries = fixture()
        explicit = registered(ASMA, "Other Player", "psn", "Viveesss", "OtherName")
        resolved = resolve_match_replay_report_players(report, (*entries, explicit))
        actual = resolved.games[0].blue.players[0]
        self.assertEqual(actual.resolution_status, "matched")
        self.assertEqual(actual.roster_player_name, "Other Player")
        tracker = replace(explicit, platform="epic", platform_id="other-account",
                          tracker_url="https://rocketleague.tracker.network/rocket-league/profile/psn/Viveesss/overview")
        resolved = resolve_match_replay_report_players(report, (*entries, tracker))
        actual = resolved.games[0].blue.players[0]
        self.assertEqual(actual.roster_player_name, "Other Player")
        self.assertNotEqual(actual.resolution_status, "name_candidate")

    def test_a_similar_name_in_another_club_does_not_replace_the_individual_candidate(self):
        report, entries = fixture()
        entries += (registered(ELYGIO, "Viveesss", "epic", "another-id", "Viveesss"),)
        resolved = resolve_match_replay_report_players(report, entries)
        self.assertEqual(resolved.games[0].blue.players[0].roster_player_name, "Vives")

    def test_similarly_named_roster_entries_remain_ambiguous_without_comparing_arbitrary_fields(self):
        report, entries = fixture()
        entries += (registered(ASMA, "Other Vives", "epic", "another-id", "Viveeesss"),)
        resolved = resolve_match_replay_report_players(report, entries)
        actual = resolved.games[0].blue.players[0]
        self.assertEqual(actual.resolution_status, "name_ambiguous")
        self.assertEqual(actual.registered_platform, "")
        self.assertEqual(actual.registered_platform_id, "")
        text = self.render(resolved)
        self.assertIn("varios nombres similares", text)
        self.assertNotIn("**Plataforma · ❌ No coincide**", text)

    def test_multiple_replay_accounts_cannot_claim_the_same_name_candidate(self):
        report, entries = fixture()
        first = report.games[0]
        duplicate = MatchReplayPlayer("Viveeesss", "ps4", "another-psn-id")
        report = replace(report, games=(replace(first, blue=replace(first.blue,
                                                                    players=(*first.blue.players, duplicate))),))
        resolved = resolve_match_replay_report_players(report, entries)
        suspects = tuple(p for p in resolved.games[0].blue.players if p.name.startswith("Vive"))
        self.assertEqual(len(suspects), 2)
        self.assertTrue(all(p.resolution_status == "name_ambiguous" for p in suspects))
        self.assertTrue(all(not p.registered_platform_id for p in suspects))

    def test_a_claimed_roster_entry_is_not_reused_for_another_similar_account(self):
        report, entries = fixture()
        first = report.games[0]
        vives = next(entry for entry in entries if entry.player_name == "Vives")
        registered_account = MatchReplayPlayer("Viveeeesss", "epic", vives.platform_id)
        report = replace(report, games=(replace(first, blue=replace(first.blue,
                                                                    players=(*first.blue.players,
                                                                             registered_account))),))
        resolved = resolve_match_replay_report_players(report, entries)
        unknown = resolved.games[0].blue.players[0]
        self.assertNotEqual(unknown.resolution_status, "name_candidate")
        self.assertFalse(unknown.registered_platform_id)

    def test_duplicate_account_entries_are_not_resolved_by_a_name_hint(self):
        report, entries = fixture()
        duplicate = registered(ASMA, "Vives", "psn", "Viveesss", "Viveeeesss")
        resolved = resolve_match_replay_report_players(report, (*entries, duplicate, duplicate))
        self.assertEqual(resolved.games[0].blue.players[0].resolution_status, "ambiguous")
        self.assertFalse(resolved.games[0].blue.players[0].registered_platform_id)

    def test_conflicting_name_hints_for_the_same_account_across_games_do_not_choose_either_entry(self):
        report, entries = fixture()
        changed = report.games[2]
        changed_players = tuple(replace(player, name="yaago.") if player.name == "Viveesss" else player
                                for player in changed.blue.players)
        changed = replace(changed, blue=replace(changed.blue, players=changed_players))
        games = (*report.games[:2], changed, report.games[3])
        for ordered in (games, tuple(reversed(games))):
            with self.subTest(order=tuple(game.number for game in ordered)):
                resolved = resolve_match_replay_report_players(replace(report, games=ordered), entries)
                summary = build_match_replay_roster_validation_summary(resolved)
                issue, = summary.unmatched_players
                self.assertEqual(issue.resolution_status, "name_ambiguous")
                self.assertFalse(issue.registered_platform_id)
                self.assertFalse(issue.missing_methods)
                self.assertIn("varios nombres similares", self.render(resolved))


if __name__ == "__main__":
    unittest.main()
