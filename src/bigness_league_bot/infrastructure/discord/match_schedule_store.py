from __future__ import annotations

import json
import logging
from pathlib import Path

from bigness_league_bot.application.services.match_schedules import MatchScheduleEntry

LOGGER = logging.getLogger(__name__)
MATCH_SCHEDULE_STATE_VERSION = 1


class MatchScheduleStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[tuple[int, int], MatchScheduleEntry] = self._load()

    def upsert(self, entry: MatchScheduleEntry) -> None:
        self._entries[(entry.guild_id, entry.channel_id)] = entry
        self._save()

    def remove(self, *, guild_id: int, channel_id: int) -> None:
        if self._entries.pop((guild_id, channel_id), None) is not None:
            self._save()

    def active_for_guild(self, guild_id: int) -> tuple[MatchScheduleEntry, ...]:
        return tuple(
            sorted(
                (
                    entry
                    for entry in self._entries.values()
                    if entry.guild_id == guild_id
                ),
                key=lambda entry: (entry.timestamp, entry.channel_id),
            )
        )

    def _load(self) -> dict[tuple[int, int], MatchScheduleEntry]:
        if not self.path.exists():
            return {}

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("MATCH_SCHEDULE_STATE_INVALID path=%s", self.path)
            return {}

        raw_entries = payload.get("schedules", [])
        if not isinstance(raw_entries, list):
            LOGGER.warning(
                "MATCH_SCHEDULE_STATE_INVALID path=%s reason=schedules_not_list",
                self.path,
            )
            return {}

        entries: dict[tuple[int, int], MatchScheduleEntry] = {}
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue

            entry = _entry_from_dict(raw_entry)
            if entry is not None:
                entries[(entry.guild_id, entry.channel_id)] = entry

        return entries

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": MATCH_SCHEDULE_STATE_VERSION,
            "schedules": [
                _entry_to_dict(entry)
                for entry in sorted(
                    self._entries.values(),
                    key=lambda item: (item.guild_id, item.timestamp, item.channel_id),
                )
            ],
        }
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.path)


def _entry_from_dict(payload: dict[str, object]) -> MatchScheduleEntry | None:
    guild_id = _required_int(payload, "guild_id")
    channel_id = _required_int(payload, "channel_id")
    timestamp = _required_int(payload, "timestamp")
    updated_at = _required_str(payload, "updated_at")
    if (
            guild_id is None
            or channel_id is None
            or timestamp is None
            or updated_at is None
    ):
        return None

    schedule_message_id = _optional_int(payload, "schedule_message_id")
    return MatchScheduleEntry(
        guild_id=guild_id,
        channel_id=channel_id,
        timestamp=timestamp,
        team_role_ids=_int_tuple(payload.get("team_role_ids")),
        caster_role_ids=_int_tuple(payload.get("caster_role_ids")),
        schedule_message_id=schedule_message_id,
        updated_at=updated_at,
    )


def _entry_to_dict(entry: MatchScheduleEntry) -> dict[str, object]:
    return {
        "guild_id": entry.guild_id,
        "channel_id": entry.channel_id,
        "timestamp": entry.timestamp,
        "team_role_ids": list(entry.team_role_ids),
        "caster_role_ids": list(entry.caster_role_ids),
        "schedule_message_id": entry.schedule_message_id,
        "updated_at": entry.updated_at,
    }


def _required_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _required_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _int_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()

    return tuple(
        int(item)
        for item in value
        if isinstance(item, int | str) and str(item).isdigit()
    )
