from __future__ import annotations

import json
import logging
from pathlib import Path

import discord

from bigness_league_bot.application.services.pending_team_signing_assignments import (
    PendingTeamSigningAssignment,
    build_pending_assignment_id,
    complete_pending_assignment,
    merge_pending_assignment,
)
from bigness_league_bot.infrastructure.discord.team_member_lookup import (
    build_member_lookup_keys,
    normalize_member_lookup_text,
)

LOGGER = logging.getLogger("bigness_league_bot.activity")
PENDING_ASSIGNMENT_STATE_VERSION = 1


class PendingTeamSigningAssignmentStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._assignments: dict[str, PendingTeamSigningAssignment] = self._load()

    def upsert(self, assignment: PendingTeamSigningAssignment) -> PendingTeamSigningAssignment:
        existing = self._assignments.get(assignment.assignment_id)
        stored = (
            assignment
            if existing is None
            else merge_pending_assignment(existing, assignment)
        )
        self._assignments[stored.assignment_id] = stored
        self._save()
        return stored

    def active_for_member(
            self,
            *,
            guild_id: int,
            member: discord.Member,
    ) -> tuple[PendingTeamSigningAssignment, ...]:
        lookup_keys = set(build_member_lookup_keys(member))
        return tuple(
            assignment
            for assignment in self._assignments.values()
            if (
                    not assignment.is_completed
                    and assignment.guild_id == guild_id
                    and assignment.normalized_member_name in lookup_keys
            )
        )

    def completed_for_member_or_name(
            self,
            *,
            guild_id: int,
            member: discord.Member,
            team_role_id: int,
            member_name: str,
    ) -> PendingTeamSigningAssignment | None:
        lookup_keys = {
            *build_member_lookup_keys(member),
            normalize_member_lookup_text(member_name),
        }
        for assignment in self._assignments.values():
            if (
                    assignment.is_completed
                    and assignment.guild_id == guild_id
                    and assignment.team_role_id == team_role_id
                    and (
                    assignment.completed_member_id == member.id
                    or assignment.normalized_member_name in lookup_keys
            )
            ):
                return assignment

        return None

    def mark_completed(
            self,
            assignment: PendingTeamSigningAssignment,
            *,
            member_id: int,
            completed_at: str,
            announcement_message_ids: tuple[int, ...],
    ) -> PendingTeamSigningAssignment:
        completed_assignment = complete_pending_assignment(
            assignment,
            completed_at=completed_at,
            completed_member_id=member_id,
            announcement_message_ids=announcement_message_ids,
        )
        self._assignments[assignment.assignment_id] = completed_assignment
        self._save()
        return completed_assignment

    def _load(self) -> dict[str, PendingTeamSigningAssignment]:
        if not self.path.exists():
            return {}

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("PENDING_TEAM_SIGNING_ASSIGNMENTS_INVALID path=%s", self.path)
            return {}

        raw_assignments = payload.get("assignments", [])
        if not isinstance(raw_assignments, list):
            LOGGER.warning(
                "PENDING_TEAM_SIGNING_ASSIGNMENTS_INVALID path=%s reason=assignments_not_list",
                self.path,
            )
            return {}

        assignments: dict[str, PendingTeamSigningAssignment] = {}
        for raw_assignment in raw_assignments:
            if not isinstance(raw_assignment, dict):
                continue
            assignment = _assignment_from_dict(raw_assignment)
            if assignment is None:
                continue
            assignments[assignment.assignment_id] = assignment

        return assignments

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": PENDING_ASSIGNMENT_STATE_VERSION,
            "assignments": [
                _assignment_to_dict(assignment)
                for assignment in sorted(
                    self._assignments.values(),
                    key=lambda item: (item.created_at, item.assignment_id),
                )
            ],
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def create_pending_team_signing_assignment(
        *,
        guild_id: int,
        member_name: str,
        team_role_id: int,
        team_role_name: str,
        division_name: str,
        team_image_url: str | None,
        is_player: bool,
        staff_role_keys: tuple[str, ...] = (),
        source: str,
        created_at: str,
) -> PendingTeamSigningAssignment | None:
    normalized_member_name = normalize_member_lookup_text(member_name)
    if not normalized_member_name:
        return None

    return PendingTeamSigningAssignment(
        assignment_id=build_pending_assignment_id(
            guild_id=guild_id,
            normalized_member_name=normalized_member_name,
            team_role_id=team_role_id,
        ),
        guild_id=guild_id,
        normalized_member_name=normalized_member_name,
        member_name=member_name,
        team_role_id=team_role_id,
        team_role_name=team_role_name,
        division_name=division_name,
        team_image_url=team_image_url,
        is_player=is_player,
        staff_role_keys=tuple(sorted(set(staff_role_keys))),
        source=source,
        created_at=created_at,
    )


