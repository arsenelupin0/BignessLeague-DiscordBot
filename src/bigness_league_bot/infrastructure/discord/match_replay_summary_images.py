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
from typing import Any, Mapping

import discord

from bigness_league_bot.application.services.match_replay_summaries import (
    MatchReplayPlayerStatTotal,
    build_match_replay_player_stat_totals,
)
from bigness_league_bot.application.services.match_replays import (
    MatchReplayReport,
    match_replay_game_score,
)
from bigness_league_bot.infrastructure.discord.match_replay_summary_game_sections import (
    _draw_game_cards,
    _draw_game_stat_cards,
    _game_stat_cards_total_height,
)
from bigness_league_bot.infrastructure.discord.match_summary_image_shared import (
    ACCENT,
    BACKGROUND,
    BLUE_DARK,
    GREEN,
    GREEN_DARK,
    MUTED,
    PADDING_X,
    PADDING_Y,
    SMALL_FONT_SIZE,
    SUBTITLE_FONT_SIZE,
    TEXT,
    Color,
    FontLike,
    ImageDrawLike,
    _draw_badge,
    _draw_card,
    _draw_section_label,
    _draw_table,
    _fit_text,
    _load_font,
    _load_logo_image,
    _parse_score,
    _png_filename,
    _resolve_team_logo_url,
    _save_png,
    _team_identity,
    _text_width,
)

LEADER_TITLE_GOLD: Color = (226, 184, 88)


def build_match_replay_summary_image_file(
        *,
        report: MatchReplayReport,
        font_path: Path | None = None,
        team_logo_urls: Mapping[str, str | None] | None = None,
        fallback_logo_url: str | None = None,
) -> discord.File:
    image_data = _render_match_replay_summary_image(
        report=report,
        font_path=font_path,
        team_logo_urls=team_logo_urls or {},
        fallback_logo_url=fallback_logo_url,
    )
    return discord.File(
        BytesIO(image_data),
        filename=_png_filename(
            f"replays-j{report.matchday}-p{report.match_number}-{report.team_one_name}-vs-{report.team_two_name}"
        ),
    )


