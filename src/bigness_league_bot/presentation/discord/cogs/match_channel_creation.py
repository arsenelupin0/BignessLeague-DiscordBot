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

from bigness_league_bot.application.services.match_channel_creation import (
    MATCH_BEST_OF_MAX,
    MATCH_BEST_OF_MIN,
    MATCH_COURTESY_MINUTES_MAX,
    MATCH_COURTESY_MINUTES_MIN,
    MATCH_NUMBER_MAX,
    MATCH_NUMBER_MIN,
    MatchChannelDivision,
)
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_management import (
    UnsupportedChannelError,
    ensure_allowed_member,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.match_channel_creation import (
    build_match_channel_specification,
    create_match_channel,
    resolve_match_channel_category,
    validate_match_team_roles,
)
from bigness_league_bot.infrastructure.discord.match_channel_welcome import (
    send_match_channel_welcome_message,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


def _string_choice(
        name: str | app_commands.locale_str,
        value: str,
) -> app_commands.Choice[str]:
    return app_commands.Choice[str](name=name, value=value)


MATCH_CHANNEL_CATEGORY_CHOICES: list[app_commands.Choice[str]] = [
    _string_choice(
        localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.choices.gold_division
        ),
        MatchChannelDivision.GOLD.value,
    ),
    _string_choice(
        localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.choices.silver_division
        ),
        MatchChannelDivision.SILVER.value,
    ),
]


class MatchChannelCreation(commands.Cog):
    @app_commands.command(
        name=localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.name
        ),
        description=localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        jornada=localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.parameters.jornada.description
        ),
        partido=localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.parameters.partido.description
        ),
        minutos_cortesia=localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.parameters.courtesy_minutes.description
        ),
        fecha=localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.parameters.date.description
        ),
        hora=localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.parameters.time.description
        ),
        bo_x=localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.parameters.best_of.description
        ),
        categoria=localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.parameters.categoria.description
        ),
        equipo_1=localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.parameters.equipo_1.description
        ),
        equipo_2=localized_locale_str(
            I18N.commands.match_channel_creation.create_match_channel.parameters.equipo_2.description
        ),
    )
    @app_commands.choices(categoria=MATCH_CHANNEL_CATEGORY_CHOICES)
    async def create_match_channel_command(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            jornada: app_commands.Range[int, MATCH_NUMBER_MIN, MATCH_NUMBER_MAX],
            partido: app_commands.Range[int, MATCH_NUMBER_MIN, MATCH_NUMBER_MAX],
            minutos_cortesia: app_commands.Range[int, MATCH_COURTESY_MINUTES_MIN, MATCH_COURTESY_MINUTES_MAX],
            fecha: str,
            hora: str,
            bo_x: app_commands.Range[int, MATCH_BEST_OF_MIN, MATCH_BEST_OF_MAX],
            categoria: app_commands.Choice[str],
            equipo_1: discord.Role,
            equipo_2: discord.Role,
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        ensure_allowed_member(interaction.user)
        division = MatchChannelDivision(categoria.value)
        validate_match_team_roles(
            guild,
            team_one=equipo_1,
            team_two=equipo_2,
            range_start_role_id=interaction.client.settings.channel_access_range_start_role_id,
            range_end_role_id=interaction.client.settings.channel_access_range_end_role_id,
        )
        category = resolve_match_channel_category(
            guild,
            division=division,
            gold_division_category_id=interaction.client.settings.gold_division_category_id,
            silver_division_category_id=interaction.client.settings.silver_division_category_id,
        )
        specification = build_match_channel_specification(
            jornada=jornada,
            partido=partido,
            courtesy_minutes=minutos_cortesia,
            date_value=fecha,
            time_value=hora,
            best_of=bo_x,
            timezone_name=interaction.client.settings.timezone,
        )

        await interaction.response.defer(thinking=True)
        creation_result = await create_match_channel(
            guild=guild,
            actor=interaction.user,
            category=category,
            specification=specification,
            team_one=equipo_1,
            team_two=equipo_2,
        )
        await send_match_channel_welcome_message(
            channel=creation_result.channel,
            localizer=interaction.client.localizer,
            locale=interaction.locale,
            settings=interaction.client.settings,
            specification=specification,
            team_one=equipo_1,
            team_two=equipo_2,
        )
        await interaction.followup.send(
            interaction.client.localizer.render(
                creation_result.summary,
                locale=interaction.locale,
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
    await bot.add_cog(MatchChannelCreation())
