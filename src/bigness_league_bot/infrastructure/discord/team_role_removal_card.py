from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import discord

PROJECT_ROOT = Path(__file__).resolve().parents[4]

TEAM_ROLE_REMOVAL_CARD_WIDTH = 980
TEAM_ROLE_REMOVAL_CARD_HEIGHT = 360
TEAM_ROLE_REMOVAL_CARD_PADDING_X = 56
TEAM_ROLE_REMOVAL_CARD_BACKGROUND = (12, 18, 28)
TEAM_ROLE_REMOVAL_CARD_BORDER_COLOR = (59, 130, 246)
TEAM_ROLE_REMOVAL_CARD_TEXT_COLOR = (241, 245, 249)
TEAM_ROLE_REMOVAL_CARD_ACCENT_COLOR = (248, 113, 113)
TEAM_ROLE_REMOVAL_CARD_ROLE_COLOR = (241, 245, 249)
TEAM_ROLE_REMOVAL_CARD_DIVIDER_COLOR = (59, 130, 246)
TEAM_ROLE_REMOVAL_CARD_BORDER_WIDTH = 1
TEAM_ROLE_REMOVAL_CARD_BORDER_GAP_WIDTH = 2
TEAM_ROLE_REMOVAL_CARD_LINE_ONE_FONT_SIZE = 34
TEAM_ROLE_REMOVAL_CARD_LINE_TWO_FONT_SIZE = 48
TEAM_ROLE_REMOVAL_CARD_LINE_THREE_FONT_SIZE = 38
TEAM_ROLE_REMOVAL_CARD_LINE_SPACING = 26
TEAM_ROLE_REMOVAL_CARD_BLOCK_SPACING = 30
TEAM_ROLE_REMOVAL_CARD_MIN_LINE_HEIGHT = 44
TEAM_ROLE_REMOVAL_CARD_FONT_CANDIDATES = (
    PROJECT_ROOT / "aa_resources/fonts/MapleMono-NF-CN-Regular.ttf",
    PROJECT_ROOT / "aa_resources/fonts/MapleMono-CN-Regular.ttf",
    Path(r"C:\Windows\Fonts\msgothic.ttc"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
    Path(r"C:\Windows\Fonts\consola.ttf"),
    Path(r"C:\Windows\Fonts\cour.ttf"),
    Path(r"C:\Windows\Fonts\lucon.ttf"),
)

Color = tuple[int, int, int]
Point = tuple[int, int]
Rectangle = tuple[int, int, int, int]
Line = tuple[int, int, int, int]

if TYPE_CHECKING:
    from PIL.ImageDraw import ImageDraw as ImageDrawLike
    from PIL.ImageFont import FreeTypeFont, ImageFont

    FontLike = ImageFont | FreeTypeFont
else:
    class ImageDrawLike(Protocol):
        def rectangle(self, xy: Rectangle, *, outline: Color, width: int) -> None:
            ...

        def line(self, xy: Line, *, fill: Color, width: int) -> None:
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


def build_team_role_removal_image_file(
        *,
        member: discord.Member,
        team_role: discord.Role,
        action_text: str,
        font_path: Path | None = None,
        accent_color: tuple[int, int, int] = TEAM_ROLE_REMOVAL_CARD_ACCENT_COLOR,
) -> discord.File:
    image_data = _render_team_role_removal_image(
        member=member,
        team_role=team_role,
        action_text=action_text,
        font_path=font_path,
        accent_color=accent_color,
    )
    filename = f"team-role-removal-{member.id}-{team_role.id}.png"
    return discord.File(
        BytesIO(image_data),
        filename=filename,
    )


def _render_team_role_removal_image(
        *,
        member: discord.Member,
        team_role: discord.Role,
        action_text: str,
        font_path: Path | None,
        accent_color: tuple[int, int, int],
) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow no está disponible para renderizar la tarjeta PNG.") from exc

    image = Image.new(
        "RGB",
        (TEAM_ROLE_REMOVAL_CARD_WIDTH, TEAM_ROLE_REMOVAL_CARD_HEIGHT),
        TEAM_ROLE_REMOVAL_CARD_BACKGROUND,
    )
    draw = ImageDraw.Draw(image)
    line_one_font = _load_font(
        size=TEAM_ROLE_REMOVAL_CARD_LINE_ONE_FONT_SIZE,
        font_path=font_path,
    )
    line_two_font = _load_font(
        size=TEAM_ROLE_REMOVAL_CARD_LINE_TWO_FONT_SIZE,
        font_path=font_path,
    )
    line_three_font = _load_font(
        size=TEAM_ROLE_REMOVAL_CARD_LINE_THREE_FONT_SIZE,
        font_path=font_path,
    )

    _draw_double_border(draw)

    max_text_width = TEAM_ROLE_REMOVAL_CARD_WIDTH - TEAM_ROLE_REMOVAL_CARD_PADDING_X * 2
    line_one_text = _fit_text_to_pixel_width(
        line_one_font,
        member.name,
        max_text_width,
    )
    line_two_text = _fit_text_to_pixel_width(
        line_two_font,
        action_text.upper(),
        max_text_width,
    )
    line_three_text = _fit_text_to_pixel_width(
        line_three_font,
        team_role.name,
        max_text_width,
    )

    line_one_height = max(TEAM_ROLE_REMOVAL_CARD_MIN_LINE_HEIGHT, _measure_line_height(line_one_font))
    line_two_height = max(TEAM_ROLE_REMOVAL_CARD_MIN_LINE_HEIGHT, _measure_line_height(line_two_font))
    line_three_height = max(TEAM_ROLE_REMOVAL_CARD_MIN_LINE_HEIGHT, _measure_line_height(line_three_font))
    total_content_height = (
            line_one_height
            + TEAM_ROLE_REMOVAL_CARD_LINE_SPACING
            + TEAM_ROLE_REMOVAL_CARD_BLOCK_SPACING
            + line_two_height
            + TEAM_ROLE_REMOVAL_CARD_BLOCK_SPACING
            + TEAM_ROLE_REMOVAL_CARD_LINE_SPACING
            + line_three_height
    )
    content_center_x = TEAM_ROLE_REMOVAL_CARD_WIDTH // 2
    current_y = max(
        TEAM_ROLE_REMOVAL_CARD_PADDING_X,
        (TEAM_ROLE_REMOVAL_CARD_HEIGHT - total_content_height) // 2,
    )

    _draw_centered_text(
        draw,
        line_one_font,
        line_one_text,
        content_center_x,
        current_y + line_one_height // 2,
        fill=TEAM_ROLE_REMOVAL_CARD_TEXT_COLOR,
    )
    current_y += line_one_height + TEAM_ROLE_REMOVAL_CARD_LINE_SPACING

    divider_half_width = max_text_width // 4
    draw.line(
        (
            content_center_x - divider_half_width,
            current_y,
            content_center_x + divider_half_width,
            current_y,
        ),
        fill=TEAM_ROLE_REMOVAL_CARD_DIVIDER_COLOR,
        width=TEAM_ROLE_REMOVAL_CARD_BORDER_WIDTH,
    )
    current_y += TEAM_ROLE_REMOVAL_CARD_BLOCK_SPACING

    _draw_centered_text(
        draw,
        line_two_font,
        line_two_text,
        content_center_x,
        current_y + line_two_height // 2,
        fill=accent_color,
    )
    current_y += line_two_height + TEAM_ROLE_REMOVAL_CARD_BLOCK_SPACING

    draw.line(
        (
            content_center_x - divider_half_width,
            current_y,
            content_center_x + divider_half_width,
            current_y,
        ),
        fill=TEAM_ROLE_REMOVAL_CARD_DIVIDER_COLOR,
        width=TEAM_ROLE_REMOVAL_CARD_BORDER_WIDTH,
    )
    current_y += TEAM_ROLE_REMOVAL_CARD_LINE_SPACING

    _draw_centered_text(
        draw,
        line_three_font,
        line_three_text,
        content_center_x,
        current_y + line_three_height // 2,
        fill=TEAM_ROLE_REMOVAL_CARD_ROLE_COLOR,
    )

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _draw_double_border(draw: ImageDrawLike) -> None:
    inset = TEAM_ROLE_REMOVAL_CARD_BORDER_WIDTH + TEAM_ROLE_REMOVAL_CARD_BORDER_GAP_WIDTH
    draw.rectangle(
        (
            0,
            0,
            TEAM_ROLE_REMOVAL_CARD_WIDTH - 1,
            TEAM_ROLE_REMOVAL_CARD_HEIGHT - 1,
        ),
        outline=TEAM_ROLE_REMOVAL_CARD_BORDER_COLOR,
        width=TEAM_ROLE_REMOVAL_CARD_BORDER_WIDTH,
    )
    draw.rectangle(
        (
            inset,
            inset,
            TEAM_ROLE_REMOVAL_CARD_WIDTH - inset - 1,
            TEAM_ROLE_REMOVAL_CARD_HEIGHT - inset - 1,
        ),
        outline=TEAM_ROLE_REMOVAL_CARD_BORDER_COLOR,
        width=TEAM_ROLE_REMOVAL_CARD_BORDER_WIDTH,
    )


def _draw_centered_text(
        draw: ImageDrawLike,
        font: FontLike,
        text: str,
        center_x: int,
        center_y: int,
        *,
        fill: Color,
) -> None:
    draw.text(
        (center_x, center_y),
        text,
        font=font,
        fill=fill,
        anchor="mm",
    )


def _fit_text_to_pixel_width(font: FontLike, text: str, width: int) -> str:
    normalized_text = " ".join(text.split()).strip()
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


def _measure_text_width(font: FontLike, text: str) -> int:
    if not text:
        return 0

    bbox = font.getbbox(text)
    return max(1, int(math.ceil(bbox[2] - bbox[0])))


def _measure_line_height(font: FontLike) -> int:
    bbox = font.getbbox("Mg")
    return max(1, int(math.ceil(bbox[3] - bbox[1])))


def _load_font(
        *,
        size: int,
        font_path: Path | None,
) -> FontLike:
    from PIL import ImageFont

    if font_path is not None and font_path.exists():
        return ImageFont.truetype(str(font_path), size)

    for candidate_path in TEAM_ROLE_REMOVAL_CARD_FONT_CANDIDATES:
        if not candidate_path.exists():
            continue
        return ImageFont.truetype(str(candidate_path), size)

    return ImageFont.load_default()
