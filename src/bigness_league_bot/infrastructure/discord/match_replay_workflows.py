from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.match_replay_groups import (
    FinalFourMatchReference,
    MatchChannelReference,
    PromotionRelegationMatchReference,
    build_final_four_replay_group_path,
    build_final_four_replay_title,
    build_match_replay_group_path,
    build_match_replay_title,
    build_promotion_relegation_replay_group_path,
    build_promotion_relegation_replay_title,
    parse_final_four_channel_reference,
    parse_match_channel_reference,
    parse_promotion_relegation_channel_reference,
)
from bigness_league_bot.application.services.match_replay_summaries import (
    build_match_replay_roster_validation_summary,
    collect_match_replay_standings_team_names,
)
from bigness_league_bot.application.services.match_replays import (
    MATCH_REPLAY_BO5_RULES,
    MATCH_REPLAY_FINAL_FOUR_BO7_RULES,
    MatchReplayDivision,
    MatchReplaySeriesRules,
    MatchReplayValidationError,
    build_match_replay_report,
    resolve_match_replay_report_players,
    sort_match_replay_games_by_replay_date,
    validate_replay_filenames,
)
from bigness_league_bot.application.services.match_standings import MatchGridManualResult
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
from bigness_league_bot.infrastructure.discord.emojis import (
    MATCH_SCHEDULE_GREEN_ARROW_EMOJI,
    render_custom_emoji,
)
from bigness_league_bot.infrastructure.discord.match_channel_creation import (
    validate_match_team_roles,
)
from bigness_league_bot.infrastructure.discord.match_replay_assets import (
    guild_icon_url,
    team_logo_url_map,
    write_replay_diagnostic_copy,
)
from bigness_league_bot.infrastructure.discord.match_replay_discord_helpers import (
    administrative_result_score_label,
    build_ballchasing_client,
    delete_original_interaction_response,
    game_winner_label,
    interaction_channel_name,
    render_division_emoji,
    resolve_replay_division_from_channel,
    send_channel_message,
    to_user_error,
)
from bigness_league_bot.infrastructure.discord.match_replay_messages import (
    format_match_replay_game_score_lines,
    format_match_replay_roster_validation,
)
from bigness_league_bot.infrastructure.discord.match_summary_images import (
    build_match_replay_summary_image_file,
    build_match_standings_image_file,
)
from bigness_league_bot.infrastructure.google.match_replay_repository import (
    GoogleSheetsMatchReplayRepository,
)
from bigness_league_bot.infrastructure.google.match_standings_repository import (
    GoogleSheetsMatchStandingsRepository,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MatchReplayWorkflowContext:
    rules: MatchReplaySeriesRules
    final_four: bool = False
    promotion_relegation: bool = False
    sync_standings: bool = True


MATCH_REPLAY_REGULAR_CONTEXT = MatchReplayWorkflowContext(
    rules=MATCH_REPLAY_BO5_RULES,
)
MATCH_REPLAY_FINAL_FOUR_CONTEXT = MatchReplayWorkflowContext(
    rules=MATCH_REPLAY_FINAL_FOUR_BO7_RULES,
    final_four=True,
    sync_standings=False,
)
MATCH_REPLAY_PROMOTION_RELEGATION_CONTEXT = MatchReplayWorkflowContext(
    rules=MATCH_REPLAY_FINAL_FOUR_BO7_RULES,
    promotion_relegation=True,
    sync_standings=False,
)


async def process_administrative_result(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        local: discord.Role,
        visitante: discord.Role,
        winner: discord.Role | None,
        suffix: str | None,
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
    if winner is not None and winner.id not in {local.id, visitante.id}:
        raise CommandUserError(
            localize(I18N.errors.match_replays.manual_result_winner_mismatch)
        )

    await interaction.response.defer(thinking=True, ephemeral=True)
    channel_name = interaction_channel_name(interaction)
    channel_reference = parse_match_channel_reference(channel_name)
    if channel_reference is None:
        raise CommandUserError(
            localize(
                I18N.errors.match_replays.channel_group_context_missing,
                channel_name=channel_name or "-",
            )
        )
    division_value = resolve_replay_division_from_channel(interaction)
    score_label = administrative_result_score_label(
        local=local,
        visitante=visitante,
        winner=winner,
        suffix=suffix,
    )

    replay_repository = GoogleSheetsMatchReplayRepository(interaction.client.settings)
    standings_repository = GoogleSheetsMatchStandingsRepository(interaction.client.settings)
    roster_data = await replay_repository.list_division_roster_data(division_value.label)
    standings_result = await standings_repository.sync_manual_result_to_standings(
        division_value,
        matchday=channel_reference.matchday,
        match_number=channel_reference.match_number,
        result=MatchGridManualResult(
            team_one_name=local.name,
            team_two_name=visitante.name,
            score_label=score_label,
        ),
        team_names=collect_match_replay_standings_team_names(
            roster_players=roster_data.roster_players,
            fallback_team_names=(local.name, visitante.name),
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
        LOGGER.exception("No se pudo renderizar la imagen de clasificación")
        image_warning = interaction.client.localizer.translate(
            I18N.messages.match_replays.image_render_failed,
            locale=interaction.locale,
        )

    message = interaction.client.localizer.translate(
        I18N.messages.match_replays.manual_result_registered,
        locale=interaction.locale,
        green_arrow=render_custom_emoji(
            guild=guild,
            bot=interaction.client,
            emoji=MATCH_SCHEDULE_GREEN_ARROW_EMOJI,
        ),
        division_emoji=render_division_emoji(guild, interaction.client, division_value),
        division=division_value.label,
        jornada=channel_reference.matchday,
        partido=channel_reference.match_number,
        team_one=local.name,
        team_two=visitante.name,
        score_label=score_label,
        standings_sheet_name=standings_result.worksheet_name,
    )
    if image_file is None:
        await send_channel_message(interaction, content=message + image_warning)
    else:
        await send_channel_message(interaction, content=message, file=image_file)
    await delete_original_interaction_response(interaction)


async def process_replay_attachments(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        local: discord.Role,
        visitante: discord.Role,
        attachments: tuple[discord.Attachment, ...],
        context: MatchReplayWorkflowContext = MATCH_REPLAY_REGULAR_CONTEXT,
) -> None:
    guild = interaction.guild
    if guild is None:
        raise UnsupportedChannelError(localize(I18N.errors.channel_management.server_only))

    try:
        validate_replay_filenames(
            (attachment.filename for attachment in attachments),
            rules=context.rules,
        )
    except MatchReplayValidationError as exc:
        raise to_user_error(exc) from exc

    channel_name = interaction_channel_name(interaction)
    channel_reference = _resolve_replay_channel_reference(
        channel_name,
        context=context,
    )
    division_value = resolve_replay_division_from_channel(interaction)
    if context.final_four and division_value is not MatchReplayDivision.GOLD:
        raise CommandUserError(
            localize(
                I18N.errors.match_replays.channel_division_context_missing,
                channel_name=channel_name or "-",
            )
        )
    jornada = channel_reference.matchday
    partido = channel_reference.match_number
    final_four_round_name = (
        channel_reference.round_name
        if isinstance(channel_reference, FinalFourMatchReference)
        else None
    )
    promotion_relegation = isinstance(channel_reference, PromotionRelegationMatchReference)

    diagnostics_dir = interaction.client.settings.log_dir.parent / "match_replays" / "uploads"
    uploads = await asyncio.gather(
        *(
            read_replay_attachment(
                attachment,
                diagnostics_dir=diagnostics_dir,
            )
            for attachment in attachments
        )
    )
    replay_repository = GoogleSheetsMatchReplayRepository(interaction.client.settings)
    existing_replays = await replay_repository.list_existing_replay_entries(division_value)
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

    ballchasing_client = build_ballchasing_client(interaction.client)
    ballchasing_group_id = await resolve_ballchasing_group_id(
        interaction,
        ballchasing_client=ballchasing_client,
        division=division_value,
        matchday=jornada,
        team_one_name=local.name,
        team_two_name=visitante.name,
        final_four_round_name=final_four_round_name,
        promotion_relegation=promotion_relegation,
    )
    games = []
    failed_uploads: list[str] = []
    for index, upload in enumerate(uploads, start=1):
        try:
            game = await ballchasing_client.upload_and_fetch_replay(
                upload,
                title=_build_workflow_replay_title(
                    context=context,
                    matchday=jornada,
                    final_four_round_name=final_four_round_name,
                    promotion_relegation=promotion_relegation,
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
                "title": _build_workflow_replay_title(
                    context=context,
                    matchday=jornada,
                    final_four_round_name=final_four_round_name,
                    promotion_relegation=promotion_relegation,
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
            rules=context.rules,
        )
    except MatchReplayValidationError as exc:
        raise to_user_error(exc) from exc
    roster_data = await replay_repository.list_division_roster_data(
        report.division.label
    )
    roster_players = roster_data.roster_players
    report = resolve_match_replay_report_players(report, roster_players)
    append_result = await replay_repository.append_report(report)
    standings_result = None
    if append_result.appended_games > 0 and context.sync_standings:
        standings_repository = GoogleSheetsMatchStandingsRepository(interaction.client.settings)
        standings_result = await standings_repository.sync_report_to_standings(
            report,
            team_names=collect_match_replay_standings_team_names(
                roster_players=roster_players,
                fallback_team_names=(report.team_one_name, report.team_two_name),
            ),
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
    image_warning = ""
    replay_summary_image_file: discord.File | None = None
    try:
        replay_summary_image_file = build_match_replay_summary_image_file(
            report=report,
            series_label=context.rules.label,
            match_context_label=_match_context_label(
                channel_reference,
                context=context,
            ),
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

    standings_image_file: discord.File | None = None
    if standings_result is not None:
        try:
            standings_image_file = build_match_standings_image_file(
                division_name=report.division.label,
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
        I18N.messages.match_replays.uploaded.summary,
        locale=interaction.locale,
        series_label=context.rules.label,
        match_context=_match_context_label(channel_reference, context=context),
        green_arrow=render_custom_emoji(
            guild=guild,
            bot=interaction.client,
            emoji=MATCH_SCHEDULE_GREEN_ARROW_EMOJI,
        ),
        division_emoji=render_division_emoji(guild, interaction.client, report.division),
        division=report.division.label,
        jornada=report.matchday,
        partido=report.match_number,
        team_one=report.team_one_name,
        team_two=report.team_two_name,
        series_score=report.series_score,
        game_scores=format_match_replay_game_score_lines(
            report,
            winner_label=game_winner_label(interaction.locale),
        ),
        roster_validation=roster_validation,
        unresolved_winners=unresolved,
        failed_replays=failed_replays,
        skipped_duplicates=skipped_duplicates,
        image_warning=image_warning,
    )
    await send_channel_message(
        interaction,
        content=message,
        file=replay_summary_image_file,
    )
    if standings_result is not None:
        standings_message = interaction.client.localizer.translate(
            I18N.messages.match_replays.uploaded.standings_image,
            locale=interaction.locale,
            green_arrow=render_custom_emoji(
                guild=guild,
                bot=interaction.client,
                emoji=MATCH_SCHEDULE_GREEN_ARROW_EMOJI,
            ),
        )
        if standings_image_file is None:
            await send_channel_message(
                interaction,
                content=standings_message + image_warning,
            )
        else:
            await send_channel_message(
                interaction,
                content=standings_message,
                file=standings_image_file,
            )
    await delete_original_interaction_response(interaction)


async def read_replay_attachment(
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


async def resolve_ballchasing_group_id(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        ballchasing_client: BallchasingClient,
        division: MatchReplayDivision,
        matchday: int,
        team_one_name: str,
        team_two_name: str,
        final_four_round_name: str | None = None,
        promotion_relegation: bool = False,
) -> str | None:
    settings = interaction.client.settings
    if (
            not settings.ballchasing_auto_groups_enabled
            and final_four_round_name is None
            and not promotion_relegation
    ):
        LOGGER.info(
            "Grupos automaticos de Ballchasing desactivados; se usara el grupo configurado como destino final group_id=%s",
            settings.ballchasing_group_id or "-",
        )
        return settings.ballchasing_group_id
    if not settings.ballchasing_group_id:
        raise CommandUserError(localize(I18N.errors.match_replays.ballchasing_group_missing))

    if final_four_round_name is not None:
        group_path = build_final_four_replay_group_path(
            round_name=final_four_round_name,
        )
    elif promotion_relegation:
        group_path = build_promotion_relegation_replay_group_path(
            team_one_name=team_one_name,
            team_two_name=team_two_name,
        )
    else:
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


def _resolve_replay_channel_reference(
        channel_name: str,
        *,
        context: MatchReplayWorkflowContext,
) -> MatchChannelReference | FinalFourMatchReference | PromotionRelegationMatchReference:
    if context.final_four:
        final_four_reference = parse_final_four_channel_reference(channel_name)
        if final_four_reference is not None:
            return final_four_reference
    elif context.promotion_relegation:
        promotion_relegation_reference = parse_promotion_relegation_channel_reference(channel_name)
        if promotion_relegation_reference is not None:
            return promotion_relegation_reference
    else:
        regular_reference = parse_match_channel_reference(channel_name)
        if regular_reference is not None:
            return regular_reference

    raise CommandUserError(
        localize(
            I18N.errors.match_replays.channel_group_context_missing,
            channel_name=channel_name or "-",
        )
    )


def _build_workflow_replay_title(
        *,
        context: MatchReplayWorkflowContext,
        matchday: int,
        final_four_round_name: str | None,
        promotion_relegation: bool,
        game_number: int,
        team_one_name: str,
        team_two_name: str,
) -> str:
    if context.final_four and final_four_round_name is not None:
        return build_final_four_replay_title(
            round_name=final_four_round_name,
            game_number=game_number,
            team_one_name=team_one_name,
            team_two_name=team_two_name,
        )

    if context.promotion_relegation and promotion_relegation:
        return build_promotion_relegation_replay_title(
            game_number=game_number,
            team_one_name=team_one_name,
            team_two_name=team_two_name,
        )

    return build_match_replay_title(
        matchday=matchday,
        game_number=game_number,
        team_one_name=team_one_name,
        team_two_name=team_two_name,
    )


def _match_context_label(
        channel_reference: MatchChannelReference | FinalFourMatchReference | PromotionRelegationMatchReference,
        *,
        context: MatchReplayWorkflowContext,
) -> str:
    if context.final_four and isinstance(channel_reference, FinalFourMatchReference):
        return f"Final Four | {channel_reference.label}"
    if context.promotion_relegation and isinstance(channel_reference, PromotionRelegationMatchReference):
        return channel_reference.label
    return (
        f"Jornada {channel_reference.matchday} | "
        f"Partido {channel_reference.match_number}"
    )
