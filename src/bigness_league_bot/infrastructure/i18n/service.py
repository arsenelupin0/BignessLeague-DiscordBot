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

from pathlib import Path
from typing import Any

import discord
from discord import app_commands

from bigness_league_bot.core.localization import (
    LocalizedText,
    TranslationKey,
    TranslationKeyLike,
    normalize_translation_key,
)
from bigness_league_bot.infrastructure.i18n.catalog import TranslationCatalog

TRANSLATION_KEY_EXTRA = "i18n_key"


def localized_locale_str(
        key: TranslationKeyLike,
        translation_key: str | None = None,
) -> app_commands.locale_str:
    if isinstance(key, TranslationKey):
        if translation_key is not None:
            raise TypeError(
                "No puedes pasar `translation_key` cuando usas `TranslationKey`."
            )
        entry = key
    else:
        if translation_key is None:
            raise TypeError(
                "Si usas una cadena como texto base, debes indicar la clave de traducción."
            )
        entry = TranslationKey(key=translation_key, default_text=key)

    return app_commands.locale_str(entry.default, **{TRANSLATION_KEY_EXTRA: entry.key})


class LocalizationService:
    def __init__(
            self,
            *,
            default_locale: str,
            catalog: TranslationCatalog,
    ) -> None:
        self.default_locale = default_locale
        self.catalog = catalog

    @classmethod
    def from_directory(
            cls,
            *,
            directory: Path,
            default_locale: str,
    ) -> "LocalizationService":
        return cls(
            default_locale=default_locale,
            catalog=TranslationCatalog.from_directory(
                directory=directory,
                default_locale=default_locale,
            ),
        )

    def translate(
            self,
            key: TranslationKeyLike,
            *,
            locale: str | discord.Locale | None = None,
            fallback: str | None = None,
            **params: Any,
    ) -> str:
        translation_key = normalize_translation_key(key)
        locale_code = self._coerce_locale(locale)
        return self.catalog.translate(
            translation_key.key,
            locale=locale_code,
            fallback=translation_key.default_text if fallback is None else fallback,
            params=params,
        )

    def render(
            self,
            text: LocalizedText,
            *,
            locale: str | discord.Locale | None = None,
            fallback: str | None = None,
    ) -> str:
        return self.translate(
            text.key,
            locale=locale,
            fallback=text.fallback if fallback is None else fallback,
            **text.params,
        )

    def _coerce_locale(self, locale: str | discord.Locale | None) -> str:
        if locale is None:
            return self.default_locale

        if isinstance(locale, discord.Locale):
            return locale.value

        return locale
