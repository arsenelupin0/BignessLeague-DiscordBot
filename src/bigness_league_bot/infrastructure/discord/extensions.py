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

import logging
from collections.abc import Iterable

from discord.ext import commands

LOGGER = logging.getLogger(__name__)

INITIAL_EXTENSIONS: tuple[str, ...] = (
    "bigness_league_bot.presentation.discord.cogs.observability",
    "bigness_league_bot.presentation.discord.cogs.general",
    "bigness_league_bot.presentation.discord.cogs.admin",
    "bigness_league_bot.presentation.discord.cogs.channel_management",
    "bigness_league_bot.presentation.discord.cogs.channel_access",
)


async def load_extensions(bot: commands.Bot, extensions: Iterable[str]) -> None:
    for extension in extensions:
        LOGGER.info("Cargando extension %s", extension)
        await bot.load_extension(extension)
