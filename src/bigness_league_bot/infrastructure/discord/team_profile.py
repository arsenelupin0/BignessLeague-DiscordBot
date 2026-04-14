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

import math
import re
from io import BytesIO
from pathlib import Path

import discord
import unicodedata

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import TranslationKeyLike, localize
from bigness_league_bot.infrastructure.i18n.keys import I18N
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


def _sanitize_text(value: str) -> str:
    return " ".join(value.split())


def _display_width(value: str) -> int:
    width = 0
    for character in value:
        if unicodedata.combining(character):
            continue

        if unicodedata.east_asian_width(character) in {"F", "W"}:
            width += 2
            continue

        width += 1

    return width


def _truncate_text_to_width(value: str, width: int) -> str:
    if width <= 0:
        return ""

    ellipsis = "\u2026"
    ellipsis_width = _display_width(ellipsis)
    if width <= ellipsis_width:
        return ellipsis[:width]

    target_width = width - ellipsis_width
    current_width = 0
    characters: list[str] = []
    for character in value:
        character_width = _display_width(character)
        if current_width + character_width > target_width:
            break

        characters.append(character)
        current_width += character_width

    return "".join(characters) + ellipsis


def _fit_text(value: str, width: int, *, align: str = "left") -> str:
    normalized_value = _sanitize_text(value)
    if _display_width(normalized_value) > width:
        normalized_value = _truncate_text_to_width(normalized_value, width)

    padding = max(0, width - _display_width(normalized_value))
    if align == "center":
        left_padding = padding // 2
        right_padding = padding - left_padding
        return (" " * left_padding) + normalized_value + (" " * right_padding)
    if align == "right":
        return (" " * padding) + normalized_value
    return normalized_value + (" " * padding)


def _ansi_cell(
        text: str,
        width: int,
        *,
        color: str,
        align: str = "left",
) -> str:
    return f"{color}{_fit_text(text, width, align=align)}"


def _ansi_padded_cell(
        text: str,
        width: int,
        *,
        color: str,
        left_padding: int = 0,
        right_padding: int = 0,
        align: str = "left",
) -> str:
    content_width = max(0, width - left_padding - right_padding)
    rendered_text = (
            " " * left_padding
            + _fit_text(text, content_width, align=align)
            + " " * right_padding
    )
    return f"{color}{rendered_text}"


def _ansi_dash_aware_cell(
        text: str,
        width: int,
        *,
        color: str,
        left_padding: int = 0,
        right_padding: int = 0,
) -> str:
    normalized_text = _sanitize_text(text)
    if normalized_text == "-":
        return _ansi_padded_cell(
            normalized_text,
            width,
            color=color,
            left_padding=left_padding,
            right_padding=right_padding,
            align="center",
        )

    return _ansi_padded_cell(
        normalized_text,
        width,
        color=color,
        left_padding=left_padding,
        right_padding=right_padding,
    )


def _ansi_block(lines: list[str]) -> str:
    return "```ansi\n" + "\n".join(lines) + f"{ANSI_RESET}\n```"


