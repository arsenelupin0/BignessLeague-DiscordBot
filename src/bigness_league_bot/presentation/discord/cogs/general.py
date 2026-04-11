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

from bigness_league_bot.application.services.text_tools import count_characters
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class General(commands.Cog):
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot

    @app_commands.command(
        name=localized_locale_str(
            "countchars",
            "commands.general.countchars.name",
        ),
        description=localized_locale_str(
            "Cuenta cuantos caracteres tiene un texto.",
            "commands.general.countchars.description",
        ),
    )
    @app_commands.describe(
        text=localized_locale_str(
            "Texto que quieres analizar",
            "commands.general.countchars.parameters.text.description",
        )
    )
    async def countchars(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            text: str,
    ) -> None:
        total_characters = count_characters(text)
        await interaction.response.send_message(
            interaction.client.localizer.translate(
                "messages.general.countchars.result",
                locale=interaction.locale,
                total_characters=total_characters,
            )
        )


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(General(bot))
