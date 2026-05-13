from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from bigness_league_bot.application.services.match_replay_summaries import (  # noqa: E402
    build_match_replay_roster_validation_summary,
)
from bigness_league_bot.application.services.match_replays import (  # noqa: E402
    MatchReplayDivision,
    MatchReplayGame,
    MatchReplayPlayer,
    MatchReplayRosterPlayer,
    MatchReplayTeam,
    build_match_replay_report,
    resolve_match_replay_report_players,
)


class MatchReplayPlayerResolutionTests(unittest.TestCase):
    def test_epic_name_match_supports_japanese_characters(self) -> None:
        report = _resolved_report(
            replay_player=MatchReplayPlayer(name="ッ", platform="epic", platform_id="epic-id"),
            roster_player=MatchReplayRosterPlayer(
                division_name="SILVER DIVISION S3",
                team_name="SPARK",
                player_name="Roster Player",
                discord_name="DiscordUser",
                epic_name="ッ",
                rocket_name="Other Name",
            ),
        )

        player = report.games[0].blue.players[0]
        summary = build_match_replay_roster_validation_summary(report)

        self.assertEqual("matched", player.resolution_status)
        self.assertEqual("epic_name", player.match_method)
        self.assertEqual(("epic_name",), player.match_methods)
        self.assertEqual(1, summary.matched_unique_players)
        self.assertEqual(0, summary.unmatched_unique_players)

    def test_rocket_name_match_does_not_verify_epic_identity(self) -> None:
        report = _resolved_report(
            replay_player=MatchReplayPlayer(name="ッ", platform="epic", platform_id="epic-id"),
            roster_player=MatchReplayRosterPlayer(
                division_name="SILVER DIVISION S3",
                team_name="SPARK",
                player_name="Roster Player",
                discord_name="DiscordUser",
                epic_name="Different Epic",
                rocket_name="ッ",
            ),
        )

        player = report.games[0].blue.players[0]
        summary = build_match_replay_roster_validation_summary(report)

        self.assertEqual("name_matched", player.resolution_status)
        self.assertEqual("rocket_name", player.match_method)
        self.assertEqual(("rocket_name",), player.match_methods)
        self.assertEqual(0, summary.matched_unique_players)
        self.assertEqual(1, summary.unmatched_unique_players)
        self.assertEqual(("epic_name",), summary.unmatched_players[0].missing_methods)

    def test_discord_player_name_and_platform_id_do_not_validate_replay_players(self) -> None:
        report = _resolved_report(
            replay_player=MatchReplayPlayer(name="Visible Replay Name", platform="ps4", platform_id="shared-id"),
            roster_player=MatchReplayRosterPlayer(
                division_name="SILVER DIVISION S3",
                team_name="SPARK",
                player_name="Visible Replay Name",
                discord_name="Visible Replay Name",
                epic_name="Other Epic",
                rocket_name="Other Rocket",
            ),
        )

        player = report.games[0].blue.players[0]
        summary = build_match_replay_roster_validation_summary(report)

        self.assertEqual("unmatched", player.resolution_status)
        self.assertEqual("", player.match_method)
        self.assertEqual(0, summary.matched_unique_players)
        self.assertEqual(("epic_name", "rocket_name"), summary.unmatched_players[0].missing_methods)


def _resolved_report(
        *,
        replay_player: MatchReplayPlayer,
        roster_player: MatchReplayRosterPlayer,
):
    report = build_match_replay_report(
        division=MatchReplayDivision.SILVER,
        matchday=4,
        match_number=3,
        team_one_name="SPARK",
        team_two_name="TRIPLE FENNECS",
        games=(
            MatchReplayGame(
                number=1,
                replay_id="replay-1",
                replay_url="https://ballchasing.com/replay/replay-1",
                blue=MatchReplayTeam(
                    color="blue",
                    name="SPARK",
                    goals=1,
                    players=(replay_player,),
                ),
                orange=MatchReplayTeam(
                    color="orange",
                    name="TRIPLE FENNECS",
                    goals=0,
                    players=(),
                ),
            ),
            MatchReplayGame(
                number=2,
                replay_id="replay-2",
                replay_url="https://ballchasing.com/replay/replay-2",
                blue=MatchReplayTeam(
                    color="blue",
                    name="SPARK",
                    goals=1,
                    players=(),
                ),
                orange=MatchReplayTeam(
                    color="orange",
                    name="TRIPLE FENNECS",
                    goals=0,
                    players=(),
                ),
            ),
            MatchReplayGame(
                number=3,
                replay_id="replay-3",
                replay_url="https://ballchasing.com/replay/replay-3",
                blue=MatchReplayTeam(
                    color="blue",
                    name="SPARK",
                    goals=1,
                    players=(),
                ),
                orange=MatchReplayTeam(
                    color="orange",
                    name="TRIPLE FENNECS",
                    goals=0,
                    players=(),
                ),
            ),
        ),
    )
    return resolve_match_replay_report_players(report, (roster_player,))


if __name__ == "__main__":
    unittest.main()