def build_team_profile_ansi_sections(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> tuple[str, ...]:
    return _wrap_ansi_blocks(
        list(
            _build_team_profile_ansi_lines(
                team_profile=team_profile,
                localizer=localizer,
                locale=locale,
            )
        )
    )


def build_team_profile_ansi_message(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> str:
    return "\n\n".join(
        build_team_profile_ansi_sections(
            team_profile=team_profile,
            localizer=localizer,
            locale=locale,
        )
    )


def build_team_profile_ansi_file(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> discord.File:
    content = build_team_profile_ansi_message(
        team_profile=team_profile,
        localizer=localizer,
        locale=locale,
    )
    file_name = _build_team_profile_file_name(team_profile.team_name)
    return discord.File(
        BytesIO(content.encode("utf-8")),
        filename=file_name,
    )


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
    file_name = _build_team_profile_png_file_name(team_profile.team_name)
    return discord.File(
        BytesIO(image_data),
        filename=file_name,
    )


def _wrap_ansi_blocks(lines: list[str]) -> tuple[str, ...]:
    if not lines:
        return ()

    chunks: list[str] = []
    current_chunk: list[str] = []
    for line in lines:
        candidate_chunk = _ansi_block(current_chunk + [line])
        if current_chunk and len(candidate_chunk) > DISCORD_MESSAGE_LIMIT:
            chunks.append(_ansi_block(current_chunk))
            current_chunk = [line]
            continue

        current_chunk.append(line)

    if current_chunk:
        chunks.append(_ansi_block(current_chunk))

    return tuple(chunks)


def _build_team_profile_ansi_lines(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> tuple[str, ...]:
    title_lines = _build_title_lines(team_profile)
    roster_lines = _build_roster_lines(
        team_profile,
        localizer=localizer,
        locale=locale,
    )
    tracker_lines = _build_tracker_lines(
        team_profile,
        localizer=localizer,
        locale=locale,
    )
    technical_staff_lines = _build_technical_staff_lines(
        team_profile,
        localizer=localizer,
        locale=locale,
    )
    lines = title_lines + roster_lines + [""] + tracker_lines
    if technical_staff_lines:
        lines += [""] + technical_staff_lines

    return tuple(lines)


def _build_title_lines(team_profile: TeamProfile) -> list[str]:
    return [
        f"{ANSI_BLUE}{BOX_TOP_LEFT}{BOX_HORIZONTAL * TITLE_BLOCK_WIDTH}{BOX_TOP_RIGHT}",
        (
            f"{ANSI_BLUE}{BOX_VERTICAL}{ANSI_WHITE}"
            f"{_fit_text(team_profile.team_name.upper(), TITLE_BLOCK_WIDTH, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
        ),
        (
            f"{ANSI_BLUE}{BOX_VERTICAL}{ANSI_MAGENTA}"
            f"{_fit_text(team_profile.division_name.upper(), TITLE_BLOCK_WIDTH, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
        ),
    ]


def _build_roster_lines(
        team_profile: TeamProfile,
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> list[str]:
    remaining_signings_label = localizer.translate(
        I18N.messages.team_profile.ansi.summary.remaining_signings,
        locale=locale,
    )
    team_average_label = localizer.translate(
        I18N.messages.team_profile.ansi.summary.team_average,
        locale=locale,
    )
    header_player = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.player,
    )
    header_discord = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.discord,
    )
    header_epic = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.epic_name,
    )
    header_rocket = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.rocket_name,
    )
    header_mmr = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.mmr,
    )

    lines = [
        (
            f"{ANSI_BLUE}{BOX_LEFT_T}{BOX_HORIZONTAL * POSITION_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * PLAYER_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * MMR_WIDTH}{BOX_TOP_RIGHT}"
        ),
        (
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(_header(localizer, locale, I18N.messages.team_profile.ansi.headers.position), POSITION_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_player, PLAYER_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_discord, DISCORD_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_epic, EPIC_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_rocket, ROCKET_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_mmr, MMR_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
        ),
        (
            f"{ANSI_BLUE}{BOX_LEFT_T}{BOX_HORIZONTAL * POSITION_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * PLAYER_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * MMR_WIDTH}{BOX_RIGHT_T}"
        ),
    ]

    for player in team_profile.players:
        lines.append(
            (
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_cell(str(player.position), POSITION_WIDTH, color=ANSI_RED, align='center')}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(player.player_name, PLAYER_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(player.discord_name, DISCORD_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(player.epic_name, EPIC_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(player.rocket_name, ROCKET_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(player.mmr, MMR_WIDTH, color=ANSI_MAGENTA, left_padding=MMR_LEFT_PADDING, right_padding=MMR_RIGHT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
            )
        )

    left_span_width = PLAYER_WIDTH + DISCORD_WIDTH + 1
    right_span_width = EPIC_WIDTH + ROCKET_WIDTH + 1
    lines.extend(
        [
            (
                f"{ANSI_BLUE}{BOX_LEFT_T}{BOX_HORIZONTAL * POSITION_WIDTH}{BOX_CROSS}"
                f"{BOX_HORIZONTAL * PLAYER_WIDTH}{BOX_BOTTOM_T}"
                f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_CROSS}"
                f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_BOTTOM_T}"
                f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_CROSS}"
                f"{BOX_HORIZONTAL * MMR_WIDTH}{BOX_RIGHT_T}"
            ),
            (
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_cell(team_profile.remaining_signings, POSITION_WIDTH, color=ANSI_YELLOW, align='center')}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(remaining_signings_label, left_span_width, color=ANSI_WHITE, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(team_average_label, right_span_width, color=ANSI_WHITE, right_padding=1, align='right')}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(team_profile.top_three_average, MMR_WIDTH, color=ANSI_YELLOW, left_padding=MMR_LEFT_PADDING, right_padding=MMR_RIGHT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
            ),
            (
                f"{ANSI_BLUE}{BOX_BOTTOM_LEFT}{BOX_HORIZONTAL * POSITION_WIDTH}{BOX_BOTTOM_T}"
                f"{BOX_HORIZONTAL * left_span_width}{BOX_BOTTOM_T}"
                f"{BOX_HORIZONTAL * right_span_width}{BOX_BOTTOM_T}"
                f"{BOX_HORIZONTAL * MMR_WIDTH}{BOX_BOTTOM_RIGHT}"
            ),
        ]
    )
    return lines


def _build_tracker_lines(
        team_profile: TeamProfile,
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> list[str]:
    tracker_title = localizer.translate(
        I18N.messages.team_profile.ansi.tracker.title,
        locale=locale,
    )

    lines = [
        (
            f"{ANSI_BLUE}{BOX_TOP_LEFT}{BOX_HORIZONTAL * POSITION_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * TRACKER_WIDTH}{BOX_TOP_RIGHT}"
        ),
        (
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(_header(localizer, locale, I18N.messages.team_profile.ansi.headers.position), POSITION_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(tracker_title, TRACKER_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
        ),
        (
            f"{ANSI_BLUE}{BOX_LEFT_T}{BOX_HORIZONTAL * POSITION_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * TRACKER_WIDTH}{BOX_RIGHT_T}"
        ),
    ]

    for player in team_profile.players:
        tracker_value = _display_tracker_value(player.tracker_url, missing_tracker)
        lines.append(
            (
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_cell(str(player.position), POSITION_WIDTH, color=ANSI_RED, align='center')}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(tracker_value, TRACKER_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
            )
        )

    lines.append(
        f"{ANSI_BLUE}{BOX_BOTTOM_LEFT}{BOX_HORIZONTAL * POSITION_WIDTH}{BOX_BOTTOM_T}"
        f"{BOX_HORIZONTAL * TRACKER_WIDTH}{BOX_BOTTOM_RIGHT}"
    )
    return lines


def _build_technical_staff_lines(
        team_profile: TeamProfile,
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> list[str]:
    if not team_profile.technical_staff:
        return []

    title = localizer.translate(
        I18N.messages.team_profile.ansi.technical_staff.title,
        locale=locale,
    )
    header_role = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.role,
    )
    header_discord = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.discord,
    )
    header_epic = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.epic_name,
    )
    header_rocket = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.rocket_name,
    )

    lines = [
        f"{ANSI_BLUE}{BOX_TOP_LEFT}{BOX_HORIZONTAL * TECHNICAL_STAFF_TABLE_WIDTH}{BOX_TOP_RIGHT}",
        (
            f"{ANSI_BLUE}{BOX_VERTICAL}{ANSI_YELLOW}"
            f"{_fit_text(title, TECHNICAL_STAFF_TABLE_WIDTH, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
        ),
        (
            f"{ANSI_BLUE}{BOX_LEFT_T}{BOX_HORIZONTAL * ROLE_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_RIGHT_T}"
        ),
        (
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_role, ROLE_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_discord, DISCORD_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_epic, EPIC_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_rocket, ROCKET_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
        ),
        (
            f"{ANSI_BLUE}{BOX_LEFT_T}{BOX_HORIZONTAL * ROLE_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_RIGHT_T}"
        ),
    ]

    for member in team_profile.technical_staff:
        lines.append(
            (
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(member.role_name, ROLE_WIDTH, color=ANSI_RED, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(member.discord_name, DISCORD_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(member.epic_name, EPIC_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(member.rocket_name, ROCKET_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
            )
        )

    lines.append(
        f"{ANSI_BLUE}{BOX_BOTTOM_LEFT}{BOX_HORIZONTAL * ROLE_WIDTH}{BOX_BOTTOM_T}"
        f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_BOTTOM_T}"
        f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_BOTTOM_T}"
        f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_BOTTOM_RIGHT}"
    )
    return lines


def _header(
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        key: TranslationKeyLike,
) -> str:
    return localizer.translate(key, locale=locale).upper()


def _display_tracker_value(url: str | None, missing_value: str) -> str:
    if not url:
        return missing_value

    normalized_url = _sanitize_text(url)
    for prefix in ("https://", "http://"):
        if normalized_url.startswith(prefix):
            normalized_url = normalized_url[len(prefix):]
            break

    normalized_url = normalized_url.rstrip("/")
    if "/" in normalized_url:
        normalized_url = normalized_url.rsplit("/", 1)[0]

    return normalized_url or missing_value


def _build_team_profile_file_name(team_name: str) -> str:
    normalized_name = "".join(
        character.lower() if character.isalnum() else "_"
        for character in _sanitize_text(team_name)
    ).strip("_")
    if not normalized_name:
        normalized_name = "equipo"

    return f"{normalized_name}.ansi.txt"


def _build_team_profile_png_file_name(team_name: str) -> str:
    return _build_team_profile_file_name(team_name).removesuffix(".ansi.txt") + ".png"


def _render_team_profile_image(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        font_path: Path | None = None,
) -> bytes:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise CommandUserError(
            localize(I18N.errors.team_profile.image_dependencies_missing)
        ) from exc

    font = _load_team_profile_font(ImageFont, font_path=font_path)
    unit_width = _measure_unit_width(font)
    line_height = _measure_line_height(font)
    row_height = line_height + TEAM_PROFILE_IMAGE_CELL_PADDING_Y * 2

    position_width = POSITION_WIDTH * unit_width
    player_width = PLAYER_WIDTH * unit_width
    discord_width = DISCORD_WIDTH * unit_width
    epic_width = EPIC_WIDTH * unit_width
    rocket_width = ROCKET_WIDTH * unit_width
    mmr_width = MMR_WIDTH * unit_width
    role_width = ROLE_WIDTH * unit_width

    main_column_widths = (
        position_width,
        player_width,
        discord_width,
        epic_width,
        rocket_width,
        mmr_width,
    )
    main_table_width = sum(main_column_widths)
    tracker_column_widths = (
        position_width,
        main_table_width - position_width,
    )
    technical_staff_extra_width = main_table_width - (
            role_width + discord_width + epic_width + rocket_width
    )
    technical_staff_discord_extra_width = technical_staff_extra_width // 2
    technical_staff_epic_extra_width = technical_staff_extra_width - technical_staff_discord_extra_width
    technical_staff_column_widths = (
        role_width,
        discord_width + technical_staff_discord_extra_width,
        epic_width + technical_staff_epic_extra_width,
        rocket_width,
    )

    tracker_table_width = sum(tracker_column_widths)
    technical_staff_table_width = sum(technical_staff_column_widths)
    title_block_width = position_width + player_width + discord_width

    title_height = row_height * 2
    main_table_height = row_height * (1 + len(team_profile.players) + 1)
    tracker_table_height = row_height * (1 + len(team_profile.players))
    technical_staff_table_height = 0
    if team_profile.technical_staff:
        technical_staff_table_height = row_height * (
                1 + 1 + len(team_profile.technical_staff)
        )

    image_width = TEAM_PROFILE_IMAGE_PADDING_X * 2 + max(
        main_table_width,
        tracker_table_width,
        technical_staff_table_width,
    )
    image_height = (
            TEAM_PROFILE_IMAGE_PADDING_Y * 2
            + title_height
            + main_table_height
            + TEAM_PROFILE_IMAGE_SECTION_SPACING
            + tracker_table_height
    )
    if technical_staff_table_height:
        image_height += (
                TEAM_PROFILE_IMAGE_SECTION_SPACING + technical_staff_table_height
        )

    image = Image.new(
        "RGB",
        (image_width, image_height),
        TEAM_PROFILE_IMAGE_BACKGROUND,
    )
    draw = ImageDraw.Draw(image)
    left_padding_px = TEXT_COLUMN_LEFT_PADDING * unit_width
    mmr_left_padding_px = MMR_LEFT_PADDING * unit_width
    mmr_right_padding_px = MMR_RIGHT_PADDING * unit_width

    position_header = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.position,
    )
    player_header = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.player,
    )
    discord_header = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.discord,
    )
    epic_header = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.epic_name,
    )
    rocket_header = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.rocket_name,
    )
    mmr_header = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.mmr,
    )
    role_header = _header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.role,
    )
    tracker_title = localizer.translate(
        I18N.messages.team_profile.ansi.tracker.title,
        locale=locale,
    )
    missing_tracker = localizer.translate(
        I18N.messages.team_profile.ansi.tracker.missing_value,
        locale=locale,
    )
    remaining_signings_label = localizer.translate(
        I18N.messages.team_profile.ansi.summary.remaining_signings,
        locale=locale,
    )
    team_average_label = localizer.translate(
        I18N.messages.team_profile.ansi.summary.team_average,
        locale=locale,
    )
    technical_staff_title = localizer.translate(
        I18N.messages.team_profile.ansi.technical_staff.title,
        locale=locale,
    )

    x_origin = TEAM_PROFILE_IMAGE_PADDING_X
    y_origin = TEAM_PROFILE_IMAGE_PADDING_Y

    _draw_horizontal_line(
        draw,
        x_origin,
        x_origin + title_block_width,
        y_origin,
    )
    _draw_horizontal_line(
        draw,
        x_origin,
        x_origin + title_block_width,
        y_origin + title_height,
    )
    _draw_vertical_line(
        draw,
        x_origin,
        y_origin,
        y_origin + title_height,
    )
    _draw_vertical_line(
        draw,
        x_origin + title_block_width,
        y_origin,
        y_origin + title_height,
    )
    _draw_cell_text(
        draw,
        font,
        (x_origin, y_origin, x_origin + title_block_width, y_origin + row_height),
        team_profile.team_name.upper(),
        fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
        align="center",
    )
    _draw_cell_text(
        draw,
        font,
        (
            x_origin,
            y_origin + row_height,
            x_origin + title_block_width,
            y_origin + title_height,
        ),
        team_profile.division_name.upper(),
        fill=ANSI_COLOR_TO_RGB[ANSI_MAGENTA],
        align="center",
    )

    main_table_y = y_origin + title_height
    summary_start_y = main_table_y + row_height * (1 + len(team_profile.players))
    _draw_box(draw, x_origin, main_table_y, main_table_width, main_table_height)
    for row_index in range(1, 1 + len(team_profile.players) + 1):
        _draw_horizontal_line(
            draw,
            x_origin,
            x_origin + main_table_width,
            main_table_y + row_height * row_index,
        )

    main_boundaries = _accumulate_boundaries(x_origin, main_column_widths)
    for boundary in main_boundaries[1:-1]:
        _draw_vertical_line(draw, boundary, main_table_y, summary_start_y)

    summary_boundaries = (
        x_origin + position_width,
        x_origin + position_width + player_width + discord_width,
        x_origin + position_width + player_width + discord_width + epic_width + rocket_width,
    )
    for boundary in summary_boundaries:
        _draw_vertical_line(
            draw,
            boundary,
            summary_start_y,
            main_table_y + main_table_height,
        )

    header_rects = _build_row_rects(
        x_origin,
        main_table_y,
        main_column_widths,
        row_height,
    )
    for rect, text in zip(
            header_rects,
            (
                    position_header,
                    player_header,
                    discord_header,
                    epic_header,
                    rocket_header,
                    mmr_header,
            ),
    ):
        _draw_cell_text(
            draw,
            font,
            rect,
            text,
            fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
            align="center",
        )

    for row_index, player in enumerate(team_profile.players, start=1):
        row_rects = _build_row_rects(
            x_origin,
            main_table_y + row_height * row_index,
            main_column_widths,
            row_height,
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[0],
            str(player.position),
            fill=ANSI_COLOR_TO_RGB[ANSI_RED],
            align="center",
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[1],
            player.player_name,
            fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
            left_padding=left_padding_px,
            dash_center=True,
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[2],
            player.discord_name,
            fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
            left_padding=left_padding_px,
            dash_center=True,
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[3],
            player.epic_name,
            fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
            left_padding=left_padding_px,
            dash_center=True,
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[4],
            player.rocket_name,
            fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
            left_padding=left_padding_px,
            dash_center=True,
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[5],
            player.mmr,
            fill=ANSI_COLOR_TO_RGB[ANSI_MAGENTA],
            left_padding=mmr_left_padding_px,
            right_padding=mmr_right_padding_px,
        )

    summary_rects = (
        (x_origin, summary_start_y, x_origin + position_width, summary_start_y + row_height),
        (
            x_origin + position_width,
            summary_start_y,
            x_origin + position_width + player_width + discord_width,
            summary_start_y + row_height,
        ),
        (
            x_origin + position_width + player_width + discord_width,
            summary_start_y,
            x_origin + position_width + player_width + discord_width + epic_width + rocket_width,
            summary_start_y + row_height,
        ),
        (
            x_origin + main_table_width - mmr_width,
            summary_start_y,
            x_origin + main_table_width,
            summary_start_y + row_height,
        ),
    )
    _draw_cell_text(
        draw,
        font,
        summary_rects[0],
        team_profile.remaining_signings,
        fill=ANSI_COLOR_TO_RGB[ANSI_YELLOW],
        align="center",
    )
    _draw_cell_text(
        draw,
        font,
        summary_rects[1],
        remaining_signings_label,
        fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
        left_padding=left_padding_px,
    )
    _draw_cell_text(
        draw,
        font,
        summary_rects[2],
        team_average_label,
        fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
        right_padding=left_padding_px,
        align="right",
    )
    _draw_cell_text(
        draw,
        font,
        summary_rects[3],
        team_profile.top_three_average,
        fill=ANSI_COLOR_TO_RGB[ANSI_YELLOW],
        left_padding=mmr_left_padding_px,
        right_padding=mmr_right_padding_px,
    )

    tracker_y = main_table_y + main_table_height + TEAM_PROFILE_IMAGE_SECTION_SPACING
    tracker_height = tracker_table_height
    _draw_box(draw, x_origin, tracker_y, tracker_table_width, tracker_height)
    _draw_horizontal_line(
        draw,
        x_origin,
        x_origin + tracker_table_width,
        tracker_y + row_height,
    )
    tracker_boundary = x_origin + position_width
    _draw_vertical_line(
        draw,
        tracker_boundary,
        tracker_y,
        tracker_y + tracker_height,
    )
    for row_index in range(2, 1 + len(team_profile.players)):
        _draw_horizontal_line(
            draw,
            x_origin,
            x_origin + tracker_table_width,
            tracker_y + row_height * row_index,
        )

    tracker_header_rects = _build_row_rects(
        x_origin,
        tracker_y,
        tracker_column_widths,
        row_height,
    )
    _draw_cell_text(
        draw,
        font,
        tracker_header_rects[0],
        position_header,
        fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
        align="center",
    )
    _draw_cell_text(
        draw,
        font,
        tracker_header_rects[1],
        tracker_title,
        fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
        align="center",
    )
    for row_index, player in enumerate(team_profile.players, start=1):
        tracker_rects = _build_row_rects(
            x_origin,
            tracker_y + row_height * row_index,
            tracker_column_widths,
            row_height,
        )
        _draw_cell_text(
            draw,
            font,
            tracker_rects[0],
            str(player.position),
            fill=ANSI_COLOR_TO_RGB[ANSI_RED],
            align="center",
        )
        _draw_cell_text(
            draw,
            font,
            tracker_rects[1],
            _display_tracker_value(player.tracker_url, "-"),
            fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
            left_padding=left_padding_px,
            dash_center=True,
        )

    if technical_staff_table_height:
        staff_y = tracker_y + tracker_height + TEAM_PROFILE_IMAGE_SECTION_SPACING
        _draw_box(
            draw,
            x_origin,
            staff_y,
            technical_staff_table_width,
            technical_staff_table_height,
        )
        _draw_horizontal_line(
            draw,
            x_origin,
            x_origin + technical_staff_table_width,
            staff_y + row_height,
        )
        _draw_horizontal_line(
            draw,
            x_origin,
            x_origin + technical_staff_table_width,
            staff_y + row_height * 2,
        )
        staff_boundaries = _accumulate_boundaries(
            x_origin,
            technical_staff_column_widths,
        )
        for boundary in staff_boundaries[1:-1]:
            _draw_vertical_line(
                draw,
                boundary,
                staff_y + row_height,
                staff_y + technical_staff_table_height,
            )
        for row_index in range(3, 2 + len(team_profile.technical_staff)):
            _draw_horizontal_line(
                draw,
                x_origin,
                x_origin + technical_staff_table_width,
                staff_y + row_height * row_index,
            )

        _draw_cell_text(
            draw,
            font,
            (
                x_origin,
                staff_y,
                x_origin + technical_staff_table_width,
                staff_y + row_height,
            ),
            technical_staff_title,
            fill=ANSI_COLOR_TO_RGB[ANSI_YELLOW],
            align="center",
        )
        staff_header_rects = _build_row_rects(
            x_origin,
            staff_y + row_height,
            technical_staff_column_widths,
            row_height,
        )
        for rect, text in zip(
                staff_header_rects,
                (role_header, discord_header, epic_header, rocket_header),
        ):
            _draw_cell_text(
                draw,
                font,
                rect,
                text,
                fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
                align="center",
            )

        for row_index, member in enumerate(team_profile.technical_staff, start=2):
            member_rects = _build_row_rects(
                x_origin,
                staff_y + row_height * row_index,
                technical_staff_column_widths,
                row_height,
            )
            _draw_cell_text(
                draw,
                font,
                member_rects[0],
                member.role_name,
                fill=ANSI_COLOR_TO_RGB[ANSI_RED],
                left_padding=left_padding_px,
            )
            _draw_cell_text(
                draw,
                font,
                member_rects[1],
                member.discord_name,
                fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
                left_padding=left_padding_px,
                dash_center=True,
            )
            _draw_cell_text(
                draw,
                font,
                member_rects[2],
                member.epic_name,
                fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
                left_padding=left_padding_px,
                dash_center=True,
            )
            _draw_cell_text(
                draw,
                font,
                member_rects[3],
                member.rocket_name,
                fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
                left_padding=left_padding_px,
                dash_center=True,
            )

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _draw_box(
        draw: object,
        x_position: int,
        y_position: int,
        width: int,
        height: int,
) -> None:
    inset = TEAM_PROFILE_IMAGE_BORDER_WIDTH + TEAM_PROFILE_IMAGE_BORDER_GAP_WIDTH
    draw.rectangle(
        (
            x_position,
            y_position,
            x_position + width,
            y_position + height,
        ),
        outline=TEAM_PROFILE_IMAGE_BORDER_COLOR,
        width=TEAM_PROFILE_IMAGE_BORDER_WIDTH,
    )
    draw.rectangle(
        (
            x_position + inset,
            y_position + inset,
            x_position + width - inset,
            y_position + height - inset,
        ),
        outline=TEAM_PROFILE_IMAGE_BORDER_COLOR,
        width=TEAM_PROFILE_IMAGE_BORDER_WIDTH,
    )


