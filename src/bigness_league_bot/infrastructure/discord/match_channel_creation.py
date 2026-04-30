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

from bigness_league_bot.application.services.channel_closure import PROTECTED_ROLE_NAMES
from bigness_league_bot.application.services.match_channel_creation import (
    MatchChannelDivision,
    MatchChannelSpecification,
    build_match_start_at,
)
from bigness_league_bot.core.localization import LocalizedText, localize
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ChannelAccessRoleCatalog,
    ChannelManagementError,
    get_channel_access_role_catalog,
    get_protected_roles,
)
from bigness_league_bot.infrastructure.discord.channel_management import (
    OverwriteTarget,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

LOGGER = logging.getLogger(__name__)


class MatchChannelAlreadyExistsError(ChannelManagementError):
    """Raised when the target channel name already exists in the destination category."""


class InvalidMatchTeamRoleError(ChannelManagementError):
    """Raised when a selected team role cannot be used for a match channel."""


class MatchChannelCategoryNotFoundError(ChannelManagementError):
    """Raised when the configured destination category cannot be resolved."""


class InvalidMatchScheduleError(ChannelManagementError):
    """Raised when the match date or time input is invalid."""


@dataclass(frozen=True, slots=True)
class MatchChannelCreationResult:
    channel: discord.TextChannel
    summary: LocalizedText


def _set_text_permissions(
        overwrite: discord.PermissionOverwrite,
        *,
        view_channel: bool,
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


def _build_match_channel_overwrites(
        guild: discord.Guild,
        team_roles: tuple[discord.Role, discord.Role],
) -> dict[OverwriteTarget, discord.PermissionOverwrite]:
    protected_roles = get_protected_roles(guild)
    overwrites: dict[OverwriteTarget, discord.PermissionOverwrite] = {
        guild.default_role: _set_text_permissions(
            discord.PermissionOverwrite(),
            view_channel=False,
            can_write=False,
        )
    }

    for role in (*protected_roles.as_tuple, *team_roles):
        overwrites[role] = _set_text_permissions(
            discord.PermissionOverwrite(),
            view_channel=True,
            can_write=True,
        )

    return overwrites


def _ensure_match_channel_absent(
        category: discord.CategoryChannel,
        specification: MatchChannelSpecification,
) -> None:
    channel_name = specification.channel_name
    candidate_names = {*specification.legacy_channel_names, channel_name}
    if any(channel.name in candidate_names for channel in category.channels):
        raise MatchChannelAlreadyExistsError(
            localize(
                I18N.errors.match_channel_creation.channel_already_exists,
                channel_name=channel_name,
            )
        )


def _validate_team_role(
        guild: discord.Guild,
        role: discord.Role,
        *,
        role_catalog: ChannelAccessRoleCatalog,
) -> None:
    if role.guild.id != guild.id:
        raise InvalidMatchTeamRoleError(
            localize(
                I18N.errors.channel_management.invalid_role_not_in_guild,
                role_name=role.name,
            )
        )

    if role == guild.default_role:
        raise InvalidMatchTeamRoleError(
            localize(I18N.errors.channel_management.invalid_role_everyone)
        )

    protected_role_names = {role_name.casefold() for role_name in PROTECTED_ROLE_NAMES}
    if role.name.casefold() in protected_role_names:
        raise InvalidMatchTeamRoleError(
            localize(
                I18N.errors.match_channel_creation.invalid_team_role,
                role_name=role.name,
            )
        )

    allowed_role_ids = {catalog_role.id for catalog_role in role_catalog.roles}
    if role.id not in allowed_role_ids:
        raise InvalidMatchTeamRoleError(
            localize(
                I18N.errors.match_channel_creation.team_role_out_of_range,
                role_name=role.name,
                range_start=role_catalog.range_start.name,
                range_end=role_catalog.range_end.name,
            )
        )


def validate_match_team_roles(
        guild: discord.Guild,
        *,
        team_one: discord.Role,
        team_two: discord.Role,
        range_start_role_id: int,
        range_end_role_id: int,
) -> tuple[discord.Role, discord.Role]:
    if team_one.id == team_two.id:
        raise InvalidMatchTeamRoleError(
            localize(
                I18N.errors.match_channel_creation.same_team_roles,
                role_name=team_one.name,
            )
        )

    role_catalog = get_channel_access_role_catalog(
        guild,
        range_start_role_id,
        range_end_role_id,
    )
    _validate_team_role(guild, team_one, role_catalog=role_catalog)
    _validate_team_role(guild, team_two, role_catalog=role_catalog)
    return team_one, team_two


def resolve_match_channel_category(
        guild: discord.Guild,
        *,
        division: MatchChannelDivision,
        gold_division_category_id: int,
        silver_division_category_id: int,
) -> discord.CategoryChannel:
    if division is MatchChannelDivision.GOLD:
        category_id = gold_division_category_id
    else:
        category_id = silver_division_category_id

    category = guild.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        raise MatchChannelCategoryNotFoundError(
            localize(
                I18N.errors.match_channel_creation.category_missing,
                category_id=category_id,
            )
        )

    return category


def build_match_channel_specification(
        *,
        jornada: int,
        partido: int,
        courtesy_minutes: int,
        date_value: str,
        time_value: str,
        best_of: int,
        timezone_name: str,
) -> MatchChannelSpecification:
    try:
        start_at = build_match_start_at(
            date_value=date_value,
            time_value=time_value,
            timezone_name=timezone_name,
        )
    except ValueError as exc:
        error_code = exc.args[0] if exc.args else ""
        if error_code == "invalid_date":
            raise InvalidMatchScheduleError(
                localize(I18N.errors.match_channel_creation.invalid_date_format)
            ) from exc

        if error_code == "invalid_time":
            raise InvalidMatchScheduleError(
                localize(I18N.errors.match_channel_creation.invalid_time_format)
            ) from exc

        raise

    return MatchChannelSpecification(
        jornada=jornada,
        partido=partido,
        courtesy_minutes=courtesy_minutes,
        start_at=start_at,
        best_of=best_of,
    )


async def create_match_channel(
        *,
        guild: discord.Guild,
        actor: discord.Member,
        category: discord.CategoryChannel,
        specification: MatchChannelSpecification,
        team_one: discord.Role,
        team_two: discord.Role,
) -> MatchChannelCreationResult:
    _ensure_match_channel_absent(category, specification)
    overwrites = _build_match_channel_overwrites(guild, (team_one, team_two))
    created_channel = await guild.create_text_channel(
        specification.channel_name,
        category=category,
        overwrites=overwrites,
        reason=(
            f"{actor} ({actor.id}) ejecutó /canal_de_jornada "
            f"jornada={specification.jornada} partido={specification.partido} "
            f"equipo_1={team_one.id} equipo_2={team_two.id} "
            f"categoría={category.id}"
        ),
    )
    LOGGER.info(
        "MATCH_CHANNEL_CREATED channel=%s(%s) actor=%s(%s) jornada=%s partido=%s team_one=%s(%s) team_two=%s(%s)",
        created_channel.name,
        created_channel.id,
        actor,
        actor.id,
        specification.jornada,
        specification.partido,
        team_one.name,
        team_one.id,
        team_two.name,
        team_two.id,
    )
    return MatchChannelCreationResult(
        channel=created_channel,
        summary=localize(
            I18N.actions.match_channel_creation.created_summary,
            channel=created_channel.mention,
            category=category.name,
            jornada=specification.jornada,
            partido=specification.partido,
            team_one=team_one.mention,
            team_two=team_two.mention,
        ),
    )
