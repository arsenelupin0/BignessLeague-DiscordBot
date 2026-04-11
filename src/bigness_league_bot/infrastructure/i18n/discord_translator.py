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

import discord
from discord import app_commands

from bigness_league_bot.infrastructure.i18n.service import (
    LocalizationService,
    TRANSLATION_KEY_EXTRA,
)


class DiscordTranslator(app_commands.Translator):
    def __init__(self, localizer: LocalizationService) -> None:
        self.localizer = localizer

    async def translate(
            self,
            string: app_commands.locale_str,
            locale: discord.Locale,
            context: app_commands.TranslationContextTypes,
    ) -> str | None:
        del context
        translation_key = string.extras.get(TRANSLATION_KEY_EXTRA)
        if not isinstance(translation_key, str):
            return None

        return self.localizer.translate(
            translation_key,
            locale=locale,
            fallback=string.message,
        )