def _draw_horizontal_line(
        draw: object,
        x_start: int,
        x_end: int,
        y_position: int,
) -> None:
    offset = TEAM_PROFILE_IMAGE_BORDER_WIDTH + TEAM_PROFILE_IMAGE_BORDER_GAP_WIDTH
    draw.line(
        ((x_start, y_position), (x_end, y_position)),
        fill=TEAM_PROFILE_IMAGE_BORDER_COLOR,
        width=TEAM_PROFILE_IMAGE_BORDER_WIDTH,
    )
    draw.line(
        ((x_start, y_position + offset), (x_end, y_position + offset)),
        fill=TEAM_PROFILE_IMAGE_BORDER_COLOR,
        width=TEAM_PROFILE_IMAGE_BORDER_WIDTH,
    )


def _draw_vertical_line(
        draw: object,
        x_position: int,
        y_start: int,
        y_end: int,
) -> None:
    offset = TEAM_PROFILE_IMAGE_BORDER_WIDTH + TEAM_PROFILE_IMAGE_BORDER_GAP_WIDTH
    draw.line(
        ((x_position, y_start), (x_position, y_end)),
        fill=TEAM_PROFILE_IMAGE_BORDER_COLOR,
        width=TEAM_PROFILE_IMAGE_BORDER_WIDTH,
    )
    draw.line(
        ((x_position + offset, y_start), (x_position + offset, y_end)),
        fill=TEAM_PROFILE_IMAGE_BORDER_COLOR,
        width=TEAM_PROFILE_IMAGE_BORDER_WIDTH,
    )


