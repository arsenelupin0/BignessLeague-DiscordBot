from __future__ import annotations

import unittest

from bigness_league_bot.application.services.match_replay_roster_candidates import find_replay_roster_name_candidate
from test_match_replay_verification import roster


class ReplayRosterCandidateTests(unittest.TestCase):
    def test_repeated_characters_and_unicode_names_can_suggest_an_individual_entry(self):
        entry = roster(player_name="Vives", epic_name="Viveeeesss")
        for name in ("Viveesss", "vivess", "VIVEEEESSS"):
            with self.subTest(name=name):
                result = find_replay_roster_name_candidate(name, (entry,))
                self.assertEqual(result.player, entry)
                self.assertFalse(result.ambiguous)
        unicode_entry = roster(epic_name="ᶠ ᵃ ᵏ ᵉDAVIDツ")
        self.assertEqual(find_replay_roster_name_candidate("f a k eDAVIDツ", (unicode_entry,)).player, unicode_entry)

    def test_short_missing_unrelated_or_excessively_long_names_do_not_propose_players(self):
        entry = roster(player_name="Vives", epic_name="Viveeeesss")
        for name in ("", "-", "abc", "Completely unrelated", "V" * 129):
            with self.subTest(name=name):
                result = find_replay_roster_name_candidate(name, (entry,))
                self.assertIsNone(result.player)
                self.assertFalse(result.ambiguous)

    def test_ties_are_ambiguous_regardless_of_roster_order(self):
        first = roster(player_name="Vives", epic_name="Viveeeesss")
        second = roster(player_name="Vives two", epic_name="Viveeesss", platform_id="another-id")
        for entries in ((first, second), (second, first)):
            result = find_replay_roster_name_candidate("Viveesss", entries)
            self.assertIsNone(result.player)
            self.assertTrue(result.ambiguous)


if __name__ == "__main__":
    unittest.main()
