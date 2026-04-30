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
from bigness_league_bot.infrastructure.discord.team_role_assignment import normalize_member_lookup_text
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
    return TeamRoleProvisionResult(role=created_role, created=True)


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
    range_start = guild.get_role(role_catalog.range_start.id) or role_catalog.range_start
    range_end = guild.get_role(role_catalog.range_end.id) or role_catalog.range_end
    upper_position = max(range_start.position, range_end.position)
    positions = {
        role: upper_position - index - 1
        for index, role in enumerate(ordered_roles)
    }
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
