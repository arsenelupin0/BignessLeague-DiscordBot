from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TYPE_CHECKING

import discord
from discord import app_commands

from bigness_league_bot.application.services.team_profile import (
    TeamProfile,
    TeamProfilePlayer,
    TeamProfileStaffMember,
)
from bigness_league_bot.application.services.team_signing import (
    TeamTechnicalStaffBatch,
    TeamTechnicalStaffMember,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ensure_allowed_member,
)
from bigness_league_bot.infrastructure.discord.team_member_lookup import (
    PLACEHOLDER_MEMBER_NAMES,
    normalize_member_lookup_text,
)
from bigness_league_bot.infrastructure.discord.team_staff_interactive import (
    INTERACTIVE_STAFF_ROLE_LABELS,
    find_selected_team_profile,
    resolve_selected_team_role,
)
from bigness_league_bot.infrastructure.discord.team_staff_roles import (
    normalize_team_staff_role_name,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
    TeamRosterPlayerUpdate,
)
from bigness_league_bot.infrastructure.google.team_sheets.errors import TeamSheetError
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

RosterBlock = Literal["players", "staff"]

_AUTOCOMPLETE_ERRORS = (
    AttributeError,
    CommandUserError,
    RuntimeError,
    TeamSheetError,
    ValueError,
)


@dataclass(frozen=True, slots=True)
class RosterModificationContext:
    team_role: discord.Role
    team_profile: TeamProfile


async def roster_member_autocomplete(
        interaction: discord.Interaction[BignessLeagueBot],
        current: str,
) -> list[app_commands.Choice[str]]:
    guild = interaction.guild
    if guild is None or not isinstance(interaction.user, discord.Member):
        return []

    selected_team = getattr(interaction.namespace, "equipo", None)
    selected_block = getattr(interaction.namespace, "bloque", None)
    if not isinstance(selected_team, (str, int)):
        return []

    team_role = resolve_selected_team_role(guild, selected_team)
    roster_block = parse_roster_block(_choice_value(selected_block))
    if team_role is None or roster_block is None:
        return []

    try:
        ensure_allowed_member(interaction.user)
        repository = GoogleSheetsTeamRepository(interaction.client.settings)
        team_profile = await repository.find_team_profile_for_role(team_role)
    except _AUTOCOMPLETE_ERRORS:
        return []

    choices: list[app_commands.Choice[str]] = []
    for label, value in _iter_roster_member_choices(team_profile, roster_block):
        if current and current.casefold().strip() not in label.casefold():
            continue

        choices.append(app_commands.Choice[str](name=label[:100], value=value))
        if len(choices) >= 25:
            break

    return choices


async def resolve_roster_modification_context(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        guild: discord.Guild,
        equipo: str,
) -> RosterModificationContext:
    team_role = resolve_selected_team_role(guild, equipo)
    if team_role is None:
        raise CommandUserError(
            localize(I18N.errors.team_signing.invalid_interactive_team)
        )

    team_profile = await find_selected_team_profile(
        interaction,
        guild=guild,
        equipo=equipo,
    )
    return RosterModificationContext(
        team_role=team_role,
        team_profile=team_profile,
    )


def parse_roster_block(value: str) -> RosterBlock | None:
    if value == "players":
        return "players"
    if value == "staff":
        return "staff"
    return None


def _choice_value(value: object) -> str:
    if isinstance(value, app_commands.Choice):
        return str(value.value)
    if isinstance(value, str):
        return value
    return ""


def find_player_for_roster_modification(
        team_profile: TeamProfile,
        discord_name: str,
) -> TeamProfilePlayer:
    normalized_target = normalize_member_lookup_text(discord_name)
    for player in team_profile.players:
        if normalize_member_lookup_text(player.discord_name) == normalized_target:
            return player

    raise CommandUserError(
        localize(
            I18N.errors.team_signing.interactive_player_not_found,
            discord_name=discord_name,
            team_name=team_profile.team_name,
        )
    )


def find_staff_members_for_roster_modification(
        team_profile: TeamProfile,
        discord_name: str,
) -> tuple[TeamProfileStaffMember, ...]:
    normalized_target = normalize_member_lookup_text(discord_name)
    staff_members = tuple(
        staff_member
        for staff_member in team_profile.technical_staff
        if normalize_member_lookup_text(staff_member.discord_name) == normalized_target
    )
    if not staff_members:
        raise CommandUserError(
            localize(
                I18N.errors.team_signing.interactive_player_not_found,
                discord_name=discord_name,
                team_name=team_profile.team_name,
            )
        )

    return staff_members


