from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    UnsupportedChannelError,
    ensure_allowed_member,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.team_staff_interactive import (
    collect_available_interactive_staff_roles,
    interactive_staff_player_autocomplete,
    interactive_staff_team_autocomplete,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str
from bigness_league_bot.presentation.discord.views.team_staff_role_selection import (
    TeamStaffRoleSelectionView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class TeamStaffInteractiveSigningCog(commands.Cog):
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot

    @app_commands.command(
        name=localized_locale_str(
            I18N.commands.team_signing.make_interactive_staff_signing.name
        ),
        description=localized_locale_str(
            I18N.commands.team_signing.make_interactive_staff_signing.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        equipo=localized_locale_str(
            I18N.commands.team_signing.make_interactive_staff_signing.parameters.team.description
        ),
        discord_jugador=localized_locale_str(
            I18N.commands.team_signing.make_interactive_staff_signing.parameters.discord_name.description
        ),
    )
    @app_commands.autocomplete(
        equipo=interactive_staff_team_autocomplete,
        discord_jugador=interactive_staff_player_autocomplete,
    )
    async def make_interactive_staff_signing(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            equipo: str,
            discord_jugador: str,
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        ensure_allowed_member(interaction.user)
        await interaction.response.defer(thinking=True, ephemeral=True)
        role_options = await collect_available_interactive_staff_roles(
            interaction,
            guild=guild,
            equipo=equipo,
        )
        if not role_options:
            raise CommandUserError(
                localize(
                    I18N.errors.team_signing.no_available_interactive_staff_roles
                )
            )

        view = TeamStaffRoleSelectionView(
            bot=self.bot,
            guild=guild,
            actor=interaction.user,
            equipo=equipo,
            discord_jugador=discord_jugador,
            role_options=role_options,
            localizer=interaction.client.localizer,
            locale=interaction.locale,
        )
        view.message = await interaction.followup.send(
            interaction.client.localizer.translate(
                I18N.messages.team_signing.interactive_staff_role_selection.prompt,
                locale=interaction.locale,
                discord_name=discord_jugador,
            ),
            view=view,
            ephemeral=True,
            wait=True,
        )

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
            await interaction.followup.send(message, ephemeral=True)
            return

        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(TeamStaffInteractiveSigningCog(bot))
