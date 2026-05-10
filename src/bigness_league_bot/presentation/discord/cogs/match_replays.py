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

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.match_replay_groups import (
    build_match_replay_group_path,
    build_match_replay_title,
    parse_match_channel_reference,
)
from bigness_league_bot.application.services.match_replay_summaries import (
    build_match_replay_roster_validation_summary,
    collect_match_replay_standings_team_names,
)
from bigness_league_bot.application.services.match_replays import (
    InvalidReplayCountError,
    InvalidReplayExtensionError,
    MATCH_REPLAY_MAX_FILES,
    MATCH_REPLAY_MIN_FILES,
    MatchReplayDivision,
    MatchReplayValidationError,
    build_match_replay_report,
    format_match_replay_game_scores,
    resolve_match_replay_report_players,
    sort_match_replay_games_by_replay_date,
    validate_replay_filenames,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.ballchasing.client import (
    BallchasingClient,
    BallchasingReplayUpload,
)
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
    write_replay_diagnostic_copy,
)
from bigness_league_bot.infrastructure.discord.match_replay_messages import (
    format_match_replay_roster_validation,
)
from bigness_league_bot.infrastructure.discord.match_summary_images import (
    build_match_replay_summary_image_file,
    build_match_standings_image_file,
)
from bigness_league_bot.infrastructure.google.match_replay_repository import (
    GoogleSheetsMatchReplayRepository,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)

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
        resumen_imagen=localized_locale_str(
            I18N.commands.match_replays.upload_replays.parameters.summary_image.description
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
            resumen_imagen: bool = False,
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(localize(I18N.errors.channel_management.server_only))

        ensure_allowed_member(interaction.user)
        validate_match_team_roles(
            guild,
            team_one=local,
            team_two=visitante,
            range_start_role_id=interaction.client.settings.channel_access_range_start_role_id,
            range_end_role_id=interaction.client.settings.channel_access_range_end_role_id,
        )
        attachments = tuple(
            attachment
            for attachment in (replay_1, replay_2, replay_3, replay_4, replay_5)
            if attachment is not None
        )
        try:
            validate_replay_filenames(attachment.filename for attachment in attachments)
        except MatchReplayValidationError as exc:
            raise _to_user_error(exc) from exc

        await interaction.response.defer(thinking=True)
        channel_name = _interaction_channel_name(interaction)
        channel_reference = parse_match_channel_reference(channel_name)
        if channel_reference is None:
            raise CommandUserError(
                localize(
                    I18N.errors.match_replays.channel_group_context_missing,
                    channel_name=channel_name or "-",
                )
            )
        division_value = _resolve_replay_division_from_channel(interaction)
        jornada = channel_reference.matchday
        partido = channel_reference.match_number

        diagnostics_dir = interaction.client.settings.log_dir.parent / "match_replays" / "uploads"
        uploads = await asyncio.gather(
            *(
                _read_replay_attachment(
                    attachment,
                    diagnostics_dir=diagnostics_dir,
                )
                for attachment in attachments
            )
        )
        repository = GoogleSheetsMatchReplayRepository(interaction.client.settings)
        existing_replays = await repository.list_existing_replay_entries(division_value)
        existing_sha256 = {
            replay.replay_sha256.casefold()
            for replay in existing_replays
            if replay.replay_sha256
        }
        if uploads and all(upload.sha256 and upload.sha256.casefold() in existing_sha256 for upload in uploads):
            await interaction.followup.send(
                interaction.client.localizer.translate(
                    I18N.messages.match_replays.uploaded.all_duplicates,
                    locale=interaction.locale,
                    replay_count=len(uploads),
                )
            )
            return

        ballchasing_client = _build_ballchasing_client(interaction.client)
        ballchasing_group_id = await _resolve_ballchasing_group_id(
            interaction,
            ballchasing_client=ballchasing_client,
            division=division_value,
            matchday=jornada,
            team_one_name=local.name,
            team_two_name=visitante.name,
        )
        games = []
        failed_uploads: list[str] = []
        for index, upload in enumerate(uploads, start=1):
            try:
                game = await ballchasing_client.upload_and_fetch_replay(
                    upload,
                    title=build_match_replay_title(
                        matchday=jornada,
                        game_number=index,
                        team_one_name=local.name,
                        team_two_name=visitante.name,
                    ),
                    group_id=ballchasing_group_id,
                )
            except CommandUserError as exc:
                LOGGER.warning(
                    "No se pudo procesar la replay filename=%s game_number=%s reason=%s",
                    upload.filename,
                    index,
                    exc,
                )
                failed_uploads.append(f"Game {index} ({upload.filename})")
                continue
            games.append(game)

        ordered_games = sort_match_replay_games_by_replay_date(games)
        for index, game in enumerate(ordered_games, start=1):
            await ballchasing_client.update_replay_metadata(
                game.replay_id,
                {
                    "title": build_match_replay_title(
                        matchday=jornada,
                        game_number=index,
                        team_one_name=local.name,
                        team_two_name=visitante.name,
                    )
                },
            )

        try:
            report = build_match_replay_report(
                division=division_value,
                matchday=jornada,
                match_number=partido,
                team_one_name=local.name,
                team_two_name=visitante.name,
                games=ordered_games,
            )
        except MatchReplayValidationError as exc:
            raise _to_user_error(exc) from exc
        roster_data = await repository.list_division_roster_data(
            report.division.label
        )
        roster_players = roster_data.roster_players
        report = resolve_match_replay_report_players(report, roster_players)
        append_result = await repository.append_report(report)
        standings_sheet_name = ""
        if append_result.appended_games > 0:
            standings_sheet_name = await repository.sync_report_to_standings(
                report,
                team_names=collect_match_replay_standings_team_names(
                    roster_players=roster_players,
                    fallback_team_names=(report.team_one_name, report.team_two_name),
                ),
            )
        standings_update = ""
        if standings_sheet_name:
            standings_update = interaction.client.localizer.translate(
                I18N.messages.match_replays.uploaded.standings_update,
                locale=interaction.locale,
                standings_sheet_name=standings_sheet_name,
            )

        unresolved = ""
        if report.unresolved_winners:
            unresolved = interaction.client.localizer.translate(
                I18N.messages.match_replays.uploaded.unresolved_winners,
                locale=interaction.locale,
                winners=", ".join(report.unresolved_winners),
            )
        failed_replays = ""
        if failed_uploads:
            failed_replays = interaction.client.localizer.translate(
                I18N.messages.match_replays.uploaded.failed_replays,
                locale=interaction.locale,
                failed_replays=", ".join(failed_uploads),
            )
        skipped_duplicates = ""
        skipped_count = len(report.games) - append_result.appended_games
        if skipped_count > 0:
            skipped_duplicates = interaction.client.localizer.translate(
                I18N.messages.match_replays.uploaded.skipped_duplicates,
                locale=interaction.locale,
                skipped_count=skipped_count,
                replay_ids=", ".join(append_result.skipped_replay_ids) or "-",
            )

        roster_validation = format_match_replay_roster_validation(
            localizer=interaction.client.localizer,
            locale=interaction.locale,
            summary=build_match_replay_roster_validation_summary(report),
        )
        image_file: discord.File | None = None
        image_warning = ""
        if resumen_imagen:
            try:
                image_file = build_match_replay_summary_image_file(
                    report=report,
                    font_path=interaction.client.settings.team_profile_font_path,
                    team_logo_urls=team_logo_url_map(roster_data.team_logos),
                    fallback_logo_url=guild_icon_url(interaction.guild),
                )
            except RuntimeError:
                LOGGER.exception("No se pudo renderizar la imagen resumen de replays")
                image_warning = interaction.client.localizer.translate(
                    I18N.messages.match_replays.image_render_failed,
                    locale=interaction.locale,
                )

        message = interaction.client.localizer.translate(
            I18N.messages.match_replays.uploaded.summary,
            locale=interaction.locale,
            division=report.division.label,
            jornada=report.matchday,
            partido=report.match_number,
            team_one=report.team_one_name,
            team_two=report.team_two_name,
            series_score=report.series_score,
            game_scores=format_match_replay_game_scores(report),
            roster_validation=roster_validation,
            replay_count=append_result.appended_games,
            sheet_name=append_result.worksheet_name,
            standings_update=standings_update,
            unresolved_winners=unresolved,
            failed_replays=failed_replays,
            skipped_duplicates=skipped_duplicates,
            image_warning=image_warning,
        )
        if image_file is None:
            await interaction.followup.send(content=message)
        else:
            await interaction.followup.send(content=message, file=image_file)

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
        imagen=localized_locale_str(
            I18N.commands.match_replays.refresh_standings.parameters.image.description
        ),
    )
    async def refresh_standings(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            division: app_commands.Choice[str],
            imagen: bool = False,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(localize(I18N.errors.channel_management.server_only))

        ensure_allowed_member(interaction.user)
        await interaction.response.defer(thinking=True)
        division_value = MatchReplayDivision(division.value)
        repository = GoogleSheetsMatchReplayRepository(interaction.client.settings)
        roster_data = await repository.list_division_roster_data(division_value.label)
        standings_result = await repository.refresh_division_standings_report(
            division_value,
            team_names=collect_match_replay_standings_team_names(
                roster_players=roster_data.roster_players,
                fallback_team_names=(),
            ),
        )
        image_file: discord.File | None = None
        image_warning = ""
        if imagen:
            try:
                image_file = build_match_standings_image_file(
                    division_name=division_value.label,
                    rows=standings_result.rows,
                    font_path=interaction.client.settings.team_profile_font_path,
                    team_logo_urls=team_logo_url_map(roster_data.team_logos),
                    fallback_logo_url=guild_icon_url(interaction.guild),
                )
            except RuntimeError:
                LOGGER.exception("No se pudo renderizar la imagen de clasificacion")
                image_warning = interaction.client.localizer.translate(
                    I18N.messages.match_replays.image_render_failed,
                    locale=interaction.locale,
                )

        message = interaction.client.localizer.translate(
            I18N.messages.match_replays.standings_refreshed,
            locale=interaction.locale,
            division=division_value.label,
            standings_sheet_name=standings_result.worksheet_name,
            image_warning=image_warning,
        )
        if image_file is None:
            await interaction.followup.send(content=message)
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


async def _read_replay_attachment(
        attachment: discord.Attachment,
        *,
        diagnostics_dir: Path,
) -> BallchasingReplayUpload:
    content = await attachment.read()
    digest = hashlib.sha256(content).hexdigest()
    diagnostics_path = write_replay_diagnostic_copy(
        diagnostics_dir=diagnostics_dir,
        filename=attachment.filename,
        content=content,
        digest=digest,
    )
    LOGGER.info(
        "Replay descargada desde Discord filename=%s discord_size=%s downloaded_size=%s sha256=%s content_type=%s saved_to=%s",
        attachment.filename,
        attachment.size,
        len(content),
        digest,
        attachment.content_type or "-",
        diagnostics_path,
    )
    if attachment.size is not None and attachment.size != len(content):
        LOGGER.warning(
            "El tamano descargado de la replay no coincide con Discord filename=%s discord_size=%s downloaded_size=%s",
            attachment.filename,
            attachment.size,
            len(content),
        )
    return BallchasingReplayUpload(
        filename=attachment.filename,
        content=content,
        expected_size=attachment.size,
        sha256=digest,
        content_type=attachment.content_type,
    )


async def _resolve_ballchasing_group_id(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        ballchasing_client: BallchasingClient,
        division: MatchReplayDivision,
        matchday: int,
        team_one_name: str,
        team_two_name: str,
) -> str | None:
    settings = interaction.client.settings
    if not settings.ballchasing_auto_groups_enabled:
        LOGGER.info(
            "Grupos automaticos de Ballchasing desactivados; se usara el grupo configurado como destino final group_id=%s",
            settings.ballchasing_group_id or "-",
        )
        return settings.ballchasing_group_id
    if not settings.ballchasing_group_id:
        raise CommandUserError(localize(I18N.errors.match_replays.ballchasing_group_missing))

    group_path = build_match_replay_group_path(
        division=division,
        matchday=matchday,
        team_one_name=team_one_name,
        team_two_name=team_two_name,
    )
    resolved_group = await ballchasing_client.ensure_group_path(
        parent_group_id=settings.ballchasing_group_id,
        group_names=group_path.names,
    )
    LOGGER.info(
        "Grupo Ballchasing resuelto root_group_id=%s target_group_id=%s path=%s",
        settings.ballchasing_group_id,
        resolved_group.id,
        group_path.label,
    )
    return resolved_group.id


def _interaction_channel_name(
        interaction: discord.Interaction[BignessLeagueBot],
) -> str:
    channel = interaction.channel
    channel_name = getattr(channel, "name", "")
    if isinstance(channel_name, str):
        return channel_name
    return ""


def _resolve_replay_division_from_channel(
        interaction: discord.Interaction[BignessLeagueBot],
) -> MatchReplayDivision:
    category_id = _interaction_channel_category_id(interaction)
    settings = interaction.client.settings
    if category_id == settings.gold_division_category_id:
        return MatchReplayDivision.GOLD
    if category_id == settings.silver_division_category_id:
        return MatchReplayDivision.SILVER

    raise CommandUserError(
        localize(
            I18N.errors.match_replays.channel_division_context_missing,
            channel_name=_interaction_channel_name(interaction) or "-",
        )
    )


def _interaction_channel_category_id(
        interaction: discord.Interaction[BignessLeagueBot],
) -> int | None:
    channel = interaction.channel
    category_id = getattr(channel, "category_id", None)
    if isinstance(category_id, int):
        return category_id

    category = getattr(channel, "category", None)
    category_id = getattr(category, "id", None)
    if isinstance(category_id, int):
        return category_id
    return None


def _build_ballchasing_client(
        bot: BignessLeagueBot,
) -> BallchasingClient:
    settings = bot.settings
    return BallchasingClient(
        api_base_url=settings.ballchasing_api_base_url,
        api_token=settings.ballchasing_api_token,
        visibility=settings.ballchasing_upload_visibility,
        group_id=settings.ballchasing_group_id,
        timeout_seconds=settings.ballchasing_request_timeout_seconds,
        poll_interval_seconds=settings.ballchasing_poll_interval_seconds,
        max_poll_attempts=settings.ballchasing_max_poll_attempts,
        min_request_interval_seconds=settings.ballchasing_min_request_interval_seconds,
        rate_limit_retry_seconds=settings.ballchasing_rate_limit_retry_seconds,
        rate_limit_max_retries=settings.ballchasing_rate_limit_max_retries,
    )


def _to_user_error(error: MatchReplayValidationError) -> CommandUserError:
    if isinstance(error, InvalidReplayCountError):
        return CommandUserError(
            localize(
                I18N.errors.match_replays.invalid_replay_count,
                min_count=MATCH_REPLAY_MIN_FILES,
                max_count=MATCH_REPLAY_MAX_FILES,
            )
        )
    if isinstance(error, InvalidReplayExtensionError):
        return CommandUserError(
            localize(
                I18N.errors.match_replays.invalid_replay_extension,
                filenames=", ".join(error.filenames),
            )
        )
    return CommandUserError(localize(I18N.errors.slash.unexpected))


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(MatchReplaysCog())
