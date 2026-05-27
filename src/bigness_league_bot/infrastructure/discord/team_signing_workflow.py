from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.tickets import current_utc_timestamp
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.pending_team_signing_assignments import (
    PendingTeamSigningAssignmentStore,
    create_pending_team_signing_assignment,
)
from bigness_league_bot.infrastructure.discord.team_member_lookup import (
    normalize_member_lookup_text,
)
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    TeamStaffRoleEntry,
    collect_team_profile_staff_role_entries,
    assign_team_roles_by_names,
    collect_team_profile_player_names,
    resolve_participant_role,
    resolve_player_role,
    resolve_team_role_by_name,
    sync_team_staff_roles_by_names,
)
from bigness_league_bot.infrastructure.discord.team_role_provisioning import (
    resolve_or_create_team_role,
)
from bigness_league_bot.infrastructure.discord.team_signing_imports import (
    resolve_team_signing_import_target,
)
from bigness_league_bot.infrastructure.discord.team_signing_messages import (
    build_team_signing_import_completed_message,
    build_team_signing_removal_visibility_message,
    build_team_signing_visibility_message,
    collect_technical_staff_role_entries,
)
from bigness_league_bot.infrastructure.discord.team_signing_visibility import (
    collect_team_signing_visibility_links,
)
from bigness_league_bot.infrastructure.discord.team_staff_roles import (
    collect_staff_role_entries_by_member,
    normalize_team_staff_role_name,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
)

if TYPE_CHECKING:
    from bigness_league_bot.application.services.team_signing import (
        TeamSigningBatch,
        TeamTechnicalStaffBatch,
    )
    from bigness_league_bot.application.services.team_profile import TeamProfile
    from bigness_league_bot.core.settings import Settings
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot
    from bigness_league_bot.infrastructure.discord.team_role_assignment import (
        TeamRoleAssignmentSummary,
        TeamStaffRoleSyncSummary,
    )


