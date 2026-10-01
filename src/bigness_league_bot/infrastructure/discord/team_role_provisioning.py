from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

import discord

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ChannelAccessRoleCatalog,
    user_audit_label,
)
from bigness_league_bot.infrastructure.discord.team_member_lookup import normalize_member_lookup_text
from bigness_league_bot.infrastructure.i18n.keys import I18N


@dataclass(frozen=True, slots=True)
class TeamRoleProvisionResult:
    role: discord.Role
    created: bool = False


async def resolve_or_create_team_role(
        guild: discord.Guild,
        *,
        team_name: str,
        role_catalog: ChannelAccessRoleCatalog,
        actor: discord.abc.User,
        create_if_missing: bool,
) -> TeamRoleProvisionResult:
    existing_role = _find_team_role_by_name(team_name, role_catalog.roles)
    if existing_role is not None:
        return TeamRoleProvisionResult(role=existing_role)

    if not create_if_missing:
        raise CommandUserError(
            localize(
                I18N.errors.team_role_assignment.team_role_not_found,
                team_name=team_name,
            )
        )

    created_role = await guild.create_role(
        name=team_name,
        colour=_random_role_colour(),
        hoist=True,
        reason=(
            f"{user_audit_label(actor)} creo el rol de equipo {team_name} "
            "tras registrar un equipo nuevo en Google Sheets"
        ),
    )
    await sort_team_roles_alphabetically(
        guild,
        role_catalog=role_catalog,
        extra_roles=(created_role,),
        actor=actor,
    )
    return TeamRoleProvisionResult(
        role=guild.get_role(created_role.id) or created_role,
        created=True,
    )


async def sort_team_roles_alphabetically(
        guild: discord.Guild,
        *,
        role_catalog: ChannelAccessRoleCatalog,
        actor: discord.abc.User,
        extra_roles: Iterable[discord.Role] = (),
) -> None:
    roles_by_id = {
        role.id: role
        for role in (*role_catalog.roles, *extra_roles)
        if role.guild.id == guild.id and role != guild.default_role and not role.managed
    }
    if not roles_by_id:
        return

    ordered_roles = tuple(
        sorted(
            roles_by_id.values(),
            key=lambda role: normalize_member_lookup_text(role.name),
        )
    )
    # Creation changes positions below the separators, and the gateway cache may
    # not reflect it yet. Use the current server hierarchy to insert the new role.
    current_roles = sorted(await guild.fetch_roles())
    current_roles_by_id = {role.id: role for role in current_roles}
    range_start = current_roles_by_id[role_catalog.range_start.id]
    range_end = current_roles_by_id[role_catalog.range_end.id]
    upper_separator = max(range_start, range_end)
    remaining_roles = [role for role in current_roles if role.id not in roles_by_id]
    insertion_index = next(
        index for index, role in enumerate(remaining_roles)
        if role.id == upper_separator.id
    )
    # Guild roles run from bottom to top; alphabetical display runs top to bottom.
    desired_roles = (
            remaining_roles[:insertion_index]
            + list(reversed(ordered_roles))
            + remaining_roles[insertion_index:]
    )
    # Reuse the existing slots; roles outside the affected interval must not be
    # renumbered, including roles above the bot that it cannot move.
    positions = {
        desired_role: current_role.position
        for current_role, desired_role in zip(current_roles, desired_roles)
        if desired_role.id != current_role.id
    }
    if not positions:
        return
    await guild.edit_role_positions(
        positions=positions,
        reason=(
            f"{user_audit_label(actor)} ordenó alfabéticamente los roles de equipo "
            "tras crear un rol nuevo"
        ),
    )


def _find_team_role_by_name(
        team_name: str,
        roles: Iterable[discord.Role],
) -> discord.Role | None:
    normalized_team_name = normalize_member_lookup_text(team_name)
    for role in roles:
        if normalize_member_lookup_text(role.name) == normalized_team_name:
            return role

    return None


def _random_role_colour() -> discord.Colour:
    return discord.Colour(random.SystemRandom().randint(0x000001, 0xFFFFFF))
