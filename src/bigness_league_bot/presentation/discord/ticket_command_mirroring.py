from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


async def mirror_ticket_command_message(
        interaction: discord.Interaction[BignessLeagueBot],
        message: discord.Message,
        *,
        command_name: str,
) -> None:
    cog = interaction.client.get_cog("TicketsCog")
    if cog is None:
        return

    mirror_method = getattr(cog, "mirror_thread_command_message", None)
    if not callable(mirror_method):
        return

    await mirror_method(message, command_name=command_name)


async def mirror_ticket_command_message_edit(
        interaction: discord.Interaction[BignessLeagueBot],
        message: discord.Message,
        *,
        command_name: str,
) -> None:
    cog = interaction.client.get_cog("TicketsCog")
    if cog is None:
        return

    mirror_method = getattr(cog, "mirror_thread_command_message_edit", None)
    if not callable(mirror_method):
        return

    await mirror_method(message, command_name=command_name)


async def fetch_interaction_message(
        interaction: discord.Interaction[Any],
        message_id: int,
) -> discord.Message | None:
    channel = interaction.channel
    if channel is None or not hasattr(channel, "fetch_message"):
        return None

    try:
        return await channel.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None
