from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bigness_league_bot.application.services.match_replay_models import (
    MatchReplayGame, MatchReplayPlayer, MatchReplayTeam,
)
from bigness_league_bot.application.services.match_replay_names import ReplayAccountName, apply_replay_account_names
from bigness_league_bot.application.services.match_replay_roster_resolution import resolve_match_replay_report_players
from bigness_league_bot.application.services.match_replay_summaries import build_match_replay_roster_validation_summary
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.replays import runtime
from bigness_league_bot.infrastructure.replays.name_recovery import build_replay_name_reader, recover_replay_game_names
from bigness_league_bot.infrastructure.replays.rrrocket import (
    ReplayNameParserError, RrrocketNameReader, extract_header_account_names,
)
from test_match_replay_verification import report, roster

NAME = "ᶠ ᵃ ᵏ ᵉDAVIDツ"
ACCOUNT = "account-123"
RUN = "bigness_league_bot.infrastructure.replays.rrrocket.subprocess.run"


def header_player(**changes):
    value = {"Name": NAME, "Platform": {"kind": "OnlinePlatform", "value": "OnlinePlatform_Epic"},
             "PlayerID": {"fields": {"EpicAccountId": ACCOUNT, "Uid": "0"}},
             "OnlineID": "0", "Team": 0, "bBot": False}
    value.update(changes)
    return value


def header(*players):
    return {"properties": {"PlayerStats": list(players) or [header_player()]}}


def game():
    return MatchReplayGame(1, "replay-id", "https://example.test/replay",
                           MatchReplayTeam("blue", "Astra Drift", 3, (
                               MatchReplayPlayer("C O IDAVID0", "epic", ACCOUNT, score=296, goals=1),)),
                           MatchReplayTeam("orange", "Other", 2, ()), replay_sha256="sha", replay_date="date")


class HeaderNamesTests(unittest.TestCase):
    def test_unicode_preserved_without_transliteration(self):
        self.assertEqual(extract_header_account_names(header()), (ReplayAccountName("epic", ACCOUNT, NAME),))

    def test_bots_and_spectators_do_not_supply_player_names(self):
        self.assertFalse(extract_header_account_names(header(
            header_player(Team=-1), header_player(bBot=True), header_player(Team=True),
        )))

    def test_zero_ids_and_absent_epic_ids_are_not_derived_from_display_name(self):
        player = header_player(PlayerID={"fields": {"EpicAccountId": "0000"}}, OnlineID="999")
        self.assertFalse(extract_header_account_names(header(player)))

    def test_platform_specific_ids_keep_their_exact_content(self):
        for source, platform in (("Steam", "steam"), ("PS4", "psn"), ("PS5", "psn"),
                                 ("PSN", "psn"), ("Dingo", "xbl"), ("Switch", "switch")):
            with self.subTest(platform=source):
                p = header_player(Platform={"value": "OnlinePlatform_" + source}, OnlineID="Account-._ 123")
                self.assertEqual(extract_header_account_names(header(p))[0].platform, platform)
                self.assertEqual(extract_header_account_names(header(p))[0].platform_id, "Account-._ 123")

    def test_malformed_optional_entries_are_skipped(self):
        variants = (None, {}, header_player(Platform=[]), header_player(Platform={"value": []}),
                    header_player(PlayerID=[]), header_player(PlayerID={"fields": []}),
                    header_player(Name=None), header_player(Name="\ufffd"), header_player(Name="bad\nname"))
        self.assertFalse(extract_header_account_names(header(*variants)))

    def test_invalid_header_schema_is_a_controlled_error(self):
        for payload in (None, [], {}, {"properties": None}, {"properties": {"PlayerStats": {}}}):
            with self.subTest(payload=payload), self.assertRaises(ReplayNameParserError):
                extract_header_account_names(payload)


