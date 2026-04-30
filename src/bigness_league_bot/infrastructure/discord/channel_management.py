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

import logging
from dataclasses import dataclass

import discord

from bigness_league_bot.application.services.channel_closure import (
    MATCH_CHANNEL_STATUS_CLOSED,
    MATCH_CHANNEL_STATUS_OPEN,
    MATCH_CHANNEL_STATUS_PLAYED,
    ChannelActionResult,
    ChannelCloseMode,
    is_match_channel_name,
    with_match_channel_status,
)
from bigness_league_bot.core.localization import LocalizedText, localize
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ChannelManagementError,
    InvalidChannelAccessRoleError,
    InvalidChannelNameError,
    ProtectedRoles,
    UnsupportedChannelError,
    get_protected_roles,
    user_audit_label,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

LOGGER = logging.getLogger(__name__)
OverwriteTarget = discord.Role | discord.Member | discord.Object

READ_ONLY_PERMISSION_FIELDS: tuple[str, ...] = (
    "send_messages",
    "send_messages_in_threads",
    "add_reactions",
    "create_public_threads",
    "create_private_threads",
)


@dataclass(frozen=True, slots=True)
class MatchChannelArchiveDestination:
    category: discord.CategoryChannel
    separator: discord.TextChannel
    place_before_separator: bool


@dataclass(frozen=True, slots=True)
class CategoryBulkDeleteResult:
    deleted_count: int
    category_name: str


def require_text_channel(channel: object) -> discord.TextChannel:
    if isinstance(channel, discord.TextChannel):
        return channel

    raise UnsupportedChannelError(
        localize(I18N.errors.channel_management.text_only)
    )


def ensure_valid_match_channel_name(channel: discord.TextChannel) -> None:
    if is_match_channel_name(channel.name):
        return

    raise InvalidChannelNameError(
        localize(I18N.errors.channel_management.invalid_channel_name)
    )


def resolve_category_by_identifier(
        guild: discord.Guild,
        category_identifier: str,
) -> discord.CategoryChannel:
    normalized_identifier = category_identifier.strip()
    if not normalized_identifier:
        raise ChannelManagementError(
            localize(
                I18N.errors.channel_management.bulk_delete_category_not_found,
                category_name=category_identifier,
            )
        )

    if normalized_identifier.isdecimal():
        channel = guild.get_channel(int(normalized_identifier))
        if isinstance(channel, discord.CategoryChannel):
            return channel

    normalized_name = normalized_identifier.casefold()
    matches = tuple(
        category
        for category in guild.categories
        if category.name.casefold() == normalized_name
    )
    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        raise ChannelManagementError(
            localize(
                I18N.errors.channel_management.bulk_delete_category_ambiguous,
                category_name=normalized_identifier,
            )
        )

    raise ChannelManagementError(
        localize(
            I18N.errors.channel_management.bulk_delete_category_not_found,
            category_name=normalized_identifier,
        )
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


async def apply_match_played_lockdown(
        channel: discord.TextChannel,
        actor: discord.abc.User,
) -> ChannelActionResult:
    protected_roles = get_protected_roles(channel.guild)
    overwrites = _current_overwrites(channel)
    protected_role_ids = {role.id for role in protected_roles.as_tuple}
    channel_name = with_match_channel_status(
        channel.name,
        MATCH_CHANNEL_STATUS_PLAYED,
    )

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
        name=channel_name,
        overwrites=overwrites,
        reason=(
            f"{user_audit_label(actor)} ejecutó /cerrar_canal "
            f"accion={ChannelCloseMode.MATCH_PLAYED.value}"
        ),
    )
    LOGGER.info(
        "CHANNEL_LOCKED_READ_ONLY channel=%s(%s) actor=%s(%s)",
        channel.name,
        channel.id,
        user_audit_label(actor),
        actor.id,
    )
    return ChannelActionResult(
        action=ChannelCloseMode.MATCH_PLAYED,
        summary=localize(I18N.actions.channel_management.match_played_summary),
    )


