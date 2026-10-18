from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from bigness_league_bot.application.services.match_replay_models import (
    MatchReplayDivision, MatchReplayGame, MatchReplayPlayer, MatchReplayReport,
    MatchReplayRosterPlayer, MatchReplayTeam,
)
from bigness_league_bot.application.services.match_replay_roster_resolution import resolve_match_replay_report_players
from bigness_league_bot.application.services.match_replay_summaries import (
    build_match_replay_player_stat_totals, build_match_replay_roster_validation_summary,
)
from bigness_league_bot.infrastructure.ballchasing.client import _parse_replay_payload
from bigness_league_bot.infrastructure.discord.match_replay_discord_helpers import send_channel_message
from bigness_league_bot.infrastructure.discord.match_replay_messages import (
    format_match_replay_roster_validation, split_match_replay_message,
)
from bigness_league_bot.infrastructure.i18n.service import LocalizationService


def roster(**changes) -> MatchReplayRosterPlayer:
    return replace(MatchReplayRosterPlayer(
        "GOLD DIVISION S4", "Astra Drift", "DAVID", "42", "epic", "account-123", "ᶠ ᵃ ᵏ ᵉDAVIDツ",
    ), **changes)


def player(**changes) -> MatchReplayPlayer:
    return replace(MatchReplayPlayer("C O IDAVID0", "epic", "account-123"), **changes)


def report(*appearances: MatchReplayPlayer) -> MatchReplayReport:
    games = tuple(MatchReplayGame(
        index, str(index), "https://example.test/replay",
        MatchReplayTeam("blue", "Astra Drift", 2, (appearance,)),
        MatchReplayTeam("orange", "Otro equipo", 1, ()),
    ) for index, appearance in enumerate(appearances, 1))
    return MatchReplayReport(MatchReplayDivision.GOLD, 1, 1, "Astra Drift", "Otro equipo", games, len(games), 0, ())


def resolve(appearance=None, entries=None):
    return resolve_match_replay_report_players(
        report(appearance or player()), entries if entries is not None else (roster(),),
    )


