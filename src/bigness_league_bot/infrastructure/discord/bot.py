#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
from __future__ import annotations

import logging

import discord
from discord.ext import commands

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

LOGGER = logging.getLogger(__name__)


class BignessLeagueBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(settings.command_prefix),
            intents=intents,
        )
        self.settings = settings
        register_tree_error_handler(self)

    async def setup_hook(self) -> None:
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
