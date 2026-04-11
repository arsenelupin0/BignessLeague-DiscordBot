#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import discord

from bigness_league_bot.application.services.channel_closure import (
    ChannelActionResult,
    ChannelCloseMode,
    PROTECTED_ROLE_NAMES,
    is_match_channel_name,
    protected_role_names_label,
)

LOGGER = logging.getLogger(__name__)
OverwriteTarget = discord.Role | discord.Member | discord.Object

READ_ONLY_PERMISSION_FIELDS: tuple[str, ...] = (
    "send_messages",
    "send_messages_in_threads",
    "add_reactions",
    "create_public_threads",
    "create_private_threads",
)


class ChannelManagementError(RuntimeError):
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


def require_text_channel(channel: object) -> discord.TextChannel:
    if isinstance(channel, discord.TextChannel):
        return channel

    raise UnsupportedChannelError(
        "Este comando solo se puede usar dentro de un canal de texto."
    )


def ensure_valid_match_channel_name(channel: discord.TextChannel) -> None:
    if is_match_channel_name(channel.name):
        return

    raise InvalidChannelNameError(
        "Este comando solo se puede usar en canales con nombre "
        "`j[1-9][0-9]?-partido-[1-9][0-9]?`."
    )


def _member_role_names(member: discord.Member) -> set[str]:
    return {role.name.casefold() for role in member.roles}


def ensure_allowed_member(member: discord.Member) -> None:
    allowed_role_names = {role_name.casefold() for role_name in PROTECTED_ROLE_NAMES}
    if _member_role_names(member) & allowed_role_names:
        return

    raise UnauthorizedRoleError(
        "Solo pueden usar este comando los roles: "
        f"{protected_role_names_label()}."
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
            f"Faltan roles protegidos en el servidor: {missing}."
        )

    return ProtectedRoles(
        staff=roles_by_name["staff"],
        administrator=roles_by_name["administrador"],
        ceo=roles_by_name["ceo"],
    )


def _set_text_permissions(
        overwrite: discord.PermissionOverwrite,
        *,
        view_channel: bool | None,
        can_write: bool,
) -> discord.PermissionOverwrite:
    overwrite.update(
        view_channel=view_channel,
        send_messages=can_write,
        send_messages_in_threads=can_write,
        add_reactions=can_write,
        create_public_threads=can_write,
        create_private_threads=can_write,
    )

    return overwrite


def _current_overwrites(
        channel: discord.TextChannel,
) -> dict[OverwriteTarget, discord.PermissionOverwrite]:
    return dict(channel.overwrites)


def _set_everyone_hidden_permissions(
        channel: discord.TextChannel,
        overwrites: dict[OverwriteTarget, discord.PermissionOverwrite],
) -> None:
    everyone_overwrite = channel.overwrites_for(channel.guild.default_role)
    overwrites[channel.guild.default_role] = _set_text_permissions(
        everyone_overwrite,
        view_channel=False,
        can_write=False,
    )


def _role_targets(
        channel: discord.TextChannel,
        protected_roles: ProtectedRoles,
) -> set[discord.Role]:
    targets: set[discord.Role] = {channel.guild.default_role, *protected_roles.as_tuple}
    for target in channel.overwrites:
        if isinstance(target, discord.Role):
            targets.add(target)
    return targets


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
                f"El rol `{role.name}` no pertenece a este servidor."
            )

        if role == guild.default_role:
            raise InvalidChannelAccessRoleError(
                "No puedes anadir `@everyone` al canal."
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
            f"No existe el rol de inicio configurado para el selector: `{range_start_role_id}`."
        )

    range_end = guild.get_role(range_end_role_id)
    if range_end is None:
        raise ChannelAccessRoleRangeError(
            f"No existe el rol de fin configurado para el selector: `{range_end_role_id}`."
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
            "No hay roles seleccionables entre los separadores configurados."
        )

    return ChannelAccessRoleCatalog(
        range_start=range_start,
        range_end=range_end,
        roles=candidate_roles,
    )


async def apply_match_played_lockdown(
        channel: discord.TextChannel,
        actor: discord.abc.User,
) -> ChannelActionResult:
    protected_roles = get_protected_roles(channel.guild)
    overwrites = _current_overwrites(channel)
    protected_role_ids = {role.id for role in protected_roles.as_tuple}

    for role in _role_targets(channel, protected_roles):
        overwrite = channel.overwrites_for(role)
        is_protected = role.id in protected_role_ids
        if role == channel.guild.default_role:
            view_channel = False
        elif is_protected:
            view_channel = True
        else:
            view_channel = getattr(overwrite, "view_channel", None)

        overwrites[role] = _set_text_permissions(
            overwrite,
            view_channel=view_channel,
            can_write=is_protected,
        )

    await channel.edit(
        overwrites=overwrites,
        reason=(
            f"{actor} ({actor.id}) ejecuto /cerrar_canal "
            f"accion={ChannelCloseMode.MATCH_PLAYED.value}"
        ),
    )
    LOGGER.info(
        "CHANNEL_LOCKED_READ_ONLY channel=%s(%s) actor=%s(%s)",
        channel.name,
        channel.id,
        actor,
        actor.id,
    )
    return ChannelActionResult(
        action=ChannelCloseMode.MATCH_PLAYED,
        summary=(
            "Canal puesto en modo solo lectura para el resto de roles. "
            "Staff, Administrador y Ceo mantienen escritura."
        ),
    )


