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

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

import discord

from bigness_league_bot.application.services.match_standings import MatchStandingRow
from bigness_league_bot.infrastructure.discord.match_summary_image_shared import (
    ACCENT,
    BACKGROUND,
    GREEN,
    MUTED,
    RED,
    TEXT,
    Color,
    FontLike,
    ImageDrawLike,
    _draw_badge,
    _draw_fitted_text,
    _load_font,
    _load_logo_image,
    _png_filename,
    _resolve_team_logo_url,
    _save_png,
    _text_width,
)


@dataclass(frozen=True, slots=True)
class _StandingZoneRules:
    top_positions: frozenset[int]
    danger_positions: frozenset[int]
    danger_label: str


_GOLD_ZONE_RULES = _StandingZoneRules(
    top_positions=frozenset((1, 2, 3, 4)),
    danger_positions=frozenset((6,)),
    danger_label="Play-out Descenso",
)
_SILVER_ZONE_RULES = _StandingZoneRules(
    top_positions=frozenset((1, 2)),
    danger_positions=frozenset((3,)),
    danger_label="Play-off Ascenso",
)


def build_match_standings_image_file(
        *,
        division_name: str,
        rows: tuple[MatchStandingRow, ...],
        font_path: Path | None = None,
        team_logo_urls: Mapping[str, str | None] | None = None,
        fallback_logo_url: str | None = None,
) -> discord.File:
    image_data = _render_match_standings_image(
        division_name=division_name,
        rows=rows,
        font_path=font_path,
        team_logo_urls=team_logo_urls or {},
        fallback_logo_url=fallback_logo_url,
    )
    return discord.File(
        BytesIO(image_data),
        filename=_png_filename(f"clasificacion-{division_name}"),
    )


def _render_match_standings_image(
        *,
        division_name: str,
        rows: tuple[MatchStandingRow, ...],
        font_path: Path | None,
        team_logo_urls: Mapping[str, str | None],
        fallback_logo_url: str | None,
) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow no esta disponible para renderizar imagenes.") from exc

    width = 1600
    height = 900
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    title_font = _load_font(size=64, font_path=font_path)
    subtitle_font = _load_font(size=24, font_path=font_path)
    header_font = _load_font(size=26, font_path=font_path)
    row_font = _load_font(size=30, font_path=font_path)
    value_font = _load_font(size=28, font_path=font_path)
    small_font = _load_font(size=20, font_path=font_path)
    logo_font = _load_font(size=22, font_path=font_path)
    zone_rules = _standing_zone_rules_for_division(division_name)

    _draw_standings_background(draw, width=width, height=height)
    _draw_standings_title(
        draw,
        width=width,
        division_name=division_name,
        title_font=title_font,
        subtitle_font=subtitle_font,
    )
    logo_images = {
        row.team_name: _load_logo_image(
            Image,
            _resolve_team_logo_url(team_logo_urls, row.team_name),
            fallback_logo_url,
            size=64,
        )
        for row in rows
    }
    _draw_standings_table(
        image,
        draw,
        x=72,
        y=190,
        width=1456,
        rows=rows,
        logo_images=logo_images,
        header_font=header_font,
        row_font=row_font,
        value_font=value_font,
        logo_font=logo_font,
        zone_rules=zone_rules,
    )
    _draw_standings_legend(draw, x=220, y=800, width=1160, font=small_font, zone_rules=zone_rules)
    return _save_png(image)


def _draw_standings_background(draw: ImageDrawLike, *, width: int, height: int) -> None:
    for y in range(0, height, 34):
        color = (8, 18, 34) if y % 68 == 0 else (10, 22, 39)
        draw.line(((0, y), (width, y)), fill=color, width=1)
    draw.rectangle((0, 0, width, 165), fill=(5, 14, 28))
    draw.rounded_rectangle((70, 180, width - 70, 762), radius=18, fill=(6, 18, 34), outline=ACCENT, width=3)


