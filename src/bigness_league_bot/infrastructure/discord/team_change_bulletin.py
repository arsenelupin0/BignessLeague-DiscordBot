from __future__ import annotations

import logging

import discord

from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
    TeamRoleSheetMetadata,
    TeamSheetError,
)

LOGGER = logging.getLogger("bigness_league_bot.activity")


async def resolve_team_change_bulletin_channel(
        *,
        guild: discord.Guild,
        channel_id: int,
) -> discord.TextChannel | discord.Thread | None:
    channel = guild.get_channel(channel_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(channel_id)
        except (discord.Forbidden, discord.HTTPException) as exc:
            LOGGER.warning(
                "TEAM_CHANGE_BULLETIN_CHANNEL_UNAVAILABLE guild=%s(%s) channel_id=%s details=%s",
                guild.name,
                guild.id,
                channel_id,
                exc,
            )
            return None

    if isinstance(channel, (discord.TextChannel, discord.Thread)):
        return channel

    LOGGER.warning(
        "TEAM_CHANGE_BULLETIN_CHANNEL_INVALID guild=%s(%s) channel_id=%s channel_type=%s",
        guild.name,
        guild.id,
        channel_id,
        type(channel).__name__,
    )
    return None


async def load_team_change_metadata(
        *,
        repository: GoogleSheetsTeamRepository | None,
        team_role: discord.Role,
        fallback: TeamRoleSheetMetadata,
        guild: discord.Guild,
) -> TeamRoleSheetMetadata:
    if repository is None:
        return fallback

    try:
        return await repository.find_team_sheet_metadata_for_role(team_role)
    except TeamSheetError as exc:
        LOGGER.warning(
            "TEAM_CHANGE_BULLETIN_METADATA_FALLBACK guild=%s(%s) role=%s(%s) details=%s",
            guild.name,
            guild.id,
            team_role.name,
            team_role.id,
            exc,
        )
        return fallback


async def create_team_change_repository(
        settings: object,
        *,
        guild: discord.Guild,
) -> GoogleSheetsTeamRepository | None:
    try:
        return GoogleSheetsTeamRepository(settings)
    except TeamSheetError as exc:
        LOGGER.warning(
            "TEAM_CHANGE_BULLETIN_METADATA_DISABLED guild=%s(%s) details=%s",
            guild.name,
            guild.id,
            exc,
        )
        return None
