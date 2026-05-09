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

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.channel_closure import (
    MATCH_CHANNEL_STATUS_SCHEDULED,
    is_match_channel_name,
)
from bigness_league_bot.application.services.match_replay_groups import (
    parse_match_channel_reference,
)
from bigness_league_bot.application.services.match_schedules import MatchScheduleEntry
from bigness_league_bot.core.localization import localize
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.core.timezones import resolve_timezone
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ChannelManagementError,
    UnsupportedChannelError,
    ensure_allowed_member,
)
from bigness_league_bot.infrastructure.discord.emojis import (
    GOLD_DIVISION_EMOJI,
    MATCH_SCHEDULE_GREEN_ARROW_EMOJI,
    SILVER_DIVISION_EMOJI,
    DiscordEmojiRef,
    render_custom_emoji,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.match_channel_schedule import (
    migrate_match_schedule_from_channel,
)
from bigness_league_bot.infrastructure.discord.match_schedule_store import (
    MatchScheduleStore,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)
GOLD_DIVISION_NAME = "Gold Division"
SILVER_DIVISION_NAME = "Silver Division"
SPANISH_WEEKDAYS = (
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
)
ENGLISH_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


@dataclass(frozen=True, slots=True)
class _ScheduleDivision:
    name: str
    emoji: DiscordEmojiRef
    category_id: int


class MatchSchedulesCog(commands.Cog):
    @app_commands.command(
        name=localized_locale_str(I18N.commands.match_schedules.fixed.name),
        description=localized_locale_str(I18N.commands.match_schedules.fixed.description),
    )
    @app_commands.guild_only()
    async def fixed_schedules(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        ensure_allowed_member(interaction.user)
        await interaction.response.defer(thinking=True)

        store = MatchScheduleStore(interaction.client.settings.match_schedule_state_file)
        migrated_count = await _migrate_missing_schedules(
            guild,
            store=store,
            bot=interaction.client,
        )
        entries = _active_entries(guild, store)
        content = _render_summary(
            interaction,
            guild=guild,
            settings=interaction.client.settings,
            entries=entries,
            migrated_count=migrated_count,
        )
        await interaction.followup.send(
            content,
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                users=False,
                roles=False,
                replied_user=False,
            ),
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


async def _migrate_missing_schedules(
        guild: discord.Guild,
        *,
        store: MatchScheduleStore,
        bot: BignessLeagueBot,
) -> int:
    stored_channel_ids = {
        entry.channel_id
        for entry in store.active_for_guild(guild.id)
    }
    migrated_count = 0
    for channel in guild.text_channels:
        if channel.id in stored_channel_ids:
            continue

        if not _is_scheduled_match_channel(channel):
            continue

        try:
            entry = await migrate_match_schedule_from_channel(
                channel,
                settings=bot.settings,
                bot=bot,
            )
        except (ChannelManagementError, discord.HTTPException):
            LOGGER.exception(
                "MATCH_SCHEDULE_MIGRATION_FAILED guild=%s channel=%s",
                guild.id,
                channel.id,
            )
            continue

        if entry is not None:
            store.upsert(entry)
            migrated_count += 1

    return migrated_count


def _active_entries(
        guild: discord.Guild,
        store: MatchScheduleStore,
) -> tuple[MatchScheduleEntry, ...]:
    active_entries: list[MatchScheduleEntry] = []
    for entry in store.active_for_guild(guild.id):
        channel = guild.get_channel(entry.channel_id)
        if not isinstance(channel, discord.TextChannel):
            store.remove(guild_id=entry.guild_id, channel_id=entry.channel_id)
            continue

        if not _is_scheduled_match_channel(channel):
            store.remove(guild_id=entry.guild_id, channel_id=entry.channel_id)
            continue

        active_entries.append(entry)

    return tuple(sorted(active_entries, key=lambda item: _entry_sort_key(guild, item)))


def _render_summary(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        guild: discord.Guild,
        settings: Settings,
        entries: tuple[MatchScheduleEntry, ...],
        migrated_count: int,
) -> str:
    green_arrow = render_custom_emoji(
        guild=guild,
        bot=interaction.client,
        emoji=MATCH_SCHEDULE_GREEN_ARROW_EMOJI,
    )
    lines = [
        interaction.client.localizer.translate(
            I18N.messages.match_schedules.fixed_header,
            locale=interaction.locale,
            green_arrow=green_arrow,
        )
    ]
    for division in _schedule_divisions(settings):
        lines.append(_render_division_header(interaction, guild=guild, division=division))
        lines.extend(
            _render_division_entries(
                interaction,
                guild=guild,
                settings=settings,
                entries=entries,
                division=division,
            )
        )
    if migrated_count:
        lines.append(
            interaction.client.localizer.translate(
                I18N.messages.match_schedules.fixed_migrated,
                locale=interaction.locale,
                migrated_count=migrated_count,
            )
        )

    return "\n\n".join(lines)


def _render_division_entries(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        guild: discord.Guild,
        settings: Settings,
        entries: tuple[MatchScheduleEntry, ...],
        division: _ScheduleDivision,
) -> tuple[str, ...]:
    division_entries = tuple(
        entry
        for entry in entries
        if _entry_belongs_to_division(guild, entry, division)
    )
    if not division_entries:
        return (
            interaction.client.localizer.translate(
                I18N.messages.match_schedules.fixed_division_empty,
                locale=interaction.locale,
            ),
        )

    lines: list[str] = []
    current_day: str | None = None
    for entry in sorted(division_entries, key=lambda item: _entry_sort_key(guild, item)):
        day = _weekday_name(
            timestamp=entry.timestamp,
            timezone_name=settings.timezone,
            locale=str(interaction.locale),
        )
        if day != current_day:
            lines.append(
                interaction.client.localizer.translate(
                    I18N.messages.match_schedules.fixed_day_header,
                    locale=interaction.locale,
                    weekday=day,
                )
            )
            current_day = day
        lines.append(_render_entry(interaction, entry))

    return tuple(lines)


def _render_division_header(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        guild: discord.Guild,
        division: _ScheduleDivision,
) -> str:
    division_emoji = render_custom_emoji(
        guild=guild,
        bot=interaction.client,
        emoji=division.emoji,
    )
    return interaction.client.localizer.translate(
        I18N.messages.match_schedules.fixed_division_header,
        locale=interaction.locale,
        division_emoji=division_emoji,
        division_name=division.name,
    )


def _render_entry(
        interaction: discord.Interaction[BignessLeagueBot],
        entry: MatchScheduleEntry,
) -> str:
    return interaction.client.localizer.translate(
        I18N.messages.match_schedules.fixed_entry,
        locale=interaction.locale,
        channel=f"<#{entry.channel_id}>",
        team_one_mention=_team_mention(entry, index=0),
        team_two_mention=_team_mention(entry, index=1),
        timestamp=entry.timestamp,
    )


def _team_mention(entry: MatchScheduleEntry, *, index: int) -> str:
    if index >= len(entry.team_role_ids):
        return ""

    return f"<@&{entry.team_role_ids[index]}>"


def _entry_sort_key(
        guild: discord.Guild,
        entry: MatchScheduleEntry,
) -> tuple[int, int, int, int]:
    channel = guild.get_channel(entry.channel_id)
    reference = (
        parse_match_channel_reference(channel.name)
        if isinstance(channel, discord.TextChannel)
        else None
    )
    if reference is None:
        return entry.timestamp, 999, 999, entry.channel_id

    return entry.timestamp, reference.matchday, reference.match_number, entry.channel_id


def _schedule_divisions(settings: Settings) -> tuple[_ScheduleDivision, ...]:
    return (
        _ScheduleDivision(
            name=GOLD_DIVISION_NAME,
            emoji=GOLD_DIVISION_EMOJI,
            category_id=settings.gold_division_category_id,
        ),
        _ScheduleDivision(
            name=SILVER_DIVISION_NAME,
            emoji=SILVER_DIVISION_EMOJI,
            category_id=settings.silver_division_category_id,
        ),
    )


def _entry_belongs_to_division(
        guild: discord.Guild,
        entry: MatchScheduleEntry,
        division: _ScheduleDivision,
) -> bool:
    channel = guild.get_channel(entry.channel_id)
    return isinstance(channel, discord.TextChannel) and channel.category_id == division.category_id


def _weekday_name(
        *,
        timestamp: int,
        timezone_name: str,
        locale: str,
) -> str:
    start_at = datetime.fromtimestamp(timestamp, tz=resolve_timezone(timezone_name))
    weekdays = SPANISH_WEEKDAYS if locale.casefold().startswith("es") else ENGLISH_WEEKDAYS
    return weekdays[start_at.weekday()]


def _is_scheduled_match_channel(channel: discord.TextChannel) -> bool:
    return (
            channel.name.endswith(MATCH_CHANNEL_STATUS_SCHEDULED)
            and is_match_channel_name(channel.name)
    )


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(MatchSchedulesCog())
