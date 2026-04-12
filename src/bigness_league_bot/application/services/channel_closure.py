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

import re
from dataclasses import dataclass
from enum import StrEnum

from bigness_league_bot.core.localization import LocalizedText

PROTECTED_ROLE_NAMES: tuple[str, ...] = ("Staff", "Administrador", "Ceo")
MATCH_CHANNEL_NAME_SUFFIX = "\u30fb\u26bd"
MATCH_CHANNEL_LEGACY_NAME_PATTERN = re.compile(
    r"^j[1-9][0-9]?-partido-[1-9][0-9]?(?:\u30fb\u26bd)?$"
)
MATCH_CHANNEL_EMOJI_NAME_PATTERN = re.compile(
    r"^\u300e\U0001d5dd\u300f(?:[0-9]\ufe0f\u20e3){1,2}"
    r"\u300e\U0001d5e3\u300f(?:[0-9]\ufe0f\u20e3){1,2}\u30fb\u26bd$"
)
MATCH_CHANNEL_J_PREFIX = "\u300e\U0001d5dd\u300f"
MATCH_CHANNEL_P_PREFIX = "\u300e\U0001d5e3\u300f"
KEYCAP_SUFFIX = "\ufe0f\u20e3"
KEYCAP_DIGITS: dict[str, str] = {
    digit: f"{digit}{KEYCAP_SUFFIX}"
    for digit in "0123456789"
}


def is_match_channel_name(channel_name: str) -> bool:
    return (
            MATCH_CHANNEL_LEGACY_NAME_PATTERN.fullmatch(channel_name) is not None
            or MATCH_CHANNEL_EMOJI_NAME_PATTERN.fullmatch(channel_name) is not None
    )


def format_match_channel_number(number: int) -> str:
    return "".join(KEYCAP_DIGITS[digit] for digit in str(number))


def format_match_channel_name(jornada: int, partido: int) -> str:
    return (
        f"{MATCH_CHANNEL_J_PREFIX}{format_match_channel_number(jornada)}"
        f"{MATCH_CHANNEL_P_PREFIX}{format_match_channel_number(partido)}"
        f"{MATCH_CHANNEL_NAME_SUFFIX}"
    )


def legacy_match_channel_names(jornada: int, partido: int) -> tuple[str, str]:
    base_channel_name = f"j{jornada}-partido-{partido}"
    return base_channel_name, f"{base_channel_name}{MATCH_CHANNEL_NAME_SUFFIX}"


def protected_role_names_label() -> str:
    return ", ".join(PROTECTED_ROLE_NAMES)


class ChannelCloseMode(StrEnum):
    MATCH_PLAYED = "partido_jugado"
    MATCHDAY_CLOSED = "jornada_cerrada"
    REOPEN_MATCH = "reabrir_partido"
    DELETE_CHANNEL = "eliminacion_canal"


@dataclass(frozen=True, slots=True)
class ChannelActionResult:
    action: ChannelCloseMode
    summary: LocalizedText
