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
from datetime import date, datetime, time
from enum import StrEnum

from bigness_league_bot.application.services.channel_closure import (
    format_match_channel_name,
    legacy_match_channel_names,
)
from bigness_league_bot.core.timezones import resolve_timezone

MATCH_NUMBER_MIN = 1
MATCH_NUMBER_MAX = 99
MATCH_COURTESY_MINUTES_MIN = 0
MATCH_COURTESY_MINUTES_MAX = 120
MATCH_BEST_OF_MIN = 1
MATCH_BEST_OF_MAX = 15
MATCH_DATE_FORMATS: tuple[str, ...] = ("%d/%m/%Y", "%Y-%m-%d")
MATCH_TIME_FORMAT = "%H:%M"


class MatchChannelDivision(StrEnum):
    GOLD = "gold_division"
    SILVER = "silver_division"


def parse_match_date(value: str) -> date:
    normalized_value = value.strip()
    for date_format in MATCH_DATE_FORMATS:
        try:
            return datetime.strptime(normalized_value, date_format).date()
        except ValueError:
            continue

    raise ValueError("invalid_date")


def parse_match_time(value: str) -> time:
    normalized_value = value.strip()
    try:
        return datetime.strptime(normalized_value, MATCH_TIME_FORMAT).time()
    except ValueError as exc:
        raise ValueError("invalid_time") from exc


def build_match_start_at(
        *,
        date_value: str,
        time_value: str,
        timezone_name: str,
) -> datetime:
    match_date = parse_match_date(date_value)
    match_time = parse_match_time(time_value)
    return datetime.combine(
        match_date,
        match_time,
        tzinfo=resolve_timezone(timezone_name),
    )


@dataclass(frozen=True, slots=True)
class MatchChannelSpecification:
    jornada: int
    partido: int
    courtesy_minutes: int
    start_at: datetime
    best_of: int

    @property
    def base_channel_name(self) -> str:
        return legacy_match_channel_names(self.jornada, self.partido)[0]

    @property
    def legacy_channel_names(self) -> tuple[str, str]:
        return legacy_match_channel_names(self.jornada, self.partido)

    @property
    def channel_name(self) -> str:
        return format_match_channel_name(self.jornada, self.partido)

    @property
    def start_timestamp(self) -> int:
        return int(self.start_at.timestamp())

    @property
    def room_name(self) -> str:
        return f"bjornada{self.jornada}"

    @property
    def room_password(self) -> str:
        return f"bpartido{self.partido}"
