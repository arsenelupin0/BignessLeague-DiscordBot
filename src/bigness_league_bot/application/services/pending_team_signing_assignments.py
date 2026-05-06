from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class PendingTeamSigningAssignment:
    assignment_id: str
    guild_id: int
    normalized_member_name: str
    member_name: str
    team_role_id: int
    team_role_name: str
    division_name: str
    team_image_url: str | None
    is_player: bool
    staff_role_keys: tuple[str, ...]
    source: str
    created_at: str
    completed_at: str | None = None
    completed_member_id: int | None = None
    announcement_message_ids: tuple[int, ...] = ()

    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None

    @property
    def dedupe_key(self) -> tuple[object, ...]:
        return (
            self.guild_id,
            self.normalized_member_name,
            self.team_role_id,
        )


def build_pending_assignment_id(
        *,
        guild_id: int,
        normalized_member_name: str,
        team_role_id: int,
) -> str:
    return f"{guild_id}:{team_role_id}:{normalized_member_name}"


def merge_pending_assignment(
        existing: PendingTeamSigningAssignment,
        incoming: PendingTeamSigningAssignment,
) -> PendingTeamSigningAssignment:
    if existing.is_completed:
        return existing

    return replace(
        existing,
        member_name=incoming.member_name or existing.member_name,
        team_role_name=incoming.team_role_name or existing.team_role_name,
        division_name=incoming.division_name or existing.division_name,
        team_image_url=incoming.team_image_url or existing.team_image_url,
        is_player=existing.is_player or incoming.is_player,
        staff_role_keys=tuple(
            sorted({*existing.staff_role_keys, *incoming.staff_role_keys})
        ),
        source=_merge_source(existing.source, incoming.source),
    )


def complete_pending_assignment(
        assignment: PendingTeamSigningAssignment,
        *,
        completed_at: str,
        completed_member_id: int,
        announcement_message_ids: tuple[int, ...],
) -> PendingTeamSigningAssignment:
    return replace(
        assignment,
        completed_at=completed_at,
        completed_member_id=completed_member_id,
        announcement_message_ids=announcement_message_ids,
    )


def _merge_source(left: str, right: str) -> str:
    if not left:
        return right
    if not right or right == left:
        return left

    sources = tuple(dict.fromkeys((*left.split("+"), *right.split("+"))))
    return "+".join(sources)
