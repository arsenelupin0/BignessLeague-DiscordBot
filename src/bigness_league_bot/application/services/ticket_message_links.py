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

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class DmThreadRelayMessage:
    dm_message_id: int
    thread_message_id: int
    user_id: int

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "DmThreadRelayMessage | None":
        dm_message_id = coerce_int(payload.get("dm_message_id"))
        thread_message_id = coerce_int(payload.get("thread_message_id"))
        user_id = coerce_int(payload.get("user_id"))
        if dm_message_id is None or thread_message_id is None or user_id is None:
            return None

        return cls(
            dm_message_id=dm_message_id,
            thread_message_id=thread_message_id,
            user_id=user_id,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "dm_message_id": self.dm_message_id,
            "thread_message_id": self.thread_message_id,
            "user_id": self.user_id,
        }


@dataclass(frozen=True, slots=True)
class ParticipantDmRelayMessage:
    source_message_id: int
    participant_id: int
    dm_message_id: int

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ParticipantDmRelayMessage | None":
        source_message_id = coerce_int(payload.get("source_message_id"))
        participant_id = coerce_int(payload.get("participant_id"))
        dm_message_id = coerce_int(payload.get("dm_message_id"))
        if source_message_id is None or participant_id is None or dm_message_id is None:
            return None

        return cls(
            source_message_id=source_message_id,
            participant_id=participant_id,
            dm_message_id=dm_message_id,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_message_id": self.source_message_id,
            "participant_id": self.participant_id,
            "dm_message_id": self.dm_message_id,
        }


def coerce_int(value: object) -> int | None:
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


def parse_dm_thread_relay_messages(value: object) -> tuple[DmThreadRelayMessage, ...]:
    return _parse_relay_messages(value, DmThreadRelayMessage.from_dict)


def parse_participant_dm_relay_messages(
        value: object,
) -> tuple[ParticipantDmRelayMessage, ...]:
    return _parse_relay_messages(value, ParticipantDmRelayMessage.from_dict)


def upsert_dm_thread_relay_message(
        relays: tuple[DmThreadRelayMessage, ...],
        *,
        dm_message_id: int,
        thread_message_id: int,
        user_id: int,
) -> tuple[DmThreadRelayMessage, ...]:
    mappings = {
        relay.dm_message_id: relay
        for relay in relays
    }
    mappings[dm_message_id] = DmThreadRelayMessage(
        dm_message_id=dm_message_id,
        thread_message_id=thread_message_id,
        user_id=user_id,
    )
    return tuple(mappings.values())


def upsert_participant_dm_relay_message(
        relays: tuple[ParticipantDmRelayMessage, ...],
        *,
        source_message_id: int,
        participant_id: int,
        dm_message_id: int,
) -> tuple[ParticipantDmRelayMessage, ...]:
    mappings = {
        (relay.source_message_id, relay.participant_id): relay
        for relay in relays
    }
    mappings[(source_message_id, participant_id)] = ParticipantDmRelayMessage(
        source_message_id=source_message_id,
        participant_id=participant_id,
        dm_message_id=dm_message_id,
    )
    return tuple(mappings.values())


def thread_relay_message_id_for_dm(
        relays: tuple[DmThreadRelayMessage, ...],
        dm_message_id: int,
) -> int | None:
    for relay in relays:
        if relay.dm_message_id == dm_message_id:
            return relay.thread_message_id
    return None


def dm_message_id_for_thread_relay(
        relays: tuple[DmThreadRelayMessage, ...],
        thread_message_id: int,
) -> int | None:
    for relay in relays:
        if relay.thread_message_id == thread_message_id:
            return relay.dm_message_id
    return None


def thread_relay_author_id(
        relays: tuple[DmThreadRelayMessage, ...],
        thread_message_id: int,
) -> int | None:
    for relay in relays:
        if relay.thread_message_id == thread_message_id:
            return relay.user_id
    return None


def participant_dm_relay_message_id(
        relays: tuple[ParticipantDmRelayMessage, ...],
        *,
        source_message_id: int,
        participant_id: int,
) -> int | None:
    for relay in relays:
        if (
                relay.source_message_id == source_message_id
                and relay.participant_id == participant_id
        ):
            return relay.dm_message_id
    return None


def participant_dm_relay_source_message_id(
        relays: tuple[ParticipantDmRelayMessage, ...],
        *,
        participant_id: int,
        dm_message_id: int,
) -> int | None:
    for relay in relays:
        if relay.participant_id == participant_id and relay.dm_message_id == dm_message_id:
            return relay.source_message_id
    return None


def thread_reply_target_for_dm_reference(
        *,
        dm_thread_relays: tuple[DmThreadRelayMessage, ...],
        participant_dm_relays: tuple[ParticipantDmRelayMessage, ...],
        participant_id: int,
        referenced_dm_message_id: int,
) -> int | None:
    source_message_id = participant_dm_relay_source_message_id(
        participant_dm_relays,
        participant_id=participant_id,
        dm_message_id=referenced_dm_message_id,
    )
    if source_message_id is None:
        return thread_relay_message_id_for_dm(
            dm_thread_relays,
            referenced_dm_message_id,
        )

    return (
            thread_relay_message_id_for_dm(dm_thread_relays, source_message_id)
            or source_message_id
    )


def participant_reply_target_for_thread_reference(
        *,
        dm_thread_relays: tuple[DmThreadRelayMessage, ...],
        participant_dm_relays: tuple[ParticipantDmRelayMessage, ...],
        participant_id: int,
        referenced_thread_message_id: int,
) -> int | None:
    source_dm_message_id = dm_message_id_for_thread_relay(
        dm_thread_relays,
        referenced_thread_message_id,
    )
    if source_dm_message_id is None:
        return participant_dm_relay_message_id(
            participant_dm_relays,
            source_message_id=referenced_thread_message_id,
            participant_id=participant_id,
        )

    if thread_relay_author_id(dm_thread_relays, referenced_thread_message_id) == participant_id:
        return source_dm_message_id

    return participant_dm_relay_message_id(
        participant_dm_relays,
        source_message_id=source_dm_message_id,
        participant_id=participant_id,
    )


def participant_reply_target_for_dm_reference(
        *,
        dm_thread_relays: tuple[DmThreadRelayMessage, ...],
        participant_dm_relays: tuple[ParticipantDmRelayMessage, ...],
        participant_id: int,
        source_participant_id: int,
        referenced_dm_message_id: int,
) -> int | None:
    source_message_id = participant_dm_relay_source_message_id(
        participant_dm_relays,
        participant_id=source_participant_id,
        dm_message_id=referenced_dm_message_id,
    )
    if source_message_id is None:
        if thread_relay_message_id_for_dm(dm_thread_relays, referenced_dm_message_id) is None:
            return None
        source_message_id = referenced_dm_message_id

    if participant_id == source_participant_id:
        return referenced_dm_message_id

    return participant_dm_relay_message_id(
        participant_dm_relays,
        source_message_id=source_message_id,
        participant_id=participant_id,
    )


def _parse_relay_messages(
        value: object,
        parser: Callable[[dict[str, object]], T | None],
) -> tuple[T, ...]:
    if not isinstance(value, list):
        return ()

    parsed_messages: list[T] = []
    for raw_entry in value:
        if not isinstance(raw_entry, dict):
            continue
        parsed_entry = parser(raw_entry)
        if parsed_entry is None:
            continue
        parsed_messages.append(parsed_entry)

    return tuple(parsed_messages)
