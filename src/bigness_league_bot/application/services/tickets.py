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

from bigness_league_bot.application.services.ticket_categories import (
    TICKET_CATEGORIES,
    TicketCategory,
    get_ticket_category,
    normalize_ticket_category_key,
    require_ticket_category,
)
from bigness_league_bot.application.services.ticket_formatting import (
    build_dm_message_link,
    build_guild_message_link,
    current_utc_timestamp,
    format_ticket_created_at,
    format_ticket_duration,
    format_ticket_number,
    parse_utc_timestamp,
)
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
from bigness_league_bot.application.services.ticket_payload import (
    TicketParticipant,
    coerce_int,
    normalize_ticket_participants,
    optional_int,
    optional_text,
    required_int,
    required_text,
)

__all__ = [
    "TICKET_CATEGORIES",
    "TicketCategory",
    "TicketParticipant",
    "TicketRecord",
    "build_dm_message_link",
    "build_guild_message_link",
    "current_utc_timestamp",
    "format_ticket_created_at",
    "format_ticket_duration",
    "format_ticket_number",
    "get_ticket_category",
    "normalize_ticket_category_key",
    "parse_utc_timestamp",
    "require_ticket_category",
]


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
    last_activity_at: str | None = None
    inactivity_notice_count: int = 0
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
        resolved_created_at = created_at or current_utc_timestamp()
        normalized_participants = normalize_ticket_participants(
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
            created_at=resolved_created_at,
            last_activity_at=resolved_created_at,
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

        dm_channel_id = optional_int(payload, "dm_channel_id")
        dm_start_message_id = optional_int(payload, "dm_start_message_id")
        raw_thread_relay_message_authors = payload.get("thread_relay_message_authors")
        thread_relay_message_authors: tuple[tuple[int, int], ...] = ()
        if isinstance(raw_thread_relay_message_authors, dict):
            parsed_mappings: list[tuple[int, int]] = []
            for raw_message_id, raw_user_id in raw_thread_relay_message_authors.items():
                message_id = coerce_int(raw_message_id)
                user_id = coerce_int(raw_user_id)
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
        user_id = required_int(payload, "user_id")
        return cls(
            ticket_number=optional_int(payload, "ticket_number") or fallback_ticket_number,
            user_id=user_id,
            thread_id=required_int(payload, "thread_id"),
            forum_channel_id=required_int(payload, "forum_channel_id"),
            thread_start_message_id=optional_int(payload, "thread_start_message_id"),
            dm_channel_id=dm_channel_id,
            dm_start_message_id=dm_start_message_id,
            participants=normalize_ticket_participants(
                participants=participants,
                owner_user_id=user_id,
                owner_dm_channel_id=dm_channel_id,
                owner_dm_start_message_id=dm_start_message_id,
            ),
            category_key=required_text(payload, "category_key"),
            created_at=required_text(payload, "created_at"),
            status=optional_text(payload, "status") or "active",
            closed_at=optional_text(payload, "closed_at"),
            last_activity_at=optional_text(payload, "last_activity_at"),
            inactivity_notice_count=max(
                0,
                optional_int(payload, "inactivity_notice_count") or 0,
            ),
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
            "last_activity_at": self.last_activity_at,
            "inactivity_notice_count": self.inactivity_notice_count,
        }

    def close(self) -> "TicketRecord":
        return replace(
            self,
            status="closed",
            closed_at=current_utc_timestamp(),
        )

    def mark_activity(self, *, occurred_at: str | None = None) -> "TicketRecord":
        return replace(
            self,
            last_activity_at=occurred_at or current_utc_timestamp(),
            inactivity_notice_count=0,
        )

    def mark_inactivity_notice(self, *, sent_at: str | None = None) -> "TicketRecord":
        return replace(
            self,
            last_activity_at=sent_at or current_utc_timestamp(),
            inactivity_notice_count=self.inactivity_notice_count + 1,
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
