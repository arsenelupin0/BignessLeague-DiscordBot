from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from bigness_league_bot.infrastructure.discord.channel_management import (
    ChannelAccessRoleRangeError,
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.emojis import (
    TEAM_ROLE_REMOVAL_WARNING_EMOJI,
    render_custom_emoji,
)
from bigness_league_bot.infrastructure.discord.team_change_announcements import (
    TEAM_ROLE_REMOVAL_SPEC,
    TEAM_ROLE_SIGNING_SPEC,
    TEAM_STAFF_ROLE_REMOVAL_SPEC,
    TEAM_STAFF_ROLE_SIGNING_SPEC,
    build_team_change_content,
    build_team_change_embed,
    build_team_role_sheet_metadata_fallback,
)
from bigness_league_bot.infrastructure.discord.team_change_bulletin import (
    create_team_change_repository,
    load_team_change_metadata,
    resolve_team_change_bulletin_channel,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import TeamRoleSheetMetadata

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger("bigness_league_bot.activity")


class TeamRoleRemovalAnnouncements(commands.Cog):
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot

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
        tracked_staff_roles = self._resolve_tracked_staff_roles(after.guild)
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
                not removed_team_roles
                and not added_team_roles
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
            content = self._build_role_removal_content(
                member=after,
                team_role=removed_team_role,
                guild=after.guild,
            )
            metadata = await load_team_change_metadata(
                repository=repository,
                team_role=removed_team_role,
                fallback=build_team_role_sheet_metadata_fallback(removed_team_role),
                guild=after.guild,
            )
            embed, image_file = self._build_role_removal_embed(
                member=after,
                team_role=removed_team_role,
                guild=after.guild,
                metadata=metadata,
            )
            allowed_mentions = discord.AllowedMentions(
                everyone=False,
                replied_user=False,
                users=[after],
                roles=[removed_team_role],
            )
            try:
                send_kwargs: dict[str, object] = {
                    "content": content,
                    "embed": embed,
                    "allowed_mentions": allowed_mentions,
                }
                if image_file is not None:
                    send_kwargs["file"] = image_file
                await channel.send(**send_kwargs)
            except (discord.Forbidden, discord.HTTPException) as exc:
                LOGGER.warning(
                    "TEAM_ROLE_REMOVAL_ANNOUNCEMENT_SEND_FAILED guild=%s(%s) user=%s(%s) role=%s(%s) details=%s",
                    after.guild.name,
                    after.guild.id,
                    after,
                    after.id,
                    removed_team_role.name,
                    removed_team_role.id,
                    exc,
                )

        for added_team_role in added_team_roles:
            content = build_team_change_content(
                bot=self.bot,
                spec=TEAM_ROLE_SIGNING_SPEC,
                member=after,
                team_role=added_team_role,
                guild=after.guild,
            )
            metadata = await load_team_change_metadata(
                repository=repository,
                team_role=added_team_role,
                fallback=build_team_role_sheet_metadata_fallback(added_team_role),
                guild=after.guild,
            )
            embed, image_file = build_team_change_embed(
                bot=self.bot,
                spec=TEAM_ROLE_SIGNING_SPEC,
                member=after,
                team_role=added_team_role,
                guild=after.guild,
                metadata=metadata,
                description=self._build_role_removal_description(after.guild),
            )
            allowed_mentions = discord.AllowedMentions(
                everyone=False,
                replied_user=False,
                users=[after],
                roles=[added_team_role],
            )
            try:
                send_kwargs: dict[str, object] = {
                    "content": content,
                    "embed": embed,
                    "allowed_mentions": allowed_mentions,
                }
                if image_file is not None:
                    send_kwargs["file"] = image_file
                await channel.send(**send_kwargs)
            except (discord.Forbidden, discord.HTTPException) as exc:
                LOGGER.warning(
                    "TEAM_ROLE_SIGNING_ANNOUNCEMENT_SEND_FAILED guild=%s(%s) user=%s(%s) role=%s(%s) details=%s",
                    after.guild.name,
                    after.guild.id,
                    after,
                    after.id,
                    added_team_role.name,
                    added_team_role.id,
                    exc,
                )

        if not removed_staff_roles and not added_staff_roles:
            return

        team_role = self._resolve_team_role_context(
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
                self._format_roles_for_log(
                    role
                    for role in before.roles
                    if role.id in tracked_role_ids
                ),
                self._format_roles_for_log(
                    role
                    for role in after.roles
                    if role.id in tracked_role_ids
                ),
                self._format_roles_for_log(removed_team_roles),
                self._format_roles_for_log(added_team_roles),
                self._format_roles_for_log(removed_staff_roles),
                self._format_roles_for_log(added_staff_roles),
            )
            return

        metadata = await load_team_change_metadata(
            repository=repository,
            team_role=team_role,
            fallback=build_team_role_sheet_metadata_fallback(team_role),
            guild=after.guild,
        )
        for removed_staff_role in removed_staff_roles:
            await self._send_staff_role_change_announcement(
                member=after,
                team_role=team_role,
                staff_role=removed_staff_role,
                guild=after.guild,
                metadata=metadata,
                spec=TEAM_STAFF_ROLE_REMOVAL_SPEC,
                channel=channel,
            )
        for added_staff_role in added_staff_roles:
            await self._send_staff_role_change_announcement(
                member=after,
                team_role=team_role,
                staff_role=added_staff_role,
                guild=after.guild,
                metadata=metadata,
                spec=TEAM_STAFF_ROLE_SIGNING_SPEC,
                channel=channel,
            )

    def _build_role_removal_content(
            self,
            *,
            member: discord.Member,
            team_role: discord.Role,
            guild: discord.Guild,
    ) -> str:
        return build_team_change_content(
            bot=self.bot,
            spec=TEAM_ROLE_REMOVAL_SPEC,
            member=member,
            team_role=team_role,
            guild=guild,
        )

    def _build_role_removal_embed(
            self,
            *,
            member: discord.Member,
            team_role: discord.Role,
            guild: discord.Guild,
            metadata: TeamRoleSheetMetadata,
    ) -> tuple[discord.Embed, discord.File | None]:
        return build_team_change_embed(
            bot=self.bot,
            spec=TEAM_ROLE_REMOVAL_SPEC,
            member=member,
            team_role=team_role,
            guild=guild,
            metadata=metadata,
            description=self._build_role_removal_description(guild),
        )

    def _build_role_removal_description(self, guild: discord.Guild) -> str:
        warning_emoji = render_custom_emoji(
            guild=guild,
            bot=self.bot,
            emoji=TEAM_ROLE_REMOVAL_WARNING_EMOJI,
        )
        return (
            "# "
            f"{warning_emoji} {warning_emoji} {warning_emoji} {warning_emoji}"
        )

    def _resolve_tracked_staff_roles(
            self,
            guild: discord.Guild,
    ) -> tuple[discord.Role, ...]:
        configured_role_ids = (
            self.bot.settings.staff_ceo_role_id,
            self.bot.settings.staff_analyst_role_id,
            self.bot.settings.staff_coach_role_id,
            self.bot.settings.staff_manager_role_id,
            self.bot.settings.staff_second_manager_role_id,
            self.bot.settings.staff_captain_role_id,
        )
        tracked_roles: dict[int, discord.Role] = {}
        for role_id in configured_role_ids:
            role = guild.get_role(role_id)
            if role is not None:
                tracked_roles[role.id] = role

        return tuple(tracked_roles.values())

    @staticmethod
    def _resolve_team_role_context(
            *,
            before: discord.Member,
            after: discord.Member,
            tracked_team_role_ids: set[int],
            removed_team_roles: tuple[discord.Role, ...],
            added_team_roles: tuple[discord.Role, ...],
            removed_staff_roles: tuple[discord.Role, ...],
            added_staff_roles: tuple[discord.Role, ...],
    ) -> discord.Role | None:
        role_groups: list[tuple[discord.Role, ...]] = []
        if removed_staff_roles:
            role_groups.append(removed_team_roles)
        if added_staff_roles:
            role_groups.append(added_team_roles)
        role_groups.extend(
            (
                tuple(role for role in after.roles if role.id in tracked_team_role_ids),
                tuple(role for role in before.roles if role.id in tracked_team_role_ids),
            )
        )
        candidate_roles = {
            role.id: role
            for role in (*after.roles, *before.roles)
            if role.id in tracked_team_role_ids
        }
        role_groups.append(tuple(candidate_roles.values()))
        for role_group in role_groups:
            unique_roles = TeamRoleRemovalAnnouncements._deduplicate_roles(role_group)
            if len(unique_roles) == 1:
                return unique_roles[0]

        return None

    @staticmethod
    def _deduplicate_roles(
            roles: tuple[discord.Role, ...],
    ) -> tuple[discord.Role, ...]:
        return tuple({role.id: role for role in roles}.values())

    @staticmethod
    def _format_roles_for_log(
            roles: Iterable[discord.Role],
    ) -> str:
        formatted_roles = tuple(f"{role.name}({role.id})" for role in roles)
        if not formatted_roles:
            return "-"

        return ", ".join(formatted_roles)

    async def _send_staff_role_change_announcement(
            self,
            *,
            member: discord.Member,
            team_role: discord.Role,
            staff_role: discord.Role,
            guild: discord.Guild,
            metadata: TeamRoleSheetMetadata,
            spec: object,
            channel: discord.abc.Messageable,
    ) -> None:
        content = build_team_change_content(
            bot=self.bot,
            spec=spec,
            member=member,
            team_role=team_role,
            guild=guild,
            staff_role_name=staff_role.name,
        )
        embed, image_file = build_team_change_embed(
            bot=self.bot,
            spec=spec,
            member=member,
            team_role=team_role,
            guild=guild,
            metadata=metadata,
            description=self._build_role_removal_description(guild),
        )
        allowed_mentions = discord.AllowedMentions(
            everyone=False,
            replied_user=False,
            users=[member],
            roles=[team_role],
        )
        try:
            send_kwargs: dict[str, object] = {
                "content": content,
                "embed": embed,
                "allowed_mentions": allowed_mentions,
            }
            if image_file is not None:
                send_kwargs["file"] = image_file
            await channel.send(**send_kwargs)
        except (discord.Forbidden, discord.HTTPException) as exc:
            LOGGER.warning(
                "TEAM_STAFF_ROLE_ANNOUNCEMENT_SEND_FAILED guild=%s(%s) user=%s(%s) team_role=%s(%s) staff_role=%s(%s) details=%s",
                guild.name,
                guild.id,
                member,
                member.id,
                team_role.name,
                team_role.id,
                staff_role.name,
                staff_role.id,
                exc,
            )


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(TeamRoleRemovalAnnouncements(bot))