def _draw_standings_title(
        draw: ImageDrawLike,
        *,
        width: int,
        division_name: str,
        title_font: FontLike,
        subtitle_font: FontLike,
) -> None:
    title = f"CLASIFICACIÓN DE LA {division_name.upper()}"
    draw.text((width // 2 + 4, 66), title, font=title_font, fill=(0, 0, 0), anchor="mm")
    draw.text((width // 2, 62), title, font=title_font, fill=TEXT, anchor="mm")
    draw.text(
        (width // 2, 132),
        "TABLA DE POSICIONES - JORNADA ACTUAL",
        font=subtitle_font,
        fill=MUTED,
        anchor="mm",
    )


def _draw_standings_table(
        image: Any,
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        rows: tuple[MatchStandingRow, ...],
        logo_images: Mapping[str, Any | None],
        header_font: FontLike,
        row_font: FontLike,
        value_font: FontLike,
        logo_font: FontLike,
        zone_rules: _StandingZoneRules,
) -> None:
    columns = (118, 520, 116, 116, 226, 116, 116, 128)
    headers = ("POS", "EQUIPO", "PTS", "S.J.", "PARTIDOS", "GF", "GC", "DG")
    header_height = 58
    row_height = 64
    current_x = x
    for index, header in enumerate(headers):
        draw.text((current_x + columns[index] // 2, y + header_height // 2), header, font=header_font, fill=MUTED,
                  anchor="mm")
        current_x += columns[index]
    row_y = y + header_height
    for index, row in enumerate(rows):
        zone = _standing_zone(index + 1, zone_rules=zone_rules)
        zone_color = _standing_zone_color(zone)
        fill = _standing_zone_fill(zone)
        draw.rounded_rectangle(
            (x + 8, row_y + 4, x + width - 8, row_y + row_height - 4),
            radius=9,
            fill=fill,
            outline=zone_color,
            width=2 if zone != "middle" else 1,
        )
        _draw_standings_row(
            image,
            draw,
            x=x,
            y=row_y,
            columns=columns,
            row_height=row_height,
            row=row,
            zone_color=zone_color,
            logo_image=logo_images.get(row.team_name),
            row_font=row_font,
            value_font=value_font,
            logo_font=logo_font,
        )
        row_y += row_height


def _draw_standings_row(
        image: Any,
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        columns: tuple[int, ...],
        row_height: int,
        row: MatchStandingRow,
        zone_color: Color,
        logo_image: Any | None,
        row_font: FontLike,
        value_font: FontLike,
        logo_font: FontLike,
) -> None:
    values = (
        row.position,
        row.team_name,
        str(row.points),
        str(row.series_played),
        row.games_summary,
        str(row.goals_for),
        str(row.goals_against),
        str(row.goal_diff),
    )
    current_x = x
    _draw_standing_position(
        draw,
        x=current_x + columns[0] // 2,
        y=y + row_height // 2,
        value=values[0],
        font=row_font,
        suffix_font=logo_font,
        fill=zone_color,
    )
    current_x += columns[0]
    _draw_badge(
        image,
        draw,
        x=current_x + 32,
        y=y + 11,
        size=42,
        team_name=row.team_name,
        fill=(8, 25, 48),
        font=logo_font,
        logo_image=logo_image,
    )
    _draw_fitted_text(
        draw,
        x=current_x + 94,
        y=y + row_height // 2,
        width=columns[1] - 112,
        text=row.team_name,
        font=row_font,
        fill=TEXT,
        anchor="lm",
    )
    current_x += columns[1]
    for index, value in enumerate(values[2:], start=2):
        color = zone_color if index in (2, 8) and value not in {"0", "0 - 0 (0)"} else TEXT
        draw.text((current_x + columns[index] // 2, y + row_height // 2), value, font=value_font, fill=color,
                  anchor="mm")
        current_x += columns[index]


def _draw_standing_position(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        value: str,
        font: FontLike,
        suffix_font: FontLike,
        fill: Color,
) -> None:
    digits = "".join(character for character in value if character.isdigit())
    if not digits:
        draw.text((x, y), value, font=font, fill=fill, anchor="mm")
        return
    digit_width = _text_width(font, digits)
    draw.text((x - 5, y), digits, font=font, fill=fill, anchor="mm")
    draw.text((x + digit_width // 2 + 5, y - 8), "o", font=suffix_font, fill=fill, anchor="mm")


def _draw_standings_legend(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        font: FontLike,
        zone_rules: _StandingZoneRules,
) -> None:
    draw.rounded_rectangle((x, y, x + width, y + 52), radius=10, fill=(8, 18, 32), outline=(75, 85, 105), width=1)
    top_label = f"Top {max(zone_rules.top_positions)}"
    items = (
        (top_label, GREEN),
        ("Zona media", TEXT),
        (zone_rules.danger_label, (251, 146, 60)),
        ("Descenso", RED),
    )
    item_widths = tuple(48 + 16 + _text_width(font, label) for label, _ in items)
    gap = max(28, (width - sum(item_widths)) // (len(items) + 1))
    item_x = x + gap
    for index, (label, color) in enumerate(items):
        draw.rounded_rectangle((item_x, y + 18, item_x + 48, y + 34), radius=4, fill=color, outline=color, width=1)
        draw.text((item_x + 64, y + 26), label, font=font, fill=TEXT, anchor="lm")
        item_x += item_widths[index] + gap


def _standing_zone(position: int, *, zone_rules: _StandingZoneRules) -> str:
    if position in zone_rules.top_positions:
        return "top"
    if position in zone_rules.danger_positions:
        return "danger"
    if position >= 6:
        return "relegation"
    return "middle"


def _standing_zone_rules_for_division(division_name: str) -> _StandingZoneRules:
    normalized = " ".join(division_name.casefold().strip().split())
    if "silver" in normalized:
        return _SILVER_ZONE_RULES
    return _GOLD_ZONE_RULES


def _standing_zone_color(zone: str) -> Color:
    if zone == "top":
        return GREEN
    if zone == "danger":
        return 251, 146, 60
    if zone == "relegation":
        return RED
    return TEXT


def _standing_zone_fill(zone: str) -> Color:
    if zone == "top":
        return 5, 55, 26
    if zone == "danger":
        return 53, 31, 7
    if zone == "relegation":
        return 54, 13, 20
    return 9, 22, 38
