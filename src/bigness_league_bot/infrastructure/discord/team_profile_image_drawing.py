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


def fit_text_to_pixel_width(font: object, text: str, width: int) -> str:
    normalized_text = sanitize_text(text)
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


def _load_team_profile_font_context(
        image_font_module: object,
        *,
        font_path: Path | None = None,
) -> tuple[object, int, int]:
    font = _load_team_profile_font(image_font_module, font_path=font_path)
    unit_width = _measure_unit_width(font)
    line_height = _measure_line_height(font)
    row_height = line_height + TEAM_PROFILE_IMAGE_CELL_PADDING_Y * 2
    return font, unit_width, row_height


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


def _measure_line_height(font: object) -> int:
    bbox = font.getbbox("Mg")
    return max(1, int(bbox[3] - bbox[1]))