class ReplayIdentityTests(unittest.TestCase):
    def test_corrupted_name_does_not_invalidate_matching_account(self):
        resolved = resolve()
        actual = resolved.games[0].blue.players[0]
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertEqual(actual.resolution_status, "matched")
        self.assertEqual(actual.match_methods, ("platform", "platform_id"))
        self.assertEqual(summary.matched_unique_players, 1)
        self.assertFalse(summary.unmatched_players)
        self.assertEqual(len(summary.epic_name_unmatched_players), 1)
        self.assertEqual(summary.epic_name_unmatched_players[0].registered_epic_name, roster().epic_name)

    def test_six_correct_accounts_report_six_ids_with_one_name_notice(self):
        entries = tuple(roster(platform_id=f"id-{i}", epic_name=f"Player{i}", player_name=f"Player{i}")
                        for i in range(6))
        players = tuple(player(platform_id=f"id-{i}", name=f"Player{i}" if i else "C O IDAVID0")
                        for i in range(6))
        original = report(player())
        original = replace(original, games=(replace(original.games[0], blue=replace(
            original.games[0].blue, players=players,
        )),))
        summary = build_match_replay_roster_validation_summary(resolve_match_replay_report_players(original, entries))
        self.assertEqual(summary.matched_unique_players, 6)
        self.assertEqual({m.method: m.count for m in summary.match_methods},
                         {"platform": 6, "platform_id": 6, "epic_name": 5})
        self.assertFalse(summary.unmatched_players)
        self.assertEqual(len(summary.epic_name_unmatched_players), 1)

    def test_unique_id_takes_priority_over_another_players_name(self):
        other = roster(player_name="Other", platform_id="other-id", epic_name="C O IDAVID0", platform="steam")
        summary = build_match_replay_roster_validation_summary(resolve(player(platform="steam"), (roster(), other)))
        self.assertEqual(summary.matched_unique_players, 0)
        self.assertEqual({m.method: m.count for m in summary.match_methods}["platform_id"], 1)
        self.assertEqual(summary.unmatched_players[0].missing_methods, ("platform",))
        self.assertEqual(summary.unmatched_players[0].registered_platform, "epic")

    def test_pair_takes_priority_over_another_players_name(self):
        other = roster(player_name="Other", platform_id="other-id", epic_name="C O IDAVID0")
        resolved = resolve(entries=(roster(), other))
        actual = resolved.games[0].blue.players[0]
        self.assertEqual(actual.roster_player_name, "DAVID")
        self.assertEqual(actual.resolution_status, "matched")
        self.assertNotIn("epic_name", actual.match_methods)

    def test_matching_name_is_only_a_hint_when_id_is_wrong(self):
        summary = build_match_replay_roster_validation_summary(resolve(
            player(name=roster().epic_name, platform_id="wrong-id"),
        ))
        self.assertEqual(summary.matched_unique_players, 0)
        self.assertEqual(summary.unmatched_players[0].missing_methods, ("platform_id",))
        self.assertFalse(summary.epic_name_unmatched_players)

    def test_duplicate_account_cannot_be_verified_using_a_unique_name(self):
        duplicate = roster(player_name="Other", epic_name="Different", discord_id="43")
        summary = build_match_replay_roster_validation_summary(resolve(
            player(name=roster().epic_name), (roster(), duplicate),
        ))
        self.assertEqual(summary.matched_unique_players, 0)
        self.assertEqual(summary.unmatched_players[0].missing_methods, ("platform_id",))

    def test_identical_duplicate_rows_are_still_ambiguous(self):
        summary = build_match_replay_roster_validation_summary(resolve(entries=(roster(), roster())))
        self.assertEqual(summary.matched_unique_players, 0)
        self.assertEqual(summary.unmatched_players[0].missing_methods, ("platform", "platform_id"))

    def test_same_id_on_different_platforms_can_match_a_unique_pair(self):
        other = roster(platform="steam", player_name="Other", epic_name="Other")
        actual = resolve(entries=(roster(), other)).games[0].blue.players[0]
        self.assertEqual(actual.resolution_status, "matched")
        self.assertEqual(actual.roster_player_name, "DAVID")

    def test_id_symbols_and_internal_spaces_are_not_erased(self):
        for different_id in ("account123", "account 123", "account_123"):
            with self.subTest(different_id=different_id):
                summary = build_match_replay_roster_validation_summary(resolve(player(platform_id=different_id)))
                self.assertEqual(summary.matched_unique_players, 0)

    def test_outer_whitespace_and_case_do_not_change_the_account(self):
        actual = resolve(player(platform=" EPIC ", platform_id=" ACCOUNT-123 ")).games[0].blue.players[0]
        self.assertEqual(actual.resolution_status, "matched")

    def test_missing_fields_never_verify_a_player_by_name(self):
        for changes, missing in (({"platform_id": ""}, ("platform_id",)),
                                 ({"platform": ""}, ("platform",))):
            with self.subTest(changes=changes):
                summary = build_match_replay_roster_validation_summary(
                    resolve(player(name=roster().epic_name, **changes)))
                self.assertEqual(summary.matched_unique_players, 0)
                self.assertEqual(summary.unmatched_players[0].missing_methods, missing)

    def test_unknown_player_is_not_verified_just_because_platform_exists(self):
        summary = build_match_replay_roster_validation_summary(resolve(player(platform_id="unknown")))
        self.assertEqual(summary.unmatched_players[0].missing_methods, ("platform", "platform_id"))

    def test_platform_aliases_share_identity_and_statistics(self):
        resolved = resolve_match_replay_report_players(
            report(player(platform="ps4"), player(platform="PSN")), (roster(platform="psn"),),
        )
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertEqual((summary.unique_players, summary.matched_appearances), (1, 2))
        self.assertEqual(build_match_replay_player_stat_totals(resolved)[0].games_played, 2)

    def test_failed_appearance_survives_in_either_game_order(self):
        matched = resolve().games[0].blue.players[0]
        failed = replace(matched, resolution_status="unmatched", match_methods=("platform_id",))
        for appearances in ((matched, failed), (failed, matched)):
            with self.subTest(order=appearances):
                summary = build_match_replay_roster_validation_summary(report(*appearances))
                self.assertEqual((summary.unique_players, summary.matched_unique_players), (1, 0))
                self.assertEqual(summary.matched_appearances, 1)
                self.assertEqual(summary.unmatched_players[0].missing_methods, ("platform",))
                self.assertEqual({m.method: m.count for m in summary.match_methods}["platform"], 0)

    def test_name_warning_detects_later_changes_without_duplicating_player(self):
        resolved = resolve_match_replay_report_players(
            report(player(name=roster().epic_name), player()), (roster(),),
        )
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertEqual(summary.matched_unique_players, 1)
        self.assertEqual(len(summary.epic_name_unmatched_players), 1)
        self.assertEqual(summary.epic_name_unmatched_players[0].player_name, "C O IDAVID0")

    def test_ballchasing_payload_keeps_name_and_identity_separate(self):
        parsed = _parse_replay_payload({
            "id": "replay-id",
            "blue": {"players": [{"name": "C O IDAVID0", "id": {"platform": "epic", "id": "account-123"}}]},
            "orange": {"players": []},
        })
        self.assertEqual(parsed.blue.players[0], player())


class ReplayVerificationMessagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.localizer = LocalizationService.from_directory(
            directory=Path(__file__).resolve().parents[1] / "aa_resources/locales", default_locale="es-ES",
        )

    def render(self, resolved, locale="es-ES"):
        return format_match_replay_roster_validation(
            localizer=self.localizer, locale=locale,
            summary=build_match_replay_roster_validation_summary(resolved),
        )

    def test_verified_account_has_informational_name_warning_without_identity_failure(self):
        text = self.render(resolve())
        self.assertIn("Jugadores verificados: **1/1** ✅", text)
        self.assertIn("Platform ID: **1/1** ✅", text)
        self.assertIn("Avisos de nombre (informativos): Epic Name **0/1** ⚠️", text)
        self.assertIn(roster().epic_name, text)
        self.assertNotIn("pendientes de verificar", text)
        self.assertNotIn("Información incorrecta", text)
        self.assertNotIn("❌", text)

    def test_correct_id_is_omitted_from_failed_fields(self):
        text = self.render(resolve(player(platform="steam")))
        self.assertIn("Platform ID: **1/1** ✅", text)
        self.assertIn("(**Plataforma**)", text)
        self.assertIn("Plataforma: replay `steam`; registrado `epic`", text)
        self.assertNotIn("Platform ID: replay", text)

    def test_wrong_id_shows_expected_and_detected_values(self):
        text = self.render(resolve(player(name=roster().epic_name, platform_id="wrong-id")))
        self.assertIn("(**Platform ID**)", text)
        self.assertIn("Platform ID: replay `wrong-id`; registrado `account-123`", text)
        self.assertNotIn("Avisos de nombre", text)

    def test_matching_name_and_account_have_no_name_warning(self):
        text = self.render(resolve(player(name=roster().epic_name)))
        self.assertNotIn("Avisos de nombre", text)
        self.assertNotIn("❌", text)

    def test_english_uses_english_messages(self):
        text = self.render(resolve(player(platform="steam")), "en-US")
        self.assertIn("Players awaiting verification", text)
        self.assertIn("Name notices (informational)", text)
        self.assertIn("Platform: replay `steam`; registered `epic`", text)
        self.assertNotIn("registrado", text)

    def test_missing_values_and_unresolved_roster_are_explicit(self):
        text = self.render(resolve(player(platform_id="")))
        self.assertIn("no disponible", text)
        self.assertIn("sin ficha única identificada", text)

    def test_duplicate_account_has_an_explicit_ambiguity_reason(self):
        text = self.render(resolve(entries=(roster(), roster())))
        self.assertIn("Cuenta ambigua: la plataforma e ID o el ID aparecen en varias fichas", text)
        self.assertIn("Jugadores verificados: **0/1**", text)

    def test_discord_markdown_in_team_or_name_is_escaped(self):
        text = self.render(resolve(player(name="`@everyone`"), (roster(team_name="*Astra*"),)))
        self.assertIn("\\*Astra*", text)
        self.assertIn("`'@everyone'`", text)


class ReplayMessageDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def test_splitting_preserves_text_and_respects_boundary_newlines(self):
        for content in ("a" * 2000 + "\n" + "b", ("  - Player\n" * 800), "x" * 4001):
            with self.subTest(length=len(content)):
                chunks = split_match_replay_message(content)
                self.assertEqual("".join(chunks), content)
                self.assertTrue(all(0 < len(chunk) <= 2000 for chunk in chunks))

    async def test_long_channel_report_sends_image_once_at_the_end_without_mentions(self):
        channel = Mock(spec=discord.abc.Messageable)
        channel.send = AsyncMock()
        interaction = SimpleNamespace(channel=channel, followup=SimpleNamespace(send=AsyncMock()))
        image = object()
        content = "line\n" * 1200
        await send_channel_message(interaction, content=content, file=image)
        calls = channel.send.await_args_list
        self.assertEqual("".join(call.kwargs["content"] for call in calls), content)
        self.assertTrue(all("file" not in call.kwargs for call in calls[:-1]))
        self.assertIs(calls[-1].kwargs["file"], image)
        self.assertTrue(all(call.kwargs["allowed_mentions"].everyone is False for call in calls))
        interaction.followup.send.assert_not_awaited()

    async def test_followup_delivery_uses_the_same_message_limit(self):
        interaction = SimpleNamespace(channel=None, followup=SimpleNamespace(send=AsyncMock()))
        await send_channel_message(interaction, content="x" * 2100)
        self.assertEqual(interaction.followup.send.await_count, 2)
        self.assertTrue(all("file" not in call.kwargs for call in interaction.followup.send.await_args_list))


if __name__ == "__main__":
    unittest.main()
