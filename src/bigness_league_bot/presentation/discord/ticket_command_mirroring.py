from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import discord

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


@runtime_checkable
class TicketCommandMirrorCog(Protocol):
    async def mirror_thread_command_message(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        ...

    async def mirror_thread_command_message_edit(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        ...


@runtime_checkable
class MessageFetchableChannel(Protocol):
    async def fetch_message(self, message_id: int) -> discord.Message:
        ...


async def _mirror_ticket_message(
        bot: BignessLeagueBot,
        message: discord.Message,
        *,
        command_name: str,
        edit: bool,
) -> None:
    cog = bot.get_cog("TicketsCog")
    if not isinstance(cog, TicketCommandMirrorCog):
        return

    if edit:
        await cog.mirror_thread_command_message_edit(
            message,
            command_name=command_name,
        )
        return

    await cog.mirror_thread_command_message(
        message,
        command_name=command_name,
    )


async def mirror_ticket_command_message(
        interaction: discord.Interaction[BignessLeagueBot],
        message: discord.Message,
        *,
        command_name: str,
) -> None:
    await _mirror_ticket_message(
        interaction.client,
        message,
        command_name=command_name,
        edit=False,
    )


async def mirror_ticket_command_message_edit(
        interaction: discord.Interaction[BignessLeagueBot],
        message: discord.Message,
        *,
        command_name: str,
) -> None:
    await _mirror_ticket_message(
        interaction.client,
        message,
        command_name=command_name,
        edit=True,
    )


async def mirror_ticket_text_command_message(
        bot: BignessLeagueBot,
        message: discord.Message,
        *,
        command_name: str,
) -> None:
    await _mirror_ticket_message(
        bot,
        message,
        command_name=command_name,
        edit=False,
    )


async def fetch_interaction_message(
        interaction: discord.Interaction[Any],
        message_id: int,
) -> discord.Message | None:
    channel = interaction.channel
    if not isinstance(channel, MessageFetchableChannel):
        return None

    try:
        return await channel.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None
