from __future__ import annotations

import unittest

from bigness_league_bot.application.services.match_replay_summaries import build_match_replay_roster_validation_summary
from bigness_league_bot.application.services.match_replay_tracker_identity import tracker_account_key
from test_match_replay_verification import player, resolve, roster

BASE = "https://rocketleague.tracker.network/rocket-league/profile/"


class ReplayTrackerReferenceTests(unittest.TestCase):
    def test_profile_reference_keeps_id_punctuation_and_decodes_url_encoding(self):
        self.assertEqual(tracker_account_key(BASE + "psn/Liquidcap_%20one/overview"), "psn:liquidcap_ one")
        self.assertEqual(tracker_account_key(BASE + "epic/%E3%83%84DAVID/overview"), "epic:ツdavid")

    def test_playstation_profile_aliases_share_the_same_account_reference(self):
        for platform in ("ps4", "ps5", "psn"):
            with self.subTest(platform=platform):
                self.assertEqual(tracker_account_key(BASE + platform + "/liquidcap_"), "psn:liquidcap_")

    def test_other_hosts_paths_and_invalid_urls_are_not_account_references(self):
        for url in (None, "", "https://[", BASE + "psn/", BASE + "unknown/id",
                    BASE + "psn/name%2Fother", BASE + "psn/name%0A", BASE + "psn/name/matches",
                    BASE.replace("tracker.network", "tracker.network.example.test") + "psn/name",
                    BASE.replace("https", "http") + "psn/name"):
            with self.subTest(url=url):
                self.assertIsNone(tracker_account_key(url))

    def test_link_does_not_verify_a_missing_registered_id(self):
        resolved = resolve(player(name="Other display", platform="ps5", platform_id="liquidcap_"),
                           (roster(platform="psn", platform_id="", tracker_url=BASE + "psn/liquidcap_"),))
        actual = resolved.games[0].blue.players[0]
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertEqual(actual.roster_player_name, "DAVID")
        self.assertEqual(actual.match_methods, ("platform",))
        self.assertEqual(summary.matched_unique_players, 0)
        self.assertEqual(summary.unmatched_players[0].unevaluated_methods, ("platform_id",))

    def test_account_columns_take_priority_over_a_conflicting_tracker_reference(self):
        other = roster(player_name="Other", platform_id="other-id", tracker_url=BASE + "epic/account-123")
        actual = resolve(entries=(roster(), other)).games[0].blue.players[0]
        self.assertEqual(actual.roster_player_name, "DAVID")
        self.assertEqual(actual.resolution_status, "matched")

    def test_duplicate_tracker_references_do_not_select_a_roster_entry(self):
        first = roster(platform_id="first-id", tracker_url=BASE + "epic/account-123")
        second = roster(player_name="Other", platform_id="second-id", tracker_url=first.tracker_url)
        actual = resolve(entries=(first, second)).games[0].blue.players[0]
        self.assertEqual(actual.resolution_status, "ambiguous")
        self.assertEqual(actual.registered_platform_id, "")

    def test_tracker_reference_never_removes_underscores_to_match_an_account(self):
        actual = resolve(player(platform="ps4", platform_id="liquidcap_"),
                         (roster(platform="psn", platform_id="other-id", tracker_url=BASE + "psn/liquidcap"),)
                         ).games[0].blue.players[0]
        self.assertEqual(actual.roster_player_name, "")
        self.assertEqual(actual.resolution_status, "unmatched")


if __name__ == "__main__":
    unittest.main()
