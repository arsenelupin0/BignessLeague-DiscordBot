#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_management import (
    MemberTeamRoleMissingError,
    UnsupportedChannelError,
    ensure_allowed_member,
    ensure_member_can_access_team_features,
    get_channel_access_role_catalog,
    get_member_team_roles,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.team_profile import (
    build_team_profile_image_file,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str
from bigness_league_bot.presentation.discord.views.team_profile_team_selection import (
    TeamProfileTeamSelectionView,
)
from bigness_league_bot.presentation.discord.views.team_profile_tracker_actions import (
    TeamProfileTrackerActionsView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class TeamProfileCog(commands.Cog):
    @app_commands.command(
        name=localized_locale_str(I18N.commands.team_profile.view_my_team.name),
        description=localized_locale_str(
            I18N.commands.team_profile.view_my_team.description
        ),
    )
    @app_commands.describe(
        equipo=localized_locale_str(
            I18N.commands.team_profile.view_my_team.parameters.team_role.description
        )
    )
    @app_commands.guild_only()
    async def view_my_team(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            equipo: discord.Role | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        settings = interaction.client.settings
        role_catalog = get_channel_access_role_catalog(
            guild,
            settings.channel_access_range_start_role_id,
            settings.channel_access_range_end_role_id,
        )
        if equipo is not None:
            ensure_allowed_member(interaction.user)
            if equipo.id not in {role.id for role in role_catalog.roles}:
                raise UnsupportedChannelError(
                    localize(
                        I18N.errors.match_channel_creation.team_role_out_of_range,
                        role_name=equipo.name,
                        range_start=role_catalog.range_start.name,
                        range_end=role_catalog.range_end.name,
                    )
                )

            team_role = equipo
        else:
            ensure_member_can_access_team_features(interaction.user, role_catalog)
            member_team_roles = get_member_team_roles(interaction.user, role_catalog)
            if not member_team_roles:
                raise MemberTeamRoleMissingError(
                    localize(I18N.errors.team_profile.team_role_missing)
                )

            if len(member_team_roles) > 1:
                role_names = ", ".join(role.name for role in member_team_roles)
                view = TeamProfileTeamSelectionView(
                    actor=interaction.user,
                    team_roles=member_team_roles,
                    localizer=interaction.client.localizer,
                    locale=interaction.locale,
                )
                await interaction.response.send_message(
                    interaction.client.localizer.translate(
                        I18N.messages.team_profile.role_selection.prompt,
                        locale=interaction.locale,
                        role_names=role_names,
                    ),
                    view=view,
                )
                view.message = await interaction.original_response()
                return

            team_role = member_team_roles[0]

        await interaction.response.defer(thinking=True)
        repository = GoogleSheetsTeamRepository(settings)
        team_profile = await repository.find_team_profile_for_role(team_role)
        image_file = build_team_profile_image_file(
            team_profile=team_profile,
            localizer=interaction.client.localizer,
            locale=interaction.locale,
            font_path=settings.team_profile_font_path,
        )
        view = TeamProfileTrackerActionsView(
            actor=interaction.user,
            team_profile=team_profile,
            localizer=interaction.client.localizer,
            locale=interaction.locale,
        )
        message = await interaction.followup.send(
            file=image_file,
            view=view,
            wait=True,
        )
        view.message = message

    async def cog_app_command_error(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            error: app_commands.AppCommandError,
    ) -> None:
        error_details = classify_app_command_error(error)
        message = interaction.client.localizer.render(
            error_details.user_message,
            locale=interaction.locale,
        )
        if interaction.response.is_done():
            await interaction.followup.send(message)
            return

        await interaction.response.send_message(message)


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(TeamProfileCog())
