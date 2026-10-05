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
    get_dm_command_names,
    get_local_command_names,
    sync_dm_commands_globally,
    sync_command_tree,
)
from bigness_league_bot.infrastructure.discord.telemetry import register_tree_error_handler
from bigness_league_bot.infrastructure.i18n.discord_translator import DiscordTranslator
from bigness_league_bot.infrastructure.i18n.service import LocalizationService
from bigness_league_bot.infrastructure.ticket_ai.control import TicketAiControl

LOGGER = logging.getLogger(__name__)


class BignessLeagueBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        setattr(intents, "members", True)
        setattr(intents, "message_content", True)

        super().__init__(
            command_prefix=commands.when_mentioned_or(settings.command_prefix),
            help_command=None,
            intents=intents,
        )
        self.settings = settings
        self.localizer: LocalizationService = LocalizationService.from_directory(
            directory=settings.locales_dir,
            default_locale=settings.default_locale,
        )
        self.ticket_ai_control = TicketAiControl(settings)
        register_tree_error_handler(self)

    @property
    def ticket_ai(self) -> TicketAiService | None:
        return self.ticket_ai_control.service

    async def setup_hook(self) -> None:
        await self.tree.set_translator(DiscordTranslator(self.localizer))
        await load_extensions(self, INITIAL_EXTENSIONS)

        local_commands = get_local_command_names(self.tree)
        LOGGER.info(
            "Comandos slash cargados localmente: %s",
            ", ".join(local_commands) if local_commands else "(ninguno)",
        )

        LOGGER.info(
            "Sincronización iniciada: entorno=%s scope=%s guild_id=%s application_id=%s bot_id=%s",
            self.settings.environment,
            self.settings.sync_scope,
            self.settings.guild_id,
            self.application_id,
            self.user.id if self.user is not None else None,
        )
        sync_report = await sync_command_tree(
            self.tree,
            self.settings.sync_scope,
            self.settings.guild_id,
        )
        LOGGER.info("Sincronización completada: %s", sync_report.format_summary())

        if self.settings.sync_scope == "guild":
            dm_command_names = get_dm_command_names(self.tree)
            dm_sync_report = await sync_dm_commands_globally(self.tree)
            LOGGER.info(
                "Sincronización global para DM completada: %s | Locales DM=[%s]",
                dm_sync_report.format_summary(),
                ", ".join(dm_command_names) if dm_command_names else "(ninguno)",
            )

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
            "TEAM_CHANGE_BULLETIN_RUNTIME environment=%s worksheets=%s channel_id=%s logos=attachment_v1",
            self.settings.environment,
            self.settings.google_sheets_team_sheet_name,
            self.settings.team_role_removal_announcement_channel_id,
        )
        LOGGER.info(
            "Ticket AI cargada=%s | Activada globalmente=%s | Provider=%s | Modelo=%s | Base URL=%s | Auto-reply=%s",
            "activada" if self.ticket_ai is not None else "desactivada",
            self.ticket_ai_control.enabled,
            self.settings.ticket_ai_provider,
            self.settings.ticket_ai_model,
            self.settings.ticket_ai_base_url,
            self.ticket_ai_control.enabled,
        )
