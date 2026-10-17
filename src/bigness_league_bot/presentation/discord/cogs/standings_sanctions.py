from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.match_replays import MatchReplayDivision
from bigness_league_bot.infrastructure.discord.channel_access_management import ensure_allowed_member, user_audit_label
from bigness_league_bot.infrastructure.discord.error_handling import classify_app_command_error
from bigness_league_bot.infrastructure.google.standings_sanctions_repository import (
    GoogleSheetsStandingsSanctionsRepository, SanctionChangeResult,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import GoogleSheetsTeamRepository
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

_keys = I18N.sanctions.commands
_division_choices = [app_commands.Choice(name="GOLD", value="gold"), app_commands.Choice(name="SILVER", value="silver")]


class StandingsSanctionsCog(commands.Cog):
    sancion = app_commands.Group(
        name=localized_locale_str(_keys.name), description=localized_locale_str(_keys.description), guild_only=True,
    )

    async def _prepare(self, interaction: discord.Interaction[BignessLeagueBot]) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise app_commands.NoPrivateMessage()
        ensure_allowed_member(interaction.user)
        await interaction.response.defer(thinking=True, ephemeral=True)

    async def _rosters(self, interaction: discord.Interaction[BignessLeagueBot]) -> tuple[tuple[str, str], ...]:
        metadata = await GoogleSheetsTeamRepository(interaction.client.settings).list_team_sheet_metadata()
        return tuple((team.worksheet_title, team.team_name) for team in metadata)

    @sancion.command(name=localized_locale_str(_keys.add_name), description=localized_locale_str(_keys.add_description))
    @app_commands.choices(division=_division_choices)
    @app_commands.describe(
        division=localized_locale_str(_keys.division), equipo=localized_locale_str(_keys.team),
        puntos=localized_locale_str(_keys.points), motivo=localized_locale_str(_keys.reason),
        tipo=localized_locale_str(_keys.kind), jornada=localized_locale_str(_keys.matchday),
        partido=localized_locale_str(_keys.match_number),
    )
    async def add(
            self, interaction: discord.Interaction[BignessLeagueBot], division: app_commands.Choice[str],
            equipo: discord.Role, puntos: app_commands.Range[int, 1], motivo: app_commands.Range[str, 1, 500],
            tipo: Literal["AI", "OTRA"] = "AI", jornada: app_commands.Range[int, 1, 7] | None = None,
            partido: app_commands.Range[int, 1, 4] | None = None,
    ) -> None:
        await self._prepare(interaction)
        result = await GoogleSheetsStandingsSanctionsRepository(interaction.client.settings).add(
            MatchReplayDivision(division.value), identifier=str(interaction.id), team_name=equipo.name,
            points=puntos, reason=motivo, kind=tipo, matchday=jornada, match_number=partido,
            actor=user_audit_label(interaction.user), rosters=await self._rosters(interaction),
        )
        await self._send_result(interaction, result, annulled=False)

    @sancion.command(name=localized_locale_str(_keys.annul_name),
                     description=localized_locale_str(_keys.annul_description))
    @app_commands.choices(division=_division_choices)
    @app_commands.describe(
        division=localized_locale_str(_keys.division), id=localized_locale_str(_keys.identifier),
        motivo=localized_locale_str(_keys.reason),
    )
    async def annul(
            self, interaction: discord.Interaction[BignessLeagueBot], division: app_commands.Choice[str],
            id: str, motivo: app_commands.Range[str, 1, 500],
    ) -> None:
        await self._prepare(interaction)
        result = await GoogleSheetsStandingsSanctionsRepository(interaction.client.settings).annul(
            MatchReplayDivision(division.value), identifier=id.strip(), reason=motivo,
            actor=user_audit_label(interaction.user), rosters=await self._rosters(interaction),
        )
        await self._send_result(interaction, result, annulled=True)

    @sancion.command(name=localized_locale_str(_keys.list_name),
                     description=localized_locale_str(_keys.list_description))
    @app_commands.choices(division=_division_choices)
    @app_commands.describe(division=localized_locale_str(_keys.division))
    async def list_sanctions(
            self, interaction: discord.Interaction[BignessLeagueBot], division: app_commands.Choice[str],
    ) -> None:
        await self._prepare(interaction)
        scope, records = await GoogleSheetsStandingsSanctionsRepository(interaction.client.settings).list(
            MatchReplayDivision(division.value))
        translate = interaction.client.localizer.translate
        keys = I18N.sanctions.messages
        if not records:
            await interaction.followup.send(
                translate(keys.empty, locale=interaction.locale, worksheet=scope.worksheet),
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        heading = translate(keys.list_title, locale=interaction.locale,
                            worksheet=discord.utils.escape_markdown(scope.worksheet))
        page = heading
        for record in records:
            block = translate(
                keys.list_row, locale=interaction.locale,
                team=discord.utils.escape_markdown(record.team_name), identifier=record.identifier,
                state=translate(keys.active if record.active else keys.annulled_state, locale=interaction.locale),
                points=record.points, kind=record.kind, matchday=record.matchday or "—",
                match_number=record.match_number or "—", reason=discord.utils.escape_markdown(record.reason),
            )
            if len(page) + len(block) + 2 > 1900:
                await interaction.followup.send(page, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
                page = heading
            page += "\n\n" + block
        await interaction.followup.send(page, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def _send_result(
            self, interaction: discord.Interaction[BignessLeagueBot], result: SanctionChangeResult, *, annulled: bool,
    ) -> None:
        sanction = result.sanction
        message = interaction.client.localizer.translate(
            I18N.sanctions.messages.annulled if annulled else I18N.sanctions.messages.added,
            locale=interaction.locale, identifier=sanction.identifier,
            team=discord.utils.escape_markdown(sanction.team_name), points=sanction.points,
            worksheet=discord.utils.escape_markdown(sanction.worksheet), kind=sanction.kind,
            reason=discord.utils.escape_markdown(sanction.annulment_reason if annulled else sanction.reason),
        )
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

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
    await bot.add_cog(StandingsSanctionsCog())
