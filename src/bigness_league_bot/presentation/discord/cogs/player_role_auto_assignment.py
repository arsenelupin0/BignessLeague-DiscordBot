from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.discord.channel_management import (
    ChannelAccessRoleRangeError,
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.emojis import (
    TEAM_ROLE_REMOVAL_WARNING_EMOJI,
    render_custom_emoji,
)
from bigness_league_bot.infrastructure.discord.team_change_announcements import (
    TEAM_ROLE_SIGNING_SPEC,
    build_team_change_content,
    build_team_change_embed,
    build_team_role_sheet_metadata_fallback,
)
from bigness_league_bot.infrastructure.discord.team_change_bulletin import (
    load_team_change_metadata,
    resolve_team_change_bulletin_channel,
)
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    resolve_optional_team_staff_roles,
    resolve_participant_role,
    resolve_player_role,
    resolve_team_role_by_name,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
    TeamSheetError,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger("bigness_league_bot.activity")


class PlayerRoleAutoAssignment(commands.Cog):
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot or not self.bot.settings.auto_assign_player_roles_on_join:
            return

        try:
            role_catalog = get_channel_access_role_catalog(
                member.guild,
                self.bot.settings.channel_access_range_start_role_id,
                self.bot.settings.channel_access_range_end_role_id,
            )
            repository = GoogleSheetsTeamRepository(self.bot.settings)
            matches = await repository.find_member_team_matches_by_discord_names(
                self._member_candidate_names(member)
            )
        except (ChannelAccessRoleRangeError, TeamSheetError) as exc:
            LOGGER.warning(
                "PLAYER_ROLE_AUTO_ASSIGN_FAILED user=%s(%s) guild=%s(%s) details=%s",
                member,
                member.id,
                member.guild.name,
                member.guild.id,
                exc,
            )
            return

        if not matches:
            return

        if len(matches) > 1:
            locations = ", ".join(
                f"{match.worksheet_title}/{match.block.title}"
                for match in matches
            )
            LOGGER.warning(
                "PLAYER_ROLE_AUTO_ASSIGN_AMBIGUOUS user=%s(%s) guild=%s(%s) locations=%s",
                member,
                member.id,
                member.guild.name,
                member.guild.id,
                locations,
            )
            return

        match = matches[0]
        try:
            team_role = resolve_team_role_by_name(match.block.title, role_catalog)
            common_roles: tuple[discord.Role, ...] = ()
            if match.affiliation.is_player:
                common_roles = (
                    resolve_participant_role(
                        member.guild,
                        self.bot.settings.participant_role_id,
                    ),
                    resolve_player_role(
                        member.guild,
                        self.bot.settings.player_role_id,
                    ),
                )
            staff_roles = resolve_optional_team_staff_roles(
                member.guild,
                ceo_role_id=self.bot.settings.staff_ceo_role_id,
                analyst_role_id=self.bot.settings.staff_analyst_role_id,
                coach_role_id=self.bot.settings.staff_coach_role_id,
                manager_role_id=self.bot.settings.staff_manager_role_id,
                second_manager_role_id=self.bot.settings.staff_second_manager_role_id,
                captain_role_id=self.bot.settings.staff_captain_role_id,
                staff_role_names=match.affiliation.staff_role_names,
            )
        except CommandUserError as exc:
            LOGGER.warning(
                "PLAYER_ROLE_AUTO_ASSIGN_CONFIGURATION_ERROR user=%s(%s) guild=%s(%s) details=%s",
                member,
                member.id,
                member.guild.name,
                member.guild.id,
                exc,
            )
            return

        roles_to_add = tuple(
            {
                role.id: role
                for role in (*common_roles, team_role, *staff_roles)
                if role not in member.roles
            }.values()
        )
        if not roles_to_add:
            return

        try:
            await member.add_roles(
                *roles_to_add,
                reason=(
                    f"Autoasignacion al entrar al servidor segun Google Sheets para "
                    f"{match.block.title} ({match.worksheet_title})"
                ),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            LOGGER.warning(
                "PLAYER_ROLE_AUTO_ASSIGN_DISCORD_ERROR user=%s(%s) guild=%s(%s) team=%s details=%s",
                member,
                member.id,
                member.guild.name,
                member.guild.id,
                match.block.title,
                exc,
            )
            return

        LOGGER.info(
            "PLAYER_ROLE_AUTO_ASSIGN_COMPLETED user=%s(%s) guild=%s(%s) team=%s roles=%s",
            member,
            member.id,
            member.guild.name,
            member.guild.id,
            match.block.title,
            ", ".join(role.name for role in roles_to_add),
        )
        if match.affiliation.is_player and team_role in roles_to_add:
            await self._publish_player_signing_bulletin(
                member=member,
                team_role=team_role,
                repository=repository,
            )

    async def _publish_player_signing_bulletin(
            self,
            *,
            member: discord.Member,
            team_role: discord.Role,
            repository: GoogleSheetsTeamRepository,
    ) -> None:
        channel = await resolve_team_change_bulletin_channel(
            guild=member.guild,
            channel_id=self.bot.settings.team_role_removal_announcement_channel_id,
        )
        if channel is None:
            return

        metadata = await load_team_change_metadata(
            repository=repository,
            team_role=team_role,
            fallback=build_team_role_sheet_metadata_fallback(team_role),
            guild=member.guild,
        )
        content = build_team_change_content(
            bot=self.bot,
            spec=TEAM_ROLE_SIGNING_SPEC,
            member=member,
            team_role=team_role,
            guild=member.guild,
        )
        embed, image_file = build_team_change_embed(
            bot=self.bot,
            spec=TEAM_ROLE_SIGNING_SPEC,
            member=member,
            team_role=team_role,
            guild=member.guild,
            metadata=metadata,
            description=self._build_team_change_description(member.guild),
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
                "PLAYER_ROLE_AUTO_ASSIGN_BULLETIN_FAILED user=%s(%s) guild=%s(%s) team=%s(%s) details=%s",
                member,
                member.id,
                member.guild.name,
                member.guild.id,
                team_role.name,
                team_role.id,
                exc,
            )

    def _build_team_change_description(self, guild: discord.Guild) -> str:
        warning_emoji = render_custom_emoji(
            guild=guild,
            bot=self.bot,
            emoji=TEAM_ROLE_REMOVAL_WARNING_EMOJI,
        )
        return (
            "## "
            f"{warning_emoji} {warning_emoji} {warning_emoji} {warning_emoji}"
        )

    @staticmethod
    def _member_candidate_names(member: discord.Member) -> tuple[str, ...]:
        candidate_names: dict[str, str] = {}
        for raw_value in (
                member.name,
                member.display_name,
                str(member),
                getattr(member, "global_name", None),
        ):
            if not isinstance(raw_value, str):
                continue
            normalized_value = " ".join(raw_value.split()).strip()
            if not normalized_value:
                continue
            candidate_names.setdefault(normalized_value.casefold(), normalized_value)

        return tuple(candidate_names.values())


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(PlayerRoleAutoAssignment(bot))
