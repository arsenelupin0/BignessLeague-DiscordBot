from __future__ import annotations

import logging
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
TEAM_ROLE_REMOVAL_FALLBACK_DIVISION_NAME = "Division no disponible"


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
        if not removed_team_roles:
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


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(TeamRoleRemovalAnnouncements(bot))
