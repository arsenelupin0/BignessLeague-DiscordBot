#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.text_tools import count_characters


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="countchars",
        description="Cuenta cuantos caracteres tiene un texto.",
    )
    @app_commands.describe(text="Texto que quieres analizar")
    async def countchars(self, interaction: discord.Interaction, text: str) -> None:
        total_characters = count_characters(text)
        await interaction.response.send_message(
            f"El texto tiene {total_characters} caracteres."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
