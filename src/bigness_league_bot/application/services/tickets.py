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

from dataclasses import dataclass, replace
from datetime import datetime, timezone

import unicodedata

from bigness_league_bot.application.services.ticket_message_links import (
    DmThreadRelayMessage,
    ParticipantDmRelayMessage,
    dm_message_id_for_thread_relay,
    participant_dm_relay_message_id,
    participant_dm_relay_source_message_id,
    participant_reply_target_for_dm_reference,
    participant_reply_target_for_thread_reference,
    parse_dm_thread_relay_messages,
    parse_participant_dm_relay_messages,
    thread_relay_author_id,
    thread_relay_message_id_for_dm,
    thread_reply_target_for_dm_reference,
    upsert_dm_thread_relay_message,
    upsert_participant_dm_relay_message,
)


@dataclass(frozen=True, slots=True)
class TicketCategory:
    key: str
    label: str
    tag_name: str
    emoji: str
    thread_prefix: str


@dataclass(frozen=True, slots=True)
class TicketParticipant:
    user_id: int
    dm_channel_id: int | None = None
    dm_start_message_id: int | None = None

    @classmethod
    def from_dict(
            cls,
            payload: dict[str, object],
    ) -> "TicketParticipant":
        return cls(
            user_id=_required_int(payload, "user_id"),
            dm_channel_id=_optional_int(payload, "dm_channel_id"),
            dm_start_message_id=_optional_int(payload, "dm_start_message_id"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "dm_channel_id": self.dm_channel_id,
            "dm_start_message_id": self.dm_start_message_id,
        }

    def with_dm(
            self,
            *,
            dm_channel_id: int | None,
            dm_start_message_id: int | None,
    ) -> "TicketParticipant":
        return TicketParticipant(
            user_id=self.user_id,
            dm_channel_id=dm_channel_id,
            dm_start_message_id=dm_start_message_id,
        )


@dataclass(frozen=True, slots=True)
class TicketRecord:
    ticket_number: int
    user_id: int
    thread_id: int
    forum_channel_id: int
    thread_start_message_id: int | None
    dm_channel_id: int | None
    dm_start_message_id: int | None
    participants: tuple[TicketParticipant, ...]
    category_key: str
    created_at: str
    status: str = "active"
    closed_at: str | None = None
    thread_relay_message_authors: tuple[tuple[int, int], ...] = ()
    dm_thread_relay_messages: tuple[DmThreadRelayMessage, ...] = ()
    participant_dm_relay_messages: tuple[ParticipantDmRelayMessage, ...] = ()

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
            participants: tuple[TicketParticipant, ...] | None = None,
            category_key: str,
            created_at: str | None = None,
    ) -> "TicketRecord":
        normalized_participants = _normalize_ticket_participants(
            participants=participants,
            owner_user_id=user_id,
            owner_dm_channel_id=dm_channel_id,
            owner_dm_start_message_id=dm_start_message_id,
        )
        return cls(
            ticket_number=ticket_number,
            user_id=user_id,
            thread_id=thread_id,
            forum_channel_id=forum_channel_id,
            thread_start_message_id=thread_start_message_id,
            dm_channel_id=dm_channel_id,
            dm_start_message_id=dm_start_message_id,
            participants=normalized_participants,
            category_key=category_key,
            created_at=created_at or current_utc_timestamp(),
            thread_relay_message_authors=(),
        )

    @classmethod
    def from_dict(
            cls,
            payload: dict[str, object],
            *,
            fallback_ticket_number: int = 0,
    ) -> "TicketRecord":
        raw_participants = payload.get("participants")
        participants: tuple[TicketParticipant, ...] | None = None
        if isinstance(raw_participants, list):
            parsed_participants: list[TicketParticipant] = []
            for raw_participant in raw_participants:
                if not isinstance(raw_participant, dict):
                    continue
                parsed_participants.append(TicketParticipant.from_dict(raw_participant))
            participants = tuple(parsed_participants)

        dm_channel_id = _optional_int(payload, "dm_channel_id")
        dm_start_message_id = _optional_int(payload, "dm_start_message_id")
        raw_thread_relay_message_authors = payload.get("thread_relay_message_authors")
        thread_relay_message_authors: tuple[tuple[int, int], ...] = ()
        if isinstance(raw_thread_relay_message_authors, dict):
            parsed_mappings: list[tuple[int, int]] = []
            for raw_message_id, raw_user_id in raw_thread_relay_message_authors.items():
                message_id = _coerce_int(raw_message_id)
                user_id = _coerce_int(raw_user_id)
                if message_id is None or user_id is None:
                    continue
                parsed_mappings.append((message_id, user_id))
            thread_relay_message_authors = tuple(parsed_mappings)
        dm_thread_relay_messages = parse_dm_thread_relay_messages(
            payload.get("dm_thread_relay_messages")
        )
        participant_dm_relay_messages = parse_participant_dm_relay_messages(
            payload.get("participant_dm_relay_messages")
        )
        user_id = _required_int(payload, "user_id")
        return cls(
            ticket_number=_optional_int(payload, "ticket_number") or fallback_ticket_number,
            user_id=user_id,
            thread_id=_required_int(payload, "thread_id"),
            forum_channel_id=_required_int(payload, "forum_channel_id"),
            thread_start_message_id=_optional_int(payload, "thread_start_message_id"),
            dm_channel_id=dm_channel_id,
            dm_start_message_id=dm_start_message_id,
            participants=_normalize_ticket_participants(
                participants=participants,
                owner_user_id=user_id,
                owner_dm_channel_id=dm_channel_id,
                owner_dm_start_message_id=dm_start_message_id,
            ),
            category_key=_required_text(payload, "category_key"),
            created_at=_required_text(payload, "created_at"),
            status=_optional_text(payload, "status") or "active",
            closed_at=_optional_text(payload, "closed_at"),
            thread_relay_message_authors=thread_relay_message_authors,
            dm_thread_relay_messages=dm_thread_relay_messages,
            participant_dm_relay_messages=participant_dm_relay_messages,
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
            "participants": [
                participant.to_dict()
                for participant in self.participants
            ],
            "thread_relay_message_authors": {
                str(message_id): user_id
                for message_id, user_id in self.thread_relay_message_authors
            },
            "dm_thread_relay_messages": [
                relay.to_dict()
                for relay in self.dm_thread_relay_messages
            ],
            "participant_dm_relay_messages": [
                relay.to_dict()
                for relay in self.participant_dm_relay_messages
            ],
            "category_key": self.category_key,
            "created_at": self.created_at,
            "status": self.status,
            "closed_at": self.closed_at,
        }

    def close(self) -> "TicketRecord":
        return replace(
            self,
            status="closed",
            closed_at=current_utc_timestamp(),
        )

    def includes_user(self, user_id: int) -> bool:
        return any(participant.user_id == user_id for participant in self.participants)

    def participant_for_user(self, user_id: int) -> TicketParticipant | None:
        for participant in self.participants:
            if participant.user_id == user_id:
                return participant
        return None

    @property
    def participant_ids(self) -> tuple[int, ...]:
        return tuple(participant.user_id for participant in self.participants)

    def with_participant_dm(
            self,
            *,
            user_id: int,
            dm_channel_id: int | None,
            dm_start_message_id: int | None,
    ) -> "TicketRecord":
        updated_participants = tuple(
            (
                participant.with_dm(
                    dm_channel_id=dm_channel_id,
                    dm_start_message_id=dm_start_message_id,
                )
                if participant.user_id == user_id
                else participant
            )
            for participant in self.participants
        )
        owner_participant = next(
            (
                participant
                for participant in updated_participants
                if participant.user_id == self.user_id
            ),
            None,
        )
        return replace(
            self,
            dm_channel_id=(
                owner_participant.dm_channel_id
                if owner_participant is not None
                else self.dm_channel_id
            ),
            dm_start_message_id=(
                owner_participant.dm_start_message_id
                if owner_participant is not None
                else self.dm_start_message_id
            ),
            participants=updated_participants,
        )

    def with_added_participants(
            self,
            user_ids: tuple[int, ...],
    ) -> "TicketRecord":
        existing_user_ids = set(self.participant_ids)
        updated_participants = list(self.participants)
        for user_id in user_ids:
            if user_id in existing_user_ids:
                continue
            updated_participants.append(TicketParticipant(user_id=user_id))
            existing_user_ids.add(user_id)

        return replace(
            self,
            participants=tuple(updated_participants),
        )

    def relay_message_author_id(self, thread_message_id: int) -> int | None:
        for message_id, user_id in self.thread_relay_message_authors:
            if message_id == thread_message_id:
                return user_id
        return None

    def with_thread_relay_message_author(
            self,
            *,
            thread_message_id: int,
            user_id: int,
    ) -> "TicketRecord":
        mappings = {
            existing_message_id: existing_user_id
            for existing_message_id, existing_user_id in self.thread_relay_message_authors
        }
        mappings[thread_message_id] = user_id
        return replace(
            self,
            thread_relay_message_authors=tuple(mappings.items()),
        )

    def thread_relay_message_id_for_dm(
            self,
            dm_message_id: int,
    ) -> int | None:
        return thread_relay_message_id_for_dm(self.dm_thread_relay_messages, dm_message_id)

    def dm_message_id_for_thread_relay(
            self,
            thread_message_id: int,
    ) -> int | None:
        return dm_message_id_for_thread_relay(self.dm_thread_relay_messages, thread_message_id)

    def thread_relay_author_id(
            self,
            thread_message_id: int,
    ) -> int | None:
        return thread_relay_author_id(self.dm_thread_relay_messages, thread_message_id)

    def thread_reply_target_for_dm_reference(
            self,
            *,
            participant_id: int,
            referenced_dm_message_id: int,
    ) -> int | None:
        return thread_reply_target_for_dm_reference(
            dm_thread_relays=self.dm_thread_relay_messages,
            participant_dm_relays=self.participant_dm_relay_messages,
            participant_id=participant_id,
            referenced_dm_message_id=referenced_dm_message_id,
        )

    def with_dm_thread_relay_message(
            self,
            *,
            dm_message_id: int,
            thread_message_id: int,
            user_id: int,
    ) -> "TicketRecord":
        return replace(
            self,
            dm_thread_relay_messages=upsert_dm_thread_relay_message(
                self.dm_thread_relay_messages,
                dm_message_id=dm_message_id,
                thread_message_id=thread_message_id,
                user_id=user_id,
            ),
        )

    def participant_dm_relay_targets(
            self,
            source_message_id: int,
    ) -> tuple[tuple[int, int], ...]:
        return tuple(
            (relay.participant_id, relay.dm_message_id)
            for relay in self.participant_dm_relay_messages
            if relay.source_message_id == source_message_id
        )

    def participant_dm_relay_message_id(
            self,
            *,
            source_message_id: int,
            participant_id: int,
    ) -> int | None:
        return participant_dm_relay_message_id(
            self.participant_dm_relay_messages,
            source_message_id=source_message_id,
            participant_id=participant_id,
        )

    def participant_dm_relay_source_message_id(
            self,
            *,
            participant_id: int,
            dm_message_id: int,
    ) -> int | None:
        return participant_dm_relay_source_message_id(
            self.participant_dm_relay_messages,
            participant_id=participant_id,
            dm_message_id=dm_message_id,
        )

    def participant_reply_target_for_thread_reference(
            self,
            *,
            participant_id: int,
            referenced_thread_message_id: int,
    ) -> int | None:
        return participant_reply_target_for_thread_reference(
            dm_thread_relays=self.dm_thread_relay_messages,
            participant_dm_relays=self.participant_dm_relay_messages,
            participant_id=participant_id,
            referenced_thread_message_id=referenced_thread_message_id,
        )

    def participant_reply_target_for_dm_reference(
            self,
            *,
            participant_id: int,
            source_participant_id: int,
            referenced_dm_message_id: int,
    ) -> int | None:
        return participant_reply_target_for_dm_reference(
            dm_thread_relays=self.dm_thread_relay_messages,
            participant_dm_relays=self.participant_dm_relay_messages,
            participant_id=participant_id,
            source_participant_id=source_participant_id,
            referenced_dm_message_id=referenced_dm_message_id,
        )

    def with_participant_dm_relay_message(
            self,
            *,
            source_message_id: int,
            participant_id: int,
            dm_message_id: int,
    ) -> "TicketRecord":
        return replace(
            self,
            participant_dm_relay_messages=upsert_participant_dm_relay_message(
                self.participant_dm_relay_messages,
                source_message_id=source_message_id,
                participant_id=participant_id,
                dm_message_id=dm_message_id,
            ),
        )


