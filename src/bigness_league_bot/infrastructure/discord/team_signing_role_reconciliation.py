from __future__ import annotations

from typing import Any

import discord

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.discord.channel_management import get_channel_access_role_catalog
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    build_member_lookup_keys,
    normalize_member_lookup_text,
    remove_roles_from_member_by_name,
    resolve_optional_team_staff_roles,
    resolve_participant_role,
    resolve_player_role,
    resolve_team_role_by_name,
)
from bigness_league_bot.infrastructure.discord.team_signing_messages import (
    format_team_role_removal_message,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    TeamMemberSheetAffiliation,
    TeamSigningRemovalResult,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N


async def remove_discord_roles_after_signing_removal(
        interaction: discord.Interaction[Any],
        *,
        discord_name: str,
        result: TeamSigningRemovalResult,
) -> str | None:
    guild = interaction.guild
    if guild is None:
        return None

    settings = interaction.client.settings
    role_catalog = get_channel_access_role_catalog(
        guild,
        settings.channel_access_range_start_role_id,
        settings.channel_access_range_end_role_id,
    )
    localizer = interaction.client.localizer
    locale = interaction.locale
    try:
        team_role = resolve_team_role_by_name(result.team_name, role_catalog)
        participant_role = resolve_participant_role(
            guild,
            settings.participant_role_id,
        )
        player_role = resolve_player_role(
            guild,
            settings.player_role_id,
        )
        has_team_affiliation_after = (
                result.is_player_present_after
                or bool(result.remaining_staff_role_names)
        )
        roles_to_remove: list[discord.Role] = []
        if result.removed_player_name is not None:
            roles_to_remove.append(player_role)

        staff_roles = resolve_optional_team_staff_roles(
            guild,
            ceo_role_id=settings.staff_ceo_role_id,
            analyst_role_id=settings.staff_analyst_role_id,
            coach_role_id=settings.staff_coach_role_id,
            manager_role_id=settings.staff_manager_role_id,
            second_manager_role_id=settings.staff_second_manager_role_id,
            captain_role_id=settings.staff_captain_role_id,
            staff_role_names=result.removed_staff_role_names,
        )
        roles_to_remove.extend(staff_roles)
        if not has_team_affiliation_after:
            roles_to_remove.extend((participant_role, team_role))

        removal_summary = await remove_roles_from_member_by_name(
            guild,
            actor=interaction.user,
            member_name=discord_name,
            roles_to_remove=roles_to_remove,
        )
    except (CommandUserError, discord.Forbidden, discord.HTTPException) as exc:
        return localizer.translate(
            I18N.actions.team_signing.role_removal_failed,
            locale=locale,
            details=str(exc),
        )

    return format_team_role_removal_message(
        localizer=localizer,
        locale=locale,
        discord_name=discord_name,
        removal_summary=removal_summary,
    )


async def reconcile_team_role_assignment(
        *,
        bot: Any,
        guild: discord.Guild,
        actor: discord.Member,
        team_role: discord.Role,
        participant_role: discord.Role,
        player_role: discord.Role,
        team_profile: Any,
) -> None:
    current_team_members = await load_current_team_members(
        guild,
        team_role=team_role,
    )
    if not current_team_members:
        return

    affiliations_by_lookup = build_team_profile_affiliations(team_profile)
    configured_staff_roles = resolve_configured_staff_roles(bot.settings, guild)
    for member in current_team_members:
        member_affiliation = resolve_member_affiliation(
            member,
            affiliations_by_lookup=affiliations_by_lookup,
        )
        desired_staff_roles = ()
        if member_affiliation is not None and member_affiliation.staff_role_names:
            desired_staff_roles = resolve_optional_team_staff_roles(
                guild,
                ceo_role_id=bot.settings.staff_ceo_role_id,
                analyst_role_id=bot.settings.staff_analyst_role_id,
                coach_role_id=bot.settings.staff_coach_role_id,
                manager_role_id=bot.settings.staff_manager_role_id,
                second_manager_role_id=bot.settings.staff_second_manager_role_id,
                captain_role_id=bot.settings.staff_captain_role_id,
                staff_role_names=member_affiliation.staff_role_names,
            )

        roles_to_remove: dict[int, discord.Role] = {}
        if member_affiliation is None and team_role in member.roles:
            roles_to_remove[team_role.id] = team_role

        if member_affiliation is None:
            if participant_role in member.roles:
                roles_to_remove[participant_role.id] = participant_role
            if player_role in member.roles:
                roles_to_remove[player_role.id] = player_role
        elif not member_affiliation.is_player:
            if player_role in member.roles:
                roles_to_remove[player_role.id] = player_role

        desired_staff_role_ids = {role.id for role in desired_staff_roles}
        for configured_staff_role in configured_staff_roles:
            if (
                    configured_staff_role in member.roles
                    and configured_staff_role.id not in desired_staff_role_ids
            ):
                roles_to_remove[configured_staff_role.id] = configured_staff_role

        if not roles_to_remove:
            continue

        await member.remove_roles(
            *roles_to_remove.values(),
            reason=(
                f"{actor} ({actor.id}) sincronizó completamente el equipo "
                f"{team_role.name} según Google Sheets para {member} ({member.id})"
            ),
        )


async def load_current_team_members(
        guild: discord.Guild,
        *,
        team_role: discord.Role,
) -> tuple[discord.Member, ...]:
    try:
        members = tuple([
            member
            async for member in guild.fetch_members(limit=None)
            if not member.bot and team_role in member.roles
        ])
    except discord.HTTPException:
        members = tuple(
            member
            for member in guild.members
            if not member.bot and team_role in member.roles
        )

    return members


def resolve_configured_staff_roles(
        settings: Any,
        guild: discord.Guild,
) -> tuple[discord.Role, ...]:
    configured_roles: dict[int, discord.Role] = {}
    for role_id in (
            settings.staff_ceo_role_id,
            settings.staff_analyst_role_id,
            settings.staff_coach_role_id,
            settings.staff_manager_role_id,
            settings.staff_second_manager_role_id,
            settings.staff_captain_role_id,
    ):
        role = guild.get_role(role_id)
        if role is not None:
            configured_roles[role.id] = role

    return tuple(configured_roles.values())


def resolve_member_affiliation(
        member: discord.Member,
        *,
        affiliations_by_lookup: dict[str, TeamMemberSheetAffiliation],
) -> TeamMemberSheetAffiliation | None:
    matched_affiliations: list[TeamMemberSheetAffiliation] = []
    for lookup_key in build_member_lookup_keys(member):
        affiliation = affiliations_by_lookup.get(lookup_key)
        if affiliation is not None:
            matched_affiliations.append(affiliation)

    if not matched_affiliations:
        return None

    merged_staff_role_names = tuple(
        sorted(
            {
                role_name
                for affiliation in matched_affiliations
                for role_name in affiliation.staff_role_names
            }
        )
    )
    return TeamMemberSheetAffiliation(
        discord_name=matched_affiliations[0].discord_name,
        is_player=any(affiliation.is_player for affiliation in matched_affiliations),
        staff_role_names=merged_staff_role_names,
    )


def build_team_profile_affiliations(
        team_profile: Any,
) -> dict[str, TeamMemberSheetAffiliation]:
    collected_affiliations: dict[str, TeamMemberSheetAffiliation] = {}

    for player in team_profile.players:
        normalized_discord_name = normalize_member_lookup_text(player.discord_name)
        if normalized_discord_name in {"", "-"}:
            continue

        existing_affiliation = collected_affiliations.get(normalized_discord_name)
        collected_affiliations[normalized_discord_name] = TeamMemberSheetAffiliation(
            discord_name=player.discord_name,
            is_player=True,
            staff_role_names=existing_affiliation.staff_role_names
            if existing_affiliation is not None
            else (),
        )

    for staff_member in team_profile.technical_staff:
        normalized_discord_name = normalize_member_lookup_text(staff_member.discord_name)
        if normalized_discord_name in {"", "-"}:
            continue

        existing_affiliation = collected_affiliations.get(normalized_discord_name)
        staff_role_names = set(
            existing_affiliation.staff_role_names
            if existing_affiliation is not None
            else ()
        )
        staff_role_names.add(staff_member.role_name)
        collected_affiliations[normalized_discord_name] = TeamMemberSheetAffiliation(
            discord_name=staff_member.discord_name,
            is_player=existing_affiliation.is_player
            if existing_affiliation is not None
            else False,
            staff_role_names=tuple(sorted(staff_role_names)),
        )

    return collected_affiliations
