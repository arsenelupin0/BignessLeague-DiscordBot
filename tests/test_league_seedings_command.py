from __future__ import annotations

import asyncio
import importlib
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.league_seedings import LeagueSeedingsDestination
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.discord.extensions import INITIAL_EXTENSIONS
from bigness_league_bot.infrastructure.google.team_sheets.client import GoogleSheetsClient
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.models import SheetCell, TeamRoleSheetMetadata
from bigness_league_bot.infrastructure.google.team_sheets.queries import TeamSheetQueryService
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

COG_MODULE = "bigness_league_bot.presentation.discord.cogs.league_seedings"


class LeagueSeedingsCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.metadata = tuple(TeamRoleSheetMetadata(f"{division} Division S4", f"{division} Equipo {index}")
                              for division in ("Gold", "Silver") for index in range(1, 9))
        self.repository = SimpleNamespace(list_team_sheet_metadata=AsyncMock(return_value=self.metadata))
        self.saved = False

        async def save(schedules):
            self.saved = True
            return tuple(LeagueSeedingsDestination(
                schedule.division, f"Clasificación - {schedule.worksheet_title}",
                f"https://docs.google.com/spreadsheets/d/test/edit#gid={index}", ("B20:D47",),
            ) for index, schedule in enumerate(schedules))

        self.writer = SimpleNamespace(write_seedings=AsyncMock(side_effect=save))
        self.localizer = LocalizationService.from_directory(
            directory=Path(__file__).resolve().parents[1] / "aa_resources/locales", default_locale="es-ES",
        )
        user = Mock(spec=discord.Member)
        user.roles = [SimpleNamespace(name="Staff")]
        self.interaction = SimpleNamespace(
            user=user, guild=Mock(), locale=discord.Locale("es-ES"),
            client=SimpleNamespace(settings=Mock(), localizer=self.localizer),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=Mock(return_value=True)),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        self.cog_module = importlib.import_module(COG_MODULE)
        self.cog = self.cog_module.LeagueSeedingsCog()

    async def execute(self):
        with (patch.object(self.cog_module, "GoogleSheetsTeamRepository", return_value=self.repository) as factory,
              patch.object(self.cog_module, "GoogleSheetsLeagueSeedingsRepository",
                           return_value=self.writer) as writer):
            await self.cog.league_seedings.callback(self.cog, self.interaction)
        factory.assert_called_once_with(self.interaction.client.settings)
        writer.assert_called_once_with(self.interaction.client.settings)

    async def test_command_writes_both_divisions_before_sending_saved_markdown_calendar(self) -> None:
        await self.assert_saved_calendar()

    async def assert_saved_calendar(self) -> None:
        async def send(**kwargs):
            self.assertTrue(self.saved)

        self.interaction.followup.send.side_effect = send
        await self.execute()
        self.repository.list_team_sheet_metadata.assert_awaited_once()
        self.interaction.response.defer.assert_awaited_once_with(thinking=True)
        self.writer.write_seedings.assert_awaited_once()
        schedules = self.writer.write_seedings.await_args.args[0]
        self.assertEqual(len(schedules), 2)
        self.assertEqual([len(schedule.matchdays) for schedule in schedules], [7, 7])
        calls = self.interaction.followup.send.await_args_list
        self.assertGreaterEqual(len(calls), 3)
        self.assertIn("Calendario guardado", calls[0].kwargs["content"])
        content = "\n".join(call.kwargs["content"] for call in calls[1:])
        self.assertIn("B20:D47", content)
        self.assertIn("https://docs.google.com/spreadsheets/d/test/edit#gid=0", content)
        self.assertIn("https://docs.google.com/spreadsheets/d/test/edit#gid=1", content)
        self.assertEqual(content.count("**P1**"), 14)
        for team in self.metadata:
            self.assertEqual(content.count(team.team_name), 7)
        for call in calls:
            self.assertNotIn("files", call.kwargs)
            self.assertFalse(call.kwargs["allowed_mentions"].everyone)
            self.assertFalse(call.kwargs["allowed_mentions"].users)
            self.assertFalse(call.kwargs["allowed_mentions"].roles)
            self.assertLessEqual(len(call.kwargs["content"]), 2000)

    async def test_command_saves_teams_from_configured_test_worksheets(self) -> None:
        self.repository.list_team_sheet_metadata.return_value = tuple(
            replace(team, worksheet_title=team.worksheet_title.upper() + " TEST")
            for team in self.metadata
        )
        await self.assert_saved_calendar()

    async def test_unauthorized_member_is_rejected_before_reading_sheets(self) -> None:
        self.interaction.user.roles = [SimpleNamespace(name="Jugador")]
        with patch.object(self.cog_module, "GoogleSheetsTeamRepository") as factory:
            with self.assertRaises(CommandUserError):
                await self.cog.league_seedings.callback(self.cog, self.interaction)
        factory.assert_not_called()
        self.interaction.response.defer.assert_not_awaited()
        self.interaction.followup.send.assert_not_awaited()
        self.writer.write_seedings.assert_not_awaited()

    async def test_invalid_silver_prevents_partial_gold_output(self) -> None:
        self.repository.list_team_sheet_metadata.return_value = self.metadata[:-1]
        with self.assertRaises(CommandUserError) as caught:
            await self.execute()
        self.assertEqual(caught.exception.message.params["division"], "Silver Division")
        self.interaction.followup.send.assert_not_awaited()
        self.writer.write_seedings.assert_not_awaited()

    async def test_failed_write_never_sends_success_or_matchdays(self) -> None:
        self.writer.write_seedings.side_effect = CommandUserError(localize(
            "errors.league_seedings.calendar_occupied", sheet_name="Silver",
        ))
        with self.assertRaises(CommandUserError):
            await self.execute()
        self.interaction.followup.send.assert_not_awaited()
        self.assertFalse(self.saved)

    async def test_simultaneous_draws_are_serialized_before_checking_and_writing(self) -> None:
        original_save = self.writer.write_seedings.side_effect

        async def save_once(schedules):
            if self.saved:
                raise CommandUserError(localize("errors.league_seedings.calendar_occupied", sheet_name="Gold"))
            await asyncio.sleep(0)
            return await original_save(schedules)

        self.writer.write_seedings.side_effect = save_once
        with (patch.object(self.cog_module, "GoogleSheetsTeamRepository", return_value=self.repository),
              patch.object(self.cog_module, "GoogleSheetsLeagueSeedingsRepository", return_value=self.writer)):
            results = await asyncio.gather(*(
                self.cog.league_seedings.callback(self.cog, self.interaction) for _ in range(2)
            ), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, CommandUserError) for result in results), 1)
        self.assertEqual(self.writer.write_seedings.await_count, 2)
        overviews = [call for call in self.interaction.followup.send.await_args_list
                     if "Calendario guardado" in call.kwargs["content"]]
        self.assertEqual(len(overviews), 1)

    async def test_sheet_error_propagates_without_output(self) -> None:
        self.repository.list_team_sheet_metadata.side_effect = RuntimeError("offline")
        with self.assertRaisesRegex(RuntimeError, "offline"):
            await self.execute()
        self.interaction.followup.send.assert_not_awaited()

    async def test_localized_error_is_ephemeral_after_and_before_deferring(self) -> None:
        self.repository.list_team_sheet_metadata.return_value = self.metadata[:-1]
        with self.assertRaises(CommandUserError) as caught:
            await self.execute()
        error = app_commands.CommandInvokeError(self.cog.league_seedings, caught.exception)
        for done in (True, False):
            self.interaction.response.is_done.return_value = done
            await self.cog.cog_app_command_error(self.interaction, error)
            send = self.interaction.followup.send if done else self.interaction.response.send_message
            self.assertTrue(send.await_args.kwargs["ephemeral"])
            self.assertIn("Silver Division", send.await_args.args[0])
            self.assertIn("7", send.await_args.args[0])

    async def test_extension_registers_exact_slash_name_without_network(self) -> None:
        extension = COG_MODULE
        self.assertIn(extension, INITIAL_EXTENSIONS)
        async with commands.Bot(command_prefix="!", intents=discord.Intents.none()) as bot:
            await bot.load_extension(extension)
            command = bot.tree.get_command("league_seedings")
            self.assertIsNotNone(command)
            assert isinstance(command, app_commands.Command)
            self.assertTrue(command.guild_only)
            self.assertEqual(command.parameters, [])