def _normalize_ticket_participants(
        *,
        participants: tuple[TicketParticipant, ...] | None,
        owner_user_id: int,
        owner_dm_channel_id: int | None,
        owner_dm_start_message_id: int | None,
) -> tuple[TicketParticipant, ...]:
    participants_by_user_id: dict[int, TicketParticipant] = {}
    if participants is not None:
        for participant in participants:
            participants_by_user_id[participant.user_id] = participant

    owner_participant = participants_by_user_id.get(owner_user_id)
    if owner_participant is None:
        participants_by_user_id[owner_user_id] = TicketParticipant(
            user_id=owner_user_id,
            dm_channel_id=owner_dm_channel_id,
            dm_start_message_id=owner_dm_start_message_id,
        )
    else:
        participants_by_user_id[owner_user_id] = owner_participant.with_dm(
            dm_channel_id=owner_dm_channel_id or owner_participant.dm_channel_id,
            dm_start_message_id=(
                    owner_dm_start_message_id or owner_participant.dm_start_message_id
            ),
        )

    ordered_participants = [participants_by_user_id.pop(owner_user_id)]
    ordered_participants.extend(participants_by_user_id.values())
    return tuple(ordered_participants)


def _required_int(payload: dict[str, object], key: str) -> int:
    value = _coerce_int(payload.get(key))
    if value is None:
        raise ValueError(f"El campo `{key}` debe ser un entero.")

    return value