class LocalNameMergeTests(unittest.TestCase):
    def test_same_unique_account_recovers_name_preserving_stats_and_raw_name(self):
        original = game()
        enriched = apply_replay_account_names(original, (ReplayAccountName("EPIC", ACCOUNT.upper(), NAME),))
        player = enriched.blue.players[0]
        self.assertEqual((player.name, player.ballchasing_name, player.name_source),
                         (NAME, "C O IDAVID0", "replay_header"))
        self.assertEqual(replace(player, name="C O IDAVID0", ballchasing_name="", name_source="ballchasing"),
                         original.blue.players[0])
        self.assertEqual(replace(enriched, blue=original.blue), original)

    def test_recovered_unicode_ign_does_not_supply_an_epic_name(self):
        enriched = apply_replay_account_names(game(), extract_header_account_names(header()))
        resolved = resolve_match_replay_report_players(report(*enriched.blue.players), (roster(),))
        summary = build_match_replay_roster_validation_summary(resolved)
        self.assertEqual(summary.matched_unique_players, 1)
        self.assertIsNone(resolved.games[0].blue.players[0].epic_name)
        self.assertFalse(summary.epic_name_unmatched_players)

    def test_different_platform_or_id_never_joins_by_display_name_or_position(self):
        for entry in (ReplayAccountName("steam", ACCOUNT, NAME), ReplayAccountName("epic", "other", NAME)):
            self.assertEqual(apply_replay_account_names(game(), (entry,)), game())

    def test_ambiguous_header_accounts_do_not_replace_the_analyzer_name(self):
        entry = ReplayAccountName("epic", ACCOUNT, NAME)
        for entries in ((entry, entry), (entry, replace(entry, name="other"))):
            self.assertEqual(apply_replay_account_names(game(), entries), game())

    def test_duplicate_analyzer_account_including_across_teams_does_not_join(self):
        original = game()
        original = replace(original, orange=replace(original.orange, players=original.blue.players))
        self.assertEqual(apply_replay_account_names(original, (ReplayAccountName("epic", ACCOUNT, NAME),)), original)

    def test_repeated_enrichment_keeps_the_original_ballchasing_name(self):
        entry = ReplayAccountName("epic", ACCOUNT, NAME)
        once = apply_replay_account_names(game(), (entry,))
        self.assertEqual(apply_replay_account_names(once, (entry,)), once)


class ParserProcessTests(unittest.TestCase):
    def setUp(self):
        self.reader = RrrocketNameReader(Path("rrrocket.exe"), timeout_seconds=3)

    def test_reads_original_bytes_via_stdin_with_crc_check_and_timeout(self):
        response = SimpleNamespace(returncode=0, stdout=json.dumps(header(), ensure_ascii=False).encode("utf-8"))
        with patch(RUN, return_value=response) as run:
            self.assertEqual(self.reader.read_names(b"original replay bytes")[0].name, NAME)
        args, kwargs = run.call_args
        self.assertEqual(args[0], [str(self.reader.executable), "--crc-check"])
        self.assertEqual(kwargs["input"], b"original replay bytes")
        self.assertEqual(kwargs["timeout"], 3)
        self.assertNotIn("shell", kwargs)

    def test_invalid_json_nonzero_exit_and_unavailable_executable_have_reasons(self):
        for response, reason in (
                (SimpleNamespace(returncode=1, stdout=b"", stderr=b"unsupported replay"), "parser_exit"),
                (SimpleNamespace(returncode=0, stdout=b"not json"), "invalid_json")):
            with self.subTest(reason=reason), patch(RUN, return_value=response):
                with self.assertRaises(ReplayNameParserError) as raised:
                    self.reader.read_names(b"bytes")
                self.assertEqual(raised.exception.reason, reason)
        with patch(RUN, side_effect=OSError()), self.assertRaises(ReplayNameParserError) as raised:
            self.reader.read_names(b"bytes")
        self.assertEqual(raised.exception.reason, "executable_unavailable")

    def test_timeout_is_a_controlled_fallback(self):
        with patch(RUN, side_effect=subprocess.TimeoutExpired("rrrocket", 3)):
            with self.assertRaises(ReplayNameParserError) as raised:
                self.reader.read_names(b"bytes")
        self.assertEqual(raised.exception.reason, "timeout")

    def test_empty_and_oversized_input_never_start_a_process(self):
        with patch(RUN) as run:
            for content in (b"", b"a" * (32 * 1024 * 1024 + 1)):
                with self.assertRaises(ReplayNameParserError):
                    self.reader.read_names(content)
            run.assert_not_called()

    def test_oversized_output_is_rejected(self):
        with patch(RUN, return_value=SimpleNamespace(returncode=0, stdout=b"x" * (8 * 1024 * 1024 + 1))):
            with self.assertRaises(ReplayNameParserError) as raised:
                self.reader.read_names(b"bytes")
        self.assertEqual(raised.exception.reason, "output_size")


class NameRecoveryWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_parser_error_keeps_ballchasing_game_and_logs_the_reason(self):
        reader = Mock(read_names=Mock(side_effect=ReplayNameParserError("timeout")))
        with self.assertLogs("bigness_league_bot.infrastructure.replays.name_recovery", level="WARNING") as logs:
            self.assertEqual(await recover_replay_game_names(game(), b"bytes", reader), game())
        self.assertIn("reason=timeout", logs.output[0])

    async def test_disabled_reader_does_not_start_parsing(self):
        self.assertEqual(await recover_replay_game_names(game(), b"bytes", None), game())

    async def test_successful_parser_runs_outside_the_event_loop(self):
        reader = Mock(read_names=Mock(return_value=extract_header_account_names(header())))

        def read(content):
            with self.assertRaises(RuntimeError):
                asyncio.get_running_loop()
            return extract_header_account_names(header())

        reader.read_names.side_effect = read
        actual = await recover_replay_game_names(game(), b"bytes", reader)
        self.assertEqual(actual.blue.players[0].name, NAME)


class ParserConfigurationTests(unittest.TestCase):
    def test_disabled_parser_does_not_even_probe_the_executable(self):
        with patch.object(Path, "is_file") as probe:
            self.assertIsNone(build_replay_name_reader(SimpleNamespace(replay_name_parser_enabled=False)))
            probe.assert_not_called()

    def test_missing_installation_falls_back_explicitly(self):
        settings = SimpleNamespace(replay_name_parser_enabled=True, replay_name_parser_path=Path("missing"))
        with patch.object(Path, "is_file", return_value=False), self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(build_replay_name_reader(settings))
        self.assertIn("reason=not_installed", logs.output[0])

    def test_settings_default_path_and_overrides(self):
        environment = {"DISCORD_TOKEN": "test", "BOT_ENV": "production"}
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()
            self.assertTrue(settings.replay_name_parser_enabled)
            self.assertTrue(settings.replay_name_parser_path.is_absolute())
            self.assertEqual(settings.replay_name_parser_timeout_seconds, 10)
            with patch.dict(os.environ,
                            {"BOT_REPLAY_NAME_PARSER_ENABLED": "false", "BOT_REPLAY_NAME_PARSER_TIMEOUT_SECONDS": "2"}):
                settings = Settings.from_env()
                self.assertFalse(settings.replay_name_parser_enabled)
                self.assertEqual(settings.replay_name_parser_timeout_seconds, 2)

    def test_invalid_timeouts_are_rejected(self):
        for value in ("0", "61"):
            with patch.dict(os.environ, {"DISCORD_TOKEN": "test", "BOT_ENV": "production",
                                         "BOT_REPLAY_NAME_PARSER_TIMEOUT_SECONDS": value}, clear=True):
                with self.assertRaisesRegex(ValueError, "BOT_REPLAY_NAME_PARSER_TIMEOUT_SECONDS"):
                    Settings.from_env()


class ParserInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installer = runtime

    def test_extracts_only_the_binary_without_writing_archive_paths(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("release/rrrocket.exe", b"binary")
            archive.writestr("../../unrelated-file", b"do not extract")
        self.assertEqual(self.installer.executable_from_archive(buffer.getvalue(), windows=True), b"binary")

    def test_ambiguous_binary_archive_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("one/rrrocket.exe", b"one")
            archive.writestr("two/rrrocket.exe", b"two")
        with self.assertRaises(runtime.ReplayRuntimeError):
            self.installer.executable_from_archive(buffer.getvalue(), windows=True)

    def test_bundled_archive_requires_the_pinned_digest(self):
        suffix, _ = runtime.host_asset()
        with self.assertRaisesRegex(runtime.ReplayRuntimeError, "bundle_checksum"):
            runtime._read_bundled(f"rrrocket-{runtime.VERSION}-{suffix}", "0" * 64)


if __name__ == "__main__":
    unittest.main()
