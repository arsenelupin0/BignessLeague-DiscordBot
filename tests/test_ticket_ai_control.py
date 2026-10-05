from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from bigness_league_bot.application.services.ticket_ai import TicketAiReply
from bigness_league_bot.application.services.tickets import TicketRecord
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot
from bigness_league_bot.infrastructure.discord.ticket_participant_messenger import TicketParticipantMessenger
from bigness_league_bot.infrastructure.i18n.service import LocalizationService
from bigness_league_bot.infrastructure.ticket_ai.control import TicketAiControl
from bigness_league_bot.infrastructure.ticket_ai.ollama import OllamaClientError
from bigness_league_bot.presentation.discord.cogs.tickets import TicketsCog
from bigness_league_bot.presentation.discord.ticket_ai_interactions import TicketAiInteractions

FACTORY = "bigness_league_bot.infrastructure.ticket_ai.control.TicketAiService.from_settings"
INTERACTIONS = "bigness_league_bot.presentation.discord.ticket_ai_interactions"
ROOT = Path(__file__).resolve().parents[1]
REPLY = TicketAiReply("Respuesta de prueba", 90, False, "Prueba", (), ())


class TicketAiControlTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(token="test", ticket_state_file=Path(temporary.name) / "tickets.json")

    def test_initial_state_requires_both_environment_flags(self) -> None:
        for enabled in (False, True):
            for auto_reply in (False, True):
                with self.subTest(enabled=enabled, auto_reply=auto_reply):
                    control = TicketAiControl(replace(
                        self.settings, ticket_ai_enabled=enabled, ticket_ai_auto_reply_enabled=auto_reply,
                    ))
                    self.assertEqual(control.enabled, enabled and auto_reply)

    def test_enabled_startup_is_lazy(self) -> None:
        with patch(FACTORY) as factory:
            control = TicketAiControl(replace(
                self.settings, ticket_ai_enabled=True, ticket_ai_auto_reply_enabled=True,
            ))
        self.assertTrue(control.enabled)
        self.assertIsNone(control.service)
        factory.assert_not_called()

    def test_disabled_get_service_does_not_load_resources(self) -> None:
        control = TicketAiControl(self.settings)
        with patch(FACTORY) as factory:
            self.assertIsNone(control.get_service())
        factory.assert_not_called()

    def test_enabling_overrides_both_flags_and_reuses_service(self) -> None:
        control = TicketAiControl(self.settings)
        with patch(FACTORY) as factory:
            control.set_enabled(True)
            self.assertIs(control.get_service(), factory.return_value)
            self.assertIs(control.get_service(), factory.return_value)
            control.set_enabled(True)
        factory.assert_called_once()
        effective_settings = factory.call_args.args[0]
        self.assertTrue(effective_settings.ticket_ai_enabled)
        self.assertTrue(effective_settings.ticket_ai_auto_reply_enabled)
        self.assertFalse(self.settings.ticket_ai_enabled)

    def test_persisted_activation_overrides_environment_after_restart(self) -> None:
        control = TicketAiControl(self.settings)
        with patch(FACTORY):
            control.set_enabled(True)
        reloaded = TicketAiControl(self.settings)
        self.assertTrue(reloaded.enabled)
        self.assertIsNone(reloaded.service)

    def test_persisted_deactivation_overrides_enabled_environment(self) -> None:
        settings = replace(self.settings, ticket_ai_enabled=True, ticket_ai_auto_reply_enabled=True)
        control = TicketAiControl(settings)
        with patch(FACTORY) as factory:
            control.set_enabled(False)
            reloaded = TicketAiControl(settings)
        self.assertFalse(reloaded.enabled)
        factory.assert_not_called()

    def test_corrupt_state_fails_closed(self) -> None:
        control = TicketAiControl(self.settings)
        for payload in ('{broken', '[]', '{"enabled": "false"}'):
            with self.subTest(payload=payload):
                control.state_path.write_text(payload, encoding="utf-8")
                with self.assertLogs("bigness_league_bot.infrastructure.ticket_ai.control", level="ERROR"):
                    reloaded = TicketAiControl(replace(
                        self.settings, ticket_ai_enabled=True, ticket_ai_auto_reply_enabled=True,
                    ))
                self.assertFalse(reloaded.enabled)

    def test_write_failure_keeps_previous_runtime_and_persisted_state(self) -> None:
        control = TicketAiControl(self.settings)
        with patch(FACTORY):
            control.set_enabled(True)
        original_service = control.service
        with patch.object(Path, "replace", side_effect=OSError("Sin permisos")):
            with self.assertRaises(OSError):
                control.set_enabled(False)
        self.assertTrue(control.enabled)
        self.assertIs(control.service, original_service)
        self.assertTrue(json.loads(control.state_path.read_text())["enabled"])

    def test_invalid_activation_does_not_save_or_change_state(self) -> None:
        control = TicketAiControl(replace(
            self.settings, ticket_ai_system_prompt_file=Path("missing_prompt_for_test.txt"),
        ))
        with self.assertRaises(OSError):
            control.set_enabled(True)
        self.assertFalse(control.enabled)
        self.assertFalse(control.state_path.exists())

    def test_bot_construction_does_not_initialize_ai(self) -> None:
        settings = replace(
            self.settings, locales_dir=ROOT / "aa_resources/locales",
            ticket_ai_enabled=True, ticket_ai_auto_reply_enabled=True,
        )
        with patch(FACTORY) as factory:
            bot = BignessLeagueBot(settings)
        self.assertTrue(bot.ticket_ai_control.enabled)
        self.assertIsNone(bot.ticket_ai)
        factory.assert_not_called()


class TicketAiInteractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(token="test", ticket_state_file=Path(temporary.name) / "tickets.json")
        self.control = TicketAiControl(self.settings)
        self.service = SimpleNamespace(
            can_auto_reply=Mock(return_value=True),
            generate_reply=AsyncMock(return_value=REPLY),
        )
        self.localizer = LocalizationService.from_directory(
            directory=ROOT / "aa_resources/locales", default_locale="es-ES",
        )
        self.bot = SimpleNamespace(
            ticket_ai_control=self.control, settings=self.settings,
            localizer=self.localizer, ticket_ai=None,
        )
        self.messenger = SimpleNamespace(broadcast_dm_message=AsyncMock())
        self.ai = TicketAiInteractions(bot=self.bot, participant_messenger=self.messenger)
        self.thread = SimpleNamespace(id=20, send=AsyncMock())
        self.message = SimpleNamespace(id=1, author=SimpleNamespace(id=10), channel=Mock())
        self.record = TicketRecord.create(
            ticket_number=1, user_id=10, thread_id=20, forum_channel_id=30, category_key="general",
        )
        self.interaction = SimpleNamespace(
            client=self.bot, locale=discord.Locale("es-ES"), followup=SimpleNamespace(send=AsyncMock()),
        )
        body = patch(f"{INTERACTIONS}.ticket_ai_message_body", return_value="Hola")
        history = patch(f"{INTERACTIONS}.build_ticket_ai_conversation", new_callable=AsyncMock, return_value=())
        self.body = body.start()
        self.history = history.start()
        self.addCleanup(body.stop)
        self.addCleanup(history.stop)

    def enable(self, service=None) -> None:
        with patch(FACTORY, return_value=service or self.service):
            self.control.set_enabled(True)

    async def reply(self, record=None) -> None:
        await self.ai.maybe_auto_reply_to_user_ticket(
            message=self.message, record=record or self.record, thread=self.thread,
        )

    async def test_disabled_ticket_does_not_load_ai_read_history_or_send_messages(self) -> None:
        with patch(FACTORY) as factory:
            await self.reply()
        factory.assert_not_called()
        self.history.assert_not_awaited()
        self.thread.send.assert_not_awaited()
        self.messenger.broadcast_dm_message.assert_not_awaited()

    async def test_disabled_status_never_pings_backend(self) -> None:
        with patch(f"{INTERACTIONS}.create_ticket_ai_chat_client") as factory:
            await self.ai.send_status(self.interaction)
        factory.assert_not_called()
        result = self.interaction.followup.send.call_args.args[0]
        self.assertIn("No comprobado (IA desactivada)", result)
        self.assertIn("Activada globalmente: `no`", result)

    async def test_global_switch_affects_existing_and_new_tickets(self) -> None:
        self.enable()
        new_record = replace(self.record, thread_id=21, ticket_number=2)
        for record in (self.record, new_record):
            await self.reply(record)
        self.assertEqual(self.service.generate_reply.await_count, 2)
        self.assertEqual(self.messenger.broadcast_dm_message.await_count, 2)
        self.control.set_enabled(False)
        for record in (self.record, new_record):
            await self.reply(record)
        self.assertEqual(self.service.generate_reply.await_count, 2)

    async def test_category_exclusion_still_blocks_generation(self) -> None:
        self.enable()
        self.service.can_auto_reply.return_value = False
        self.service.is_force_escalate_category = Mock(return_value=True)
        await self.reply()
        self.service.generate_reply.assert_not_awaited()

    async def test_disable_while_loading_context_prevents_backend_request(self) -> None:
        self.enable()

        async def context(**kwargs):
            self.control.set_enabled(False)
            return ()

        self.history.side_effect = context
        await self.reply()
        self.service.generate_reply.assert_not_awaited()
        self.thread.send.assert_not_awaited()

    async def test_disable_cancels_pending_response_without_errors(self) -> None:
        self.enable()
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def generate(**kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        self.service.generate_reply.side_effect = generate
        task = asyncio.create_task(self.reply())
        await asyncio.wait_for(started.wait(), timeout=2)
        self.control.set_enabled(False)
        await asyncio.wait_for(task, timeout=2)
        self.assertTrue(cancelled.is_set())
        self.thread.send.assert_not_awaited()
        self.messenger.broadcast_dm_message.assert_not_awaited()

    async def test_old_error_after_disable_and_reenable_is_suppressed(self) -> None:
        self.enable()
        started = asyncio.Event()

        async def generate(**kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise OllamaClientError("Error de consulta anterior")

        self.service.generate_reply.side_effect = generate
        task = asyncio.create_task(self.reply())
        await asyncio.wait_for(started.wait(), timeout=2)
        self.control.set_enabled(False)
        self.enable(SimpleNamespace(generate_reply=AsyncMock(return_value=REPLY)))
        with patch(f"{INTERACTIONS}.LOGGER.warning") as warning:
            await asyncio.wait_for(task, timeout=2)
        warning.assert_not_called()
        self.thread.send.assert_not_awaited()

    async def test_old_success_after_disable_and_reenable_is_discarded(self) -> None:
        self.enable()
        started = asyncio.Event()

        async def generate(**kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return REPLY

        self.service.generate_reply.side_effect = generate
        task = asyncio.create_task(self.reply())
        await asyncio.wait_for(started.wait(), timeout=2)
        self.control.set_enabled(False)
        self.enable(SimpleNamespace(generate_reply=AsyncMock(return_value=REPLY)))
        await asyncio.wait_for(task, timeout=2)
        self.thread.send.assert_not_awaited()
        self.messenger.broadcast_dm_message.assert_not_awaited()

    async def test_external_cancellation_is_propagated(self) -> None:
        self.enable()
        started = asyncio.Event()

        async def generate(**kwargs):
            started.set()
            await asyncio.Event().wait()

        self.service.generate_reply.side_effect = generate
        task = asyncio.create_task(self.reply())
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_disable_during_thread_send_blocks_user_response(self) -> None:
        self.enable()

        async def send(*args, **kwargs):
            self.control.set_enabled(False)

        self.thread.send.side_effect = send
        await self.reply()
        self.messenger.broadcast_dm_message.assert_not_awaited()

    async def test_active_backend_failure_is_reported_to_staff(self) -> None:
        self.enable()
        self.service.generate_reply.side_effect = OllamaClientError("Backend inaccesible")
        with self.assertLogs(INTERACTIONS, level="WARNING"):
            await self.reply()
        self.assertIn("Backend inaccesible", self.thread.send.call_args.args[0])
        self.messenger.broadcast_dm_message.assert_not_awaited()

    async def test_command_activation_failure_is_localized_and_keeps_state(self) -> None:
        with patch(FACTORY, side_effect=OSError("Falta prompt")):
            with self.assertLogs(INTERACTIONS, level="ERROR"):
                with self.assertRaises(CommandUserError):
                    await self.ai.set_enabled(self.interaction, enabled=True)
        self.assertFalse(self.control.enabled)
        self.interaction.followup.send.assert_not_awaited()

    async def test_activation_confirmation_persists_global_state(self) -> None:
        with patch(FACTORY, return_value=self.service):
            await self.ai.set_enabled(self.interaction, enabled=True)
        self.assertTrue(TicketAiControl(self.settings).enabled)
        self.assertIn("tickets abiertos y nuevos", self.interaction.followup.send.call_args.args[0])
        await self.ai.set_enabled(self.interaction, enabled=False)
        self.assertFalse(TicketAiControl(self.settings).enabled)

    async def test_broadcast_stops_if_disabled_while_resolving_recipient(self) -> None:
        self.enable()
        messenger = object.__new__(TicketParticipantMessenger)
        messenger._send_dm = AsyncMock()

        async def resolve(user_id):
            self.control.set_enabled(False)
            return Mock()

        messenger._resolve_ticket_user = AsyncMock(side_effect=resolve)
        await messenger.broadcast_dm_message(
            record=self.record, content=REPLY.answer,
            should_continue=lambda: self.control.is_current(self.service),
        )
        messenger._send_dm.assert_not_awaited()

    async def test_normal_broadcast_keeps_working_without_ai_guard(self) -> None:
        messenger = object.__new__(TicketParticipantMessenger)
        messenger._send_dm = AsyncMock()
        messenger._resolve_ticket_user = AsyncMock(return_value=Mock())
        await messenger.broadcast_dm_message(record=self.record, content="Mensaje del staff")
        messenger._send_dm.assert_awaited_once()


class TicketAiCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Only the command's dependencies are needed; no monitor or Discord connection.
        self.cog = object.__new__(TicketsCog)
        self.cog.ticket_ai_interactions = SimpleNamespace(set_enabled=AsyncMock())
        self.member = Mock(spec=discord.Member)
        self.member.roles = [SimpleNamespace(name="CEO")]
        self.interaction = SimpleNamespace(
            guild=Mock(), user=self.member,
            response=SimpleNamespace(defer=AsyncMock()),
        )

    async def test_ceo_can_enable_and_disable_globally(self) -> None:
        for enabled in (True, False):
            await self.cog.configure_ticket_ai.callback(self.cog, self.interaction, enabled)
            self.cog.ticket_ai_interactions.set_enabled.assert_awaited_with(
                self.interaction, enabled=enabled,
            )

    async def test_non_ceo_cannot_change_global_switch(self) -> None:
        self.member.roles = [SimpleNamespace(name="Jugador")]
        with self.assertRaises(CommandUserError):
            await self.cog.configure_ticket_ai.callback(self.cog, self.interaction, False)
        self.cog.ticket_ai_interactions.set_enabled.assert_not_awaited()
        self.interaction.response.defer.assert_not_awaited()

    async def test_dm_is_rejected_before_changing_state(self) -> None:
        self.interaction.guild = None
        with self.assertRaises(CommandUserError):
            await self.cog.configure_ticket_ai.callback(self.cog, self.interaction, True)
        self.cog.ticket_ai_interactions.set_enabled.assert_not_awaited()

    async def test_command_is_registered_as_required_boolean_and_guild_only(self) -> None:
        command = TicketsCog.configure_ticket_ai
        self.assertEqual(command.name, "activar_ia")
        self.assertTrue(command.guild_only)
        self.assertEqual(len(command.parameters), 1)
        self.assertEqual(command.parameters[0].name, "activada")
        self.assertTrue(command.parameters[0].required)
        self.assertEqual(command.parameters[0].type, discord.AppCommandOptionType.boolean)


if __name__ == "__main__":
    unittest.main()
