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
from typing import TypeAlias

import discord

from bigness_league_bot.application.services.channel_closure import PROTECTED_ROLE_NAMES
from bigness_league_bot.application.services.match_channel_creation import (
    FINAL_FOUR_SEMIFINAL_MAX,
    FINAL_FOUR_SEMIFINAL_MIN,
    FinalFourMatchChannelSpecification,
    MatchChannelDivision,
    MatchChannelSpecification,
    PromotionRelegationMatchChannelSpecification,
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


MatchChannelSpecificationLike: TypeAlias = (
        MatchChannelSpecification
        | FinalFourMatchChannelSpecification
        | PromotionRelegationMatchChannelSpecification
)


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
        extra_roles: tuple[discord.Role, ...] = (),
) -> dict[OverwriteTarget, discord.PermissionOverwrite]:
    protected_roles = get_protected_roles(guild)
    overwrites: dict[OverwriteTarget, discord.PermissionOverwrite] = {
        guild.default_role: _set_text_permissions(
            discord.PermissionOverwrite(),
            view_channel=False,
            can_write=False,
        )
    }

    for role in (*protected_roles.as_tuple, *team_roles, *extra_roles):
        overwrites[role] = _set_text_permissions(
            discord.PermissionOverwrite(),
            view_channel=True,
            can_write=True,
        )

    return overwrites


def _resolve_extra_roles(
        guild: discord.Guild,
        role_ids: tuple[int, ...],
) -> tuple[discord.Role, ...]:
    extra_roles: dict[int, discord.Role] = {}
    missing_role_ids: list[int] = []
    for role_id in role_ids:
        role = guild.get_role(role_id)
        if role is None:
            missing_role_ids.append(role_id)
            continue

        extra_roles[role.id] = role

    if missing_role_ids:
        raise ChannelManagementError(
            localize(
                I18N.errors.channel_management.invalid_role_not_in_guild,
                role_name=", ".join(str(role_id) for role_id in missing_role_ids),
            )
        )

    return tuple(extra_roles.values())


def _ensure_match_channel_absent(
        category: discord.CategoryChannel,
        specification: MatchChannelSpecificationLike,
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


def build_final_four_match_channel_specification(
        *,
        semifinal: int | None,
        courtesy_minutes: int,
        date_value: str,
        time_value: str,
        best_of: int,
        timezone_name: str,
) -> FinalFourMatchChannelSpecification:
    if (
            semifinal is not None
            and (semifinal < FINAL_FOUR_SEMIFINAL_MIN or semifinal > FINAL_FOUR_SEMIFINAL_MAX)
    ):
        raise ValueError("semifinal fuera del rango soportado.")

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

    return FinalFourMatchChannelSpecification(
        semifinal=semifinal,
        courtesy_minutes=courtesy_minutes,
        start_at=start_at,
        best_of=best_of,
    )


def build_promotion_relegation_match_channel_specification(
        *,
        courtesy_minutes: int,
        date_value: str,
        time_value: str,
        best_of: int,
        timezone_name: str,
) -> PromotionRelegationMatchChannelSpecification:
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

    return PromotionRelegationMatchChannelSpecification(
        courtesy_minutes=courtesy_minutes,
        start_at=start_at,
        best_of=best_of,
    )


async def create_match_channel(
        *,
        guild: discord.Guild,
        actor: discord.Member,
        category: discord.CategoryChannel,
        specification: MatchChannelSpecificationLike,
        team_one: discord.Role,
        team_two: discord.Role,
        extra_role_ids: tuple[int, ...] = (),
        command_name: str = "canal_de_jornada",
) -> MatchChannelCreationResult:
    _ensure_match_channel_absent(category, specification)
    extra_roles = _resolve_extra_roles(guild, extra_role_ids)
    extra_role_ids_label = ",".join(str(role_id) for role_id in extra_role_ids) or "ninguno"
    overwrites = _build_match_channel_overwrites(
        guild,
        (team_one, team_two),
        extra_roles,
    )
    context_label = _audit_specification_label(specification)
    created_channel = await guild.create_text_channel(
        specification.channel_name,
        category=category,
        overwrites=overwrites,
        reason=(
            f"{actor} ({actor.id}) ejecuto /{command_name} "
            f"{context_label} "
            f"equipo_1={team_one.id} equipo_2={team_two.id} "
            f"roles_extra={extra_role_ids_label} "
            f"categoría={category.id}"
        ),
    )
    LOGGER.info(
        "MATCH_CHANNEL_CREATED channel=%s(%s) actor=%s(%s) context=%s team_one=%s(%s) team_two=%s(%s)",
        created_channel.name,
        created_channel.id,
        actor,
        actor.id,
        context_label,
        team_one.name,
        team_one.id,
        team_two.name,
        team_two.id,
    )
    return MatchChannelCreationResult(
        channel=created_channel,
        summary=_created_summary(
            specification,
            channel=created_channel,
            category=category,
            team_one=team_one,
            team_two=team_two,
        ),
    )


def _created_summary(
        specification: MatchChannelSpecificationLike,
        *,
        channel: discord.TextChannel,
        category: discord.CategoryChannel,
        team_one: discord.Role,
        team_two: discord.Role,
) -> LocalizedText:
    if isinstance(
            specification,
            (FinalFourMatchChannelSpecification, PromotionRelegationMatchChannelSpecification),
    ):
        return localize(
            I18N.actions.match_channel_creation.created_special_summary,
            channel=channel.mention,
            category=category.name,
            round_label=specification.round_label,
            team_one=team_one.mention,
            team_two=team_two.mention,
        )

    return localize(
        I18N.actions.match_channel_creation.created_summary,
        channel=channel.mention,
        category=category.name,
        jornada=specification.jornada,
        partido=specification.partido,
        team_one=team_one.mention,
        team_two=team_two.mention,
    )


def _audit_specification_label(specification: MatchChannelSpecificationLike) -> str:
    if isinstance(specification, FinalFourMatchChannelSpecification):
        if specification.semifinal is None:
            return "final_four=final"

        return f"final_four=semifinal semifinal={specification.semifinal}"

    if isinstance(specification, PromotionRelegationMatchChannelSpecification):
        return "promotion_relegation=true"

    return f"jornada={specification.jornada} partido={specification.partido}"
