from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import discord

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ChannelAccessRoleCatalog,
    user_audit_label,
)
from bigness_league_bot.infrastructure.discord.team_member_lookup import (
    PLACEHOLDER_MEMBER_NAMES,
    index_members_by_lookup_keys,
    load_guild_members,
    normalize_member_lookup_text,
    resolve_members_for_name,
)
from bigness_league_bot.infrastructure.discord.team_staff_roles import (
    filter_team_staff_role_names_for_player_status,
    normalize_team_staff_role_name,
)


@dataclass(frozen=True, slots=True)
class TeamProfileAffiliation:
    discord_name: str
    is_player: bool
    staff_role_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TeamRoleBulkSyncSummary:
    processed_team_count: int
    assigned_member_count: int
    removed_member_count: int
    assigned_role_count: int
    removed_role_count: int
    already_configured_member_count: int
    unresolved_names: tuple[str, ...]
    ambiguous_names: tuple[str, ...]
    missing_team_role_names: tuple[str, ...]


async def sync_all_team_roles_from_profiles(
        guild: discord.Guild,
        *,
        actor: discord.abc.User,
        role_catalog: ChannelAccessRoleCatalog,
        participant_role: discord.Role,
        player_role: discord.Role,
        staff_roles_by_key: dict[str, discord.Role],
        team_profiles: Iterable[TeamProfile],
) -> TeamRoleBulkSyncSummary:
    members = await load_guild_members(guild)
    members_by_lookup = index_members_by_lookup_keys(members)
    team_roles_by_name = {
        normalize_member_lookup_text(role.name): role
        for role in role_catalog.roles
    }
    desired_roles_by_member_id: dict[int, dict[int, discord.Role]] = {}
    unresolved_names: list[str] = []
    ambiguous_names: list[str] = []
    missing_team_role_names: list[str] = []
    processed_team_count = 0

    for team_profile in team_profiles:
        team_role = team_roles_by_name.get(
            normalize_member_lookup_text(team_profile.team_name)
        )
        if team_role is None:
            missing_team_role_names.append(team_profile.team_name)
            continue

        processed_team_count += 1
        affiliations_by_lookup = build_team_profile_affiliations(team_profile)
        for lookup_key, affiliation in affiliations_by_lookup.items():
            if lookup_key in PLACEHOLDER_MEMBER_NAMES:
                continue

            matches = resolve_members_for_name(
                affiliation.discord_name,
                members_by_lookup,
                guild,
            )
            if not matches:
                unresolved_names.append(
                    f"{team_profile.team_name}: {affiliation.discord_name}"
                )
                continue

            if len(matches) > 1:
                ambiguous_names.append(
                    f"{team_profile.team_name}: {affiliation.discord_name}"
                )
                continue

            member = matches[0]
            desired_roles = desired_roles_by_member_id.setdefault(member.id, {})
            _add_desired_role(desired_roles, participant_role)
            _add_desired_role(desired_roles, team_role)
            if affiliation.is_player:
                _add_desired_role(desired_roles, player_role)

            for role_name in filter_team_staff_role_names_for_player_status(
                    affiliation.staff_role_names,
                    is_player_in_same_team=affiliation.is_player,
            ):
                role_key = normalize_team_staff_role_name(role_name)
                if role_key is None:
                    continue

                staff_role = staff_roles_by_key.get(role_key)
                if staff_role is not None:
                    _add_desired_role(desired_roles, staff_role)

    managed_role_ids = {
        participant_role.id,
        player_role.id,
        *(role.id for role in staff_roles_by_key.values()),
        *(role.id for role in role_catalog.roles),
    }
    assigned_member_count = 0
    removed_member_count = 0
    assigned_role_count = 0
    removed_role_count = 0
    already_configured_member_count = 0

    for member in members:
        if member.bot:
            continue

        desired_roles = desired_roles_by_member_id.get(member.id, {})
        current_managed_roles = {
            role.id: role
            for role in member.roles
            if role.id in managed_role_ids
        }
        roles_to_add = tuple(
            role
            for role_id, role in desired_roles.items()
            if role_id not in current_managed_roles
        )
        roles_to_remove = tuple(
            role
            for role_id, role in current_managed_roles.items()
            if role_id not in desired_roles
        )

        if roles_to_add:
            await member.add_roles(
                *roles_to_add,
                reason=(
                    f"{user_audit_label(actor)} sincronizó masivamente roles "
                    f"según Google Sheets para {user_audit_label(member)}"
                ),
            )
            assigned_member_count += 1
            assigned_role_count += len(roles_to_add)

        if roles_to_remove:
            await member.remove_roles(
                *roles_to_remove,
                reason=(
                    f"{user_audit_label(actor)} sincronizó masivamente roles "
                    f"según Google Sheets para {user_audit_label(member)}"
                ),
            )
            removed_member_count += 1
            removed_role_count += len(roles_to_remove)

        if member.id in desired_roles_by_member_id and not roles_to_add and not roles_to_remove:
            already_configured_member_count += 1

    return TeamRoleBulkSyncSummary(
        processed_team_count=processed_team_count,
        assigned_member_count=assigned_member_count,
        removed_member_count=removed_member_count,
        assigned_role_count=assigned_role_count,
        removed_role_count=removed_role_count,
        already_configured_member_count=already_configured_member_count,
        unresolved_names=tuple(unresolved_names),
        ambiguous_names=tuple(ambiguous_names),
        missing_team_role_names=tuple(missing_team_role_names),
    )


def _add_desired_role(
        desired_roles: dict[int, discord.Role],
        role: discord.Role,
) -> None:
    desired_roles[role.id] = role


def build_team_profile_affiliations(
        team_profile: TeamProfile,
) -> dict[str, TeamProfileAffiliation]:
    collected_affiliations: dict[str, TeamProfileAffiliation] = {}

    for player in team_profile.players:
        normalized_discord_name = normalize_member_lookup_text(player.discord_name)
        if normalized_discord_name in PLACEHOLDER_MEMBER_NAMES:
            continue

        existing_affiliation = collected_affiliations.get(normalized_discord_name)
        collected_affiliations[normalized_discord_name] = TeamProfileAffiliation(
            discord_name=player.discord_name,
            is_player=True,
            staff_role_names=(
                existing_affiliation.staff_role_names
                if existing_affiliation is not None
                else ()
            ),
        )

    for staff_member in team_profile.technical_staff:
        normalized_discord_name = normalize_member_lookup_text(staff_member.discord_name)
        if normalized_discord_name in PLACEHOLDER_MEMBER_NAMES:
            continue

        existing_affiliation = collected_affiliations.get(normalized_discord_name)
        staff_role_names = set(
            existing_affiliation.staff_role_names
            if existing_affiliation is not None
            else ()
        )
        staff_role_names.add(staff_member.role_name)
        collected_affiliations[normalized_discord_name] = TeamProfileAffiliation(
            discord_name=staff_member.discord_name,
            is_player=(
                existing_affiliation.is_player
                if existing_affiliation is not None
                else False
            ),
            staff_role_names=tuple(sorted(staff_role_names)),
        )

    return collected_affiliations
