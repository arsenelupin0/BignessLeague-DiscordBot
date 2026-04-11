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
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.infrastructure.discord.telemetry import (
    channel_label,
    command_label,
    guild_label,
    user_label,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger("bigness_league_bot.activity")


def _message_preview(content: str, limit: int = 200) -> str:
    if len(content) <= limit:
        return content
    return f"{content[:limit]}...<truncated>"


class Observability(commands.Cog):
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_connect(self) -> None:
        LOGGER.info("DISCORD_CONNECT")

    @commands.Cog.listener()
    async def on_disconnect(self) -> None:
        LOGGER.warning("DISCORD_DISCONNECT")

    @commands.Cog.listener()
    async def on_resumed(self) -> None:
        LOGGER.info("DISCORD_RESUMED")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        LOGGER.info("GUILD_JOIN guild=%s", guild_label(guild))

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        LOGGER.warning("GUILD_REMOVE guild=%s", guild_label(guild))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not self.bot.settings.log_all_messages:
            return

        LOGGER.info(
            "MESSAGE guild=%s channel=%s user=%s content=%r",
            guild_label(message.guild),
            channel_label(message.channel),
            user_label(message.author),
            _message_preview(message.content),
        )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction[BignessLeagueBot]) -> None:
        if interaction.type == discord.InteractionType.application_command:
            LOGGER.info(
                "SLASH_COMMAND_RECEIVED command=%s user=%s guild=%s channel=%s",
                command_label(interaction.command),
                user_label(interaction.user),
                guild_label(interaction.guild),
                channel_label(interaction.channel),
            )
            return

        LOGGER.info(
            "INTERACTION type=%s user=%s guild=%s channel=%s",
            interaction.type.name,
            user_label(interaction.user),
            guild_label(interaction.guild),
            channel_label(interaction.channel),
        )

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context[BignessLeagueBot]) -> None:
        command_name = ctx.command.qualified_name if ctx.command is not None else "unknown-command"
        LOGGER.info(
            "TEXT_COMMAND_RECEIVED command=%s user=%s guild=%s channel=%s content=%r",
            command_name,
            user_label(ctx.author),
            guild_label(ctx.guild),
            channel_label(ctx.channel),
            _message_preview(ctx.message.content),
        )

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context[BignessLeagueBot]) -> None:
        command_name = ctx.command.qualified_name if ctx.command is not None else "unknown-command"
        LOGGER.info(
            "TEXT_COMMAND_COMPLETED command=%s user=%s guild=%s channel=%s",
            command_name,
            user_label(ctx.author),
            guild_label(ctx.guild),
            channel_label(ctx.channel),
        )

    @commands.Cog.listener()
    async def on_command_error(
            self,
            ctx: commands.Context[BignessLeagueBot],
            error: commands.CommandError,
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return

        command_name = ctx.command.qualified_name if ctx.command is not None else "unknown-command"
        LOGGER.exception(
            "TEXT_COMMAND_ERROR command=%s user=%s guild=%s channel=%s",
            command_name,
            user_label(ctx.author),
            guild_label(ctx.guild),
            channel_label(ctx.channel),
            exc_info=error,
        )

    @commands.Cog.listener()
    async def on_app_command_completion(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            command: app_commands.Command | app_commands.ContextMenu,
    ) -> None:
        LOGGER.info(
            "SLASH_COMMAND_COMPLETED command=%s user=%s guild=%s channel=%s",
            command_label(command),
            user_label(interaction.user),
            guild_label(interaction.guild),
            channel_label(interaction.channel),
        )


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(Observability(bot))
