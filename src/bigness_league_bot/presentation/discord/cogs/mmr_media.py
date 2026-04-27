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

from bigness_league_bot.application.services.mmr_media import calculate_mmr_media
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class MmrMediaCog(commands.Cog):
    @app_commands.command(
        name=localized_locale_str(I18N.commands.mmr_media.calculate.name),
        description=localized_locale_str(I18N.commands.mmr_media.calculate.description),
    )
    @app_commands.describe(
        mmr_1=localized_locale_str(
            I18N.commands.mmr_media.calculate.parameters.mmr_1.description
        ),
        mmr_2=localized_locale_str(
            I18N.commands.mmr_media.calculate.parameters.mmr_2.description
        ),
        mmr_3=localized_locale_str(
            I18N.commands.mmr_media.calculate.parameters.mmr_3.description
        ),
    )
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=False)
    async def calculate(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            mmr_1: app_commands.Range[int, 0, 5000],
            mmr_2: app_commands.Range[int, 0, 5000],
            mmr_3: app_commands.Range[int, 0, 5000],
    ) -> None:
        result = calculate_mmr_media(
            mmr_1,
            mmr_2,
            mmr_3,
            limit=interaction.client.settings.mmr_media_limit,
        )
        message_key = (
            I18N.messages.mmr_media.eligible
            if result.is_eligible
            else I18N.messages.mmr_media.too_high
        )
        await interaction.response.send_message(
            interaction.client.localizer.translate(
                message_key,
                locale=interaction.locale,
                mmr_1=mmr_1,
                mmr_2=mmr_2,
                mmr_3=mmr_3,
                average=result.average,
                limit=result.limit,
            )
        )

    async def cog_app_command_error(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            error: app_commands.AppCommandError,
    ) -> None:
        error_details = classify_app_command_error(error)
        message = interaction.client.localizer.render(
            error_details.user_message,
            locale=interaction.locale,
        )
        if interaction.response.is_done():
            await interaction.followup.send(message)
            return

        await interaction.response.send_message(message)


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(MmrMediaCog())
