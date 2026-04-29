from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from bigness_league_bot.infrastructure.discord.channel_management import (
    ChannelAccessRoleRangeError,
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.team_change_announcements import (
    TEAM_PLAYER_ROLE_REMOVAL_SPEC,
    TEAM_PLAYER_ROLE_SIGNING_SPEC,
    TEAM_ROLE_REMOVAL_SPEC,
    TEAM_ROLE_SIGNING_SPEC,
    TEAM_STAFF_ROLE_REMOVAL_SPEC,
    TEAM_STAFF_ROLE_SIGNING_SPEC,
    build_team_role_sheet_metadata_fallback,
)
from bigness_league_bot.infrastructure.discord.team_change_bulletin import (
    create_team_change_repository,
    load_team_change_metadata,
    resolve_team_change_bulletin_channel,
)
from bigness_league_bot.infrastructure.discord.team_role_change_context import (
    format_roles_for_log,
    has_any_role,
    resolve_player_role_change_team_context,
    resolve_team_role_context,
    resolve_tracked_staff_roles,
)
from bigness_league_bot.infrastructure.discord.team_role_change_delivery import (
    TeamChangeAnnouncementDeduplicator,
    TeamRoleChangeAnnouncementSender,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger("bigness_league_bot.activity")


class TeamRoleRemovalAnnouncements(commands.Cog):
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot
        deduplicator = TeamChangeAnnouncementDeduplicator()
        self.announcement_sender = TeamRoleChangeAnnouncementSender(
            bot=bot,
            deduplicator=deduplicator,
        )

    @commands.Cog.listener()
    async def on_member_update(
            self,
            before: discord.Member,
            after: discord.Member,
    ) -> None:
        if before.bot or before.roles == after.roles:
            return

        try:
            role_catalog = get_channel_access_role_catalog(
                after.guild,
                self.bot.settings.channel_access_range_start_role_id,
                self.bot.settings.channel_access_range_end_role_id,
            )
        except ChannelAccessRoleRangeError as exc:
            LOGGER.warning(
                "TEAM_ROLE_REMOVAL_ANNOUNCEMENT_SKIPPED guild=%s(%s) user=%s(%s) details=%s",
                after.guild.name,
                after.guild.id,
                after,
                after.id,
                exc,
            )
            return

        tracked_role_ids = {role.id for role in role_catalog.roles}
        removed_team_roles = tuple(
            role
            for role in before.roles
            if role.id in tracked_role_ids and role not in after.roles
        )
        added_team_roles = tuple(
            role
            for role in after.roles
            if role.id in tracked_role_ids and role not in before.roles
        )
        has_team_role_change = bool(removed_team_roles or added_team_roles)
        player_role = after.guild.get_role(self.bot.settings.player_role_id)
        player_role_added = (
                player_role is not None
                and player_role not in before.roles
                and player_role in after.roles
        )
        player_role_removed = (
                player_role is not None
                and player_role in before.roles
                and player_role not in after.roles
        )
        tracked_staff_roles = resolve_tracked_staff_roles(
            settings=self.bot.settings,
            guild=after.guild,
        )
        tracked_staff_role_ids = {role.id for role in tracked_staff_roles}
        removed_staff_roles = tuple(
            role
            for role in before.roles
            if role.id in tracked_staff_role_ids and role not in after.roles
        )
        added_staff_roles = tuple(
            role
            for role in after.roles
            if role.id in tracked_staff_role_ids and role not in before.roles
        )
        if (
                not has_team_role_change
                and not player_role_added
                and not player_role_removed
                and not removed_staff_roles
                and not added_staff_roles
        ):
            return

        channel = await resolve_team_change_bulletin_channel(
            guild=after.guild,
            channel_id=self.bot.settings.team_role_removal_announcement_channel_id,
        )
        if channel is None:
            return

        repository = await create_team_change_repository(
            self.bot.settings,
            guild=after.guild,
        )
        for removed_team_role in removed_team_roles:
            metadata = await load_team_change_metadata(
                repository=repository,
                team_role=removed_team_role,
                fallback=build_team_role_sheet_metadata_fallback(removed_team_role),
                guild=after.guild,
            )
            await self.announcement_sender.send_team_role_change_announcement(
                member=after,
                team_role=removed_team_role,
                guild=after.guild,
                metadata=metadata,
                spec=TEAM_ROLE_REMOVAL_SPEC,
                channel=channel,
                failure_log_code="TEAM_ROLE_REMOVAL_ANNOUNCEMENT_SEND_FAILED",
            )

        for added_team_role in added_team_roles:
            metadata = await load_team_change_metadata(
                repository=repository,
                team_role=added_team_role,
                fallback=build_team_role_sheet_metadata_fallback(added_team_role),
                guild=after.guild,
            )
            await self.announcement_sender.send_team_role_change_announcement(
                member=after,
                team_role=added_team_role,
                guild=after.guild,
                metadata=metadata,
                spec=TEAM_ROLE_SIGNING_SPEC,
                channel=channel,
                failure_log_code="TEAM_ROLE_SIGNING_ANNOUNCEMENT_SEND_FAILED",
            )

        if removed_team_roles and not added_team_roles:
            return
        if has_team_role_change and not removed_staff_roles and not added_staff_roles:
            return

        if player_role_removed:
            team_role = resolve_player_role_change_team_context(
                after=after,
                tracked_team_role_ids=tracked_role_ids,
            )
            if team_role is None:
                LOGGER.warning(
                    "TEAM_PLAYER_ROLE_REMOVAL_ANNOUNCEMENT_SKIPPED guild=%s(%s) user=%s(%s) details=no-team-role-context after_team_roles=%s",
                    after.guild.name,
                    after.guild.id,
                    after,
                    after.id,
                    format_roles_for_log(
                        role
                        for role in after.roles
                        if role.id in tracked_role_ids
                    ),
                )
            else:
                metadata = await load_team_change_metadata(
                    repository=repository,
                    team_role=team_role,
                    fallback=build_team_role_sheet_metadata_fallback(team_role),
                    guild=after.guild,
                )
                await self.announcement_sender.send_team_role_change_announcement(
                    member=after,
                    team_role=team_role,
                    guild=after.guild,
                    metadata=metadata,
                    spec=TEAM_PLAYER_ROLE_REMOVAL_SPEC,
                    channel=channel,
                    failure_log_code="TEAM_PLAYER_ROLE_REMOVAL_ANNOUNCEMENT_SEND_FAILED",
                )

        if (
                player_role_added
                and has_any_role(before.roles, tracked_staff_role_ids)
        ):
            team_role = resolve_player_role_change_team_context(
                after=after,
                tracked_team_role_ids=tracked_role_ids,
            )
            if team_role is None:
                LOGGER.warning(
                    "TEAM_PLAYER_ROLE_SIGNING_ANNOUNCEMENT_SKIPPED guild=%s(%s) user=%s(%s) details=no-team-role-context after_team_roles=%s",
                    after.guild.name,
                    after.guild.id,
                    after,
                    after.id,
                    format_roles_for_log(
                        role
                        for role in after.roles
                        if role.id in tracked_role_ids
                    ),
                )
            else:
                metadata = await load_team_change_metadata(
                    repository=repository,
                    team_role=team_role,
                    fallback=build_team_role_sheet_metadata_fallback(team_role),
                    guild=after.guild,
                )
                await self.announcement_sender.send_team_role_change_announcement(
                    member=after,
                    team_role=team_role,
                    guild=after.guild,
                    metadata=metadata,
                    spec=TEAM_PLAYER_ROLE_SIGNING_SPEC,
                    channel=channel,
                    failure_log_code="TEAM_PLAYER_ROLE_SIGNING_ANNOUNCEMENT_SEND_FAILED",
                )

        if not removed_staff_roles and not added_staff_roles:
            return

        team_role = resolve_team_role_context(
            before=before,
            after=after,
            tracked_team_role_ids=tracked_role_ids,
            removed_team_roles=removed_team_roles,
            added_team_roles=added_team_roles,
            removed_staff_roles=removed_staff_roles,
            added_staff_roles=added_staff_roles,
        )
        if team_role is None:
            LOGGER.warning(
                "TEAM_STAFF_ROLE_ANNOUNCEMENT_SKIPPED guild=%s(%s) user=%s(%s) details=no-team-role-context before_team_roles=%s after_team_roles=%s removed_team_roles=%s added_team_roles=%s removed_staff_roles=%s added_staff_roles=%s",
                after.guild.name,
                after.guild.id,
                after,
                after.id,
                format_roles_for_log(
                    role
                    for role in before.roles
                    if role.id in tracked_role_ids
                ),
                format_roles_for_log(
                    role
                    for role in after.roles
                    if role.id in tracked_role_ids
                ),
                format_roles_for_log(removed_team_roles),
                format_roles_for_log(added_team_roles),
                format_roles_for_log(removed_staff_roles),
                format_roles_for_log(added_staff_roles),
            )
            return

        metadata = await load_team_change_metadata(
            repository=repository,
            team_role=team_role,
            fallback=build_team_role_sheet_metadata_fallback(team_role),
            guild=after.guild,
        )
        for removed_staff_role in removed_staff_roles:
            await self.announcement_sender.send_staff_role_change_announcement(
                member=after,
                team_role=team_role,
                staff_role=removed_staff_role,
                guild=after.guild,
                metadata=metadata,
                spec=TEAM_STAFF_ROLE_REMOVAL_SPEC,
                channel=channel,
            )
        for added_staff_role in added_staff_roles:
            await self.announcement_sender.send_staff_role_change_announcement(
                member=after,
                team_role=team_role,
                staff_role=added_staff_role,
                guild=after.guild,
                metadata=metadata,
                spec=TEAM_STAFF_ROLE_SIGNING_SPEC,
                channel=channel,
            )

async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(TeamRoleRemovalAnnouncements(bot))
