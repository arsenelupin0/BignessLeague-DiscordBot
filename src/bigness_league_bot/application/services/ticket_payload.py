from __future__ import annotations

from dataclasses import dataclass


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
            user_id=required_int(payload, "user_id"),
            dm_channel_id=optional_int(payload, "dm_channel_id"),
            dm_start_message_id=optional_int(payload, "dm_start_message_id"),
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


def normalize_ticket_participants(
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


def required_int(payload: dict[str, object], key: str) -> int:
    value = coerce_int(payload.get(key))
    if value is None:
        raise ValueError(f"El campo `{key}` debe ser un entero.")

    return value


def optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None

    parsed_value = coerce_int(value)
    if parsed_value is None:
        raise ValueError(f"El campo `{key}` debe ser un entero.")

    return parsed_value


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


def required_text(payload: dict[str, object], key: str) -> str:
    value = optional_text(payload, key)
    if value is None:
        raise ValueError(f"El campo `{key}` debe ser texto.")

    return value


def optional_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)

    raise ValueError(f"El campo `{key}` debe ser texto.")