class LeagueSeedingsSheetQueryTests(unittest.TestCase):
    def test_configured_test_sheet_titles_are_used_as_exact_google_ranges(self) -> None:
        settings = Settings(
            token="unused-test-token",
            google_service_account_file=Path(__file__), google_sheets_spreadsheet_id="test-document",
            google_sheets_team_sheet_name="GOLD DIVISION S4 TEST,SILVER DIVISION S4 TEST",
        )
        config = TeamSheetLookupConfig.from_settings(settings)
        expected = ("GOLD DIVISION S4 TEST", "SILVER DIVISION S4 TEST")
        self.assertEqual(config.worksheet_names, expected)
        service = Mock()
        service.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": title}, "data": []}
                       for title in (*expected, "Gold Division S4")],
        }
        _, grids = GoogleSheetsClient(config).fetch_sheet_grids(service)
        self.assertEqual(service.spreadsheets.return_value.get.call_args.kwargs["ranges"], list(expected))
        self.assertEqual(tuple(title for title, _ in grids), expected)

    def test_existing_query_reads_registered_teams_without_discord_roles_and_skips_free_blocks(self) -> None:
        def grid(title):
            rows = {0: [title], 1: ["Jugador", "Discord ID", "Platform", "Platform ID", "Epic Name", "MMR"],
                    9: ["STAFF TÉCNICO"], 10: ["Rol", "Jugador", "Discord ID", "Epic Name"]}
            return {row: {col: SheetCell(value=v) for col, v in enumerate(values)} for row, values in rows.items()}

        client = Mock()
        client.fetch_sheet_grids.return_value = ("scope", (
            ("GOLD DIVISION S4 TEST", grid("Águilas")),
            ("SILVER DIVISION S4 TEST", grid("Silver Team")),
            ("GOLD DIVISION S4 TEST", grid("-")),
        ))
        metadata = TeamSheetQueryService(client).list_team_sheet_metadata_sync()
        self.assertEqual([(t.worksheet_title, t.team_name) for t in metadata], [
            ("GOLD DIVISION S4 TEST", "Águilas"), ("SILVER DIVISION S4 TEST", "Silver Team"),
        ])
        client.build_service.assert_called_once_with(read_only=True)
        client.fetch_sheet_grids.assert_called_once()


if __name__ == "__main__":
    unittest.main()
