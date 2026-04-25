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

import json
import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger("bigness_league_bot.activity")


def _truncate(value: str, limit: int = 500) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...<truncated>"


def _serialize_payload(payload: Any) -> str:
    try:
        serialized = json.dumps(payload, ensure_ascii=True, default=str)
    except TypeError:
        serialized = repr(payload)
    return _truncate(serialized)


def user_label(user: discord.abc.User | discord.Member | None) -> str:
    if user is None:
        return "unknown-user"
    return f"{user.name}({user.id})"


def guild_label(guild: discord.Guild | None) -> str:
    if guild is None:
        return "DM"
    return f"{guild.name}({guild.id})"


def channel_label(channel: object) -> str:
    if channel is None:
        return "unknown-channel"

    channel_id = getattr(channel, "id", "unknown-id")
    channel_name = getattr(channel, "name", type(channel).__name__)
    return f"{channel_name}({channel_id})"


def command_label(
        command: app_commands.Command | app_commands.Group | app_commands.ContextMenu | app_commands.AppCommand | None,
) -> str:
    if command is None:
        return "unknown-command"

    qualified_name = getattr(command, "qualified_name", None)
    if isinstance(qualified_name, str) and qualified_name:
        return qualified_name

    name = getattr(command, "name", None)
    if isinstance(name, str) and name:
        return name

    return type(command).__name__


def register_tree_error_handler(bot: BignessLeagueBot) -> None:
    @bot.tree.error
    async def on_app_command_error(
            interaction: discord.Interaction[BignessLeagueBot],
            error: app_commands.AppCommandError,
    ) -> None:
        command_name = command_label(interaction.command)
        error_details = classify_app_command_error(error)
        LOGGER.log(
            error_details.log_level,
            "%s command=%s user=%s guild=%s channel=%s payload=%s",
            error_details.log_code,
            command_name,
            user_label(interaction.user),
            guild_label(interaction.guild),
            channel_label(interaction.channel),
            _serialize_payload(interaction.data),
            exc_info=error if error_details.include_traceback else None,
        )
