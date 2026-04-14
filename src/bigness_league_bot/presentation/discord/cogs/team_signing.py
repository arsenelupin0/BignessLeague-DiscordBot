from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.team_signing import (
    TeamSigningParseError,
    parse_team_signing_message,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_management import (
    UnsupportedChannelError,
    ensure_allowed_member,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.team_signing import (
    fetch_linked_message,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class TeamSigningCog(commands.Cog):
    @app_commands.command(
        name=localized_locale_str(I18N.commands.team_signing.make_signing.name),
        description=localized_locale_str(
            I18N.commands.team_signing.make_signing.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        enlace_mensaje=localized_locale_str(
            I18N.commands.team_signing.make_signing.parameters.message_link.description
        )
    )
    async def make_signing(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            enlace_mensaje: str,
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        ensure_allowed_member(interaction.user)

        await interaction.response.defer(thinking=True)
        linked_message = await fetch_linked_message(
            interaction.client,
            guild,
            enlace_mensaje,
        )
        try:
            signing_batch = parse_team_signing_message(linked_message.content)
        except TeamSigningParseError as exc:
            raise CommandUserError(
                localize(
                    I18N.errors.team_signing.invalid_message_format,
                    details=str(exc),
                )
            ) from exc

        repository = GoogleSheetsTeamRepository(interaction.client.settings)
        result = await repository.register_team_signings(signing_batch)
        await interaction.followup.send(
            interaction.client.localizer.translate(
                I18N.actions.team_signing.completed,
                locale=interaction.locale,
                division_name=result.worksheet_title,
                team_name=result.team_name,
                inserted_count=str(result.inserted_count),
                total_players=str(result.total_players),
            )
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
            await interaction.followup.send(message)
            return

        await interaction.response.send_message(message)


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(TeamSigningCog())
