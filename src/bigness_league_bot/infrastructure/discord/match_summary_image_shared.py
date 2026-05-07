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
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bigness_league_bot.application.services.match_replays import (
    TEAM_NAME_IGNORED_TOKENS,
    TEAM_TOKEN_PATTERN,
)
from bigness_league_bot.infrastructure.discord.team_profile_layout import (
    TEAM_PROFILE_FONT_CANDIDATES,
    sanitize_text,
)

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PIL.Image import Image as SaveableImage
    from PIL.ImageDraw import ImageDraw as ImageDrawLike
    from PIL.ImageFont import FreeTypeFont, ImageFont

    FontLike = ImageFont | FreeTypeFont
else:
    class ImageDrawLike(Protocol):
        def rectangle(
                self,
                xy: tuple[int, int, int, int],
                *,
                fill: tuple[int, int, int] | None = None,
                outline: tuple[int, int, int] | None = None,
                width: int = 1,
        ) -> None:
            ...

        def rounded_rectangle(
                self,
                xy: tuple[int, int, int, int],
                radius: int = 0,
                *,
                fill: tuple[int, int, int] | None = None,
                outline: tuple[int, int, int] | None = None,
                width: int = 1,
        ) -> None:
            ...

        def text(
                self,
                xy: tuple[int, int],
                text: str,
                *,
                font: "FontLike",
                fill: tuple[int, int, int],
                anchor: str | None = None,
        ) -> None:
            ...

        def line(
                self,
                xy: tuple[tuple[int, int], tuple[int, int]],
                *,
                fill: tuple[int, int, int],
                width: int = 1,
        ) -> None:
            ...


    class FontLike(Protocol):
        def getbbox(self, text: str) -> tuple[float, float, float, float]:
            ...


class LogoImageLike(Protocol):
    def resize(self, size: tuple[int, int]) -> "LogoImageLike":
        ...


if not TYPE_CHECKING:
    class SaveableImage(Protocol):
        def save(self, fp: BytesIO, **params: object) -> None:
            ...

Color = tuple[int, int, int]
TableRow = tuple[str, ...]

BACKGROUND: Color = (12, 18, 28)
PANEL: Color = (17, 24, 39)
PANEL_ALT: Color = (24, 33, 49)
TEXT: Color = (241, 245, 249)
MUTED: Color = (148, 163, 184)
ACCENT: Color = (59, 130, 246)
BLUE_DARK: Color = (11, 39, 79)
GREEN_DARK: Color = (31, 75, 24)
GREEN: Color = (74, 222, 128)
RED: Color = (248, 113, 113)

PADDING_X = 42
PADDING_Y = 34
TITLE_FONT_SIZE = 32
SUBTITLE_FONT_SIZE = 22
BODY_FONT_SIZE = 18
SMALL_FONT_SIZE = 16
ROW_HEIGHT = 34
HEADER_HEIGHT = 38
SECTION_GAP = 30


def _draw_section_label(
        draw: ImageDrawLike,
        x: int,
        y: int,
        label: str,
        font: FontLike,
) -> None:
    draw.text((x, y), label, font=font, fill=ACCENT)


def _draw_card(
        draw: ImageDrawLike,
        rect: tuple[int, int, int, int],
        *,
        fill: Color = PANEL,
        outline: Color = ACCENT,
        radius: int = 12,
        width: int = 1,
) -> None:
    draw.rounded_rectangle(rect, radius=radius, fill=fill, outline=outline, width=width)


