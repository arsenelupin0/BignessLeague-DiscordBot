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
from bigness_league_bot.core.localization import localize
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
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str
from bigness_league_bot.presentation.discord.views.channel_delete_confirmation import (
    ChannelDeleteConfirmationView,
)
from bigness_league_bot.presentation.discord.views.channel_matchday_close_confirmation import (
    ChannelMatchdayCloseConfirmationView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


def _string_choice(
        name: str | app_commands.locale_str,
        value: str,
) -> app_commands.Choice[str]:
    return cast(app_commands.Choice[str], app_commands.Choice(name=name, value=value))


CHANNEL_CLOSE_CHOICES: list[app_commands.Choice[str]] = [
    _string_choice(
        name=localized_locale_str(
            I18N.commands.channel_management.close_channel.choices.match_played
        ),
        value=ChannelCloseMode.MATCH_PLAYED.value,
    ),
    _string_choice(
        name=localized_locale_str(
            I18N.commands.channel_management.close_channel.choices.matchday_closed
        ),
        value=ChannelCloseMode.MATCHDAY_CLOSED.value,
    ),
    _string_choice(
        name=localized_locale_str(
            I18N.commands.channel_management.close_channel.choices.reopen_match
        ),
        value=ChannelCloseMode.REOPEN_MATCH.value,
    ),
    _string_choice(
        name=localized_locale_str(
            I18N.commands.channel_management.close_channel.choices.delete_channel
        ),
        value=ChannelCloseMode.DELETE_CHANNEL.value,
    ),
]


class ChannelManagement(commands.Cog):
    @app_commands.command(
        name=localized_locale_str(I18N.commands.channel_management.close_channel.name),
        description=localized_locale_str(
            I18N.commands.channel_management.close_channel.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        accion=localized_locale_str(
            I18N.commands.channel_management.close_channel.parameters.action.description
        ),
    )
    @app_commands.choices(accion=CHANNEL_CLOSE_CHOICES)
    async def close_channel(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            accion: app_commands.Choice[str],
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        channel = require_text_channel(interaction.channel)
        ensure_valid_match_channel_name(channel)
        ensure_allowed_member(interaction.user)
        selected_action = ChannelCloseMode(accion.value)

        if selected_action is ChannelCloseMode.DELETE_CHANNEL:
            await self._prompt_channel_deletion(interaction, channel)
            return

        if selected_action is ChannelCloseMode.MATCHDAY_CLOSED:
            await self._prompt_matchday_close(interaction, channel)
            return

        await interaction.response.defer(thinking=True)
        action_result = await self._execute_channel_action(
            channel=channel,
            actor=interaction.user,
            action=selected_action,
        )
        await interaction.followup.send(
            interaction.client.localizer.render(
                action_result.summary,
                locale=interaction.locale,
            )
        )

    @staticmethod
    async def _prompt_channel_deletion(
            interaction: discord.Interaction[BignessLeagueBot],
            channel: discord.TextChannel,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        protected_roles = protected_role_names_label()
        view = ChannelDeleteConfirmationView(
            channel=channel,
            actor=interaction.user,
            localizer=interaction.client.localizer,
            locale=interaction.locale,
        )
        await interaction.response.send_message(
            interaction.client.localizer.translate(
                I18N.messages.channel_management.delete_prompt,
                locale=interaction.locale,
                channel_name=channel.name,
                protected_roles=protected_roles,
            ),
            view=view,
        )
        view.message = await interaction.original_response()

    @staticmethod
    async def _prompt_matchday_close(
            interaction: discord.Interaction[BignessLeagueBot],
            channel: discord.TextChannel,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        protected_roles = protected_role_names_label()
        view = ChannelMatchdayCloseConfirmationView(
            channel=channel,
            actor=interaction.user,
            localizer=interaction.client.localizer,
            locale=interaction.locale,
        )
        await interaction.response.send_message(
            interaction.client.localizer.translate(
                I18N.messages.channel_management.matchday_close_prompt,
                locale=interaction.locale,
                channel_name=channel.name,
                protected_roles=protected_roles,
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
        await self._send_error(
            interaction,
            interaction.client.localizer.render(
                error_details.user_message,
                locale=interaction.locale,
            ),
        )

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
