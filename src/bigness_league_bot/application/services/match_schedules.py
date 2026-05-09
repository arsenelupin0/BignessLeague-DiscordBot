from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class MatchScheduleEntry:
    guild_id: int
    channel_id: int
    timestamp: int
    team_role_ids: tuple[int, ...]
    caster_role_ids: tuple[int, ...]
    schedule_message_id: int | None
    updated_at: str

    def with_message_id(self, message_id: int) -> "MatchScheduleEntry":
        return replace(self, schedule_message_id=message_id)
