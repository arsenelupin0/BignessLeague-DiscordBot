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

import discord

from bigness_league_bot.application.services.match_replay_summaries import (
    MatchReplayRosterValidationSummary,
    MatchReplayUnmatchedPlayer,
)
from bigness_league_bot.application.services.match_replays import (
    MatchReplayReport,
    match_replay_game_score,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

ROSTER_VALIDATION_METHODS = ("epic_name", "rocket_name")


def format_match_replay_game_score_lines(
        report: MatchReplayReport,
        *,
        winner_label: str,
) -> str:
    return "\n".join(
        (
            f"  - Game {game.number}: **{match_replay_game_score(report, game)}**"
            f" | _{winner_label} -> {_escape_discord_markdown(game.winner_name)}_"
        )
        for game in report.games
    )


def format_match_replay_roster_validation(
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        summary: MatchReplayRosterValidationSummary,
        max_unmatched_players: int = 6,
) -> str:
    method_counts = {item.method: item.count for item in summary.match_methods}
    method_text = _format_method_list(ROSTER_VALIDATION_METHODS)
    method_breakdown = "\n".join(
        _format_method_count_line(
            method=method,
            count=method_counts.get(method, 0),
            total=summary.unique_players,
        )
        for method in ROSTER_VALIDATION_METHODS
    )
    status_icon = "✅" if not summary.unmatched_players else "❌"
    if not summary.unmatched_players:
        return localizer.translate(
            I18N.messages.match_replays.uploaded.roster_validation_all_matched,
            locale=locale,
            matched_unique=summary.matched_unique_players,
            unique_players=summary.unique_players,
            matched_appearances=summary.matched_appearances,
            total_appearances=summary.total_appearances,
            match_methods=method_text,
            method_breakdown=method_breakdown,
            status_icon=status_icon,
        )

    visible_unmatched = summary.unmatched_players[:max_unmatched_players]
    unmatched_text = "\n".join(
        _format_unmatched_player_line(player) for player in visible_unmatched
    )
    remaining = len(summary.unmatched_players) - len(visible_unmatched)
    if remaining > 0:
        unmatched_text += "\n" + localizer.translate(
            I18N.messages.match_replays.uploaded.roster_validation_more_unmatched,
            locale=locale,
            remaining=remaining,
        )
    return localizer.translate(
        I18N.messages.match_replays.uploaded.roster_validation_with_unmatched,
        locale=locale,
        matched_unique=summary.matched_unique_players,
        unique_players=summary.unique_players,
        matched_appearances=summary.matched_appearances,
        total_appearances=summary.total_appearances,
        match_methods=method_text,
        method_breakdown=method_breakdown,
        status_icon=status_icon,
        unmatched_players=unmatched_text,
    )


def _format_method_list(methods: tuple[str, ...]) -> str:
    formatted_methods = tuple(f"**{method}**" for method in methods)
    if len(formatted_methods) == 1:
        return formatted_methods[0]
    return f"{', '.join(formatted_methods[:-1])} y {formatted_methods[-1]}"


def _format_method_count_line(
        *,
        method: str,
        count: int,
        total: int,
) -> str:
    icon = "✅" if 0 < total == count else "❌"
    return f"  - {_format_method_label(method)}: **{count}/{total}** {icon}"


def _format_method_label(method: str) -> str:
    return "_".join(part.title() for part in method.split("_"))


def _format_unmatched_player_line(player: MatchReplayUnmatchedPlayer) -> str:
    team_name = _escape_discord_markdown(player.team_name)
    player_name = _format_inline_code(player.player_name)
    missing_methods = player.missing_methods
    if missing_methods:
        method_text = _format_method_list(tuple(missing_methods))
        return f"  - {team_name} -> {player_name} ({method_text})"
    return f"  - {team_name} -> {player_name}"


def _format_inline_code(value: str) -> str:
    if "`" not in value:
        return f"`{value}`"
    escaped_value = value.replace("`", "'")
    return f"`{escaped_value}`"


def _escape_discord_markdown(value: str) -> str:
    return discord.utils.escape_markdown(value, as_needed=True)
