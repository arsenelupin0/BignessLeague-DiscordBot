from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import discord


def resolve_tracked_staff_roles(
        *,
        settings: Any,
        guild: discord.Guild,
) -> tuple[discord.Role, ...]:
    configured_role_ids = (
        settings.staff_ceo_role_id,
        settings.staff_analyst_role_id,
        settings.staff_coach_role_id,
        settings.staff_manager_role_id,
        settings.staff_second_manager_role_id,
        settings.staff_captain_role_id,
    )
    tracked_roles: dict[int, discord.Role] = {}
    for role_id in configured_role_ids:
        role = guild.get_role(role_id)
        if role is not None:
            tracked_roles[role.id] = role

    return tuple(tracked_roles.values())


def resolve_player_role_change_team_context(
        *,
        after: discord.Member,
        tracked_team_role_ids: set[int],
) -> discord.Role | None:
    team_roles = tuple(
        role
        for role in after.roles
        if role.id in tracked_team_role_ids
    )
    unique_roles = deduplicate_roles(team_roles)
    if len(unique_roles) == 1:
        return unique_roles[0]

    return None


def has_any_role(
        roles: Iterable[discord.Role],
        tracked_role_ids: set[int],
) -> bool:
    return any(role.id in tracked_role_ids for role in roles)


def resolve_team_role_context(
        *,
        before: discord.Member,
        after: discord.Member,
        tracked_team_role_ids: set[int],
        removed_team_roles: tuple[discord.Role, ...],
        added_team_roles: tuple[discord.Role, ...],
        removed_staff_roles: tuple[discord.Role, ...],
        added_staff_roles: tuple[discord.Role, ...],
) -> discord.Role | None:
    role_groups: list[tuple[discord.Role, ...]] = []
    if removed_staff_roles:
        role_groups.append(removed_team_roles)
    if added_staff_roles:
        role_groups.append(added_team_roles)
    role_groups.extend(
        (
            tuple(role for role in after.roles if role.id in tracked_team_role_ids),
            tuple(role for role in before.roles if role.id in tracked_team_role_ids),
        )
    )
    candidate_roles = {
        role.id: role
        for role in (*after.roles, *before.roles)
        if role.id in tracked_team_role_ids
    }
    role_groups.append(tuple(candidate_roles.values()))
    for role_group in role_groups:
        unique_roles = deduplicate_roles(role_group)
        if len(unique_roles) == 1:
            return unique_roles[0]

    return None


def deduplicate_roles(
        roles: tuple[discord.Role, ...],
) -> tuple[discord.Role, ...]:
    return tuple({role.id: role for role in roles}.values())


def format_roles_for_log(
        roles: Iterable[discord.Role],
) -> str:
    formatted_roles = tuple(f"{role.name}({role.id})" for role in roles)
    if not formatted_roles:
        return "-"

    return ", ".join(formatted_roles)
