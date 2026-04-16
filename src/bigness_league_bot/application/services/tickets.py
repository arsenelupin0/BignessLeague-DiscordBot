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
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class TicketCategory:
    key: str
    label: str
    tag_name: str
    emoji: str
    thread_prefix: str


@dataclass(frozen=True, slots=True)
class TicketRecord:
    ticket_number: int
    user_id: int
    thread_id: int
    forum_channel_id: int
    thread_start_message_id: int | None
    dm_channel_id: int | None
    dm_start_message_id: int | None
    category_key: str
    created_at: str
    status: str = "active"
    closed_at: str | None = None

    @classmethod
    def create(
            cls,
            *,
            ticket_number: int,
            user_id: int,
            thread_id: int,
            forum_channel_id: int,
            thread_start_message_id: int | None = None,
            dm_channel_id: int | None = None,
            dm_start_message_id: int | None = None,
            category_key: str,
            created_at: str | None = None,
    ) -> "TicketRecord":
        return cls(
            ticket_number=ticket_number,
            user_id=user_id,
            thread_id=thread_id,
            forum_channel_id=forum_channel_id,
            thread_start_message_id=thread_start_message_id,
            dm_channel_id=dm_channel_id,
            dm_start_message_id=dm_start_message_id,
            category_key=category_key,
            created_at=created_at or current_utc_timestamp(),
        )

    @classmethod
    def from_dict(
            cls,
            payload: dict[str, object],
            *,
            fallback_ticket_number: int = 0,
    ) -> "TicketRecord":
        return cls(
            ticket_number=int(payload.get("ticket_number", fallback_ticket_number)),
            user_id=int(payload["user_id"]),
            thread_id=int(payload["thread_id"]),
            forum_channel_id=int(payload["forum_channel_id"]),
            thread_start_message_id=(
                int(payload["thread_start_message_id"])
                if payload.get("thread_start_message_id") is not None
                else None
            ),
            dm_channel_id=(
                int(payload["dm_channel_id"])
                if payload.get("dm_channel_id") is not None
                else None
            ),
            dm_start_message_id=(
                int(payload["dm_start_message_id"])
                if payload.get("dm_start_message_id") is not None
                else None
            ),
            category_key=str(payload["category_key"]),
            created_at=str(payload["created_at"]),
            status=str(payload.get("status", "active")),
            closed_at=(
                str(payload["closed_at"])
                if payload.get("closed_at") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ticket_number": self.ticket_number,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "forum_channel_id": self.forum_channel_id,
            "thread_start_message_id": self.thread_start_message_id,
            "dm_channel_id": self.dm_channel_id,
            "dm_start_message_id": self.dm_start_message_id,
            "category_key": self.category_key,
            "created_at": self.created_at,
            "status": self.status,
            "closed_at": self.closed_at,
        }

    def close(self) -> "TicketRecord":
        return TicketRecord(
            ticket_number=self.ticket_number,
            user_id=self.user_id,
            thread_id=self.thread_id,
            forum_channel_id=self.forum_channel_id,
            thread_start_message_id=self.thread_start_message_id,
            dm_channel_id=self.dm_channel_id,
            dm_start_message_id=self.dm_start_message_id,
            category_key=self.category_key,
            created_at=self.created_at,
            status="closed",
            closed_at=current_utc_timestamp(),
        )


TICKET_CATEGORIES: tuple[TicketCategory, ...] = (
    TicketCategory(
        key="general",
        label="Soporte general",
        tag_name="Soporte general",
        emoji="\U0001f6e0\ufe0f",
        thread_prefix="soporte-general",
    ),
    TicketCategory(
        key="competition",
        label="Competici\u00f3n Bigness League",
        tag_name="Competicion",
        emoji="\U0001f4dd",
        thread_prefix="competicion",
    ),
    TicketCategory(
        key="player_market",
        label="Mercado de jugadores",
        tag_name="Mercado",
        emoji="\U0001f680",
        thread_prefix="mercado",
    ),
    TicketCategory(
        key="stream",
        label="\u00bfQuieres hacer stream de tu partido?",
        tag_name="Streaming",
        emoji="\U0001f310",
        thread_prefix="stream",
    ),
    TicketCategory(
        key="appeals",
        label="Apelaciones, problemas con alg\u00fan equipo, jugador, etc",
        tag_name="Apelaciones",
        emoji="\U0001f4dc",
        thread_prefix="apelaciones",
    ),
    TicketCategory(
        key="bot",
        label="Bot de discord",
        tag_name="Bot",
        emoji="\U0001f916",
        thread_prefix="bot",
    ),
    TicketCategory(
        key="social",
        label="Social",
        tag_name="Social",
        emoji="\U0001f4f1",
        thread_prefix="social",
    ),
)
TICKET_CATEGORIES_BY_KEY: dict[str, TicketCategory] = {
    category.key: category
    for category in TICKET_CATEGORIES
}


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


def get_ticket_category(category_key: str) -> TicketCategory | None:
    return TICKET_CATEGORIES_BY_KEY.get(category_key)


def require_ticket_category(category_key: str) -> TicketCategory:
    category = get_ticket_category(category_key)
    if category is None:
        raise ValueError(f"Categoria de ticket no soportada: {category_key}")

    return category
