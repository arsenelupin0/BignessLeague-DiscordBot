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
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC_OFFSET_PATTERN = re.compile(r"^(?P<sign>[+-])(?P<hours>\d{2}):(?P<minutes>\d{2})$")


def resolve_timezone(value: str) -> tzinfo:
    normalized_value = value.strip() or "local"
    if normalized_value.casefold() == "local":
        return datetime.now().astimezone().tzinfo or timezone.utc

    offset_match = UTC_OFFSET_PATTERN.fullmatch(normalized_value)
    if offset_match is not None:
        hours = int(offset_match.group("hours"))
        minutes = int(offset_match.group("minutes"))
        if hours > 23 or minutes > 59:
            raise ValueError("invalid_timezone")

        offset = timedelta(hours=hours, minutes=minutes)
        if offset_match.group("sign") == "-":
            offset = -offset
        return timezone(offset)

    try:
        return ZoneInfo(normalized_value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid_timezone") from exc
