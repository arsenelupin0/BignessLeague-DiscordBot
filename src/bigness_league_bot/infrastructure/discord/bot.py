#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from bigness_league_bot.application.services.ticket_ai import TicketAiService
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.discord.extensions import (
    INITIAL_EXTENSIONS,
    load_extensions,
)
from bigness_league_bot.infrastructure.discord.sync import (
    get_local_command_names,
    sync_command_tree,
)
from bigness_league_bot.infrastructure.discord.telemetry import register_tree_error_handler
from bigness_league_bot.infrastructure.i18n.discord_translator import DiscordTranslator
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

LOGGER = logging.getLogger(__name__)


class BignessLeagueBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(settings.command_prefix),
            intents=intents,
        )
        self.settings = settings
        self.localizer: LocalizationService = LocalizationService.from_directory(
            directory=settings.locales_dir,
            default_locale=settings.default_locale,
        )
        self.ticket_ai: TicketAiService | None = TicketAiService.from_settings(settings)
        register_tree_error_handler(self)

    async def setup_hook(self) -> None:
        await self.tree.set_translator(DiscordTranslator(self.localizer))
        await load_extensions(self, INITIAL_EXTENSIONS)

        local_commands = get_local_command_names(self.tree)
        LOGGER.info(
            "Comandos slash cargados localmente: %s",
            ", ".join(local_commands) if local_commands else "(ninguno)",
        )

        sync_report = await sync_command_tree(
            self.tree,
            self.settings.sync_scope,
            self.settings.guild_id,
        )
        LOGGER.info("Sincronizacion completada: %s", sync_report.format_summary())

    async def on_ready(self) -> None:
        user = self.user
        if user is None:
            return

        LOGGER.info("Bot conectado como %s (%s).", user, user.id)
        LOGGER.info(
            "Prefijo=%s | Entorno=%s | Sync scope=%s | Guild de desarrollo=%s",
            self.settings.command_prefix,
            self.settings.environment,
            self.settings.sync_scope,
            self.settings.guild_id or "(sin configurar)",
        )
        LOGGER.info(
            "Ticket AI runtime=%s | Configurada=%s | Provider=%s | Modelo=%s | Base URL=%s | Auto-reply=%s",
            "activada" if self.ticket_ai is not None else "desactivada",
            self.settings.ticket_ai_enabled,
            self.settings.ticket_ai_provider,
            self.settings.ticket_ai_model,
            self.settings.ticket_ai_base_url,
            self.settings.ticket_ai_auto_reply_enabled,
        )
