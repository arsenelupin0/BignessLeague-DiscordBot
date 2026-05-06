from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.pending_team_signing_assignments import (
    PendingTeamSigningAssignment,
)
from bigness_league_bot.application.services.tickets import current_utc_timestamp
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.discord.pending_team_signing_assignments import (
    PendingTeamSigningAssignmentStore,
    create_pending_team_signing_assignment,
)
from bigness_league_bot.infrastructure.discord.team_change_announcements import (
    TEAM_ROLE_SIGNING_SPEC,
    TEAM_STAFF_ROLE_SIGNING_SPEC,
)
from bigness_league_bot.infrastructure.discord.team_change_bulletin import (
    resolve_team_change_bulletin_channel,
)
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    resolve_participant_role,
    resolve_player_role,
    suppress_role_restore_signing_announcements,
)
from bigness_league_bot.infrastructure.discord.team_role_change_delivery import (
    TeamChangeAnnouncementDeduplicator,
    TeamRoleChangeAnnouncementSender,
)
from bigness_league_bot.infrastructure.discord.team_staff_roles import (
    filter_team_staff_role_names_for_player_status,
    resolve_optional_team_staff_roles,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    TeamRoleSheetMetadata,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger("bigness_league_bot.activity")


class PendingTeamSigningAssignmentResolver:
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot
        self.store = PendingTeamSigningAssignmentStore(
            bot.settings.pending_team_signing_assignments_file
        )
        self.announcement_sender = TeamRoleChangeAnnouncementSender(
            bot=bot,
            deduplicator=TeamChangeAnnouncementDeduplicator(),
        )

    async def resolve_member_join(self, member: discord.Member) -> bool:
        pending_assignments = self.store.active_for_member(
            guild_id=member.guild.id,
            member=member,
        )
        if not pending_assignments:
            return False

        team_role_ids = {assignment.team_role_id for assignment in pending_assignments}
        if len(team_role_ids) > 1:
            LOGGER.warning(
                "PENDING_TEAM_SIGNING_ASSIGNMENT_AMBIGUOUS user=%s(%s) guild=%s(%s) assignments=%s",
                member,
                member.id,
                member.guild.name,
                member.guild.id,
                ", ".join(assignment.assignment_id for assignment in pending_assignments),
            )
            return True

        assignment = _merge_pending_assignments(pending_assignments)
        team_role = member.guild.get_role(assignment.team_role_id)
        if team_role is None:
            LOGGER.warning(
                "PENDING_TEAM_SIGNING_ASSIGNMENT_TEAM_ROLE_MISSING user=%s(%s) guild=%s(%s) team_role_id=%s",
                member,
                member.id,
                member.guild.name,
                member.guild.id,
                assignment.team_role_id,
            )
            return True

        try:
            participant_role = resolve_participant_role(
                member.guild,
                self.bot.settings.participant_role_id,
            )
            player_role = (
                resolve_player_role(member.guild, self.bot.settings.player_role_id)
                if assignment.is_player
                else None
            )
            staff_roles = resolve_optional_team_staff_roles(
                member.guild,
                ceo_role_id=self.bot.settings.staff_ceo_role_id,
                analyst_role_id=self.bot.settings.staff_analyst_role_id,
                coach_role_id=self.bot.settings.staff_coach_role_id,
                manager_role_id=self.bot.settings.staff_manager_role_id,
                second_manager_role_id=self.bot.settings.staff_second_manager_role_id,
                captain_role_id=self.bot.settings.staff_captain_role_id,
                staff_role_names=filter_team_staff_role_names_for_player_status(
                    assignment.staff_role_keys,
                    is_player_in_same_team=assignment.is_player,
                ),
            )
        except CommandUserError as exc:
            LOGGER.warning(
                "PENDING_TEAM_SIGNING_ASSIGNMENT_CONFIGURATION_ERROR user=%s(%s) guild=%s(%s) details=%s",
                member,
                member.id,
                member.guild.name,
                member.guild.id,
                exc,
            )
            return True

        common_roles = (participant_role, team_role)
        if player_role is not None:
            common_roles = (participant_role, player_role, team_role)
        roles_to_add = tuple(
            {
                role.id: role
                for role in (*common_roles, *staff_roles)
                if role not in member.roles
            }.values()
        )
        if roles_to_add:
            suppress_role_restore_signing_announcements(
                guild=member.guild,
                member=member,
                team_role=team_role,
                roles_to_add=roles_to_add,
                player_role=player_role,
                staff_roles=staff_roles,
            )
            try:
                await member.add_roles(
                    *roles_to_add,
                    reason=(
                        "Asignacion pendiente de fichaje/inscripcion al entrar al "
                        f"servidor para {assignment.team_role_name}"
                    ),
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                LOGGER.warning(
                    "PENDING_TEAM_SIGNING_ASSIGNMENT_DISCORD_ERROR user=%s(%s) guild=%s(%s) team=%s details=%s",
                    member,
                    member.id,
                    member.guild.name,
                    member.guild.id,
                    assignment.team_role_name,
                    exc,
                )
                return True

        announcement_message_ids = await self._send_announcements(
            member=member,
            assignment=assignment,
            team_role=team_role,
            staff_roles=staff_roles,
            added_role_ids={role.id for role in roles_to_add},
        )
        completed_at = current_utc_timestamp()
        for pending_assignment in pending_assignments:
            self.store.mark_completed(
                pending_assignment,
                member_id=member.id,
                completed_at=completed_at,
                announcement_message_ids=announcement_message_ids,
            )

        LOGGER.info(
            "PENDING_TEAM_SIGNING_ASSIGNMENT_COMPLETED user=%s(%s) guild=%s(%s) team=%s roles=%s announcements=%s",
            member,
            member.id,
            member.guild.name,
            member.guild.id,
            assignment.team_role_name,
            ", ".join(role.name for role in roles_to_add) if roles_to_add else "(sin cambios)",
            ",".join(str(message_id) for message_id in announcement_message_ids) or "(ninguno)",
        )
        return True

    async def record_sheet_auto_assignment(
            self,
            *,
            member: discord.Member,
            member_name: str,
            team_role: discord.Role,
            division_name: str,
            is_player: bool,
            staff_roles: tuple[discord.Role, ...],
            added_role_ids: set[int],
    ) -> tuple[int, ...]:
        completed_assignment = self.store.completed_for_member_or_name(
            guild_id=member.guild.id,
            member=member,
            team_role_id=team_role.id,
            member_name=member_name,
        )
        if completed_assignment is not None:
            return ()

        assignment = create_pending_team_signing_assignment(
            guild_id=member.guild.id,
            member_name=member_name,
            team_role_id=team_role.id,
            team_role_name=team_role.name,
            division_name=division_name,
            team_image_url=None,
            is_player=is_player,
            staff_role_keys=tuple(role.name for role in staff_roles),
            source="auto_assign_on_join",
            created_at=current_utc_timestamp(),
        )
        if assignment is None:
            return ()

        message_ids = await self._send_announcements(
            member=member,
            assignment=assignment,
            team_role=team_role,
            staff_roles=staff_roles,
            added_role_ids=added_role_ids,
        )
        self.store.upsert(assignment)
        self.store.mark_completed(
            assignment,
            member_id=member.id,
            completed_at=current_utc_timestamp(),
            announcement_message_ids=message_ids,
        )
        return message_ids

    async def _send_announcements(
            self,
            *,
            member: discord.Member,
            assignment: PendingTeamSigningAssignment,
            team_role: discord.Role,
            staff_roles: tuple[discord.Role, ...],
            added_role_ids: set[int],
    ) -> tuple[int, ...]:
        if not added_role_ids:
            return ()

        channel = await resolve_team_change_bulletin_channel(
            guild=member.guild,
            channel_id=self.bot.settings.team_role_removal_announcement_channel_id,
        )
        if channel is None:
            return ()

        metadata = TeamRoleSheetMetadata(
            worksheet_title=assignment.division_name,
            team_name=assignment.team_role_name,
            team_image_url=assignment.team_image_url,
        )
        sent_messages: list[discord.Message] = []
        if team_role.id in added_role_ids:
            team_message = await self.announcement_sender.send_team_role_change_announcement(
                member=member,
                team_role=team_role,
                guild=member.guild,
                metadata=metadata,
                spec=TEAM_ROLE_SIGNING_SPEC,
                channel=channel,
                failure_log_code="PENDING_TEAM_SIGNING_TEAM_ANNOUNCEMENT_SEND_FAILED",
                ignore_suppression=True,
            )
            if team_message is not None:
                sent_messages.append(team_message)

        for staff_role in staff_roles:
            if staff_role.id not in added_role_ids:
                continue

            staff_message = await self.announcement_sender.send_staff_role_change_announcement(
                member=member,
                team_role=team_role,
                staff_role=staff_role,
                guild=member.guild,
                metadata=metadata,
                spec=TEAM_STAFF_ROLE_SIGNING_SPEC,
                channel=channel,
                ignore_suppression=True,
            )
            if staff_message is not None:
                sent_messages.append(staff_message)

        return tuple(message.id for message in sent_messages)


def _merge_pending_assignments(
        assignments: tuple[PendingTeamSigningAssignment, ...],
) -> PendingTeamSigningAssignment:
    if len(assignments) == 1:
        return assignments[0]

    first_assignment = assignments[0]
    staff_role_keys = tuple(
        sorted(
            {
                role_key
                for assignment in assignments
                for role_key in assignment.staff_role_keys
            }
        )
    )
    return PendingTeamSigningAssignment(
        assignment_id=first_assignment.assignment_id,
        guild_id=first_assignment.guild_id,
        normalized_member_name=first_assignment.normalized_member_name,
        member_name=first_assignment.member_name,
        team_role_id=first_assignment.team_role_id,
        team_role_name=first_assignment.team_role_name,
        division_name=first_assignment.division_name,
        team_image_url=first_assignment.team_image_url,
        is_player=any(assignment.is_player for assignment in assignments),
        staff_role_keys=staff_role_keys,
        source="+".join(
            dict.fromkeys(assignment.source for assignment in assignments)
        ),
        created_at=min(assignment.created_at for assignment in assignments),
    )
