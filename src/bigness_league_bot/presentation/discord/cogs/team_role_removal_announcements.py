from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from bigness_league_bot.infrastructure.discord.channel_management import (
    ChannelAccessRoleRangeError,
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.team_role_removal_card import (
    build_team_role_removal_image_file,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
    TeamRoleSheetMetadata,
    TeamSheetError,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger("bigness_league_bot.activity")
TEAM_ROLE_REMOVAL_EMBED_COLOR = 15_403_534
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

        channel = await self._resolve_announcement_channel(after.guild)
        if channel is None:
            return

        try:
            repository: GoogleSheetsTeamRepository | None = GoogleSheetsTeamRepository(
                self.bot.settings
            )
        except TeamSheetError as exc:
            LOGGER.warning(
                "TEAM_ROLE_REMOVAL_ANNOUNCEMENT_METADATA_DISABLED guild=%s(%s) details=%s",
                after.guild.name,
                after.guild.id,
                exc,
            )
            repository = None
        for removed_team_role in removed_team_roles:
            metadata = await self._load_team_role_metadata(
                repository,
                removed_team_role,
                after.guild,
            )
            embed, image_file = self._build_role_removal_embed(
                member=after,
                team_role=removed_team_role,
                guild=after.guild,
                metadata=metadata,
            )
            try:
                await channel.send(
                    embed=embed,
                    file=image_file,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except TypeError:
                await channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
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

    async def _resolve_announcement_channel(
            self,
            guild: discord.Guild,
    ) -> discord.TextChannel | discord.Thread | None:
        channel_id = self.bot.settings.team_role_removal_announcement_channel_id
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.Forbidden, discord.HTTPException) as exc:
                LOGGER.warning(
                    "TEAM_ROLE_REMOVAL_ANNOUNCEMENT_CHANNEL_UNAVAILABLE guild=%s(%s) channel_id=%s details=%s",
                    guild.name,
                    guild.id,
                    channel_id,
                    exc,
                )
                return None

        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            return channel

        LOGGER.warning(
            "TEAM_ROLE_REMOVAL_ANNOUNCEMENT_CHANNEL_INVALID guild=%s(%s) channel_id=%s channel_type=%s",
            guild.name,
            guild.id,
            channel_id,
            type(channel).__name__,
        )
        return None

    async def _load_team_role_metadata(
            self,
            repository: GoogleSheetsTeamRepository | None,
            team_role: discord.Role,
            guild: discord.Guild,
    ) -> TeamRoleSheetMetadata:
        if repository is None:
            return TeamRoleSheetMetadata(
                worksheet_title=TEAM_ROLE_REMOVAL_FALLBACK_DIVISION_NAME,
                team_name=team_role.name,
                team_image_url=None,
            )

        try:
            return await repository.find_team_sheet_metadata_for_role(team_role)
        except TeamSheetError as exc:
            LOGGER.warning(
                "TEAM_ROLE_REMOVAL_ANNOUNCEMENT_METADATA_FALLBACK guild=%s(%s) role=%s(%s) details=%s",
                guild.name,
                guild.id,
                team_role.name,
                team_role.id,
                exc,
            )
            return TeamRoleSheetMetadata(
                worksheet_title=TEAM_ROLE_REMOVAL_FALLBACK_DIVISION_NAME,
                team_name=team_role.name,
                team_image_url=None,
            )

    def _build_role_removal_embed(
            self,
            *,
            member: discord.Member,
            team_role: discord.Role,
            guild: discord.Guild,
            metadata: TeamRoleSheetMetadata,
    ) -> tuple[discord.Embed, discord.File | None]:
        localizer = self.bot.localizer
        description = localizer.translate(
            I18N.messages.team_role_removal_announcement.description,
            locale=guild.preferred_locale,
            member_mention=member.mention,
            team_role_mention=team_role.mention,
        )
        author_name = localizer.translate(
            I18N.messages.team_role_removal_announcement.author,
            locale=guild.preferred_locale,
            division_name=metadata.worksheet_title,
        )
        footer_text = localizer.translate(
            I18N.messages.team_role_removal_announcement.footer,
            locale=guild.preferred_locale,
        )
        action_text = localizer.translate(
            I18N.messages.team_role_removal_announcement.action,
            locale=guild.preferred_locale,
        )

        embed = discord.Embed(
            description=description,
            color=TEAM_ROLE_REMOVAL_EMBED_COLOR,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=author_name)
        embed.set_footer(text=footer_text)

        thumbnail_url = metadata.team_image_url
        if not thumbnail_url and guild.icon is not None:
            thumbnail_url = guild.icon.url
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)

        try:
            image_file = build_team_role_removal_image_file(
                member=member,
                team_role=team_role,
                action_text=action_text,
                font_path=self.bot.settings.team_profile_font_path,
            )
        except RuntimeError as exc:
            LOGGER.warning(
                "TEAM_ROLE_REMOVAL_ANNOUNCEMENT_IMAGE_FALLBACK guild=%s(%s) user=%s(%s) role=%s(%s) details=%s",
                guild.name,
                guild.id,
                member,
                member.id,
                team_role.name,
                team_role.id,
                exc,
            )
            embed.add_field(
                name="\u200b",
                value="\n".join(
                    (
                        f"@{member.name}",
                        "_ _",
                        f"**{action_text.upper()}**",
                        "_ _",
                        team_role.name,
                    )
                ),
                inline=False,
            )
            return embed, None

        embed.set_image(url=f"attachment://{image_file.filename}")
        return embed, image_file


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(TeamRoleRemovalAnnouncements(bot))
