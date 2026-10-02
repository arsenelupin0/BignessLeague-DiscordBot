from __future__ import annotations

import io
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.discord_verification import normalize_identity
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ensure_allowed_member, get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.discord_verification import verify_discord_rosters
from bigness_league_bot.infrastructure.discord.discord_verification_messages import build_verification_pages
from bigness_league_bot.infrastructure.discord.error_handling import classify_app_command_error
from bigness_league_bot.infrastructure.google.team_sheet_repository import GoogleSheetsTeamRepository
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str
from bigness_league_bot.presentation.discord.views.discord_verification import DiscordVerificationView

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class DiscordVerificationCog(commands.Cog):
    @app_commands.command(
        name=localized_locale_str(I18N.commands.discord_verification.name),
        description=localized_locale_str(I18N.commands.discord_verification.description),
    )
    @app_commands.guild_only()
    @app_commands.describe(equipo=localized_locale_str(I18N.commands.discord_verification.team_description))
    async def verification(
            self, interaction: discord.Interaction[BignessLeagueBot], equipo: str | None = None,
    ) -> None:
        ensure_allowed_member(interaction.user)
        await interaction.response.defer(thinking=True)
        settings = interaction.client.settings
        profiles = await GoogleSheetsTeamRepository(settings).list_team_profiles()
        if equipo is not None:
            profiles = tuple(p for p in profiles if normalize_identity(p.team_name) == normalize_identity(equipo))
            if not profiles:
                raise CommandUserError(localize(I18N.errors.discord_verification.team_not_found))
        catalog = get_channel_access_role_catalog(
            interaction.guild, settings.channel_access_range_start_role_id,
            settings.channel_access_range_end_role_id, allow_empty=True,
        )
        reports = await verify_discord_rosters(interaction.guild, profiles, settings=settings, role_catalog=catalog)
        pages = build_verification_pages(
            reports, localizer=interaction.client.localizer, locale=interaction.locale,
            missing_only=equipo is not None,
        )
        if len(pages) == 1:
            await interaction.followup.send(
                content=pages[0], allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        view = DiscordVerificationView(
            pages=pages, actor_id=interaction.user.id,
            localizer=interaction.client.localizer, locale=interaction.locale,
        )
        view.message = await interaction.followup.send(
            content=view.content(), view=view,
            file=discord.File(io.BytesIO("\n\n".join(pages).encode("utf-8")), filename="verificacion_discord.md"),
            allowed_mentions=discord.AllowedMentions.none(),
            wait=True,
        )

    @verification.autocomplete("equipo")
    async def team_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        try:
            ensure_allowed_member(interaction.user)
            metadata = await GoogleSheetsTeamRepository(interaction.client.settings).list_team_sheet_metadata()
        except CommandUserError:
            return []
        names = sorted({m.team_name for m in metadata}, key=str.casefold)
        return [app_commands.Choice(name=name, value=name) for name in names
                if len(name) <= 100 and normalize_identity(current) in normalize_identity(name)][:25]

    async def cog_app_command_error(self, interaction: discord.Interaction,
                                    error: app_commands.AppCommandError) -> None:
        details = classify_app_command_error(error)
        message = interaction.client.localizer.render(details.user_message, locale=interaction.locale)
        if interaction.response.is_done():
            await interaction.followup.send(message, allowed_mentions=discord.AllowedMentions.none())
        else:
            await interaction.response.send_message(message, ephemeral=True,
                                                    allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(DiscordVerificationCog())
