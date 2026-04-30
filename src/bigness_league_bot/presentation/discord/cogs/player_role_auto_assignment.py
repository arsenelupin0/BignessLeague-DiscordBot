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
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    resolve_participant_role,
    resolve_player_role,
    resolve_team_role_by_name,
    suppress_role_restore_signing_announcements,
)
from bigness_league_bot.infrastructure.discord.team_staff_roles import (
    filter_team_staff_role_names_for_player_status,
    resolve_optional_team_staff_roles,
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
            participant_role = resolve_participant_role(
                member.guild,
                self.bot.settings.participant_role_id,
            )
            player_role = None
            common_roles = (participant_role,)
            if match.affiliation.is_player:
                player_role = resolve_player_role(
                    member.guild,
                    self.bot.settings.player_role_id,
                )
                common_roles = (
                    participant_role,
                    player_role,
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
                    match.affiliation.staff_role_names,
                    is_player_in_same_team=match.affiliation.is_player,
                ),
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
                    f"Auto-asignación al entrar al servidor según Google Sheets para "
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