def _accumulate_boundaries(
        start_x: int,
        widths: tuple[int, ...],
) -> tuple[int, ...]:
    boundaries = [start_x]
    current = start_x
    for width in widths:
        current += width
        boundaries.append(current)

    return tuple(boundaries)


def _build_row_rects(
        start_x: int,
        start_y: int,
        widths: tuple[int, ...],
        row_height: int,
) -> tuple[tuple[int, int, int, int], ...]:
    boundaries = _accumulate_boundaries(start_x, widths)
    rects: list[tuple[int, int, int, int]] = []
    for left, right in zip(boundaries, boundaries[1:]):
        rects.append((left, start_y, right, start_y + row_height))

    return tuple(rects)


def _draw_cell_text(
        draw: object,
        font: object,
        rect: tuple[int, int, int, int],
        text: str,
        *,
        fill: tuple[int, int, int],
        align: str = "left",
        left_padding: int = 0,
        right_padding: int = 0,
        dash_center: bool = False,
) -> None:
    normalized_text = _sanitize_text(text)
    if dash_center and normalized_text == "-":
        align = "center"
        left_padding = 0
        right_padding = 0

    rect_left, rect_top, rect_right, rect_bottom = rect
    content_top = rect_top + TEAM_PROFILE_IMAGE_TEXT_BORDER_INSET
    content_bottom = rect_bottom - TEAM_PROFILE_IMAGE_TEXT_BORDER_INSET
    effective_left_padding = left_padding
    effective_right_padding = right_padding
    if align != "center":
        if effective_left_padding == 0:
            effective_left_padding = TEAM_PROFILE_IMAGE_CELL_PADDING_X
        if effective_right_padding == 0:
            effective_right_padding = TEAM_PROFILE_IMAGE_CELL_PADDING_X

    available_width = max(
        0,
        rect_right - rect_left - effective_left_padding - effective_right_padding,
    )
    fitted_text = _fit_text_to_pixel_width(font, normalized_text, available_width)
    content_left = rect_left + effective_left_padding
    content_right = rect_right - effective_right_padding
    content_center_y = content_top + max(0, (content_bottom - content_top) // 2)
    if align == "center":
        text_x = rect_left + max(0, (rect_right - rect_left) // 2)
        anchor = "mm"
    elif align == "right":
        text_x = content_right
        anchor = "rm"
    else:
        text_x = content_left
        anchor = "lm"

    draw.text(
        (text_x, content_center_y),
        fitted_text,
        font=font,
        fill=fill,
        anchor=anchor,
    )


def _fit_text_to_pixel_width(font: object, text: str, width: int) -> str:
    normalized_text = _sanitize_text(text)
    if width <= 0:
        return ""

    if _measure_text_width(font, normalized_text) <= width:
        return normalized_text

    ellipsis = "\u2026"
    ellipsis_width = _measure_text_width(font, ellipsis)
    if ellipsis_width >= width:
        return ""

    characters: list[str] = []
    current_width = 0
    for character in normalized_text:
        character_width = _measure_text_width(font, character)
        if current_width + character_width + ellipsis_width > width:
            break

        characters.append(character)
        current_width += character_width

    return "".join(characters) + ellipsis


def _load_team_profile_font(
        image_font_module: object,
        *,
        font_path: Path | None = None,
) -> object:
    truetype = getattr(image_font_module, "truetype")
    if font_path is not None and font_path.exists():
        return truetype(str(font_path), TEAM_PROFILE_IMAGE_FONT_SIZE)

    for candidate_path in TEAM_PROFILE_FONT_CANDIDATES:
        if not candidate_path.exists():
            continue

        return truetype(str(candidate_path), TEAM_PROFILE_IMAGE_FONT_SIZE)

    return getattr(image_font_module, "load_default")()


def _measure_unit_width(font: object) -> int:
    return max(
        1,
        _measure_text_width(font, "0"),
        _measure_text_width(font, "M"),
    )


def _measure_text_width(font: object, text: str) -> int:
    if not text:
        return 0

    getlength = getattr(font, "getlength", None)
    if callable(getlength):
        return max(1, int(math.ceil(float(getlength(text)))))

    bbox = font.getbbox(text)
    return max(1, int(math.ceil(bbox[2] - bbox[0])))


def _measure_rendered_line_width(
        line_segments: tuple[tuple[str, tuple[int, int, int]], ...],
        font: object,
) -> int:
    return sum(
        _measure_text_width(font, text)
        for text, _color in line_segments
        if text
    )


def _measure_line_height(font: object) -> int:
    bbox = font.getbbox("Mg")
    return max(1, int(bbox[3] - bbox[1]))


def _parse_ansi_segments(line: str) -> tuple[tuple[str, tuple[int, int, int]], ...]:
    current_color = TEAM_PROFILE_IMAGE_DEFAULT_COLOR
    segments: list[tuple[str, tuple[int, int, int]]] = []
    for part in ANSI_ESCAPE_PATTERN.split(line):
        if not part:
            continue

        if ANSI_ESCAPE_PATTERN.fullmatch(part):
            current_color = ANSI_COLOR_TO_RGB.get(part, current_color)
            continue

        segments.append((part, current_color))

    return tuple(segments)