def _render_match_replay_summary_image(
        *,
        report: MatchReplayReport,
        font_path: Path | None,
        team_logo_urls: Mapping[str, str | None],
        fallback_logo_url: str | None,
) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow no esta disponible para renderizar imagenes.") from exc

    totals = build_match_replay_player_stat_totals(report)
    width = 1360
    game_stats_height = _game_stat_cards_total_height(report)
    team_one_totals = _totals_for_team(report, totals, report.team_one_name)
    team_two_totals = _totals_for_team(report, totals, report.team_two_name)
    totals_height = _player_totals_table_height(max(len(team_one_totals), len(team_two_totals), 1))
    height = 902 + game_stats_height + totals_height
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_replay_background(draw, width=width, height=height)
    team_one_logo = _load_logo_image(
        Image,
        _resolve_team_logo_url(team_logo_urls, report.team_one_name),
        fallback_logo_url,
        size=96,
    )
    team_two_logo = _load_logo_image(
        Image,
        _resolve_team_logo_url(team_logo_urls, report.team_two_name),
        fallback_logo_url,
        size=96,
    )
    title_font = _load_font(size=48, font_path=font_path)
    subtitle_font = _load_font(size=SUBTITLE_FONT_SIZE, font_path=font_path)
    section_font = _load_font(size=26, font_path=font_path)
    series_font = _load_font(size=40, font_path=font_path)
    team_name_font = _load_font(size=28, font_path=font_path)
    body_font = _load_font(size=20, font_path=font_path)
    small_font = _load_font(size=SMALL_FONT_SIZE, font_path=font_path)

    y = PADDING_Y
    team_one_won_series = report.team_one_games > report.team_two_games
    team_two_won_series = report.team_two_games > report.team_one_games
    team_one_header_color, team_one_color = _result_colors(won=team_one_won_series)
    team_two_header_color, team_two_color = _result_colors(won=team_two_won_series)
    draw.text(
        (width // 2, y),
        f"{report.division.label}  |  Jornada {report.matchday}  |  Partido {report.match_number}",
        font=subtitle_font,
        fill=MUTED,
        anchor="ma",
    )
    y += 52

    _draw_series_score_panel(
        image,
        draw,
        x=PADDING_X,
        y=y,
        width=width - PADDING_X * 2,
        report=report,
        score_font=series_font,
        team_name_font=team_name_font,
        team_one_color=team_one_color,
        team_two_color=team_two_color,
        team_one_header_color=team_one_header_color,
        team_two_header_color=team_two_header_color,
        team_one_logo=team_one_logo,
        team_two_logo=team_two_logo,
    )
    y += 150

    _draw_section_label(draw, PADDING_X, y, "RESULTADOS POR GAME (BO5)", section_font)
    y += 42
    _draw_game_cards(
        draw,
        x=PADDING_X,
        y=y,
        width=width - PADDING_X * 2,
        report=report,
        title_font=body_font,
        score_font=title_font,
        small_font=small_font,
        team_one_color=team_one_color,
        team_two_color=team_two_color,
    )
    y += 178

    _draw_section_label(draw, PADDING_X, y, "ESTADÍSTICAS POR GAME", section_font)
    y += 42
    _draw_game_stat_cards(
        draw,
        x=PADDING_X,
        y=y,
        width=width - PADDING_X * 2,
        report=report,
        body_font=small_font,
        team_one_color=team_one_color,
        team_two_color=team_two_color,
    )
    y += game_stats_height + 30

    _draw_section_label(draw, PADDING_X, y, "LÍDERES DE LA SERIE", section_font)
    y += 42
    _draw_leader_cards(
        draw,
        x=PADDING_X,
        y=y,
        width=width - PADDING_X * 2,
        totals=totals,
        title_font=small_font,
        value_font=body_font,
    )
    y += 150

    _draw_section_label(draw, PADDING_X, y, "ESTADÍSTICAS TOTALES DE JUGADORES", section_font)
    y += 42
    _draw_team_totals(
        draw,
        x=PADDING_X,
        y=y,
        width=width - PADDING_X * 2,
        report=report,
        team_one_rows=team_one_totals,
        team_two_rows=team_two_totals,
        table_height=totals_height,
        header_font=body_font,
        body_font=small_font,
        team_one_color=team_one_color,
        team_two_color=team_two_color,
        team_one_header_color=team_one_header_color,
        team_two_header_color=team_two_header_color,
    )
    return _save_png(image)


def _draw_replay_background(draw: ImageDrawLike, *, width: int, height: int) -> None:
    for y in range(0, height, 28):
        color = (10, 29, 56) if y % 56 == 0 else (9, 22, 42)
        draw.line(((0, y), (width, y)), fill=color, width=1)
    for x in range(-height, width, 100):
        draw.line(((x, height), (x + height // 2, height // 2)), fill=(8, 42, 82), width=1)


def _draw_series_score_panel(
        image: Any,
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        report: MatchReplayReport,
        score_font: FontLike,
        team_name_font: FontLike,
        team_one_color: Color,
        team_two_color: Color,
        team_one_header_color: Color,
        team_two_header_color: Color,
        team_one_logo: Any | None,
        team_two_logo: Any | None,
) -> None:
    _draw_card(draw, (x, y, x + width, y + 126), fill=(10, 20, 35), outline=(75, 85, 105))
    center_x = x + width // 2
    goals_one, goals_two = _series_goals(report)
    won_games_badge_width = 78
    team_logo_size = 76
    team_two_won_games_x = x + width - 505
    team_two_logo_x = x + width - 106
    team_two_name_left = team_two_won_games_x + won_games_badge_width + 24
    team_two_name_right = team_two_logo_x - 24
    team_two_name_width = team_two_name_right - team_two_name_left
    _draw_badge(
        image,
        draw,
        x=x + 30,
        y=y + 25,
        size=76,
        team_name=report.team_one_name,
        fill=team_one_header_color,
        font=team_name_font,
        logo_image=team_one_logo,
    )
    _draw_wrapped_team_name(
        draw,
        x=x + 128 + 130,
        y=y + 63,
        width=260,
        text=report.team_one_name,
        font=team_name_font,
        fill=TEXT,
        anchor="mm",
    )
    _draw_won_games_badge(
        draw,
        x=x + 410,
        y=y + 36,
        games=report.team_one_games,
        color=team_one_color,
        score_font=score_font,
    )
    draw.text((center_x, y + 64), f"{goals_one} - {goals_two}", font=score_font, fill=TEXT, anchor="mm")
    _draw_won_games_badge(
        draw,
        x=team_two_won_games_x,
        y=y + 36,
        games=report.team_two_games,
        color=team_two_color,
        score_font=score_font,
    )
    _draw_wrapped_team_name(
        draw,
        x=team_two_name_left + team_two_name_width // 2,
        y=y + 63,
        width=team_two_name_width,
        text=report.team_two_name,
        font=team_name_font,
        fill=TEXT,
        anchor="mm",
    )
    _draw_badge(
        image,
        draw,
        x=team_two_logo_x,
        y=y + 25,
        size=team_logo_size,
        team_name=report.team_two_name,
        fill=team_two_header_color,
        font=team_name_font,
        logo_image=team_two_logo,
    )


def _draw_won_games_badge(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        games: int,
        color: Color,
        score_font: FontLike,
) -> None:
    draw.rounded_rectangle(
        (x, y, x + 78, y + 54),
        radius=10,
        fill=(8, 19, 34),
        outline=(45, 57, 79),
        width=1,
    )
    draw.text((x + 39, y + 27), str(games), font=score_font, fill=color, anchor="mm")


def _draw_leader_cards(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        totals: tuple[MatchReplayPlayerStatTotal, ...],
        title_font: FontLike,
        value_font: FontLike,
) -> None:
    leaders = (
        ("MVP", _leader(totals, "score")),
        ("MÁS GOLES", _leader(totals, "goals")),
        ("MÁS ASISTENCIAS", _leader(totals, "assists")),
        ("MÁS SALVADAS", _leader(totals, "saves")),
        ("MÁS TIROS", _leader(totals, "shots")),
    )
    gap = 18
    card_width = (width - gap * (len(leaders) - 1)) // len(leaders)
    for index, (label, leader) in enumerate(leaders):
        card_x = x + index * (card_width + gap)
        _draw_card(draw, (card_x, y, card_x + card_width, y + 118), fill=(9, 22, 42), outline=(75, 85, 105))
        draw.text((card_x + card_width // 2, y + 24), label, font=title_font, fill=LEADER_TITLE_GOLD, anchor="mm")
        if leader is None:
            draw.text((card_x + card_width // 2, y + 70), "-", font=value_font, fill=TEXT, anchor="mm")
            continue
        name, value = leader
        draw.text((card_x + card_width // 2, y + 62), name, font=title_font, fill=TEXT, anchor="mm")
        draw.text((card_x + card_width // 2, y + 92), str(value), font=value_font, fill=GREEN, anchor="mm")


def _draw_team_totals(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        report: MatchReplayReport,
        team_one_rows: tuple[MatchReplayPlayerStatTotal, ...],
        team_two_rows: tuple[MatchReplayPlayerStatTotal, ...],
        table_height: int,
        header_font: FontLike,
        body_font: FontLike,
        team_one_color: Color,
        team_two_color: Color,
        team_one_header_color: Color,
        team_two_header_color: Color,
) -> None:
    gap = 24
    table_width = (width - gap) // 2
    _draw_player_totals_table(
        draw,
        x=x,
        y=y,
        width=table_width,
        team_name=report.team_one_name,
        rows=team_one_rows,
        table_height=table_height,
        header_color=team_one_header_color,
        accent=team_one_color,
        header_font=header_font,
        body_font=body_font,
    )
    _draw_player_totals_table(
        draw,
        x=x + table_width + gap,
        y=y,
        width=table_width,
        team_name=report.team_two_name,
        rows=team_two_rows,
        table_height=table_height,
        header_color=team_two_header_color,
        accent=team_two_color,
        header_font=header_font,
        body_font=body_font,
    )


def _draw_player_totals_table(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        team_name: str,
        rows: tuple[MatchReplayPlayerStatTotal, ...],
        table_height: int,
        header_color: Color,
        accent: Color,
        header_font: FontLike,
        body_font: FontLike,
) -> None:
    table_rows = tuple(
        (
            row.player_name,
            str(row.games_played),
            str(row.score),
            str(row.goals),
            str(row.assists),
            str(row.saves),
            str(row.shots),
        )
        for row in rows
    )
    _draw_card(draw, (x, y, x + width, y + table_height), fill=(9, 20, 35), outline=accent)
    draw.rounded_rectangle((x, y, x + width, y + 48), radius=12, fill=header_color, outline=accent, width=1)
    draw.text((x + width // 2, y + 25), team_name, font=header_font, fill=TEXT, anchor="mm")
    _draw_table(
        draw,
        x=x + 16,
        y=y + 62,
        columns=(260, 44, 86, 44, 44, 58, 58),
        headers=("Jugador", "J", "PTS", "G", "A", "S", "T"),
        rows=table_rows,
        header_font=body_font,
        body_font=body_font,
        alignments=("left", "center", "right", "center", "center", "center", "center"),
        outline=None,
        vertical_lines=False,
    )


def _result_colors(*, won: bool) -> tuple[Color, Color]:
    if won:
        return GREEN_DARK, GREEN
    return BLUE_DARK, ACCENT


def _draw_wrapped_team_name(
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
    lines = _wrap_text_lines(text, font=font, width=width, max_lines=2)
    if not lines:
        return

    line_height = _font_line_height(font)
    first_y = y - ((len(lines) - 1) * line_height // 2)
    line_anchor = "mm" if anchor == "mm" else anchor
    for index, line in enumerate(lines):
        fitted_line = _fit_text(font, line, width)
        draw.text(
            (x, first_y + index * line_height),
            fitted_line,
            font=font,
            fill=fill,
            anchor=line_anchor,
        )


def _wrap_text_lines(
        text: str,
        *,
        font: FontLike,
        width: int,
        max_lines: int,
) -> tuple[str, ...]:
    words = [word for word in text.strip().split() if word]
    if not words:
        return ()

    lines: list[str] = []
    current_line = ""
    for word in words:
        candidate = f"{current_line} {word}".strip()
        if not current_line or _text_width(font, candidate) <= width:
            current_line = candidate
            continue
        lines.append(current_line)
        current_line = word
    if current_line:
        lines.append(current_line)

    if len(lines) <= max_lines:
        return tuple(lines)
    return _balance_wrapped_lines(words, font=font, width=width, max_lines=max_lines)


def _balance_wrapped_lines(
        words: list[str],
        *,
        font: FontLike,
        width: int,
        max_lines: int,
) -> tuple[str, ...]:
    if max_lines != 2 or len(words) < 2:
        return tuple(" ".join(words[index::max_lines]) for index in range(max_lines))

    candidates: list[tuple[int, tuple[str, str]]] = []
    for split_index in range(1, len(words)):
        first_line = " ".join(words[:split_index])
        second_line = " ".join(words[split_index:])
        first_width = _text_width(font, first_line)
        second_width = _text_width(font, second_line)
        if first_width <= width and second_width <= width:
            candidates.append((abs(first_width - second_width), (first_line, second_line)))
    if candidates:
        return min(candidates, key=lambda item: item[0])[1]
    return " ".join(words[: len(words) // 2]), " ".join(words[len(words) // 2:])


def _font_line_height(font: FontLike) -> int:
    _, top, _, bottom = font.getbbox("Ag")
    return int(bottom - top + 6)


def _player_totals_table_height(row_count: int) -> int:
    return 62 + 30 + max(row_count, 1) * 28 + 44


def _series_goals(report: MatchReplayReport) -> tuple[int, int]:
    team_one_goals = 0
    team_two_goals = 0
    for game in report.games:
        score = match_replay_game_score(report, game)
        parsed_score = _parse_score(score)
        if parsed_score is None:
            continue
        team_one_goals += parsed_score[0]
        team_two_goals += parsed_score[1]
    return team_one_goals, team_two_goals


def _leader(
        totals: tuple[MatchReplayPlayerStatTotal, ...],
        field_name: str,
) -> tuple[str, int] | None:
    if not totals:
        return None
    leader = max(totals, key=lambda row: getattr(row, field_name))
    return leader.player_name, int(getattr(leader, field_name))


def _totals_for_team(
        report: MatchReplayReport,
        totals: tuple[MatchReplayPlayerStatTotal, ...],
        team_name: str,
) -> tuple[MatchReplayPlayerStatTotal, ...]:
    expected = _team_identity(team_name)
    return tuple(
        total
        for total in totals
        if _team_identity(total.team_name) == expected
        or _team_identity(total.official_team_name) == expected
        or (
                expected == _team_identity(report.team_one_name)
                and total.team_name == report.team_one_name
        )
        or (
                expected == _team_identity(report.team_two_name)
                and total.team_name == report.team_two_name
        )
    )
