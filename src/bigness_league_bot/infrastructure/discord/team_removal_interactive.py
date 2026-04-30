from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.team_member_lookup import (
    PLACEHOLDER_MEMBER_NAMES,
    normalize_member_lookup_text,
)
from bigness_league_bot.infrastructure.discord.team_signing_removal_workflow import (
    TeamSigningRemovalScope,
)
from bigness_league_bot.infrastructure.discord.team_staff_interactive import (
    find_selected_team_profile,
    resolve_selected_team_role,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


@dataclass(frozen=True, slots=True)
class InteractiveRemovalMemberOption:
    label: str
    value: str
    description: str | None = None


async def resolve_interactive_removal_context(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        guild: discord.Guild,
        equipo: str,
) -> tuple[discord.Role, TeamProfile]:
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
    return team_role, team_profile


def collect_interactive_removal_member_options(
        team_profile: TeamProfile,
        *,
        removal_scope: TeamSigningRemovalScope,
) -> tuple[InteractiveRemovalMemberOption, ...]:
    if removal_scope == "player":
        return _collect_player_options(team_profile)
    if removal_scope == "staff":
        return _collect_staff_options(team_profile)
    return _collect_full_member_options(team_profile)


def _collect_player_options(
        team_profile: TeamProfile,
) -> tuple[InteractiveRemovalMemberOption, ...]:
    return tuple(
        InteractiveRemovalMemberOption(
            label=_choice_name(player.discord_name, player.player_name),
            value=player.discord_name,
        )
        for player in team_profile.players
        if _is_real_member_name(player.discord_name)
    )


def _collect_staff_options(
        team_profile: TeamProfile,
) -> tuple[InteractiveRemovalMemberOption, ...]:
    roles_by_member = _collect_staff_roles_by_member(team_profile)
    return tuple(
        InteractiveRemovalMemberOption(
            label=_choice_name(discord_name, ", ".join(role_names)),
            value=discord_name,
        )
        for discord_name, role_names in roles_by_member.items()
    )


def _collect_full_member_options(
        team_profile: TeamProfile,
) -> tuple[InteractiveRemovalMemberOption, ...]:
    players_by_lookup = {
        normalize_member_lookup_text(player.discord_name): player
        for player in team_profile.players
        if _is_real_member_name(player.discord_name)
    }
    staff_roles_by_member = _collect_staff_roles_by_member(team_profile)
    options_by_lookup: dict[str, InteractiveRemovalMemberOption] = {}
    for lookup_key, player in players_by_lookup.items():
        options_by_lookup[lookup_key] = InteractiveRemovalMemberOption(
            label=_choice_name(player.discord_name, player.player_name),
            value=player.discord_name,
        )

    for discord_name, role_names in staff_roles_by_member.items():
        lookup_key = normalize_member_lookup_text(discord_name)
        if lookup_key in options_by_lookup:
            continue

        options_by_lookup[lookup_key] = InteractiveRemovalMemberOption(
            label=_choice_name(discord_name, ", ".join(role_names)),
            value=discord_name,
        )

    return tuple(options_by_lookup.values())


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
