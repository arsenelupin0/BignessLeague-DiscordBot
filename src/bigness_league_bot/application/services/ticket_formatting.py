from __future__ import annotations

from datetime import datetime, timezone


def current_utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_utc_timestamp(value: str) -> datetime:
    parsed_value = datetime.fromisoformat(value)
    if parsed_value.tzinfo is None:
        return parsed_value.replace(tzinfo=timezone.utc)

    return parsed_value.astimezone(timezone.utc)


def format_ticket_number(ticket_number: int) -> str:
    return f"#{ticket_number}"


def format_ticket_created_at(value: str) -> str:
    created_at = parse_utc_timestamp(value)
    return f"<t:{int(created_at.timestamp())}:F>"


def build_guild_message_link(
        *,
        guild_id: int,
        channel_id: int,
        message_id: int | None,
) -> str | None:
    if message_id is None:
        return None

    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def build_dm_message_link(
        *,
        channel_id: int | None,
        message_id: int | None,
) -> str | None:
    if channel_id is None or message_id is None:
        return None

    return f"https://discord.com/channels/@me/{channel_id}/{message_id}"


def format_ticket_duration(
        *,
        created_at: str,
        closed_at: str,
) -> str:
    delta_seconds = max(
        0,
        int((parse_utc_timestamp(closed_at) - parse_utc_timestamp(created_at)).total_seconds()),
    )
    days, remainder = divmod(delta_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(_pluralize_span(days, "dia", "dias"))
    if hours:
        parts.append(_pluralize_span(hours, "hora", "horas"))
    if minutes:
        parts.append(_pluralize_span(minutes, "minuto", "minutos"))
    if not parts:
        parts.append(_pluralize_span(seconds, "segundo", "segundos"))

    if len(parts) == 1:
        return parts[0]

    if len(parts) == 2:
        return f"{parts[0]} y {parts[1]}"

    return f"{' '.join(parts[:-1])} y {parts[-1]}"


def _pluralize_span(value: int, singular: str, plural: str) -> str:
    return f"{value} {singular if value == 1 else plural}"