async def apply_matchday_closed(
        channel: discord.TextChannel,
        actor: discord.abc.User,
) -> ChannelActionResult:
    protected_roles = get_protected_roles(channel.guild)
    protected_role_ids = {role.id for role in protected_roles.as_tuple}
    overwrites = _current_overwrites(channel)
    channel_name = with_match_channel_status(
        channel.name,
        MATCH_CHANNEL_STATUS_CLOSED,
    )

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
        name=channel_name,
        overwrites=overwrites,
        reason=(
            f"{user_audit_label(actor)} ejecutó /cerrar_canal "
            f"accion={ChannelCloseMode.MATCHDAY_CLOSED.value}"
        ),
    )
    LOGGER.info(
        "CHANNEL_MATCHDAY_CLOSED channel=%s(%s) actor=%s(%s)",
        channel.name,
        channel.id,
        user_audit_label(actor),
        actor.id,
    )
    return ChannelActionResult(
        action=ChannelCloseMode.MATCHDAY_CLOSED,
        summary=localize(I18N.actions.channel_management.matchday_closed_summary),
    )


async def apply_match_reopen(
        channel: discord.TextChannel,
        actor: discord.abc.User,
        extra_roles: tuple[discord.Role, ...] = (),
) -> ChannelActionResult:
    protected_roles = get_protected_roles(channel.guild)
    overwrites = _current_overwrites(channel)
    protected_role_ids = {role.id for role in protected_roles.as_tuple}
    channel_name = with_match_channel_status(
        channel.name,
        MATCH_CHANNEL_STATUS_OPEN,
    )
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
        name=channel_name,
        overwrites=overwrites,
        reason=(
            f"{user_audit_label(actor)} ejecutó /cerrar_canal "
            f"accion={ChannelCloseMode.REOPEN_MATCH.value}"
        ),
    )
    LOGGER.info(
        "CHANNEL_REOPENED channel=%s(%s) actor=%s(%s)",
        channel.name,
        channel.id,
        user_audit_label(actor),
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
) -> LocalizedText:
    if not roles:
        raise InvalidChannelAccessRoleError(
            localize(I18N.errors.channel_management.no_valid_additional_roles)
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
            f"{user_audit_label(actor)} ejecutó /anadir_al_canal "
            f"roles={','.join(str(role.id) for role in roles)}"
        ),
    )
    LOGGER.info(
        "CHANNEL_ROLES_ADDED channel=%s(%s) actor=%s(%s) roles=%s",
        channel.name,
        channel.id,
        user_audit_label(actor),
        actor.id,
        ",".join(str(role.id) for role in roles),
    )
    return _add_roles_summary(roles)


def _reopen_summary(extra_roles: tuple[discord.Role, ...]) -> LocalizedText:
    if not extra_roles:
        return localize(I18N.actions.channel_management.reopen_summary)

    roles_label = ", ".join(role.mention for role in extra_roles)
    return localize(
        I18N.actions.channel_management.reopen_with_roles_summary,
        roles=roles_label,
    )


def _add_roles_summary(roles: tuple[discord.Role, ...]) -> LocalizedText:
    roles_label = ", ".join(role.mention for role in roles)
    return localize(
        I18N.actions.channel_management.add_roles_summary,
        roles=roles_label,
    )