async def apply_matchday_closed(
        channel: discord.TextChannel,
        actor: discord.abc.User,
) -> ChannelActionResult:
    protected_roles = get_protected_roles(channel.guild)
    protected_role_ids = {role.id for role in protected_roles.as_tuple}
    overwrites = _current_overwrites(channel)

    for target in list(overwrites):
        if isinstance(target, discord.Role) and target.id not in protected_role_ids:
            overwrites.pop(target, None)

    _set_everyone_hidden_permissions(channel, overwrites)

    for role in protected_roles.as_tuple:
        overwrite = channel.overwrites_for(role)
        overwrites[role] = _set_text_permissions(
            overwrite,
            view_channel=True,
            can_write=True,
        )

    await channel.edit(
        overwrites=overwrites,
        reason=(
            f"{actor} ({actor.id}) ejecuto /cerrar_canal "
            f"accion={ChannelCloseMode.MATCHDAY_CLOSED.value}"
        ),
    )
    LOGGER.info(
        "CHANNEL_MATCHDAY_CLOSED channel=%s(%s) actor=%s(%s)",
        channel.name,
        channel.id,
        actor,
        actor.id,
    )
    return ChannelActionResult(
        action=ChannelCloseMode.MATCHDAY_CLOSED,
        summary=(
            "Canal cerrado para roles no protegidos. "
            "Solo Staff, Administrador y Ceo conservan acceso."
        ),
    )


async def apply_match_reopen(
        channel: discord.TextChannel,
        actor: discord.abc.User,
        extra_roles: tuple[discord.Role, ...] = (),
) -> ChannelActionResult:
    protected_roles = get_protected_roles(channel.guild)
    overwrites = _current_overwrites(channel)
    protected_role_ids = {role.id for role in protected_roles.as_tuple}
    _set_everyone_hidden_permissions(channel, overwrites)

    for role in _role_targets(channel, protected_roles):
        overwrite = channel.overwrites_for(role)
        is_protected = role.id in protected_role_ids
        if role == channel.guild.default_role:
            view_channel = False
            can_write = False
        elif is_protected:
            view_channel = True
            can_write = True
        else:
            view_channel = getattr(overwrite, "view_channel", None)
            can_write = True

        overwrites[role] = _set_text_permissions(
            overwrite,
            view_channel=view_channel,
            can_write=can_write,
        )

    for role in extra_roles:
        overwrite = channel.overwrites_for(role)
        overwrites[role] = _set_text_permissions(
            overwrite,
            view_channel=True,
            can_write=True,
        )

    await channel.edit(
        overwrites=overwrites,
        reason=(
            f"{actor} ({actor.id}) ejecuto /cerrar_canal "
            f"accion={ChannelCloseMode.REOPEN_MATCH.value}"
        ),
    )
    LOGGER.info(
        "CHANNEL_REOPENED channel=%s(%s) actor=%s(%s)",
        channel.name,
        channel.id,
        actor,
        actor.id,
    )
    return ChannelActionResult(
        action=ChannelCloseMode.REOPEN_MATCH,
        summary=_reopen_summary(extra_roles),
    )


async def add_roles_to_channel(
        channel: discord.TextChannel,
        actor: discord.abc.User,
        roles: tuple[discord.Role, ...],
) -> str:
    if not roles:
        raise InvalidChannelAccessRoleError(
            "Selecciona al menos un rol adicional valido."
        )

    overwrites = _current_overwrites(channel)
    _set_everyone_hidden_permissions(channel, overwrites)

    for role in roles:
        overwrite = channel.overwrites_for(role)
        overwrites[role] = _set_text_permissions(
            overwrite,
            view_channel=True,
            can_write=True,
        )

    await channel.edit(
        overwrites=overwrites,
        reason=(
            f"{actor} ({actor.id}) ejecuto /anadir_al_canal "
            f"roles={','.join(str(role.id) for role in roles)}"
        ),
    )
    LOGGER.info(
        "CHANNEL_ROLES_ADDED channel=%s(%s) actor=%s(%s) roles=%s",
        channel.name,
        channel.id,
        actor,
        actor.id,
        ",".join(str(role.id) for role in roles),
    )
    return _add_roles_summary(roles)


def _reopen_summary(extra_roles: tuple[discord.Role, ...]) -> str:
    if not extra_roles:
        return "Canal reabierto. Se ha restaurado la escritura para los roles con acceso al canal."

    roles_label = ", ".join(role.mention for role in extra_roles)
    return (
        "Canal reabierto. Se ha restaurado la escritura para los roles con acceso al canal "
        f"y se han anadido estos roles: {roles_label}."
    )


def _add_roles_summary(roles: tuple[discord.Role, ...]) -> str:
    roles_label = ", ".join(role.mention for role in roles)
    return f"Se han anadido al canal estos roles: {roles_label}."


async def delete_text_channel(
        channel: discord.TextChannel,
        actor: discord.abc.User,
) -> None:
    LOGGER.warning(
        "CHANNEL_DELETE_REQUEST channel=%s(%s) actor=%s(%s)",
        channel.name,
        channel.id,
        actor,
        actor.id,
    )
    await channel.delete(
        reason=(
            f"{actor} ({actor.id}) confirmo /cerrar_canal "
            f"accion={ChannelCloseMode.DELETE_CHANNEL.value}"
        )
    )
