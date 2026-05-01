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
from bigness_league_bot.infrastructure.discord.team_roster_modification import (
    find_player_for_roster_modification,
    find_staff_members_for_roster_modification,
    parse_roster_block,
    resolve_roster_modification_context,
    roster_member_autocomplete,
)
from bigness_league_bot.infrastructure.discord.team_staff_interactive import (
    interactive_team_autocomplete,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str
from bigness_league_bot.presentation.discord.views.team_roster_modification import (
    PlayerRosterModificationView,
    StaffRosterModificationView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class TeamRosterModificationCog(commands.Cog):
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot

    @app_commands.command(
        name=localized_locale_str(I18N.commands.team_signing.modify_roster.name),
        description=localized_locale_str(
            I18N.commands.team_signing.modify_roster.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        equipo=localized_locale_str(
            I18N.commands.team_signing.modify_roster.parameters.team.description
        ),
        bloque=localized_locale_str(
            I18N.commands.team_signing.modify_roster.parameters.block.description
        ),
        discord_miembro=localized_locale_str(
            I18N.commands.team_signing.modify_roster.parameters.discord_name.description
        ),
    )
    @app_commands.choices(
        bloque=[
            app_commands.Choice(
                name=localized_locale_str(
                    I18N.commands.team_signing.modify_roster.choices.players
                ),
                value="players",
            ),
            app_commands.Choice(
                name=localized_locale_str(
                    I18N.commands.team_signing.modify_roster.choices.staff
                ),
                value="staff",
            ),
        ]
    )
    @app_commands.autocomplete(
        equipo=interactive_team_autocomplete,
        discord_miembro=roster_member_autocomplete,
    )
    async def modify_roster(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            equipo: str,
            bloque: app_commands.Choice[str],
            discord_miembro: str,
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        ensure_allowed_member(interaction.user)
        await interaction.response.defer(thinking=True, ephemeral=True)
        roster_block = parse_roster_block(bloque.value)
        if roster_block is None:
            raise CommandUserError(
                localize(I18N.errors.team_signing.no_import_payload_provided)
            )

        context = await resolve_roster_modification_context(
            interaction,
            guild=guild,
            equipo=equipo,
        )
        if roster_block == "players":
            player = find_player_for_roster_modification(
                context.team_profile,
                discord_miembro,
            )
            view = PlayerRosterModificationView(
                actor=interaction.user,
                team_profile=context.team_profile,
                player=player,
                localizer=interaction.client.localizer,
                locale=interaction.locale,
            )
        else:
            staff_members = find_staff_members_for_roster_modification(
                context.team_profile,
                discord_miembro,
            )
            view = StaffRosterModificationView(
                bot=self.bot,
                guild=guild,
                actor=interaction.user,
                team_profile=context.team_profile,
                discord_name=discord_miembro,
                staff_members=staff_members,
                localizer=interaction.client.localizer,
                locale=interaction.locale,
            )

        view.message = await interaction.followup.send(
            interaction.client.localizer.translate(
                I18N.messages.team_signing.roster_modification.prompt,
                locale=interaction.locale,
                discord_name=discord_miembro,
                team_name=context.team_profile.team_name,
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
    await bot.add_cog(TeamRosterModificationCog(bot))
