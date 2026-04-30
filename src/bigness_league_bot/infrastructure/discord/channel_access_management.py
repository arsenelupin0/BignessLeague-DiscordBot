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

from collections.abc import Sequence
from dataclasses import dataclass

import discord

from bigness_league_bot.application.services.channel_closure import (
    PROTECTED_ROLE_NAMES,
    protected_role_names_label,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.i18n.keys import I18N


def user_audit_label(user: discord.abc.User | discord.Member) -> str:
    return f"{user.name} ({user.id})"


class ChannelManagementError(CommandUserError):
    """Base error for channel management operations."""


class UnsupportedChannelError(ChannelManagementError):
    """Raised when the interaction is not executed in a text channel."""


class ProtectedRoleMissingError(ChannelManagementError):
    """Raised when a protected role cannot be found in the guild."""


class InvalidChannelNameError(ChannelManagementError):
    """Raised when the channel name does not match the expected pattern."""


class UnauthorizedRoleError(ChannelManagementError):
    """Raised when the user lacks the allowed roles."""


class InvalidChannelAccessRoleError(ChannelManagementError):
    """Raised when an invalid role is provided for channel access changes."""


class ChannelAccessRoleRangeError(ChannelManagementError):
    """Raised when the configured role range for channel access is invalid."""


class MemberTeamRoleMissingError(ChannelManagementError):
    """Raised when the member does not have a team role in the configured range."""


class MemberTeamRoleAmbiguousError(ChannelManagementError):
    """Raised when the member has more than one team role in the configured range."""


@dataclass(frozen=True, slots=True)
class ProtectedRoles:
    staff: discord.Role
    administrator: discord.Role
    ceo: discord.Role

    @property
    def as_tuple(self) -> tuple[discord.Role, ...]:
        return self.staff, self.administrator, self.ceo


@dataclass(frozen=True, slots=True)
class ChannelAccessRoleCatalog:
    range_start: discord.Role
    range_end: discord.Role
    roles: tuple[discord.Role, ...]


def _member_role_names(member: discord.Member) -> set[str]:
    return {role.name.casefold() for role in member.roles}


def ensure_allowed_member(member: discord.Member) -> None:
    allowed_role_names = {role_name.casefold() for role_name in PROTECTED_ROLE_NAMES}
    if _member_role_names(member) & allowed_role_names:
        return

    raise UnauthorizedRoleError(
        localize(
            I18N.errors.channel_management.unauthorized_role,
            protected_roles=protected_role_names_label(),
        )
    )


def get_protected_roles(guild: discord.Guild) -> ProtectedRoles:
    roles_by_name = {role.name.casefold(): role for role in guild.roles}
    missing_roles = [
        role_name
        for role_name in PROTECTED_ROLE_NAMES
        if role_name.casefold() not in roles_by_name
    ]
    if missing_roles:
        missing = ", ".join(missing_roles)
        raise ProtectedRoleMissingError(
            localize(
                I18N.errors.channel_management.protected_roles_missing,
                missing_roles=missing,
            )
        )

    return ProtectedRoles(
        staff=roles_by_name["staff"],
        administrator=roles_by_name["administrador"],
        ceo=roles_by_name["ceo"],
    )


def normalize_channel_access_roles(
        guild: discord.Guild,
        roles: Sequence[discord.Role | None],
) -> tuple[discord.Role, ...]:
    unique_roles: dict[int, discord.Role] = {}
    protected_role_names = {role_name.casefold() for role_name in PROTECTED_ROLE_NAMES}
    provided_roles = tuple(role for role in roles if isinstance(role, discord.Role))

    for role in provided_roles:
        if role.guild.id != guild.id:
            raise InvalidChannelAccessRoleError(
                localize(
                    I18N.errors.channel_management.invalid_role_not_in_guild,
                    role_name=role.name,
                )
            )

        if role == guild.default_role:
            raise InvalidChannelAccessRoleError(
                localize(I18N.errors.channel_management.invalid_role_everyone)
            )

        if role.name.casefold() in protected_role_names:
            continue

        unique_roles[role.id] = role

    return tuple(unique_roles.values())


def get_channel_access_role_catalog(
        guild: discord.Guild,
        range_start_role_id: int,
        range_end_role_id: int,
) -> ChannelAccessRoleCatalog:
    range_start = guild.get_role(range_start_role_id)
    if range_start is None:
        raise ChannelAccessRoleRangeError(
            localize(
                I18N.errors.channel_management.range_start_missing,
                role_id=range_start_role_id,
            )
        )

    range_end = guild.get_role(range_end_role_id)
    if range_end is None:
        raise ChannelAccessRoleRangeError(
            localize(
                I18N.errors.channel_management.range_end_missing,
                role_id=range_end_role_id,
            )
        )

    upper_position = max(range_start.position, range_end.position)
    lower_position = min(range_start.position, range_end.position)
    candidate_roles = tuple(
        sorted(
            (
                role
                for role in guild.roles
                if role != guild.default_role
                   and not role.managed
                   and role.id not in {range_start.id, range_end.id}
                   and lower_position < role.position < upper_position
            ),
            key=lambda role: role.position,
            reverse=True,
        )
    )
    if not candidate_roles:
        raise ChannelAccessRoleRangeError(
            localize(I18N.errors.channel_management.range_empty)
        )

    return ChannelAccessRoleCatalog(
        range_start=range_start,
        range_end=range_end,
        roles=candidate_roles,
    )


def get_member_team_roles(
        member: discord.Member,
        role_catalog: ChannelAccessRoleCatalog,
) -> tuple[discord.Role, ...]:
    allowed_role_ids = {role.id for role in role_catalog.roles}
    return tuple(
        sorted(
            (
                role
                for role in member.roles
                if role.id in allowed_role_ids
            ),
            key=lambda role: role.position,
            reverse=True,
        )
    )


def ensure_member_can_access_team_features(
        member: discord.Member,
        role_catalog: ChannelAccessRoleCatalog,
) -> None:
    if get_member_team_roles(member, role_catalog):
        return

    ensure_allowed_member(member)


def resolve_member_team_role(
        member: discord.Member,
        role_catalog: ChannelAccessRoleCatalog,
) -> discord.Role:
    member_team_roles = get_member_team_roles(member, role_catalog)
    if not member_team_roles:
        raise MemberTeamRoleMissingError(
            localize(I18N.errors.team_profile.team_role_missing)
        )

    if len(member_team_roles) > 1:
        role_names = ", ".join(role.name for role in member_team_roles)
        raise MemberTeamRoleAmbiguousError(
            localize(
                I18N.errors.team_profile.multiple_team_roles,
                role_names=role_names,
            )
        )

    return member_team_roles[0]