def _assignment_from_dict(payload: dict[str, object]) -> PendingTeamSigningAssignment | None:
    assignment_id = _required_str(payload, "assignment_id")
    guild_id = _required_int(payload, "guild_id")
    normalized_member_name = _required_str(payload, "normalized_member_name")
    member_name = _required_str(payload, "member_name")
    team_role_id = _required_int(payload, "team_role_id")
    team_role_name = _required_str(payload, "team_role_name")
    division_name = _required_str(payload, "division_name")
    is_player = _required_bool(payload, "is_player")
    source = _required_str(payload, "source")
    created_at = _required_str(payload, "created_at")
    if (
            assignment_id is None
            or guild_id is None
            or normalized_member_name is None
            or member_name is None
            or team_role_id is None
            or team_role_name is None
            or division_name is None
            or is_player is None
            or source is None
            or created_at is None
    ):
        return None

    raw_team_image_url = payload.get("team_image_url")
    team_image_url = raw_team_image_url if isinstance(raw_team_image_url, str) else None
    raw_staff_role_keys = payload.get("staff_role_keys", [])
    staff_role_keys = (
        tuple(str(role_key) for role_key in raw_staff_role_keys)
        if isinstance(raw_staff_role_keys, list)
        else ()
    )
    raw_completed_at = payload.get("completed_at")
    completed_at = raw_completed_at if isinstance(raw_completed_at, str) else None
    raw_completed_member_id = payload.get("completed_member_id")
    completed_member_id = (
        int(raw_completed_member_id)
        if isinstance(raw_completed_member_id, int | str)
           and str(raw_completed_member_id).isdigit()
        else None
    )
    raw_announcement_message_ids = payload.get("announcement_message_ids", [])
    announcement_message_ids = (
        tuple(
            int(message_id)
            for message_id in raw_announcement_message_ids
            if isinstance(message_id, int | str) and str(message_id).isdigit()
        )
        if isinstance(raw_announcement_message_ids, list)
        else ()
    )
    return PendingTeamSigningAssignment(
        assignment_id=assignment_id,
        guild_id=guild_id,
        normalized_member_name=normalized_member_name,
        member_name=member_name,
        team_role_id=team_role_id,
        team_role_name=team_role_name,
        division_name=division_name,
        team_image_url=team_image_url,
        is_player=is_player,
        staff_role_keys=staff_role_keys,
        source=source,
        created_at=created_at,
        completed_at=completed_at,
        completed_member_id=completed_member_id,
        announcement_message_ids=announcement_message_ids,
    )


def _assignment_to_dict(assignment: PendingTeamSigningAssignment) -> dict[str, object]:
    return {
        "assignment_id": assignment.assignment_id,
        "guild_id": assignment.guild_id,
        "normalized_member_name": assignment.normalized_member_name,
        "member_name": assignment.member_name,
        "team_role_id": assignment.team_role_id,
        "team_role_name": assignment.team_role_name,
        "division_name": assignment.division_name,
        "team_image_url": assignment.team_image_url,
        "is_player": assignment.is_player,
        "staff_role_keys": list(assignment.staff_role_keys),
        "source": assignment.source,
        "created_at": assignment.created_at,
        "completed_at": assignment.completed_at,
        "completed_member_id": assignment.completed_member_id,
        "announcement_message_ids": list(assignment.announcement_message_ids),
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


def _required_bool(payload: dict[str, object], key: str) -> bool | None:
    value = payload.get(key)
    return value if isinstance(value, bool) else None