def build_player_roster_update(
        team_profile: TeamProfile,
        *,
        discord_name: str,
        player_name: str,
        tracker_url: str,
        epic_name: str,
        rocket_name: str,
        mmr: str,
) -> TeamRosterPlayerUpdate:
    return TeamRosterPlayerUpdate(
        division_name=team_profile.division_name,
        team_name=team_profile.team_name,
        discord_name=discord_name,
        player_name=player_name.strip(),
        tracker_url=tracker_url.strip(),
        epic_name=epic_name.strip(),
        rocket_name=rocket_name.strip(),
        mmr=mmr.strip(),
    )


def current_staff_role_keys(
        staff_members: tuple[TeamProfileStaffMember, ...],
) -> tuple[str, ...]:
    role_keys: list[str] = []
    for staff_member in staff_members:
        role_key = normalize_team_staff_role_name(staff_member.role_name)
        if role_key is None:
            continue

        role_keys.append(role_key)

    return tuple(role_keys)


def build_staff_roster_modification_batch(
        team_profile: TeamProfile,
        *,
        discord_name: str,
        selected_role_keys: tuple[str, ...],
        epic_name: str,
        rocket_name: str,
) -> TeamTechnicalStaffBatch:
    normalized_selected_role_keys: list[str] = []
    for selected_role_key in selected_role_keys:
        role_key = normalize_team_staff_role_name(selected_role_key)
        if role_key is None or role_key in normalized_selected_role_keys:
            continue
        normalized_selected_role_keys.append(role_key)

    if not normalized_selected_role_keys:
        raise CommandUserError(
            localize(
                I18N.errors.team_signing.unsupported_interactive_staff_role,
                staff_role=", ".join(selected_role_keys),
            )
        )

    members: list[TeamTechnicalStaffMember] = [
        TeamTechnicalStaffMember(
            role_name=INTERACTIVE_STAFF_ROLE_LABELS[role_key],
            discord_name=discord_name,
            epic_name=epic_name.strip(),
            rocket_name=rocket_name.strip(),
        )
        for role_key in normalized_selected_role_keys
    ]
    selected_role_key_set = set(normalized_selected_role_keys)
    for staff_member in find_staff_members_for_roster_modification(
            team_profile,
            discord_name,
    ):
        role_key = normalize_team_staff_role_name(staff_member.role_name)
        if role_key is None or role_key in selected_role_key_set:
            continue

        members.append(
            TeamTechnicalStaffMember(
                role_name=INTERACTIVE_STAFF_ROLE_LABELS[role_key],
                discord_name="",
                epic_name="",
                rocket_name="",
            )
        )

    return TeamTechnicalStaffBatch(
        division_name=team_profile.division_name,
        team_name=team_profile.team_name,
        members=tuple(members),
    )


def _iter_roster_member_choices(
        team_profile: TeamProfile,
        roster_block: RosterBlock,
) -> tuple[tuple[str, str], ...]:
    if roster_block == "players":
        return tuple(
            (_choice_name(player.discord_name, player.player_name), player.discord_name)
            for player in team_profile.players
            if _is_real_member_name(player.discord_name)
        )

    staff_roles_by_member = _collect_staff_roles_by_member(team_profile)
    return tuple(
        (_choice_name(discord_name, ", ".join(role_names)), discord_name)
        for discord_name, role_names in staff_roles_by_member.items()
    )


def _collect_staff_roles_by_member(team_profile: TeamProfile) -> dict[str, tuple[str, ...]]:
    staff_roles_by_lookup: dict[str, list[str]] = {}
    member_names_by_lookup: dict[str, str] = {}
    for staff_member in team_profile.technical_staff:
        if not _is_real_member_name(staff_member.discord_name):
            continue

        lookup_key = normalize_member_lookup_text(staff_member.discord_name)
        member_names_by_lookup.setdefault(lookup_key, staff_member.discord_name)
        staff_roles_by_lookup.setdefault(lookup_key, []).append(staff_member.role_name)

    return {
        member_names_by_lookup[lookup_key]: tuple(role_names)
        for lookup_key, role_names in staff_roles_by_lookup.items()
    }


def _choice_name(label: str, detail: str | None = None) -> str:
    if not detail:
        return label[:100]

    return f"{label} ({detail})"[:100]


def _is_real_member_name(value: str) -> bool:
    return normalize_member_lookup_text(value) not in PLACEHOLDER_MEMBER_NAMES
