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

from dataclasses import dataclass
from enum import StrEnum

from bigness_league_bot.application.services.channel_closure import (
    format_match_channel_name,
    legacy_match_channel_names,
)

MATCH_NUMBER_MIN = 1
MATCH_NUMBER_MAX = 99


class MatchChannelDivision(StrEnum):
    GOLD = "gold_division"
    SILVER = "silver_division"


@dataclass(frozen=True, slots=True)
class MatchChannelSpecification:
    jornada: int
    partido: int

    @property
    def base_channel_name(self) -> str:
        return legacy_match_channel_names(self.jornada, self.partido)[0]

    @property
    def legacy_channel_names(self) -> tuple[str, str]:
        return legacy_match_channel_names(self.jornada, self.partido)

    @property
    def channel_name(self) -> str:
        return format_match_channel_name(self.jornada, self.partido)
