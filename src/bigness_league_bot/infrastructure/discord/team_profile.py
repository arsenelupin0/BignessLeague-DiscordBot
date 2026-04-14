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
from io import BytesIO
from pathlib import Path

import discord

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import TranslationKeyLike, localize
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

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
PLAYER_WIDTH = 16
DISCORD_WIDTH = 22
EPIC_WIDTH = 17
ROCKET_WIDTH = 26
MMR_WIDTH = 7
TRACKER_WIDTH = PLAYER_WIDTH + DISCORD_WIDTH + EPIC_WIDTH + ROCKET_WIDTH + 3
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


def _sanitize_text(value: str) -> str:
    return " ".join(value.split())


def _fit_text(value: str, width: int, *, align: str = "left") -> str:
    normalized_value = _sanitize_text(value)
    if len(normalized_value) > width:
        normalized_value = normalized_value[: max(0, width - 1)] + "\u2026"

    if align == "center":
        return normalized_value.center(width)
    if align == "right":
        return normalized_value.rjust(width)
    return normalized_value.ljust(width)


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
) -> discord.File:
    image_data = _render_team_profile_image(
        team_profile=team_profile,
        localizer=localizer,
        locale=locale,
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
    return tuple(title_lines + roster_lines + [""] + tracker_lines)


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
                f"{_ansi_padded_cell(player.player_name, PLAYER_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(player.discord_name, DISCORD_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(player.epic_name, EPIC_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(player.rocket_name, ROCKET_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
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
    missing_tracker = localizer.translate(
        I18N.messages.team_profile.ansi.tracker.missing_value,
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

    if normalized_url.endswith("/overview"):
        normalized_url = normalized_url[: -len("/overview")]

    return normalized_url.rstrip("/") or missing_value


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
) -> bytes:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise CommandUserError(
            localize(I18N.errors.team_profile.image_dependencies_missing)
        ) from exc

    ansi_lines = _build_team_profile_ansi_lines(
        team_profile=team_profile,
        localizer=localizer,
        locale=locale,
    )
    parsed_lines = tuple(_parse_ansi_segments(line) for line in ansi_lines)
    font = _load_team_profile_font(ImageFont)
    char_width = _measure_char_width(font)
    line_height = _measure_line_height(font)
    max_line_length = max(
        (_plain_ansi_length(line) for line in ansi_lines),
        default=0,
    )
    image_width = TEAM_PROFILE_IMAGE_PADDING_X * 2 + max_line_length * char_width
    image_height = (
            TEAM_PROFILE_IMAGE_PADDING_Y * 2
            + len(parsed_lines) * line_height
            + max(0, len(parsed_lines) - 1) * TEAM_PROFILE_IMAGE_LINE_SPACING
    )

    image = Image.new(
        "RGB",
        (image_width, image_height),
        TEAM_PROFILE_IMAGE_BACKGROUND,
    )
    draw = ImageDraw.Draw(image)
    y_position = TEAM_PROFILE_IMAGE_PADDING_Y
    for line_segments in parsed_lines:
        x_position = TEAM_PROFILE_IMAGE_PADDING_X
        for text, color in line_segments:
            if not text:
                continue

            draw.text(
                (x_position, y_position),
                text,
                font=font,
                fill=color,
            )
            x_position += len(text) * char_width

        y_position += line_height + TEAM_PROFILE_IMAGE_LINE_SPACING

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _load_team_profile_font(image_font_module: object) -> object:
    truetype = getattr(image_font_module, "truetype")
    for font_path in TEAM_PROFILE_FONT_CANDIDATES:
        if not font_path.exists():
            continue

        return truetype(str(font_path), TEAM_PROFILE_IMAGE_FONT_SIZE)

    return getattr(image_font_module, "load_default")()


def _measure_char_width(font: object) -> int:
    bbox = font.getbbox("M")
    return max(1, int(bbox[2] - bbox[0]))


def _measure_line_height(font: object) -> int:
    bbox = font.getbbox("Mg")
    return max(1, int(bbox[3] - bbox[1]))


def _plain_ansi_length(line: str) -> int:
    return len(ANSI_ESCAPE_PATTERN.sub("", line))


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