def _resolve_match_channel_archive_destination(
        channel: discord.TextChannel,
        settings: Settings,
) -> MatchChannelArchiveDestination:
    if channel.category_id == settings.gold_division_category_id:
        place_before_separator = True
    elif channel.category_id == settings.silver_division_category_id:
        place_before_separator = False
    else:
        raise ChannelManagementError(
            localize(I18N.errors.channel_management.archive_source_category_unsupported)
        )

    archive_category = channel.guild.get_channel(
        settings.archived_match_channel_category_id
    )
    if not isinstance(archive_category, discord.CategoryChannel):
        raise ChannelManagementError(
            localize(
                I18N.errors.channel_management.archive_category_missing,
                category_id=settings.archived_match_channel_category_id,
            )
        )

    separator = channel.guild.get_channel(settings.archived_match_channel_separator_id)
    if not isinstance(separator, discord.TextChannel):
        raise ChannelManagementError(
            localize(
                I18N.errors.channel_management.archive_separator_missing,
                channel_id=settings.archived_match_channel_separator_id,
            )
        )

    if separator.category_id != archive_category.id:
        raise ChannelManagementError(
            localize(
                I18N.errors.channel_management.archive_separator_not_in_category,
                channel_id=separator.id,
                category_id=archive_category.id,
            )
        )

    return MatchChannelArchiveDestination(
        category=archive_category,
        separator=separator,
        place_before_separator=place_before_separator,
    )


async def archive_text_channel(
        channel: discord.TextChannel,
        actor: discord.abc.User,
        settings: Settings,
) -> ChannelActionResult:
    destination = _resolve_match_channel_archive_destination(channel, settings)
    placement = "encima" if destination.place_before_separator else "debajo"
    LOGGER.info(
        "CHANNEL_ARCHIVE_REQUEST channel=%s(%s) actor=%s(%s) archive_category=%s separator=%s placement=%s",
        channel.name,
        channel.id,
        user_audit_label(actor),
        actor.id,
        destination.category.id,
        destination.separator.id,
        placement,
    )
    move_kwargs: dict[str, object] = {
        "category": destination.category,
        "reason": (
            f"{user_audit_label(actor)} confirmo /cerrar_canal "
            f"accion={ChannelCloseMode.ARCHIVE_CHANNEL.value} "
            f"destino_categoria={destination.category.id} "
            f"separador={destination.separator.id} "
            f"ubicacion={placement}"
        ),
        "sync_permissions": False,
    }
    if destination.place_before_separator:
        move_kwargs["before"] = destination.separator
    else:
        move_kwargs["after"] = destination.separator

    await channel.move(**move_kwargs)

    summary_key = (
        I18N.actions.channel_management.archive_above_separator_summary
        if destination.place_before_separator
        else I18N.actions.channel_management.archive_below_separator_summary
    )
    return ChannelActionResult(
        action=ChannelCloseMode.ARCHIVE_CHANNEL,
        summary=localize(summary_key),
    )


async def bulk_delete_category_channels(
        category: discord.CategoryChannel,
        actor: discord.abc.User,
) -> CategoryBulkDeleteResult:
    channels = tuple(category.channels)
    if not channels:
        raise ChannelManagementError(
            localize(
                I18N.errors.channel_management.bulk_delete_category_empty,
                category_name=category.name,
            )
        )

    LOGGER.warning(
        "CATEGORY_BULK_DELETE_REQUEST category=%s(%s) actor=%s(%s) channels=%s",
        category.name,
        category.id,
        user_audit_label(actor),
        actor.id,
        ",".join(f"{channel.name}({channel.id})" for channel in channels),
    )
    for channel in channels:
        await channel.delete(
            reason=(
                f"{user_audit_label(actor)} confirmo /borrado_masivo "
                f"categoria={category.name}({category.id})"
            )
        )

    return CategoryBulkDeleteResult(
        deleted_count=len(channels),
        category_name=category.name,
    )


async def _legacy_delete_text_channel_unused(
        channel: discord.TextChannel,
        actor: discord.abc.User,
) -> None:
    LOGGER.warning(
        "CHANNEL_DELETE_REQUEST channel=%s(%s) actor=%s(%s)",
        channel.name,
        channel.id,
        user_audit_label(actor),
        actor.id,
    )
    await channel.delete(
        reason=(
            f"{user_audit_label(actor)} confirmó /cerrar_canal "
            f"accion={ChannelCloseMode.ARCHIVE_CHANNEL.value}"
        )
    )
