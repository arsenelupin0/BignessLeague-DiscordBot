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
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from PIL import ImageFont as PillowImageFont

from bigness_league_bot.infrastructure.discord.team_profile_layout import (
    TEAM_PROFILE_FONT_CANDIDATES,
    TEAM_PROFILE_IMAGE_BORDER_COLOR,
    TEAM_PROFILE_IMAGE_BORDER_GAP_WIDTH,
    TEAM_PROFILE_IMAGE_BORDER_WIDTH,
    TEAM_PROFILE_IMAGE_CELL_PADDING_X,
    TEAM_PROFILE_IMAGE_CELL_PADDING_Y,
    TEAM_PROFILE_IMAGE_FONT_SIZE,
    TEAM_PROFILE_IMAGE_TEXT_BORDER_INSET,
    sanitize_text,
)
from bigness_league_bot.main import LOGGER

Color = tuple[int, int, int]
Point = tuple[int, int]
Rectangle = tuple[int, int, int, int]
LinePoints = tuple[Point, Point]

if TYPE_CHECKING:
    from PIL.ImageDraw import ImageDraw as ImageDrawLike
    from PIL.ImageFont import FreeTypeFont, ImageFont

    FontLike = ImageFont | FreeTypeFont
else:
    class ImageDrawLike(Protocol):
        def rectangle(self, xy: Rectangle, *, outline: Color, width: int) -> None:
            ...

        def line(self, xy: LinePoints, *, fill: Color, width: int) -> None:
            ...

        def text(
                self,
                xy: Point,
                text: str,
                *,
                font: "FontLike",
                fill: Color,
                anchor: str,
        ) -> None:
            ...


    class FontLike(Protocol):
        def getbbox(self, text: str) -> tuple[float, float, float, float]:
            ...


def _draw_box(
        draw: ImageDrawLike,
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
        draw: ImageDrawLike,
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
        draw: ImageDrawLike,
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
        draw: ImageDrawLike,
        font: FontLike,
        rect: Rectangle,
        text: str,
        *,
        fill: Color,
        align: str = "left",
        left_padding: int = 0,
        right_padding: int = 0,
        dash_center: bool = False,
) -> None:
    normalized_text = sanitize_text(text)
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
    fitted_text = fit_text_to_pixel_width(font, normalized_text, available_width)
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


def fit_text_to_pixel_width(font: FontLike, text: str, width: int) -> str:
    normalized_text = sanitize_text(text)
    if width <= 0:
        return ""

    if _measure_text_width(font, normalized_text) <= width:
        return normalized_text

    ellipsis_text = "\u2026"
    ellipsis_width = _measure_text_width(font, ellipsis_text)
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

    return "".join(characters) + ellipsis_text


def _load_team_profile_font(
        *,
        font_path: Path | None = None,
) -> FontLike:
    if font_path is not None:
        font = _try_load_team_profile_font(font_path)
        if font is not None:
            return font

    for candidate_path in TEAM_PROFILE_FONT_CANDIDATES:
        font = _try_load_team_profile_font(candidate_path)
        if font is not None:
            return font

    return PillowImageFont.load_default()


def _try_load_team_profile_font(font_path: Path) -> FontLike | None:
    if not font_path.exists():
        return None

    try:
        return PillowImageFont.truetype(
            str(font_path),
            TEAM_PROFILE_IMAGE_FONT_SIZE,
        )
    except OSError:
        LOGGER.warning(
            "No se pudo cargar la fuente para la imagen de perfil de equipo: %s",
            font_path,
        )
        return None


def _load_team_profile_font_context(
        *,
        font_path: Path | None = None,
) -> tuple[FontLike, int, int]:
    font = _load_team_profile_font(font_path=font_path)
    unit_width = _measure_unit_width(font)
    line_height = _measure_line_height(font)
    row_height = line_height + TEAM_PROFILE_IMAGE_CELL_PADDING_Y * 2
    return font, unit_width, row_height


def _measure_unit_width(font: FontLike) -> int:
    return max(
        1,
        _measure_text_width(font, "0"),
        _measure_text_width(font, "M"),
    )


def _measure_text_width(font: FontLike, text: str) -> int:
    if not text:
        return 0

    bbox = font.getbbox(text)
    return max(1, int(math.ceil(bbox[2] - bbox[0])))


def _measure_line_height(font: FontLike) -> int:
    bbox = font.getbbox("Mg")
    return max(1, int(bbox[3] - bbox[1]))
