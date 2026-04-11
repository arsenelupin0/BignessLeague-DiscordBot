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

from typing import TYPE_CHECKING

import discord

from bigness_league_bot.infrastructure.discord.channel_management import (
    delete_text_channel,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class ChannelDeleteConfirmationView(discord.ui.View):
    def __init__(
            self,
            *,
            channel: discord.TextChannel,
            actor: discord.Member,
            timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.channel = channel
        self.actor = actor
        self.message: discord.InteractionMessage | None = None

    async def interaction_check(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> bool:
        if interaction.user.id == self.actor.id:
            return True

        await interaction.response.send_message(
            "Solo quien ejecuto el comando puede confirmar esta accion.",
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True

        if self.message is not None:
            await self.message.edit(
                content="La confirmacion ha expirado. No se ha eliminado el canal.",
                view=self,
            )

    @discord.ui.button(
        label="Confirmar eliminacion",
        style=discord.ButtonStyle.danger,
    )
    async def confirm_delete(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            button: discord.ui.Button[discord.ui.View],
    ) -> None:
        del button
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="Eliminando canal...",
            view=self,
        )
        self.stop()
        await delete_text_channel(self.channel, self.actor)

    @discord.ui.button(
        label="Cancelar",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel_delete(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            button: discord.ui.Button[discord.ui.View],
    ) -> None:
        del button
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="Eliminacion cancelada.",
            view=self,
        )
        self.stop()
