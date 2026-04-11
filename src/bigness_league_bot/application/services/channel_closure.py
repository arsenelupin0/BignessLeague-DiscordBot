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

PROTECTED_ROLE_NAMES: tuple[str, ...] = ("Staff", "Administrador", "Ceo")
MATCH_CHANNEL_NAME_PATTERN = re.compile(r"^j[1-9][0-9]?-partido-[1-9][0-9]?$")


def is_match_channel_name(channel_name: str) -> bool:
    return MATCH_CHANNEL_NAME_PATTERN.fullmatch(channel_name) is not None


def protected_role_names_label() -> str:
    return ", ".join(PROTECTED_ROLE_NAMES)


class ChannelCloseMode(StrEnum):
    MATCH_PLAYED = "partido_jugado"
    MATCHDAY_CLOSED = "jornada_cerrada"
    REOPEN_MATCH = "reabrir_partido"
    DELETE_CHANNEL = "eliminacion_canal"

    @property
    def label(self) -> str:
        if self is ChannelCloseMode.MATCH_PLAYED:
            return "Partido jugado"
        if self is ChannelCloseMode.MATCHDAY_CLOSED:
            return "Jornada cerrada"
        if self is ChannelCloseMode.REOPEN_MATCH:
            return "Reabrir partido"
        return "Eliminacion de canal"


@dataclass(frozen=True, slots=True)
class ChannelActionResult:
    action: ChannelCloseMode
    summary: str
