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

from bigness_league_bot.application.services.match_replays import (
    MatchReplayGame,
    MatchReplayReport,
    MatchReplayTeam,
    match_replay_game_score,
)
from bigness_league_bot.infrastructure.discord.match_summary_image_shared import (
    BLUE_DARK,
    GREEN_DARK,
    MUTED,
    TEXT,
    Color,
    FontLike,
    ImageDrawLike,
    TableRow,
    _draw_card,
    _draw_table,
    _parse_score,
    _team_names_match_for_render,
)


def _draw_game_cards(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        report: MatchReplayReport,
        title_font: FontLike,
        score_font: FontLike,
        small_font: FontLike,
        team_one_color: Color,
        team_two_color: Color,
) -> None:
    gap = 18
    card_width = (width - gap * 4) // 5
    for index in range(5):
        card_x = x + index * (card_width + gap)
        _draw_card(draw, (card_x, y, card_x + card_width, y + 128), fill=(9, 22, 42), outline=(80, 91, 113))
        draw.text((card_x + card_width // 2, y + 22), f"GAME {index + 1}", font=title_font, fill=TEXT, anchor="mm")
        if index >= len(report.games):
            draw.text((card_x + card_width // 2, y + 72), "-", font=score_font, fill=MUTED, anchor="mm")
            continue

        game: MatchReplayGame = report.games[index]
        score = match_replay_game_score(report, game)
        winner = _game_winner_for_report(report, game)
        score_color = team_one_color if winner == report.team_one_name else team_two_color
        draw.text((card_x + card_width // 2, y + 66), score, font=score_font, fill=score_color, anchor="mm")
        winner_fill = BLUE_DARK if winner == report.team_one_name else GREEN_DARK
        draw.rounded_rectangle(
            (card_x + 8, y + 96, card_x + card_width - 8, y + 122),
            radius=7,
            fill=winner_fill,
            outline=(65, 80, 105),
        )
        draw.text((card_x + card_width // 2, y + 109), f"Gana: {winner}", font=small_font, fill=TEXT, anchor="mm")


def _draw_game_stat_cards(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        report: MatchReplayReport,
        body_font: FontLike,
        team_one_color: Color,
        team_two_color: Color,
) -> None:
    card_y = y
    for index, game in enumerate(report.games):
        card_height = _game_stat_card_height(game)
        _draw_game_stat_card(
            draw,
            x=x,
            y=card_y,
            width=width,
            height=card_height,
            report=report,
            game=game,
            body_font=body_font,
            team_one_color=team_one_color,
            team_two_color=team_two_color,
        )
        card_y += card_height + 18


def _draw_game_stat_card(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        height: int,
        report: MatchReplayReport,
        game: MatchReplayGame,
        body_font: FontLike,
        team_one_color: Color,
        team_two_color: Color,
) -> None:
    _draw_card(draw, (x, y, x + width, y + height), fill=(8, 20, 35), outline=(75, 85, 105))
    score = match_replay_game_score(report, game)
    parsed_score = _parse_score(score)
    team_one_goals = parsed_score[0] if parsed_score is not None else game.blue.goals
    team_two_goals = parsed_score[1] if parsed_score is not None else game.orange.goals

    gap = 24
    table_width = (width - 40 - gap) // 2
    team_one = _game_team_for_report_name(game, report.team_one_name)
    team_two = _game_team_for_report_name(game, report.team_two_name)
    _draw_game_player_table(
        draw,
        x=x + 20,
        y=y + 28,
        width=table_width,
        team_name=report.team_one_name,
        team=team_one,
        goals=team_one_goals,
        header_color=BLUE_DARK,
        accent=team_one_color,
        header_font=body_font,
        body_font=body_font,
        mirrored=False,
    )
    _draw_game_player_table(
        draw,
        x=x + 20 + table_width + gap,
        y=y + 28,
        width=table_width,
        team_name=report.team_two_name,
        team=team_two,
        goals=team_two_goals,
        header_color=GREEN_DARK,
        accent=team_two_color,
        header_font=body_font,
        body_font=body_font,
        mirrored=True,
    )


def _draw_game_player_table(
        draw: ImageDrawLike,
        *,
        x: int,
        y: int,
        width: int,
        team_name: str,
        team: MatchReplayTeam | None,
        goals: int,
        header_color: Color,
        accent: Color,
        header_font: FontLike,
        body_font: FontLike,
        mirrored: bool,
) -> None:
    draw.rounded_rectangle((x, y, x + width, y + 38), radius=8, fill=header_color, outline=accent, width=1)
    if mirrored:
        draw.text((x + 16, y + 20), str(goals), font=header_font, fill=accent, anchor="lm")
        draw.text((x + width - 12, y + 20), team_name, font=header_font, fill=TEXT, anchor="rm")
    else:
        draw.text((x + 12, y + 20), team_name, font=header_font, fill=TEXT, anchor="lm")
        draw.text((x + width - 16, y + 20), str(goals), font=header_font, fill=accent, anchor="rm")

    rows = _game_player_rows(team)
    columns = (max(190, width - 294), 118, 44, 44, 44, 44)
    headers = ("Jugador", "PTS", "G", "A", "S", "T")
    alignments = ("left", "right", "center", "center", "center", "center")
    if mirrored:
        rows = tuple(tuple(reversed(row)) for row in rows)
        columns = tuple(reversed(columns))
        headers = tuple(reversed(headers))
        alignments = ("center", "center", "center", "center", "left", "right")

    _draw_table(
        draw,
        x=x,
        y=y + 44,
        columns=columns,
        headers=headers,
        rows=rows,
        header_font=body_font,
        body_font=body_font,
        alignments=alignments,
        header_height=30,
        row_height=28,
        outline=None,
        vertical_lines=False,
    )


def _game_stat_cards_total_height(report: MatchReplayReport) -> int:
    if not report.games:
        return _game_stat_card_height(None)
    return sum(_game_stat_card_height(game) for game in report.games) + (len(report.games) - 1) * 18


def _game_stat_card_height(game: MatchReplayGame | None) -> int:
    if game is None:
        row_count = 3
    else:
        row_count = max(len(game.blue.players), len(game.orange.players), 1)
    return 28 + 44 + 30 + row_count * 28 + 20


def _game_winner_for_report(report: MatchReplayReport, game: MatchReplayGame) -> str:
    score = match_replay_game_score(report, game)
    parsed_score = _parse_score(score)
    if parsed_score is None:
        return getattr(game, "winner_name", "Sin resolver")
    if parsed_score[0] > parsed_score[1]:
        return report.team_one_name
    if parsed_score[1] > parsed_score[0]:
        return report.team_two_name
    return "Empate"


def _game_team_for_report_name(game: MatchReplayGame, team_name: str) -> MatchReplayTeam | None:
    if _team_names_match_for_render(game.blue.name, team_name):
        return game.blue
    if _team_names_match_for_render(game.orange.name, team_name):
        return game.orange
    return None


def _game_player_rows(team: MatchReplayTeam | None) -> tuple[TableRow, ...]:
    if team is None:
        return ()
    return tuple(
        (
            player.roster_player_name or player.name,
            str(player.score or 0),
            str(player.goals or 0),
            str(player.assists or 0),
            str(player.saves or 0),
            str(player.shots or 0),
        )
        for player in sorted(
            team.players,
            key=lambda candidate: (
                -(candidate.score or 0),
                -(candidate.goals or 0),
                (candidate.roster_player_name or candidate.name).casefold(),
            ),
        )[:4]
    )