def _optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None

    parsed_value = _coerce_int(value)
    if parsed_value is None:
        raise ValueError(f"El campo `{key}` debe ser un entero.")

    return parsed_value


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None

    return None


def _required_text(payload: dict[str, object], key: str) -> str:
    value = _optional_text(payload, key)
    if value is None:
        raise ValueError(f"El campo `{key}` debe ser texto.")

    return value


def _optional_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)

    raise ValueError(f"El campo `{key}` debe ser texto.")


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
    return TICKET_CATEGORIES_BY_KEY.get(normalize_ticket_category_key(category_key))


def require_ticket_category(category_key: str) -> TicketCategory:
    category = get_ticket_category(category_key)
    if category is None:
        raise ValueError(f"Categoría de ticket no soportada: {category_key}")

    return category


def normalize_ticket_category_key(category_key: str) -> str:
    normalized_key = _normalize_ticket_category_lookup_key(category_key)
    return TICKET_CATEGORY_KEYS_BY_ALIAS.get(normalized_key, normalized_key)


def _normalize_ticket_category_lookup_key(value: str) -> str:
    normalized_value = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character
        for character in normalized_value
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.replace("_", " ").split())


TICKET_CATEGORY_KEYS_BY_ALIAS: dict[str, str] = {}
for _category in TICKET_CATEGORIES:
    for _alias in (
            _category.key,
            _category.label,
            _category.tag_name,
            _category.thread_prefix,
    ):
        TICKET_CATEGORY_KEYS_BY_ALIAS[_normalize_ticket_category_lookup_key(_alias)] = _category.key
