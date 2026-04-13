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

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class TranslationCatalogError(RuntimeError):
    """Raised when a translation catalog cannot be loaded or rendered."""


def _resolve_key_path(payload: Mapping[str, Any], key: str) -> str | None:
    current: Any = payload
    for segment in key.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return None
        current = current[segment]

    if isinstance(current, str):
        return current

    raise TranslationCatalogError(f"La clave `{key}` no apunta a una cadena traducible.")


@dataclass(frozen=True, slots=True)
class TranslationCatalog:
    directory: Path
    default_locale: str
    catalogs: dict[str, dict[str, Any]]

    @classmethod
    def from_directory(
            cls,
            directory: Path,
            default_locale: str,
    ) -> "TranslationCatalog":
        resolved_directory = directory.resolve()
        if not resolved_directory.exists():
            raise TranslationCatalogError(
                f"No existe el directorio de traducciones `{resolved_directory}`."
            )

        catalogs: dict[str, dict[str, Any]] = {}
        for path in sorted(resolved_directory.glob("*.json")):
            with path.open("r", encoding="utf-8-sig") as file:
                loaded_payload = json.load(file)

            if not isinstance(loaded_payload, dict):
                raise TranslationCatalogError(
                    f"El catalogo `{path}` debe contener un objeto JSON en la raiz."
                )

            catalogs[path.stem] = loaded_payload

        if default_locale not in catalogs:
            raise TranslationCatalogError(
                f"Falta el catalogo por defecto `{default_locale}` en `{resolved_directory}`."
            )

        return cls(
            directory=resolved_directory,
            default_locale=default_locale,
            catalogs=catalogs,
        )

    def translate(
            self,
            key: str,
            *,
            locale: str,
            fallback: str | None = None,
            params: Mapping[str, Any] | None = None,
    ) -> str:
        template = self._find_template(key, locale)
        if template is None:
            template = fallback

        if template is None:
            LOGGER.warning(
                "TRANSLATION_MISSING key=%s locale=%s default_locale=%s",
                key,
                locale,
                self.default_locale,
            )
            return key

        if not params:
            return template

        try:
            return template.format(**params)
        except KeyError as exc:
            raise TranslationCatalogError(
                f"Falta el parametro `{exc.args[0]}` al renderizar `{key}`."
            ) from exc

    def _find_template(self, key: str, locale: str) -> str | None:
        for candidate_locale in self._candidate_locales(locale):
            payload = self.catalogs.get(candidate_locale)
            if payload is None:
                continue

            resolved_template = _resolve_key_path(payload, key)
            if resolved_template is not None:
                return resolved_template

        return None

    def _candidate_locales(self, locale: str) -> tuple[str, ...]:
        candidates: list[str] = []
        for candidate in self._expand_locale_candidates(locale):
            if candidate not in candidates:
                candidates.append(candidate)

        for candidate in self._expand_locale_candidates(self.default_locale):
            if candidate not in candidates:
                candidates.append(candidate)

        return tuple(candidates)

    def _expand_locale_candidates(self, locale: str) -> tuple[str, ...]:
        normalized_locale = locale.strip()
        if not normalized_locale:
            return ()

        candidates = [normalized_locale]
        language = normalized_locale.split("-", maxsplit=1)[0]
        if language not in candidates:
            candidates.append(language)

        for catalog_locale in sorted(self.catalogs):
            catalog_language = catalog_locale.split("-", maxsplit=1)[0]
            if catalog_language == language and catalog_locale not in candidates:
                candidates.append(catalog_locale)

        return tuple(candidates)
