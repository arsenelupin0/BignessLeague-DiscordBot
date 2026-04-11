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
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_management import (
    UnsupportedChannelError,
    ensure_allowed_member,
    ensure_valid_match_channel_name,
    get_channel_access_role_catalog,
    require_text_channel,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str
from bigness_league_bot.presentation.discord.views.channel_role_addition import (
    ChannelRoleAdditionView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class ChannelAccess(commands.Cog):
    @app_commands.command(
        name=localized_locale_str(I18N.commands.channel_access.add_to_channel.name),
        description=localized_locale_str(
            I18N.commands.channel_access.add_to_channel.description
        ),
    )
    @app_commands.guild_only()
    async def add_roles_to_channel(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        channel = require_text_channel(interaction.channel)
        ensure_valid_match_channel_name(channel)
        ensure_allowed_member(interaction.user)
        settings = interaction.client.settings
        role_catalog = get_channel_access_role_catalog(
            channel.guild,
            settings.channel_access_range_start_role_id,
            settings.channel_access_range_end_role_id,
        )

        view = ChannelRoleAdditionView(
            channel=channel,
            actor=interaction.user,
            role_catalog=role_catalog,
            localizer=interaction.client.localizer,
            locale=interaction.locale,
        )
        await interaction.response.send_message(
            view.render_content(),
            view=view,
        )
        view.message = await interaction.original_response()

    async def cog_app_command_error(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            error: app_commands.AppCommandError,
    ) -> None:
        error_details = classify_app_command_error(error)
        if interaction.response.is_done():
            await interaction.followup.send(
                interaction.client.localizer.render(
                    error_details.user_message,
                    locale=interaction.locale,
                )
            )
            return

        await interaction.response.send_message(
            interaction.client.localizer.render(
                error_details.user_message,
                locale=interaction.locale,
            )
        )


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(ChannelAccess())
