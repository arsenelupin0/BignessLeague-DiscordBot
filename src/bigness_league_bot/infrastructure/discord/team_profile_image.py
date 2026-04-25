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

from io import BytesIO
from pathlib import Path

import discord

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.infrastructure.discord.team_profile_image_renderer import _render_team_profile_image
from bigness_league_bot.infrastructure.discord.team_profile_layout import build_team_profile_png_file_name
from bigness_league_bot.infrastructure.i18n.service import LocalizationService


def build_team_profile_image_file(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        font_path: Path | None = None,
) -> discord.File:
    image_data = _render_team_profile_image(
        team_profile=team_profile,
        localizer=localizer,
        locale=locale,
        font_path=font_path,
    )
    file_name = build_team_profile_png_file_name(team_profile.team_name)
    return discord.File(
        BytesIO(image_data),
        filename=file_name,
    )
