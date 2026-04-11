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

from typing import TYPE_CHECKING, cast

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.channel_closure import (
    ChannelActionResult,
    ChannelCloseMode,
    protected_role_names_label,
)
from bigness_league_bot.infrastructure.discord.channel_management import (
    UnsupportedChannelError,
    apply_match_reopen,
    apply_match_played_lockdown,
    apply_matchday_closed,
    ensure_allowed_member,
    ensure_valid_match_channel_name,
    require_text_channel,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.presentation.discord.views.channel_delete_confirmation import (
    ChannelDeleteConfirmationView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


def _string_choice(name: str, value: str) -> app_commands.Choice[str]:
    return cast(app_commands.Choice[str], app_commands.Choice(name=name, value=value))


CHANNEL_CLOSE_CHOICES: list[app_commands.Choice[str]] = [
    _string_choice(
        name=ChannelCloseMode.MATCH_PLAYED.label,
        value=ChannelCloseMode.MATCH_PLAYED.value,
    ),
    _string_choice(
        name=ChannelCloseMode.MATCHDAY_CLOSED.label,
        value=ChannelCloseMode.MATCHDAY_CLOSED.value,
    ),
    _string_choice(
        name=ChannelCloseMode.REOPEN_MATCH.label,
        value=ChannelCloseMode.REOPEN_MATCH.value,
    ),
    _string_choice(
        name=ChannelCloseMode.DELETE_CHANNEL.label,
        value=ChannelCloseMode.DELETE_CHANNEL.value,
    ),
]


class ChannelManagement(commands.Cog):
    @app_commands.command(
        name="cerrar_canal",
        description="Aplica una accion de cierre sobre el canal actual.",
    )
    @app_commands.guild_only()
    @app_commands.describe(
        accion="Selecciona el tipo de cierre que quieres aplicar",
    )
    @app_commands.choices(accion=CHANNEL_CLOSE_CHOICES)
    async def close_channel(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            accion: app_commands.Choice[str],
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                "Este comando solo se puede usar dentro de un servidor."
            )

        channel = require_text_channel(interaction.channel)
        ensure_valid_match_channel_name(channel)
        ensure_allowed_member(interaction.user)
        selected_action = ChannelCloseMode(accion.value)

        if selected_action is ChannelCloseMode.DELETE_CHANNEL:
            await self._prompt_channel_deletion(interaction, channel)
            return

        await interaction.response.defer(thinking=True)
        action_result = await self._execute_channel_action(
            channel=channel,
            actor=interaction.user,
            action=selected_action,
        )
        await interaction.followup.send(action_result.summary)

    @staticmethod
    async def _prompt_channel_deletion(
            interaction: discord.Interaction[BignessLeagueBot],
            channel: discord.TextChannel,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                "Este comando solo se puede usar dentro de un servidor."
            )

        protected_roles = protected_role_names_label()
        view = ChannelDeleteConfirmationView(
            channel=channel,
            actor=interaction.user,
        )
        await interaction.response.send_message(
            (
                f"Vas a eliminar el canal `{channel.name}` de forma permanente.\n"
                f"Roles protegidos del sistema: {protected_roles}.\n"
                "Confirma solo si estas completamente seguro."
            ),
            view=view,
        )
        view.message = await interaction.original_response()

    @staticmethod
    async def _execute_channel_action(
            *,
            channel: discord.TextChannel,
            actor: discord.Member,
            action: ChannelCloseMode,
    ) -> ChannelActionResult:
        if action is ChannelCloseMode.MATCH_PLAYED:
            return await apply_match_played_lockdown(channel, actor)

        if action is ChannelCloseMode.MATCHDAY_CLOSED:
            return await apply_matchday_closed(channel, actor)

        if action is ChannelCloseMode.REOPEN_MATCH:
            return await apply_match_reopen(channel, actor)

        raise RuntimeError(f"Accion no soportada: {action}")

    async def cog_app_command_error(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            error: app_commands.AppCommandError,
    ) -> None:
        error_details = classify_app_command_error(error)
        await self._send_error(interaction, error_details.user_message)

    @staticmethod
    async def _send_error(
            interaction: discord.Interaction[BignessLeagueBot],
            message: str,
    ) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message)
            return

        await interaction.response.send_message(message)


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(ChannelManagement())
