from __future__ import annotations

import logging
from io import BytesIO

import discord

from bigness_league_bot.infrastructure.google.team_sheets.models import TeamRoleSheetMetadata
from bigness_league_bot.infrastructure.images.team_logos import TeamLogoLoadError, load_team_logo_png_async

LOGGER = logging.getLogger("bigness_league_bot.activity")
TEAM_LOGO_ATTACHMENT_NAME = "team-logo.png"


async def attach_team_change_logo(
        *, embed: discord.Embed, metadata: TeamRoleSheetMetadata, team_key: str,
) -> discord.File | None:
    try:
        content = await load_team_logo_png_async(metadata.team_image_url, team_key=team_key)
    except TeamLogoLoadError as exc:
        LOGGER.warning("TEAM_CHANGE_LOGO_FALLBACK team=%s worksheet=%s team_key=%s reason=%s",
                       metadata.team_name, metadata.worksheet_title, team_key, exc)
        return None
    logo_file = discord.File(BytesIO(content), filename=TEAM_LOGO_ATTACHMENT_NAME)
    embed.set_thumbnail(url=f"attachment://{logo_file.filename}")
    LOGGER.info("TEAM_CHANGE_LOGO_ATTACHED team=%s worksheet=%s team_key=%s",
                metadata.team_name, metadata.worksheet_title, team_key)
    return logo_file
