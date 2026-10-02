from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.league_seedings import LeagueTeam, generate_league_seedings
from bigness_league_bot.infrastructure.discord.channel_access_management import ensure_allowed_member
from bigness_league_bot.infrastructure.discord.error_handling import classify_app_command_error
from bigness_league_bot.infrastructure.discord.league_seedings_messages import build_seedings_pages
from bigness_league_bot.infrastructure.google.league_seedings_repository import GoogleSheetsLeagueSeedingsRepository
from bigness_league_bot.infrastructure.google.team_sheet_repository import GoogleSheetsTeamRepository
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class LeagueSeedingsCog(commands.Cog):
    def __init__(self) -> None:
        self._seedings_lock = asyncio.Lock()

    @app_commands.command(
        name=localized_locale_str(I18N.commands.league_seedings.name),
        description=localized_locale_str(I18N.commands.league_seedings.description),
    )
    @app_commands.guild_only()
    async def league_seedings(self, interaction: discord.Interaction[BignessLeagueBot]) -> None:
        if not isinstance(interaction.user, discord.Member):
            raise app_commands.NoPrivateMessage()
        ensure_allowed_member(interaction.user)
        await interaction.response.defer(thinking=True)
        async with self._seedings_lock:
            metadata = await GoogleSheetsTeamRepository(interaction.client.settings).list_team_sheet_metadata()
            schedules = generate_league_seedings(LeagueTeam(team.worksheet_title, team.team_name) for team in metadata)
            destinations = await GoogleSheetsLeagueSeedingsRepository(interaction.client.settings).write_seedings(
                schedules)
        localizer = interaction.client.localizer
        locale = interaction.locale
        pages = tuple(page for schedule, destination in zip(schedules, destinations) for page in build_seedings_pages(
            schedule, destination, localizer=localizer, locale=locale,
        ))
        await interaction.followup.send(
            content=localizer.translate(I18N.messages.league_seedings.overview, locale=locale),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        for page in pages:
            await interaction.followup.send(content=page, allowed_mentions=discord.AllowedMentions.none())

    async def cog_app_command_error(
            self, interaction: discord.Interaction[BignessLeagueBot], error: app_commands.AppCommandError,
    ) -> None:
        details = classify_app_command_error(error)
        message = interaction.client.localizer.render(details.user_message, locale=interaction.locale)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        else:
            await interaction.response.send_message(message, ephemeral=True,
                                                    allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(LeagueSeedingsCog())
