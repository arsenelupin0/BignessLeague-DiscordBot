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

import discord

from bigness_league_bot.application.services.channel_closure import (
    MATCH_CHANNEL_STATUS_OPEN,
    MATCH_CHANNEL_STATUS_SCHEDULED,
    ChannelActionResult,
    ChannelCloseMode,
    with_match_channel_status,
)
from bigness_league_bot.application.services.match_channel_creation import (
    build_match_start_at,
)
from bigness_league_bot.core.localization import localize
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ChannelManagementError,
    get_channel_access_role_catalog,
    user_audit_label,
)
from bigness_league_bot.infrastructure.discord.emojis import (
    MATCH_SCHEDULE_GREEN_ARROW_EMOJI,
    render_custom_emoji,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

LOGGER = logging.getLogger(__name__)
MATCH_SCHEDULED_NOTICE_MARKERS: tuple[str, ...] = (
    "Horario fijado",
    "Scheduled time",
)
MATCH_SCHEDULE_NOTICE_HISTORY_LIMIT = 100


async def apply_match_scheduled(
        channel: discord.TextChannel,
        actor: discord.abc.User,
        *,
        date_value: str,
        time_value: str,
        settings: Settings,
        bot: discord.Client,
) -> ChannelActionResult:
    try:
        start_at = build_match_start_at(
            date_value=date_value,
            time_value=time_value,
            timezone_name=settings.timezone,
        )
    except ValueError as exc:
        error_code = exc.args[0] if exc.args else ""
        if error_code == "invalid_date":
            raise ChannelManagementError(
                localize(I18N.errors.match_channel_creation.invalid_date_format)
            ) from exc

        if error_code == "invalid_time":
            raise ChannelManagementError(
                localize(I18N.errors.match_channel_creation.invalid_time_format)
            ) from exc

        raise

    green_arrow = render_custom_emoji(
        guild=channel.guild,
        bot=bot,
        emoji=MATCH_SCHEDULE_GREEN_ARROW_EMOJI,
    )
    team_mentions = _match_team_mentions(channel, settings)
    caster_mentions = _match_caster_mentions(channel, settings)
    channel_name = with_match_channel_status(
        channel.name,
        MATCH_CHANNEL_STATUS_SCHEDULED,
    )
    deleted_notice_count = await _delete_previous_match_scheduled_notices(
        channel,
        bot,
    )
    await channel.edit(
        name=channel_name,
        reason=(
            f"{user_audit_label(actor)} ejecutó /cerrar_canal "
            f"accion={ChannelCloseMode.MATCH_SCHEDULED.value} "
            f"timestamp={int(start_at.timestamp())}"
        ),
    )
    LOGGER.info(
        "CHANNEL_MATCH_SCHEDULED channel=%s(%s) actor=%s(%s) timestamp=%s",
        channel.name,
        channel.id,
        user_audit_label(actor),
        actor.id,
        int(start_at.timestamp()),
    )
    if deleted_notice_count:
        LOGGER.info(
            "CHANNEL_MATCH_SCHEDULED_PREVIOUS_NOTICES_DELETED channel=%s(%s) count=%s",
            channel.name,
            channel.id,
            deleted_notice_count,
        )
    return ChannelActionResult(
        action=ChannelCloseMode.MATCH_SCHEDULED,
        summary=localize(
            I18N.actions.channel_management.match_scheduled_summary,
            green_arrow=green_arrow,
            timestamp=str(int(start_at.timestamp())),
            team_mentions=team_mentions,
            caster_mentions=caster_mentions,
        ),
    )


async def apply_match_in_progress(
        channel: discord.TextChannel,
        actor: discord.abc.User,
        *,
        settings: Settings,
        bot: discord.Client,
) -> ChannelActionResult:
    caster_mentions = _match_caster_mentions(channel, settings)
    channel_name = with_match_channel_status(
        channel.name,
        MATCH_CHANNEL_STATUS_OPEN,
    )
    deleted_notice_count = await _delete_previous_match_scheduled_notices(
        channel,
        bot,
    )
    await channel.edit(
        name=channel_name,
        reason=(
            f"{user_audit_label(actor)} ejecutó /cerrar_canal "
            f"accion={ChannelCloseMode.MATCH_IN_PROGRESS.value}"
        ),
    )
    LOGGER.info(
        "CHANNEL_MATCH_IN_PROGRESS channel=%s(%s) actor=%s(%s)",
        channel.name,
        channel.id,
        user_audit_label(actor),
        actor.id,
    )
    if deleted_notice_count:
        LOGGER.info(
            "CHANNEL_MATCH_IN_PROGRESS_PREVIOUS_NOTICES_DELETED channel=%s(%s) count=%s",
            channel.name,
            channel.id,
            deleted_notice_count,
        )
    return ChannelActionResult(
        action=ChannelCloseMode.MATCH_IN_PROGRESS,
        summary=localize(
            I18N.actions.channel_management.match_in_progress_summary,
            green_arrow=render_custom_emoji(
                guild=channel.guild,
                bot=bot,
                emoji=MATCH_SCHEDULE_GREEN_ARROW_EMOJI,
            ),
            caster_mentions=caster_mentions,
        ),
    )


async def _delete_previous_match_scheduled_notices(
        channel: discord.TextChannel,
        bot: discord.Client,
) -> int:
    bot_user = bot.user
    if bot_user is None:
        return 0

    deleted_count = 0
    async for message in channel.history(limit=MATCH_SCHEDULE_NOTICE_HISTORY_LIMIT):
        if message.author.id != bot_user.id:
            continue

        if not _is_match_scheduled_notice(message.content):
            continue

        try:
            await message.delete()
        except discord.NotFound:
            continue
        except discord.Forbidden:
            LOGGER.warning(
                "MATCH_SCHEDULE_NOTICE_DELETE_FORBIDDEN channel=%s(%s) message=%s",
                channel.name,
                channel.id,
                message.id,
            )
            continue
        except discord.HTTPException as exc:
            LOGGER.warning(
                "MATCH_SCHEDULE_NOTICE_DELETE_FAILED channel=%s(%s) message=%s details=%s",
                channel.name,
                channel.id,
                message.id,
                exc,
            )
            continue

        deleted_count += 1

    return deleted_count


def _is_match_scheduled_notice(content: str) -> bool:
    return any(marker in content for marker in MATCH_SCHEDULED_NOTICE_MARKERS)


def _channel_role_overwrite_targets(channel: discord.TextChannel) -> tuple[discord.Role, ...]:
    return tuple(
        target
        for target in channel.overwrites
        if isinstance(target, discord.Role)
    )


def _match_team_mentions(channel: discord.TextChannel, settings: Settings) -> str:
    role_catalog = get_channel_access_role_catalog(
        channel.guild,
        settings.channel_access_range_start_role_id,
        settings.channel_access_range_end_role_id,
    )
    team_role_ids = {role.id for role in role_catalog.roles}
    team_roles = tuple(
        sorted(
            (
                role
                for role in _channel_role_overwrite_targets(channel)
                if role.id in team_role_ids
            ),
            key=lambda role: role.position,
            reverse=True,
        )
    )
    if len(team_roles) != 2:
        raise ChannelManagementError(
            localize(
                I18N.errors.channel_management.match_channel_team_roles_unresolved,
                role_count=str(len(team_roles)),
            )
        )

    return " ".join(role.mention for role in team_roles)


def _match_caster_mentions(channel: discord.TextChannel, settings: Settings) -> str:
    if not settings.match_channel_extra_role_ids:
        raise ChannelManagementError(
            localize(I18N.errors.channel_management.match_channel_caster_roles_unresolved)
        )

    channel_role_ids = {role.id for role in _channel_role_overwrite_targets(channel)}
    caster_roles: list[discord.Role] = []
    for role_id in settings.match_channel_extra_role_ids:
        if role_id not in channel_role_ids:
            continue

        role = channel.guild.get_role(role_id)
        if role is not None:
            caster_roles.append(role)

    if not caster_roles:
        raise ChannelManagementError(
            localize(I18N.errors.channel_management.match_channel_caster_roles_unresolved)
        )

    return " ".join(role.mention for role in caster_roles)
