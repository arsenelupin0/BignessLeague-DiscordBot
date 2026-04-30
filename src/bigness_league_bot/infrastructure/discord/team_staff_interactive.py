from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.application.services.team_signing import (
    TeamTechnicalStaffBatch,
    TeamTechnicalStaffMember,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ensure_allowed_member,
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.team_staff_roles import (
    PLACEHOLDER_MEMBER_NAMES,
    TEAM_STAFF_ROLE_ANALYST,
    TEAM_STAFF_ROLE_CAPTAIN,
    TEAM_STAFF_ROLE_CEO,
    TEAM_STAFF_ROLE_COACH,
    TEAM_STAFF_ROLE_MANAGER,
    TEAM_STAFF_ROLE_SECOND_MANAGER,
    normalize_team_staff_role_name,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
)
from bigness_league_bot.infrastructure.google.team_sheets.errors import TeamSheetError
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

_AUTOCOMPLETE_ERRORS = (
    AttributeError,
    CommandUserError,
    RuntimeError,
    TeamSheetError,
    ValueError,
)


@dataclass(frozen=True)
class InteractiveStaffRoleOption:
    label: str
    value: str
    current_discord_name: str | None = None


INTERACTIVE_STAFF_ROLE_LABELS: dict[str, str] = {
    TEAM_STAFF_ROLE_CEO: "CEO",
    TEAM_STAFF_ROLE_MANAGER: "Mánager",
    TEAM_STAFF_ROLE_SECOND_MANAGER: "Segundo Mánager",
    TEAM_STAFF_ROLE_COACH: "Coach",
    TEAM_STAFF_ROLE_ANALYST: "Analista",
    TEAM_STAFF_ROLE_CAPTAIN: "Capitán",
}


async def interactive_staff_team_autocomplete(
        interaction: discord.Interaction[BignessLeagueBot],
        current: str,
) -> list[app_commands.Choice[str]]:
    guild = interaction.guild
    if guild is None or not isinstance(interaction.user, discord.Member):
        return []

    try:
        ensure_allowed_member(interaction.user)
        settings = interaction.client.settings
        role_catalog = get_channel_access_role_catalog(
            guild,
            settings.channel_access_range_start_role_id,
            settings.channel_access_range_end_role_id,
        )
        roles_by_name = {role.name.casefold(): role for role in role_catalog.roles}
        repository = GoogleSheetsTeamRepository(settings)
        sheet_metadata = await repository.list_team_sheet_metadata()
    except _AUTOCOMPLETE_ERRORS:
        return []

    choices: list[app_commands.Choice[str]] = []
    for metadata in sorted(
            sheet_metadata,
            key=lambda item: (item.team_name.casefold(), item.worksheet_title.casefold()),
    ):
        if not _matches_current(metadata.team_name, current):
            continue

        role = roles_by_name.get(metadata.team_name.casefold())
        if role is None:
            continue

        choices.append(
            app_commands.Choice[str](
                name=_choice_name(metadata.team_name, metadata.worksheet_title),
                value=str(role.id),
            )
        )
        if len(choices) >= 25:
            break

    return choices


async def interactive_staff_player_autocomplete(
        interaction: discord.Interaction[BignessLeagueBot],
        current: str,
) -> list[app_commands.Choice[str]]:
    guild = interaction.guild
    if guild is None:
        return []

    selected_team = getattr(interaction.namespace, "equipo", None)
    if not isinstance(selected_team, (str, int)):
        return []

    team_role = _resolve_selected_team_role(guild, selected_team)
    if team_role is None:
        return []

    try:
        repository = GoogleSheetsTeamRepository(interaction.client.settings)
        team_profile = await repository.find_team_profile_for_role(team_role)
    except _AUTOCOMPLETE_ERRORS:
        return []

    choices: list[app_commands.Choice[str]] = []
    for player in team_profile.players:
        if not player.discord_name or not _matches_current(player.discord_name, current):
            continue

        choices.append(
            app_commands.Choice[str](
                name=_choice_name(player.discord_name, player.player_name),
                value=player.discord_name,
            )
        )
        if len(choices) >= 25:
            break

    return choices


async def build_interactive_staff_signing_batch(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        guild: discord.Guild,
        equipo: str,
        discord_jugador: str,
        cargos: Sequence[str],
) -> TeamTechnicalStaffBatch:
    team_profile = await _find_selected_team_profile(
        interaction,
        guild=guild,
        equipo=equipo,
    )
    player = next(
        (
            candidate
            for candidate in team_profile.players
            if candidate.discord_name
               and candidate.discord_name.casefold() == discord_jugador.casefold()
        ),
        None,
    )
    if player is None:
        raise CommandUserError(
            localize(
                I18N.errors.team_signing.interactive_player_not_found,
                discord_name=discord_jugador,
                team_name=team_profile.team_name,
            )
        )

    selected_role_keys: list[str] = []
    for cargo in cargos:
        staff_role_key = normalize_team_staff_role_name(cargo)
        if staff_role_key is None:
            raise CommandUserError(
                localize(
                    I18N.errors.team_signing.unsupported_interactive_staff_role,
                    staff_role=cargo,
                )
            )
        if staff_role_key in selected_role_keys:
            continue
        selected_role_keys.append(staff_role_key)

    if not selected_role_keys:
        raise CommandUserError(
            localize(
                I18N.errors.team_signing.unsupported_interactive_staff_role,
                staff_role="",
            )
        )

    members: list[TeamTechnicalStaffMember] = []
    for staff_role_key in selected_role_keys:
        members.append(
            TeamTechnicalStaffMember(
                role_name=INTERACTIVE_STAFF_ROLE_LABELS[staff_role_key],
                discord_name=player.discord_name,
                epic_name="",
                rocket_name="",
            )
        )

    members.extend(
        _collect_staff_clear_members_for_unselected_roles(
            team_profile,
            discord_name=player.discord_name,
            selected_role_keys=selected_role_keys,
        )
    )

    return TeamTechnicalStaffBatch(
        division_name=team_profile.division_name,
        team_name=team_profile.team_name,
        members=tuple(members),
    )


async def collect_available_interactive_staff_roles(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        guild: discord.Guild,
        equipo: str,
) -> tuple[InteractiveStaffRoleOption, ...]:
    team_profile = await _find_selected_team_profile(
        interaction,
        guild=guild,
        equipo=equipo,
    )
    occupied_member_names_by_role_key: dict[str, str] = {}
    for member in team_profile.technical_staff:
        role_key = normalize_team_staff_role_name(member.role_name)
        if role_key is None or not _is_real_member_name(member.discord_name):
            continue
        occupied_member_names_by_role_key[role_key] = member.discord_name

    return tuple(
        InteractiveStaffRoleOption(
            label=(
                _choice_name(label, current_discord_name)
                if (current_discord_name := occupied_member_names_by_role_key.get(role_key))
                else label
            ),
            value=label,
            current_discord_name=current_discord_name,
        )
        for role_key, label in INTERACTIVE_STAFF_ROLE_LABELS.items()
    )


async def _find_selected_team_profile(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        guild: discord.Guild,
        equipo: str,
) -> TeamProfile:
    team_role = _resolve_selected_team_role(guild, equipo)
    if team_role is None:
        raise CommandUserError(
            localize(I18N.errors.team_signing.invalid_interactive_team)
        )

    settings = interaction.client.settings
    role_catalog = get_channel_access_role_catalog(
        guild,
        settings.channel_access_range_start_role_id,
        settings.channel_access_range_end_role_id,
    )
    if team_role.id not in {role.id for role in role_catalog.roles}:
        raise CommandUserError(
            localize(
                I18N.errors.match_channel_creation.team_role_out_of_range,
                role_name=team_role.name,
                range_start=role_catalog.range_start.name,
                range_end=role_catalog.range_end.name,
            )
        )

    repository = GoogleSheetsTeamRepository(settings)
    return await repository.find_team_profile_for_role(team_role)


def _choice_name(label: str, detail: str | None = None) -> str:
    if not detail:
        return label[:100]

    return f"{label} ({detail})"[:100]


def _resolve_selected_team_role(
        guild: discord.Guild,
        raw_role_id: str | int | None,
) -> discord.Role | None:
    if raw_role_id is None:
        return None

    try:
        role_id = int(raw_role_id)
    except ValueError:
        return None

    return guild.get_role(role_id)


def _matches_current(label: str, current: str) -> bool:
    normalized_current = current.casefold().strip()
    return not normalized_current or normalized_current in label.casefold()


def _is_real_member_name(value: str) -> bool:
    normalized_value = " ".join(value.split()).strip()
    if normalized_value.startswith("@"):
        normalized_value = normalized_value[1:]

    return normalized_value.casefold() not in PLACEHOLDER_MEMBER_NAMES


def _collect_staff_clear_members_for_unselected_roles(
        team_profile: TeamProfile,
        *,
        discord_name: str,
        selected_role_keys: Sequence[str],
) -> tuple[TeamTechnicalStaffMember, ...]:
    normalized_target_name = _normalize_member_name(discord_name)
    if not normalized_target_name:
        return ()

    selected_role_key_set = set(selected_role_keys)
    clear_members: list[TeamTechnicalStaffMember] = []
    for staff_member in team_profile.technical_staff:
        if _normalize_member_name(staff_member.discord_name) != normalized_target_name:
            continue

        staff_role_key = normalize_team_staff_role_name(staff_member.role_name)
        if staff_role_key is None or staff_role_key in selected_role_key_set:
            continue

        clear_members.append(
            TeamTechnicalStaffMember(
                role_name=INTERACTIVE_STAFF_ROLE_LABELS[staff_role_key],
                discord_name="",
                epic_name="",
                rocket_name="",
            )
        )

    return tuple(clear_members)


def _normalize_member_name(value: str | None) -> str:
    if value is None:
        return ""

    normalized_value = " ".join(value.split()).strip()
    if normalized_value.startswith("@"):
        normalized_value = normalized_value[1:]

    return normalized_value.casefold()
