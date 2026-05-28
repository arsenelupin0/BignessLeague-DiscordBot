from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.match_replays import (
    InvalidReplayCountError,
    InvalidReplayExtensionError,
    MATCH_REPLAY_MAX_FILES,
    MATCH_REPLAY_MIN_FILES,
    MatchReplayDivision,
    MatchReplayValidationError,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.ballchasing.client import BallchasingClient
from bigness_league_bot.infrastructure.discord.emojis import (
    DiscordEmojiRef,
    GOLD_DIVISION_EMOJI,
    SILVER_DIVISION_EMOJI,
    render_custom_emoji,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


def interaction_channel_name(
        interaction: discord.Interaction[BignessLeagueBot],
) -> str:
    channel = interaction.channel
    channel_name = getattr(channel, "name", "")
    if isinstance(channel_name, str):
        return channel_name
    return ""


def resolve_replay_division_from_channel(
        interaction: discord.Interaction[BignessLeagueBot],
) -> MatchReplayDivision:
    category_id = interaction_channel_category_id(interaction)
    settings = interaction.client.settings
    if category_id == settings.gold_division_category_id:
        return MatchReplayDivision.GOLD
    if category_id == settings.silver_division_category_id:
        return MatchReplayDivision.SILVER

    raise CommandUserError(
        localize(
            I18N.errors.match_replays.channel_division_context_missing,
            channel_name=interaction_channel_name(interaction) or "-",
        )
    )


def division_emoji(division: MatchReplayDivision) -> DiscordEmojiRef:
    if division is MatchReplayDivision.GOLD:
        return GOLD_DIVISION_EMOJI
    return SILVER_DIVISION_EMOJI


def render_division_emoji(
        guild: discord.Guild,
        bot: BignessLeagueBot,
        division: MatchReplayDivision,
) -> str:
    return render_custom_emoji(
        guild=guild,
        bot=bot,
        emoji=division_emoji(division),
    )


def game_winner_label(locale: str | discord.Locale | None) -> str:
    if str(locale or "").lower().startswith("en"):
        return "Winner"
    return "Gana"


def administrative_result_score_label(
        *,
        local: discord.Role,
        visitante: discord.Role,
        winner: discord.Role | None,
        suffix: str | None,
) -> str:
    if winner is None or suffix is None:
        return "NULO"
    if winner.id == local.id:
        return f"3 - 0 ({suffix})"
    if winner.id == visitante.id:
        return f"0 - 3 ({suffix})"
    raise CommandUserError(localize(I18N.errors.match_replays.manual_result_winner_mismatch))


async def send_channel_message(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        content: str,
        file: discord.File | None = None,
) -> None:
    channel = interaction.channel
    if isinstance(channel, discord.abc.Messageable):
        if file is None:
            await channel.send(content=content)
            return
        await channel.send(content=content, file=file)
        return

    if file is None:
        await interaction.followup.send(content=content)
        return
    await interaction.followup.send(content=content, file=file)


async def delete_original_interaction_response(
        interaction: discord.Interaction[BignessLeagueBot],
) -> None:
    try:
        await interaction.delete_original_response()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return


def interaction_channel_category_id(
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


def build_ballchasing_client(
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


def to_user_error(error: MatchReplayValidationError) -> CommandUserError:
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
