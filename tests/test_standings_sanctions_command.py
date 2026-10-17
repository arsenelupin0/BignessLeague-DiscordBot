from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands

from bigness_league_bot.application.services.match_replays import MatchReplayDivision
from bigness_league_bot.application.services.standings_sanctions import SanctionScope, sanction_error
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.discord.extensions import INITIAL_EXTENSIONS
from bigness_league_bot.infrastructure.google.standings_sanctions_repository import SanctionChangeResult
from bigness_league_bot.infrastructure.i18n.service import LocalizationService
from test_standings_sanctions import WORKSHEET, sanction

MODULE = "bigness_league_bot.presentation.discord.cogs.standings_sanctions"


class SanctionsCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = importlib.import_module(MODULE)
        self.cog = self.module.StandingsSanctionsCog()
        self.localizer = LocalizationService.from_directory(
            directory=Path(__file__).resolve().parents[1] / "aa_resources/locales", default_locale="es-ES")
        member = Mock(spec=discord.Member)
        member.roles = [SimpleNamespace(name="Staff")]
        member.name, member.id = "Staff", 42
        self.interaction = SimpleNamespace(
            id=123456789012345678, user=member, guild=object(), locale=discord.Locale.spain_spanish,
            client=SimpleNamespace(settings=object(), localizer=self.localizer),
            response=SimpleNamespace(defer=AsyncMock(), is_done=Mock(return_value=True), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        self.repository = SimpleNamespace(
            add=AsyncMock(return_value=SanctionChangeResult(sanction(), ())),
            annul=AsyncMock(return_value=SanctionChangeResult(sanction(), ())),
            list=AsyncMock(return_value=(SanctionScope.from_worksheet(WORKSHEET), (sanction(),))),
        )
        self.teams = SimpleNamespace(list_team_sheet_metadata=AsyncMock(return_value=(
            SimpleNamespace(worksheet_title="GOLD DIVISION S4 TEST", team_name="Equipo A"),)))
        self.division = app_commands.Choice(name="GOLD", value="gold")

    async def invoke(self, method="add", **overrides):
        kwargs = {"division": self.division}
        if method == "add":
            kwargs.update(equipo=SimpleNamespace(name="Equipo A"), puntos=1, motivo="Alineación indebida",
                          jornada=1, partido=1)
        elif method == "annul":
            kwargs.update(id="123", motivo="Recurso")
        kwargs.update(overrides)
        with (patch.object(self.module, "GoogleSheetsStandingsSanctionsRepository", return_value=self.repository),
              patch.object(self.module, "GoogleSheetsTeamRepository", return_value=self.teams)):
            await getattr(self.cog, method).callback(self.cog, self.interaction, **kwargs)

    async def test_add_carries_exact_team_match_actor_and_interaction_identifier(self):
        await self.invoke()
        args = self.repository.add.await_args
        self.assertEqual(args.args, (MatchReplayDivision.GOLD,))
        self.assertEqual(args.kwargs["identifier"], "123456789012345678")
        self.assertEqual(args.kwargs["actor"], "Staff (42)")
        self.assertEqual(args.kwargs["rosters"], (("GOLD DIVISION S4 TEST", "Equipo A"),))
        self.assertEqual((args.kwargs["matchday"], args.kwargs["match_number"]), (1, 1))
        self.assertEqual(args.kwargs["kind"], "AI")
        self.assertIn("Sanción registrada", self.interaction.followup.send.await_args.args[0])

    async def test_unauthorized_members_cannot_read_or_change_sanctions(self):
        self.interaction.user.roles = [SimpleNamespace(name="Jugador")]
        for method in ("add", "annul", "list_sanctions"):
            with self.subTest(method=method), self.assertRaises(CommandUserError):
                await self.invoke(method)
        self.repository.add.assert_not_awaited()
        self.repository.annul.assert_not_awaited()
        self.repository.list.assert_not_awaited()
        self.teams.list_team_sheet_metadata.assert_not_awaited()
        self.interaction.response.defer.assert_not_awaited()

    async def test_dm_is_rejected(self):
        self.interaction.guild = None
        with self.assertRaises(app_commands.NoPrivateMessage):
            await self.invoke()
        self.repository.add.assert_not_awaited()

    async def test_failed_write_never_claims_success(self):
        self.repository.add.side_effect = sanction_error("write", details="Denied")
        with self.assertRaises(CommandUserError):
            await self.invoke()
        self.interaction.followup.send.assert_not_awaited()

    async def test_annul_sends_id_and_reason_and_confirmation_is_private(self):
        await self.invoke("annul")
        args = self.repository.annul.await_args
        self.assertEqual(args.kwargs["identifier"], "123")
        self.assertEqual(args.kwargs["reason"], "Recurso")
        self.assertTrue(self.interaction.followup.send.await_args.kwargs["ephemeral"])
        self.assertFalse(self.interaction.followup.send.await_args.kwargs["allowed_mentions"].roles)

    async def test_list_is_paginated_and_contains_identifiers_without_ping(self):
        records = tuple(sanction(identifier=str(index), reason="Motivo " * 65) for index in range(15))
        self.repository.list.return_value = (SanctionScope.from_worksheet(WORKSHEET), records)
        await self.invoke("list_sanctions")
        sends = self.interaction.followup.send.await_args_list
        self.assertGreater(len(sends), 1)
        content = "\n".join(call.args[0] for call in sends)
        for record in records:
            self.assertIn(f"`{record.identifier}`", content)
        for call in sends:
            self.assertLessEqual(len(call.args[0]), 1900)
            self.assertTrue(call.kwargs["ephemeral"])
            self.assertFalse(call.kwargs["allowed_mentions"].everyone)

    async def test_command_group_is_loaded_and_original_classification_has_no_extra_parameters(self):
        self.assertIn(MODULE, INITIAL_EXTENSIONS)
        group = self.cog.sancion
        self.assertEqual(group.name, "sancion")
        self.assertEqual({command.name for command in group.commands}, {"añadir", "anular", "listar"})
        match_replays = importlib.import_module("bigness_league_bot.presentation.discord.cogs.match_replays")
        self.assertEqual([p.name for p in match_replays.MatchReplaysCog.refresh_standings.parameters], ["division"])

    async def test_cog_registers_the_three_commands_in_a_real_discord_command_tree(self):
        from discord.ext import commands
        async with commands.Bot(command_prefix="!", intents=discord.Intents.none()) as bot:
            await bot.add_cog(self.cog)
            payload = bot.tree.get_command("sancion").to_dict(bot.tree)
        self.assertEqual(payload["name"], "sancion")
        self.assertEqual(len(payload["options"]), 3)
        parameters = next(option["options"] for option in payload["options"] if option["name"] == "añadir")
        self.assertEqual(next(p["min_value"] for p in parameters if p["name"] == "puntos"), 1)

    async def test_errors_and_messages_are_translated_in_both_languages(self):
        for locale in ("es-ES", "en-US"):
            for error in (sanction_error("invalid_record", identifier="123"),
                          sanction_error("scope", sheet_name=WORKSHEET),
                          sanction_error("match_team", team="Equipo A", matchday=1, match_number=1),
                          sanction_error("write", details="Denied")):
                message = self.localizer.render(error.message, locale=locale)
                self.assertNotIn("sanctions.errors", message)
                self.assertNotIn("{", message)
            self.interaction.locale = discord.Locale(locale)
            await self.invoke()
            self.assertNotIn("sanctions.messages", self.interaction.followup.send.await_args.args[0])

    async def test_locale_key_sets_and_placeholders_match(self):
        root = Path(__file__).resolve().parents[1] / "aa_resources/locales"

        def flatten(value, prefix=""):
            return {f"{prefix}.{key}": text for key, child in value.items()
                    for text in ([child] if isinstance(child, str) else [])} | {
                key: text for name, child in value.items() if isinstance(child, dict)
                for key, text in flatten(child, f"{prefix}.{name}").items()}

        es = flatten(json.loads((root / "es-ES.json").read_text(encoding="utf-8"))["sanctions"])
        en = flatten(json.loads((root / "en-US.json").read_text(encoding="utf-8"))["sanctions"])
        self.assertEqual(es.keys(), en.keys())
        from string import Formatter
        for key in es:
            self.assertEqual({name for _, name, _, _ in Formatter().parse(es[key]) if name},
                             {name for _, name, _, _ in Formatter().parse(en[key]) if name}, key)
