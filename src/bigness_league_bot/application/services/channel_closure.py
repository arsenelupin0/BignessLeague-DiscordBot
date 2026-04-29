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
MATCH_CHANNEL_STATUS_SEPARATOR = "\u30fb"
MATCH_CHANNEL_STATUS_OPEN = "\u26bd"
MATCH_CHANNEL_STATUS_PLAYED = "\u2705"
MATCH_CHANNEL_STATUS_CLOSED = "\U0001f512"
MATCH_CHANNEL_STATUS_ICONS: tuple[str, ...] = (
    MATCH_CHANNEL_STATUS_OPEN,
    MATCH_CHANNEL_STATUS_PLAYED,
    MATCH_CHANNEL_STATUS_CLOSED,
)
MATCH_CHANNEL_NAME_SUFFIX = f"{MATCH_CHANNEL_STATUS_SEPARATOR}{MATCH_CHANNEL_STATUS_OPEN}"
MATCH_CHANNEL_LEGACY_NAME_PATTERN = re.compile(
    r"^j[1-9][0-9]?-partido-[1-9][0-9]?(?:・[⚽✅🔒])?$"
)
MATCH_CHANNEL_EMOJI_NAME_PATTERN = re.compile(
    r"^『𝗝』(?:[0-9]️⃣){1,2}"
    r"『𝗣』(?:[0-9]️⃣){1,2}"
    r"・[⚽✅🔒]$"
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


def with_match_channel_status(channel_name: str, status_icon: str) -> str:
    if status_icon not in MATCH_CHANNEL_STATUS_ICONS:
        raise ValueError(f"Estado de canal no soportado: {status_icon}")

    for current_icon in MATCH_CHANNEL_STATUS_ICONS:
        current_suffix = f"{MATCH_CHANNEL_STATUS_SEPARATOR}{current_icon}"
        if channel_name.endswith(current_suffix):
            return (
                f"{channel_name[:-len(current_suffix)]}"
                f"{MATCH_CHANNEL_STATUS_SEPARATOR}{status_icon}"
            )

    return f"{channel_name}{MATCH_CHANNEL_STATUS_SEPARATOR}{status_icon}"


def protected_role_names_label() -> str:
    return ", ".join(PROTECTED_ROLE_NAMES)


class ChannelCloseMode(StrEnum):
    MATCH_PLAYED = "partido_jugado"
    MATCHDAY_CLOSED = "jornada_cerrada"
    REOPEN_MATCH = "reabrir_partido"
    ARCHIVE_CHANNEL = "archivar_canal"


@dataclass(frozen=True, slots=True)
class ChannelActionResult:
    action: ChannelCloseMode
    summary: LocalizedText
