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

from bigness_league_bot.application.services.match_replay_summaries import (
    collect_match_replay_standings_team_names,
)
from bigness_league_bot.application.services.match_replays import (
    MATCH_REPLAY_EXTENSION,
    MatchReplayDivision,
    MatchReplayValidationError,
    validate_replay_filenames,
)
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    UnsupportedChannelError,
    ensure_allowed_member,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.match_channel_creation import (
    validate_match_team_roles,
)
from bigness_league_bot.infrastructure.discord.match_replay_assets import (
    guild_icon_url,
    team_logo_url_map,
)
from bigness_league_bot.infrastructure.discord.match_replay_discord_helpers import (
    render_division_emoji,
    to_user_error,
)
from bigness_league_bot.infrastructure.discord.match_replay_workflows import (
    process_administrative_result,
    process_replay_attachments,
)
from bigness_league_bot.infrastructure.discord.match_summary_images import (
    build_match_standings_image_file,
)
from bigness_league_bot.infrastructure.discord.message_links import fetch_linked_message
from bigness_league_bot.infrastructure.google.match_replay_repository import (
    GoogleSheetsMatchReplayRepository,
)
from bigness_league_bot.infrastructure.google.match_standings_repository import (
    GoogleSheetsMatchStandingsRepository,
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


MATCH_REPLAY_DIVISION_CHOICES: list[app_commands.Choice[str]] = [
    _string_choice(
        localized_locale_str(I18N.commands.match_replays.choices.gold_division),
        MatchReplayDivision.GOLD.value,
    ),
    _string_choice(
        localized_locale_str(I18N.commands.match_replays.choices.silver_division),
        MatchReplayDivision.SILVER.value,
    ),
]


class MatchReplaysCog(commands.Cog):
    @app_commands.command(
        name=localized_locale_str(I18N.commands.match_replays.upload_replays.name),
        description=localized_locale_str(
            I18N.commands.match_replays.upload_replays.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        local=localized_locale_str(
            I18N.commands.match_replays.upload_replays.parameters.local.description
        ),
        visitante=localized_locale_str(
            I18N.commands.match_replays.upload_replays.parameters.visitante.description
        ),
        replay_1=localized_locale_str(
            I18N.commands.match_replays.upload_replays.parameters.replay_1.description
        ),
        replay_2=localized_locale_str(
            I18N.commands.match_replays.upload_replays.parameters.replay_2.description
        ),
        replay_3=localized_locale_str(
            I18N.commands.match_replays.upload_replays.parameters.replay_3.description
        ),
        replay_4=localized_locale_str(
            I18N.commands.match_replays.upload_replays.parameters.replay_4.description
        ),
        replay_5=localized_locale_str(
            I18N.commands.match_replays.upload_replays.parameters.replay_5.description
        ),
    )
    async def upload_replays(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            local: discord.Role,
            visitante: discord.Role,
            replay_1: discord.Attachment,
            replay_2: discord.Attachment,
            replay_3: discord.Attachment,
            replay_4: discord.Attachment | None = None,
            replay_5: discord.Attachment | None = None,
    ) -> None:
        guild = _ensure_guild_member_interaction(interaction)
        _ensure_match_team_roles(interaction, guild=guild, local=local, visitante=visitante)
        attachments = tuple(
            attachment
            for attachment in (replay_1, replay_2, replay_3, replay_4, replay_5)
            if attachment is not None
        )
        try:
            validate_replay_filenames(attachment.filename for attachment in attachments)
        except MatchReplayValidationError as exc:
            raise to_user_error(exc) from exc

        await interaction.response.defer(thinking=True, ephemeral=True)
        await process_replay_attachments(
            interaction,
            local=local,
            visitante=visitante,
            attachments=attachments,
        )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.match_replays.link_replays.name),
        description=localized_locale_str(
            I18N.commands.match_replays.link_replays.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        local=localized_locale_str(
            I18N.commands.match_replays.link_replays.parameters.local.description
        ),
        visitante=localized_locale_str(
            I18N.commands.match_replays.link_replays.parameters.visitante.description
        ),
        mensaje=localized_locale_str(
            I18N.commands.match_replays.link_replays.parameters.mensaje.description
        ),
    )
    async def link_replays(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            local: discord.Role,
            visitante: discord.Role,
            mensaje: str,
    ) -> None:
        guild = _ensure_guild_member_interaction(interaction)
        _ensure_match_team_roles(interaction, guild=guild, local=local, visitante=visitante)

        await interaction.response.defer(thinking=True, ephemeral=True)
        linked_message = await fetch_linked_message(interaction.client, guild, mensaje)
        attachments = tuple(
            attachment
            for attachment in linked_message.attachments
            if attachment.filename.lower().endswith(MATCH_REPLAY_EXTENSION)
        )
        await process_replay_attachments(
            interaction,
            local=local,
            visitante=visitante,
            attachments=attachments,
        )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.match_replays.free_win.name),
        description=localized_locale_str(
            I18N.commands.match_replays.free_win.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        local=localized_locale_str(
            I18N.commands.match_replays.free_win.parameters.local.description
        ),
        visitante=localized_locale_str(
            I18N.commands.match_replays.free_win.parameters.visitante.description
        ),
        ganador=localized_locale_str(
            I18N.commands.match_replays.free_win.parameters.winner.description
        ),
    )
    async def replay_free_win(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            local: discord.Role,
            visitante: discord.Role,
            ganador: discord.Role,
    ) -> None:
        await process_administrative_result(
            interaction,
            local=local,
            visitante=visitante,
            winner=ganador,
            suffix="FW",
        )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.match_replays.walkover.name),
        description=localized_locale_str(
            I18N.commands.match_replays.walkover.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        local=localized_locale_str(
            I18N.commands.match_replays.walkover.parameters.local.description
        ),
        visitante=localized_locale_str(
            I18N.commands.match_replays.walkover.parameters.visitante.description
        ),
        ganador=localized_locale_str(
            I18N.commands.match_replays.walkover.parameters.winner.description
        ),
    )
    async def replay_walkover(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            local: discord.Role,
            visitante: discord.Role,
            ganador: discord.Role,
    ) -> None:
        await process_administrative_result(
            interaction,
            local=local,
            visitante=visitante,
            winner=ganador,
            suffix="WO",
        )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.match_replays.null_result.name),
        description=localized_locale_str(
            I18N.commands.match_replays.null_result.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        local=localized_locale_str(
            I18N.commands.match_replays.null_result.parameters.local.description
        ),
        visitante=localized_locale_str(
            I18N.commands.match_replays.null_result.parameters.visitante.description
        ),
    )
    async def replay_nulo(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            local: discord.Role,
            visitante: discord.Role,
    ) -> None:
        await process_administrative_result(
            interaction,
            local=local,
            visitante=visitante,
            winner=None,
            suffix=None,
        )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.match_replays.refresh_standings.name),
        description=localized_locale_str(
            I18N.commands.match_replays.refresh_standings.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.choices(division=MATCH_REPLAY_DIVISION_CHOICES)
    @app_commands.describe(
        division=localized_locale_str(
            I18N.commands.match_replays.refresh_standings.parameters.division.description
        ),
    )
    async def refresh_standings(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            division: app_commands.Choice[str],
    ) -> None:
        guild = _ensure_guild_member_interaction(interaction)
        await interaction.response.defer(thinking=True)
        division_value = MatchReplayDivision(division.value)
        replay_repository = GoogleSheetsMatchReplayRepository(interaction.client.settings)
        standings_repository = GoogleSheetsMatchStandingsRepository(interaction.client.settings)
        roster_data = await replay_repository.list_division_roster_data(division_value.label)
        standings_result = await standings_repository.refresh_division_standings_report(
            division_value,
            team_names=collect_match_replay_standings_team_names(
                roster_players=roster_data.roster_players,
                fallback_team_names=(),
            ),
        )
        image_file: discord.File | None = None
        image_warning = ""
        try:
            image_file = build_match_standings_image_file(
                division_name=division_value.label,
                rows=standings_result.rows,
                font_path=interaction.client.settings.team_profile_font_path,
                team_logo_urls=team_logo_url_map(roster_data.team_logos),
                fallback_logo_url=guild_icon_url(guild),
            )
        except RuntimeError:
            image_warning = interaction.client.localizer.translate(
                I18N.messages.match_replays.image_render_failed,
                locale=interaction.locale,
            )

        message = interaction.client.localizer.translate(
            I18N.messages.match_replays.standings_refreshed,
            locale=interaction.locale,
            division_emoji=render_division_emoji(guild, interaction.client, division_value),
        )
        if image_file is None:
            await interaction.followup.send(content=message + image_warning)
        else:
            await interaction.followup.send(content=message, file=image_file)

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


def _ensure_guild_member_interaction(
        interaction: discord.Interaction[BignessLeagueBot],
) -> discord.Guild:
    guild = interaction.guild
    if guild is None or not isinstance(interaction.user, discord.Member):
        raise UnsupportedChannelError(localize(I18N.errors.channel_management.server_only))
    ensure_allowed_member(interaction.user)
    return guild


def _ensure_match_team_roles(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        guild: discord.Guild,
        local: discord.Role,
        visitante: discord.Role,
) -> None:
    validate_match_team_roles(
        guild,
        team_one=local,
        team_two=visitante,
        range_start_role_id=interaction.client.settings.channel_access_range_start_role_id,
        range_end_role_id=interaction.client.settings.channel_access_range_end_role_id,
    )


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(MatchReplaysCog())
