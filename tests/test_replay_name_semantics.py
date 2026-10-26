from __future__ import annotations

import unittest
from dataclasses import replace

import test_match_replay_verification as replay_cases
from bigness_league_bot.application.services.match_replay_identity import normalize_epic_display_name
from bigness_league_bot.application.services.match_replay_names import ReplayAccountName, apply_replay_account_names
from bigness_league_bot.application.services.match_replay_summaries import build_match_replay_roster_validation_summary
from test_match_replay_verification import player, report, resolve, roster


class ReplayNameSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        replay_cases.ReplayVerificationMessagesTests.setUpClass()
        cls.renderer = replay_cases.ReplayVerificationMessagesTests()

    def test_screenshot_igns_differ_from_epic_names_without_creating_account_notices(self):
        cases = (("Arsene Lupin", "arsenelupin0", "steam", "76561198311931080"),
                 ("ArtickRL", "ArtiickO_O", "ps4", "ArtickRL"),
                 ("Malamadre332", "s0cr4m clipped u", "ps4", "Malamadre332"))
        for ign, epic, platform, identifier in cases:
            with self.subTest(ign=ign):
                registered = roster(epic_name=epic, platform="psn" if platform == "ps4" else platform,
                                    platform_id=identifier)
                resolved = resolve(player(name=ign, platform=platform, platform_id=identifier), (registered,))
                summary = build_match_replay_roster_validation_summary(resolved)
                text = self.renderer.render(resolved)
                self.assertEqual(summary.matched_unique_players, 1)
                self.assertFalse(summary.epic_name_unmatched_players)
                self.assertEqual(next(m.evaluated_count for m in summary.match_methods if m.method == "epic_name"), 0)
                self.assertNotIn("Epic Name", text)
                self.assertNotIn("⚠️", text)

    def test_supplied_replay_and_roster_snapshot_verify_six_accounts_without_epic_name_notices(self):
        # AD533872421E2D47898AC9B1A0ABE4EB.replay, SHA256
        # a72048409d15645e590263952a16993f5db1bad05051ae03f798075f476824e2.
        # IGN / account IDs extracted from header and network; Epic names from Sheets.
        cases = (
            ("Arsene Lupin", "steam", "76561198311931080", "arsenelupin0"),
            ("Demon_Naico", "epic", "e41e74c0b0bd420499f156f6d67e89e9", "Demon_Naico"),
            ("alegears", "epic", "221f5159c5f549e885ab2687cd437fa7", "alegears"),
            ("Beltrixzz", "psn", "Beltrixzz", "Beltrixzz"),
            ("Malamadre332", "psn", "Malamadre332", "s0cr4m clipped u"),
            ("ArtickRL", "psn", "ArtickRL", "ArtiickO_O"),
        )
        players = tuple(player(name=ign, platform=platform, platform_id=identifier)
                        for ign, platform, identifier, _ in cases)
        entries = tuple(roster(player_name=ign, platform=platform, platform_id=identifier, epic_name=epic)
                        for ign, platform, identifier, epic in cases)
        resolved = replay_cases.resolve_match_replay_report_players(report(*players), entries)
        summary = build_match_replay_roster_validation_summary(resolved)
        text = self.renderer.render(resolved)
        self.assertEqual(summary.matched_unique_players, 6)
        self.assertFalse(summary.epic_name_unmatched_players)
        self.assertIn("Jugadores verificados: **6/6** ✅", text)
        self.assertIn("Platform ID: **6/6** ✅", text)
        self.assertNotIn("Avisos", text)
        self.assertNotIn("Epic Name", text)

    def test_ballchasing_player_name_is_not_an_epic_display_name_even_on_epic_platform(self):
        payload = {"id": "sample", "blue": {"players": [{"name": "IGN", "id": {"platform": "epic", "id": "account"}}]},
                   "orange": {"players": []}}
        actual = replay_cases._parse_replay_payload(payload).blue.players[0]
        self.assertEqual(actual.name, "IGN")
        self.assertIsNone(actual.epic_name)

    def test_actual_epic_name_mismatch_remains_informational_in_both_locales(self):
        resolved = resolve(player(name="Steam IGN", epic_name="actual_epic"))
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertEqual(summary.matched_unique_players, 1)
        self.assertEqual(summary.epic_name_unmatched_players[0].detected_epic_name, "actual_epic")
        for locale, label in (("es-ES", "Epic Name obtenido"), ("en-US", "Obtained Epic Name")):
            with self.subTest(locale=locale):
                text = self.renderer.render(resolved, locale)
                self.assertIn(f"**{label}:** `actual_epic`", text)
                self.assertIn(f"**Excel (Epic Name):** `{roster().epic_name}`", text)
                self.assertIn("**1/1** ✅", text)
                self.assertNotIn("Steam IGN", text)
                self.assertNotIn("❌", text)

    def test_matching_actual_epic_name_is_independent_of_the_ign(self):
        resolved = resolve(player(name="Other IGN", epic_name=roster().epic_name))
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertFalse(summary.epic_name_unmatched_players)
        self.assertIn("epic_name", resolved.games[0].blue.players[0].match_methods)
        self.assertEqual(next(m.count for m in summary.match_methods if m.method == "epic_name"), 1)

    def test_absent_or_placeholder_epic_name_is_not_an_evaluated_mismatch(self):
        for value in (None, "", " ", "-"):
            with self.subTest(epic_name=value):
                resolved = resolve(player(name=roster().epic_name, epic_name=value))
                summary = build_match_replay_roster_validation_summary(resolved)
                self.assertFalse(summary.epic_name_unmatched_players)
                self.assertNotIn("epic_name", resolved.games[0].blue.players[0].match_methods)
                self.assertEqual(next(m.evaluated_count for m in summary.match_methods if m.method == "epic_name"), 0)

    def test_unmatched_accounts_do_not_show_epic_name_notices_for_missing_values(self):
        for detected, registered in ((None, "registered"), ("", "registered"), (" ", "registered"),
                                     ("-", "registered"), ("actual", ""), ("actual", "-")):
            with self.subTest(detected=detected, registered=registered):
                resolved = resolve(player(platform="steam", epic_name=detected), (roster(epic_name=registered),))
                text = self.renderer.render(resolved)
                self.assertIn("**Plataforma · ❌ No coincide**", text)
                self.assertNotIn("Epic Name", text)

    def test_real_epic_name_can_locate_a_row_but_cannot_verify_a_wrong_id(self):
        resolved = resolve(player(name="Different Steam IGN", epic_name=roster().epic_name, platform_id="wrong-id"))
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertEqual(summary.matched_unique_players, 0)
        self.assertEqual(summary.unmatched_players[0].missing_methods, ("platform_id",))
        self.assertEqual(summary.unmatched_players[0].registered_player_name, roster().player_name)

    def test_unicode_ign_recovery_does_not_overwrite_a_separately_obtained_epic_name(self):
        original = report(player(name="Corrupt IGN", epic_name="actual_epic")).games[0]
        enriched = apply_replay_account_names(original, (ReplayAccountName("epic", "account-123", "ᶠ ᵃ ᵏ ᵉDAVIDツ"),))
        actual = enriched.blue.players[0]
        self.assertEqual(actual.name, "ᶠ ᵃ ᵏ ᵉDAVIDツ")
        self.assertEqual(actual.epic_name, "actual_epic")
        self.assertEqual(actual.ballchasing_name, "Corrupt IGN")

    def test_epic_name_comparison_preserves_punctuation_and_internal_spaces(self):
        self.assertNotEqual(normalize_epic_display_name("epic_name"), normalize_epic_display_name("epicname"))
        self.assertNotEqual(normalize_epic_display_name("epic name"), normalize_epic_display_name("epicname"))
        self.assertEqual(normalize_epic_display_name(" EPIC_Name "), "epic_name")

    def test_legacy_method_flag_without_an_actual_epic_name_does_not_claim_a_comparison(self):
        resolved = resolve().games[0].blue.players[0]
        resolved = replace(resolved, match_methods=("platform", "platform_id", "epic_name"))
        summary = build_match_replay_roster_validation_summary(report(resolved))
        epic = next(m for m in summary.match_methods if m.method == "epic_name")
        self.assertEqual((epic.count, epic.evaluated_count), (0, 0))
        self.assertFalse(summary.epic_name_unmatched_players)


if __name__ == "__main__":
    unittest.main()
