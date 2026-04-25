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

import re
from pathlib import Path

import discord
import unicodedata

from bigness_league_bot.core.localization import TranslationKeyLike
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

PROJECT_ROOT = Path(__file__).resolve().parents[4]
ANSI_BLUE = "\u001b[1;34m"
ANSI_WHITE = "\u001b[1;37m"
ANSI_RED = "\u001b[1;31m"
ANSI_GREEN = "\u001b[1;32m"
ANSI_YELLOW = "\u001b[1;33m"
ANSI_MAGENTA = "\u001b[1;35m"
ANSI_RESET = "\u001b[0m"
BOX_TOP_LEFT = "\u2554"
BOX_TOP_RIGHT = "\u2557"
BOX_BOTTOM_LEFT = "\u255a"
BOX_BOTTOM_RIGHT = "\u255d"
BOX_HORIZONTAL = "\u2550"
BOX_VERTICAL = "\u2551"
BOX_LEFT_T = "\u2560"
BOX_RIGHT_T = "\u2563"
BOX_TOP_T = "\u2566"
BOX_BOTTOM_T = "\u2569"
BOX_CROSS = "\u256c"
POSITION_WIDTH = 5
PLAYER_WIDTH = 18
DISCORD_WIDTH = 22
EPIC_WIDTH = 19
ROCKET_WIDTH = 26
MMR_WIDTH = 7
TRACKER_WIDTH = PLAYER_WIDTH + DISCORD_WIDTH + EPIC_WIDTH + ROCKET_WIDTH + 3
ROLE_WIDTH = 18
DISCORD_MESSAGE_LIMIT = 2_000
TEXT_COLUMN_LEFT_PADDING = 1
MMR_LEFT_PADDING = 1
MMR_RIGHT_PADDING = 2
TEAM_PROFILE_IMAGE_BACKGROUND = (12, 18, 28)
TEAM_PROFILE_IMAGE_PADDING_X = 32
TEAM_PROFILE_IMAGE_PADDING_Y = 28
TEAM_PROFILE_IMAGE_LINE_SPACING = 10
TEAM_PROFILE_IMAGE_FONT_SIZE = 24
TEAM_PROFILE_IMAGE_DEFAULT_COLOR = (241, 245, 249)
TEAM_PROFILE_IMAGE_BORDER_COLOR = (59, 130, 246)
TEAM_PROFILE_IMAGE_BORDER_WIDTH = 1
TEAM_PROFILE_IMAGE_BORDER_GAP_WIDTH = 2
TEAM_PROFILE_IMAGE_CELL_PADDING_X = 12
TEAM_PROFILE_IMAGE_CELL_PADDING_Y = 12
TEAM_PROFILE_IMAGE_SECTION_SPACING = 48
TEAM_PROFILE_IMAGE_TEXT_BORDER_INSET = (
        TEAM_PROFILE_IMAGE_BORDER_WIDTH * 2 + TEAM_PROFILE_IMAGE_BORDER_GAP_WIDTH
)
ANSI_ESCAPE_PATTERN = re.compile(r"(\x1b\[[0-9;]*m)")
ANSI_COLOR_TO_RGB = {
    ANSI_BLUE: (59, 130, 246),
    ANSI_WHITE: (241, 245, 249),
    ANSI_RED: (248, 113, 113),
    ANSI_GREEN: (74, 222, 128),
    ANSI_YELLOW: (250, 204, 21),
    ANSI_MAGENTA: (216, 180, 254),
    ANSI_RESET: TEAM_PROFILE_IMAGE_DEFAULT_COLOR,
}
TEAM_PROFILE_FONT_CANDIDATES = (
    PROJECT_ROOT / "aa_resources/fonts/MapleMono-NF-CN-Regular.ttf",
    PROJECT_ROOT / "aa_resources/fonts/MapleMono-CN-Regular.ttf",
    Path(r"C:\Windows\Fonts\msgothic.ttc"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
    Path(r"C:\Windows\Fonts\consola.ttf"),
    Path(r"C:\Windows\Fonts\cour.ttf"),
    Path(r"C:\Windows\Fonts\lucon.ttf"),
)
MAIN_TABLE_WIDTH = (
        POSITION_WIDTH
        + PLAYER_WIDTH
        + DISCORD_WIDTH
        + EPIC_WIDTH
        + ROCKET_WIDTH
        + MMR_WIDTH
        + 5
)
TRACKER_TABLE_WIDTH = POSITION_WIDTH + TRACKER_WIDTH + 1
TITLE_BLOCK_WIDTH = POSITION_WIDTH + PLAYER_WIDTH + DISCORD_WIDTH + 2
TECHNICAL_STAFF_TABLE_WIDTH = ROLE_WIDTH + DISCORD_WIDTH + EPIC_WIDTH + ROCKET_WIDTH + 3


def sanitize_text(value: str) -> str:
    return " ".join(value.split())


def display_width(value: str) -> int:
    width = 0
    for character in value:
        if unicodedata.combining(character):
            continue

        if unicodedata.east_asian_width(character) in {"F", "W"}:
            width += 2
            continue

        width += 1

    return width


def truncate_text_to_width(value: str, width: int) -> str:
    if width <= 0:
        return ""

    ellipsis_text = "\u2026"
    ellipsis_width = display_width(ellipsis_text)
    if width <= ellipsis_width:
        return ellipsis_text[:width]

    target_width = width - ellipsis_width
    current_width = 0
    characters: list[str] = []
    for character in value:
        character_width = display_width(character)
        if current_width + character_width > target_width:
            break

        characters.append(character)
        current_width += character_width

    return "".join(characters) + ellipsis_text


def fit_text(value: str, width: int, *, align: str = "left") -> str:
    normalized_value = sanitize_text(value)
    if display_width(normalized_value) > width:
        normalized_value = truncate_text_to_width(normalized_value, width)

    padding = max(0, width - display_width(normalized_value))
    if align == "center":
        left_padding = padding // 2
        right_padding = padding - left_padding
        return (" " * left_padding) + normalized_value + (" " * right_padding)
    if align == "right":
        return (" " * padding) + normalized_value
    return normalized_value + (" " * padding)


def translate_header(
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        key: TranslationKeyLike,
) -> str:
    return localizer.translate(key, locale=locale).upper()


def build_team_profile_file_name(team_name: str) -> str:
    normalized_name = "".join(
        character.lower() if character.isalnum() else "_"
        for character in sanitize_text(team_name)
    ).strip("_")
    if not normalized_name:
        normalized_name = "equipo"

    return f"{normalized_name}.ansi.txt"


def build_team_profile_png_file_name(team_name: str) -> str:
    return build_team_profile_file_name(team_name).removesuffix(".ansi.txt") + ".png"
