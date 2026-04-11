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

from dataclasses import dataclass, field
from typing import Any, TypeAlias


@dataclass(frozen=True, slots=True)
class TranslationKey:
    key: str
    default_text: str | None = None

    @property
    def default(self) -> str:
        return self.default_text or self.key


TranslationKeyLike: TypeAlias = str | TranslationKey


@dataclass(frozen=True, slots=True)
class LocalizedText:
    key: str
    params: dict[str, Any] = field(default_factory=dict)
    fallback: str | None = None


def normalize_translation_key(key: TranslationKeyLike, /) -> TranslationKey:
    if isinstance(key, TranslationKey):
        return key

    return TranslationKey(key=key)


def localize(key: TranslationKeyLike, /, **params: Any) -> LocalizedText:
    translation_key = normalize_translation_key(key)
    return LocalizedText(
        key=translation_key.key,
        params=params,
        fallback=translation_key.default_text,
    )