def _draw_badge(
        image: Any,
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        size: int,
        team_name: str,
        fill: Color,
        font: FontLike,
        logo_image: LogoImageLike | None = None,
) -> None:
    draw.rounded_rectangle((x, y, x + size, y + size), radius=size // 5, fill=fill, outline=TEXT, width=1)
    if logo_image is not None:
        logo = logo_image.resize((size - 10, size - 10))
        image.paste(logo, (x + 5, y + 5), logo)
        return

    draw.text(
        (x + size // 2, y + size // 2),
        _team_initials(team_name),
        font=font,
        fill=TEXT,
        anchor="mm",
    )


def _draw_table(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        columns: tuple[int, ...],
        headers: TableRow,
        rows: tuple[TableRow, ...],
        header_font: FontLike,
        body_font: FontLike,
        alignments: tuple[str, ...],
        header_height: int = HEADER_HEIGHT,
        row_height: int = ROW_HEIGHT,
        outline: Color | None = ACCENT,
        vertical_lines: bool = True,
) -> None:
    total_width = sum(columns)
    if outline is not None:
        draw.rectangle(
            (x, y, x + total_width, y + header_height + len(rows) * row_height),
            outline=outline,
            width=1,
        )
    draw.rectangle(
        (x, y, x + total_width, y + header_height),
        fill=PANEL_ALT,
    )
    _draw_row(
        draw,
        x=x,
        y=y,
        columns=columns,
        row=headers,
        font=header_font,
        row_height=header_height,
        alignments=alignments,
        fill=TEXT,
        vertical_lines=vertical_lines,
    )
    current_y = y + header_height
    for row in rows:
        _draw_row(
            draw,
            x=x,
            y=current_y,
            columns=columns,
            row=row,
            font=body_font,
            row_height=row_height,
            alignments=alignments,
            fill=_row_fill(row),
            vertical_lines=vertical_lines,
        )
        current_y += row_height


def _draw_row(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        columns: tuple[int, ...],
        row: TableRow,
        font: FontLike,
        row_height: int,
        alignments: tuple[str, ...],
        fill: Color,
        vertical_lines: bool = True,
) -> None:
    current_x = x
    for index, width in enumerate(columns):
        value = row[index] if index < len(row) else ""
        align = alignments[index] if index < len(alignments) else "left"
        _draw_cell(
            draw,
            x=current_x,
            y=y,
            width=width,
            height=row_height,
            text=value,
            font=font,
            fill=fill,
            align=align,
        )
        current_x += width
        if vertical_lines and index < len(columns) - 1:
            draw.line(((current_x, y), (current_x, y + row_height)), fill=(30, 41, 59), width=1)


def _draw_cell(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        height: int,
        text: str,
        font: FontLike,
        fill: Color,
        align: str,
) -> None:
    if width <= 40:
        padding = 3
    elif width <= 64:
        padding = 5
    else:
        padding = 10
    available_width = max(0, width - padding * 2)
    fitted_text = _fit_text(font, sanitize_text(text), available_width)
    center_y = y + height // 2
    if align == "center":
        text_x = x + width // 2
        anchor = "mm"
    elif align == "right":
        text_x = x + width - padding
        anchor = "rm"
    else:
        text_x = x + padding
        anchor = "lm"
    draw.text((text_x, center_y), fitted_text, font=font, fill=fill, anchor=anchor)


def _draw_fitted_text(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        text: str,
        font: FontLike,
        fill: Color,
        anchor: str,
) -> None:
    draw.text((x, y), _fit_text(font, sanitize_text(text), width), font=font, fill=fill, anchor=anchor)


def _row_fill(row: TableRow) -> Color:
    if "NO" in row:
        return RED
    if "SI" in row:
        return GREEN
    return TEXT


def _resolve_team_logo_url(
        team_logo_urls: Mapping[str, str | None],
        team_name: str,
) -> str | None:
    for key in (_team_identity(team_name), team_name):
        logo_url = team_logo_urls.get(key)
        if isinstance(logo_url, str) and logo_url.strip():
            return logo_url.strip()
    normalized_team = _team_identity(team_name)
    for candidate_name, logo_url in team_logo_urls.items():
        if not isinstance(logo_url, str) or not logo_url.strip():
            continue
        if _team_names_match_for_render(candidate_name, normalized_team):
            return logo_url.strip()
    return None


def _load_logo_image(
        image_module: Any,
        logo_url: str | None,
        fallback_logo_url: str | None,
        *,
        size: int,
) -> Any | None:
    for candidate_url in (logo_url, fallback_logo_url):
        if not candidate_url:
            continue
        try:
            return _fetch_logo_image(image_module, candidate_url, size=size)
        except HTTPError as exc:
            LOGGER.info(
                "No se pudo cargar logo para imagen de resumen url=%s status=%s reason=%s",
                candidate_url,
                exc.code,
                exc.reason,
            )
        except (OSError, TimeoutError, URLError, ValueError) as exc:
            LOGGER.info(
                "No se pudo cargar logo para imagen de resumen url=%s error=%s",
                candidate_url,
                exc,
            )
    return None


def _fetch_logo_image(image_module: Any, logo_url: str, *, size: int) -> Any:
    request = Request(
        logo_url,
        headers={"User-Agent": "BignessLeagueBot/1.0"},
    )
    with urlopen(request, timeout=8) as response:
        content = response.read(4 * 1024 * 1024)
    image = image_module.open(BytesIO(content)).convert("RGBA")
    image.thumbnail((size, size))
    canvas = image_module.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - image.width) // 2
    y = (size - image.height) // 2
    canvas.paste(image, (x, y), image)
    return canvas


def _team_names_match_for_render(candidate: str, expected: str) -> bool:
    normalized_candidate = _team_identity(candidate)
    normalized_expected = _team_identity(expected)
    if normalized_candidate == normalized_expected:
        return True
    if normalized_candidate and normalized_expected and (
            normalized_candidate in normalized_expected
            or normalized_expected in normalized_candidate
    ):
        return True
    candidate_tokens = set(_team_identity_tokens_for_render(normalized_candidate))
    expected_tokens = set(_team_identity_tokens_for_render(normalized_expected))
    return bool(candidate_tokens and expected_tokens) and (
            candidate_tokens <= expected_tokens
            or expected_tokens <= candidate_tokens
    )


def _team_identity_tokens_for_render(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in TEAM_TOKEN_PATTERN.findall(value)
        if token not in TEAM_NAME_IGNORED_TOKENS
    )


def _team_identity(value: str) -> str:
    return " ".join(value.casefold().split())


def _team_initials(team_name: str) -> str:
    words = [word for word in sanitize_text(team_name).split() if word]
    if not words:
        return "BL"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(word[0] for word in words[:3]).upper()


def _parse_score(value: str) -> tuple[int, int] | None:
    parts = value.replace(" ", "").split("-")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _load_font(
        *,
        size: int,
        font_path: Path | None,
) -> FontLike:
    try:
        from PIL import ImageFont
    except ImportError as exc:
        raise RuntimeError("Pillow no esta disponible para renderizar imagenes.") from exc

    candidates: list[Path] = []
    if font_path is not None:
        candidates.append(font_path)
    candidates.extend(TEAM_PROFILE_FONT_CANDIDATES)
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            if font_path is not None and candidate == font_path:
                LOGGER.warning("No se pudo cargar la fuente configurada para imagen de resumen: %s", candidate)
    return ImageFont.load_default()


def _fit_text(font: FontLike, text: str, width: int) -> str:
    if width <= 0:
        return ""
    if _text_width(font, text) <= width:
        return text
    ellipsis_text = "..."
    ellipsis_width = _text_width(font, ellipsis_text)
    if ellipsis_width >= width:
        return ""

    characters: list[str] = []
    current_width = 0
    for character in text:
        character_width = _text_width(font, character)
        if current_width + character_width + ellipsis_width > width:
            break
        characters.append(character)
        current_width += character_width
    return "".join(characters) + ellipsis_text


def _text_width(font: FontLike, text: str) -> int:
    left, _, right, _ = font.getbbox(text)
    return int(right - left)


def _save_png(image: SaveableImage) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _png_filename(value: str) -> str:
    safe_name = "".join(
        character.lower() if character.isalnum() else "-"
        for character in sanitize_text(value)
    ).strip("-")
    return f"{safe_name or 'resumen'}.png"