async def handle_team_signing_import(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        bot: BignessLeagueBot,
        guild: discord.Guild,
        signing_batch: TeamSigningBatch | None,
        technical_staff_batch: TeamTechnicalStaffBatch | None,
        require_new_team_block: bool,
        publish_announcements: bool = True,
) -> None:
    settings = interaction.client.settings
    role_catalog = get_channel_access_role_catalog(
        guild,
        settings.channel_access_range_start_role_id,
        settings.channel_access_range_end_role_id,
    )
    division_name, team_name = resolve_team_signing_import_target(
        signing_batch=signing_batch,
        technical_staff_batch=technical_staff_batch,
    )

    repository = GoogleSheetsTeamRepository(interaction.client.settings)
    participant_role = resolve_participant_role(guild, settings.participant_role_id)
    announcement_since = monotonic()
    player_result = None
    assignment_summary = None
    team_role_created = False
    team_role: discord.Role | None = None
    if signing_batch is None:
        team_role = resolve_team_role_by_name(team_name, role_catalog)

    if signing_batch is not None:
        player_role = resolve_player_role(guild, settings.player_role_id)
        player_result = await repository.register_team_signings(
            signing_batch,
            require_new_team_block=require_new_team_block,
        )
        team_role_result = await resolve_or_create_team_role(
            guild,
            team_name=team_name,
            role_catalog=role_catalog,
            actor=interaction.user,
            create_if_missing=player_result.created_team_block,
        )
        provisioned_team_role = team_role_result.role
        team_role = provisioned_team_role
        team_role_created = team_role_result.created
        assignment_summary = await assign_team_roles_by_names(
            guild,
            team_role=provisioned_team_role,
            common_roles=(participant_role, player_role),
            actor=interaction.user,
            member_names=(player.discord_name for player in signing_batch.players),
            suppress_player_signing_announcements=True,
        )

    technical_staff_result = None
    staff_role_sync_summary = None
    staff_entries: tuple[TeamStaffRoleEntry, ...] = ()
    resolved_team_role = (
        team_role
        if team_role is not None
        else resolve_team_role_by_name(team_name, role_catalog)
    )
    if technical_staff_batch is not None:
        previous_team_profile = await repository.find_team_profile_for_role(
            resolved_team_role
        )
        technical_staff_result = await repository.register_team_technical_staff(
            technical_staff_batch
        )
        current_team_profile = await repository.find_team_profile_for_role(
            resolved_team_role
        )
        player_member_names = (
            tuple(player.discord_name for player in signing_batch.players)
            if signing_batch is not None
            else collect_team_profile_player_names(
                current_team_profile
            )
        )
        staff_entries = collect_technical_staff_role_entries(technical_staff_batch)
        previous_affected_staff_names = _collect_previous_staff_names_for_roles(
            previous_team_profile,
            technical_staff_batch,
        )
        staff_entries = (
            *staff_entries,
            *_collect_current_staff_entries_for_members(
                current_team_profile,
                previous_affected_staff_names,
            ),
        )
        staff_role_sync_summary = await sync_team_staff_roles_by_names(
            guild,
            team_role=resolved_team_role,
            participant_role=participant_role,
            ceo_role_id=settings.staff_ceo_role_id,
            analyst_role_id=settings.staff_analyst_role_id,
            coach_role_id=settings.staff_coach_role_id,
            manager_role_id=settings.staff_manager_role_id,
            second_manager_role_id=settings.staff_second_manager_role_id,
            captain_role_id=settings.staff_captain_role_id,
            actor=interaction.user,
            staff_entries=staff_entries,
            player_member_names=player_member_names,
            staff_member_names_to_prune=previous_affected_staff_names,
            unchanged_staff_entries=collect_team_profile_staff_role_entries(
                previous_team_profile
            ),
            count_existing_staff_roles_as_assigned=True,
            suppress_team_role_signing_announcements=not publish_announcements,
            suppress_staff_signing_announcements=True,
            suppress_staff_removal_announcements=not publish_announcements,
        )

    visibility_links = (
        await collect_team_signing_visibility_links(
            settings=settings,
            guild=guild,
            bot=bot,
            team_role=resolved_team_role,
            assignment_summary=assignment_summary,
            technical_staff_batch=technical_staff_batch,
            staff_sync_summary=staff_role_sync_summary,
            since=announcement_since,
        )
        if publish_announcements
        else None
    )
    completed_message = build_team_signing_import_completed_message(
        localizer=interaction.client.localizer,
        locale=interaction.locale,
        division_name=division_name,
        team_name=team_name,
        signing_batch=signing_batch,
        technical_staff_batch=technical_staff_batch,
        player_result=player_result,
        technical_staff_result=technical_staff_result,
        assignment_summary=assignment_summary,
        staff_sync_summary=staff_role_sync_summary,
        created_team_role=team_role_created,
    )
    visibility_message = build_team_signing_visibility_message(
        localizer=interaction.client.localizer,
        locale=interaction.locale,
        team_role_mention=resolved_team_role.mention,
        team_links=(
            visibility_links.team_links
            if visibility_links is not None
            else ()
        ),
        staff_links=(
            visibility_links.staff_links
            if visibility_links is not None
            else ()
        ),
    )
    removal_visibility_message = build_team_signing_removal_visibility_message(
        localizer=interaction.client.localizer,
        locale=interaction.locale,
        team_role_mention=resolved_team_role.mention,
        staff_links=(
            visibility_links.staff_removal_links
            if visibility_links is not None
            else ()
        ),
    )
    await interaction.followup.send(
        f"{completed_message}{visibility_message}{removal_visibility_message}",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    if publish_announcements:
        _record_pending_assignments_for_unresolved_members(
            settings=settings,
            guild=guild,
            team_role=resolved_team_role,
            division_name=division_name,
            team_image_url=(
                signing_batch.team_logo_url
                if signing_batch is not None
                else None
            ),
            assignment_summary=assignment_summary,
            staff_sync_summary=staff_role_sync_summary,
            staff_entries=staff_entries,
            source=(
                "hacer_inscripcion"
                if require_new_team_block
                else "hacer_fichaje"
            ),
        )


def _record_pending_assignments_for_unresolved_members(
        *,
        settings: Settings,
        guild: discord.Guild,
        team_role: discord.Role,
        division_name: str,
        team_image_url: str | None,
        assignment_summary: TeamRoleAssignmentSummary | None,
        staff_sync_summary: TeamStaffRoleSyncSummary | None,
        staff_entries: tuple[TeamStaffRoleEntry, ...],
        source: str,
) -> None:
    unresolved_player_names = (
        assignment_summary.unresolved_names
        if assignment_summary is not None
        else ()
    )
    unresolved_staff_names = (
        staff_sync_summary.unresolved_names
        if staff_sync_summary is not None
        else ()
    )
    if not unresolved_player_names and not unresolved_staff_names:
        return

    store = PendingTeamSigningAssignmentStore(
        settings.pending_team_signing_assignments_file
    )
    now = current_utc_timestamp()
    staff_entries_by_member = collect_staff_role_entries_by_member(staff_entries)
    for member_name in unresolved_player_names:
        assignment = create_pending_team_signing_assignment(
            guild_id=guild.id,
            member_name=member_name,
            team_role_id=team_role.id,
            team_role_name=team_role.name,
            division_name=division_name,
            team_image_url=team_image_url,
            is_player=True,
            source=source,
            created_at=now,
        )
        if assignment is not None:
            store.upsert(assignment)

    for member_name in unresolved_staff_names:
        normalized_name = normalize_member_lookup_text(member_name)
        staff_role_keys = (
            tuple(staff_entries_by_member[normalized_name].role_keys)
            if normalized_name is not None
               and normalized_name in staff_entries_by_member
            else ()
        )
        assignment = create_pending_team_signing_assignment(
            guild_id=guild.id,
            member_name=member_name,
            team_role_id=team_role.id,
            team_role_name=team_role.name,
            division_name=division_name,
            team_image_url=team_image_url,
            is_player=False,
            staff_role_keys=staff_role_keys,
            source=source,
            created_at=now,
        )
        if assignment is not None:
            store.upsert(assignment)


def _collect_previous_staff_names_for_roles(
        previous_team_profile: TeamProfile,
        technical_staff_batch: TeamTechnicalStaffBatch,
) -> tuple[str, ...]:
    target_role_keys = {
        role_key
        for role_key in (
            normalize_team_staff_role_name(member.role_name)
            for member in technical_staff_batch.members
        )
        if role_key is not None
    }
    return tuple(
        member.discord_name
        for member in previous_team_profile.technical_staff
        if (
                normalize_team_staff_role_name(member.role_name) in target_role_keys
                and member.discord_name
        )
    )


def _collect_current_staff_entries_for_members(
        current_team_profile: TeamProfile,
        member_names: tuple[str, ...],
) -> tuple[TeamStaffRoleEntry, ...]:
    normalized_member_names = {
        _normalize_staff_member_name(member_name)
        for member_name in member_names
        if _normalize_staff_member_name(member_name)
    }
    return tuple(
        TeamStaffRoleEntry(
            role_name=member.role_name,
            member_name=member.discord_name,
        )
        for member in current_team_profile.technical_staff
        if _normalize_staff_member_name(member.discord_name) in normalized_member_names
    )


def _normalize_staff_member_name(value: str | None) -> str:
    if value is None:
        return ""

    normalized = " ".join(value.split()).strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    return normalized.casefold()
