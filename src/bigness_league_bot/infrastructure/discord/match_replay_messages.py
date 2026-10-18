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

ROSTER_VALIDATION_METHODS = ("platform", "platform_id")


def split_match_replay_message(content: str, *, limit: int = 2000) -> tuple[str, ...]:
    """Keep the complete report, preferring line boundaries between messages."""
    chunks: list[str] = []
    remaining = content
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        else:
            split_at += 1
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining or not chunks:
        chunks.append(remaining)
    return tuple(chunks)


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
) -> str:
    keys = I18N.messages.match_replays.uploaded
    method_counts = {item.method: item.count for item in summary.match_methods}
    labels = {
        "platform": localizer.translate(keys.roster_platform_label, locale=locale),
        "platform_id": localizer.translate(keys.roster_platform_id_label, locale=locale),
    }
    method_text = _format_method_list(ROSTER_VALIDATION_METHODS, labels)
    method_breakdown = "\n".join(
        f"  - {labels[method]}: **{method_counts.get(method, 0)}/{summary.unique_players}** "
        + ("✅" if 0 < summary.unique_players == method_counts.get(method, 0) else "❌")
        for method in ROSTER_VALIDATION_METHODS
    )
    name_section = ""
    if summary.epic_name_unmatched_players:
        warnings = "\n".join(
            localizer.translate(
                keys.roster_name_warning_player,
                locale=locale,
                team=_escape_discord_markdown(player.team_name),
                replay_name=_format_inline_code(player.player_name),
                registered_name=_format_inline_code(player.registered_epic_name) if player.registered_epic_name
                else localizer.translate(
                    keys.roster_missing_value if player.registered_platform or player.registered_platform_id
                    else keys.roster_no_unique_record, locale=locale,
                ),
            )
            for player in summary.epic_name_unmatched_players
        )
        name_section = localizer.translate(
            keys.roster_name_warnings,
            locale=locale,
            matched=summary.unique_players - len(summary.epic_name_unmatched_players),
            total=summary.unique_players,
            players=warnings,
        )
    unmatched_text = "\n".join(
        _format_unmatched_player_line(player, localizer=localizer, locale=locale, labels=labels)
        for player in summary.unmatched_players
    )
    return localizer.translate(
        keys.roster_validation_with_unmatched if summary.unmatched_players
        else keys.roster_validation_all_matched,
        locale=locale,
        matched_unique=summary.matched_unique_players,
        unique_players=summary.unique_players,
        match_methods=method_text,
        method_breakdown=method_breakdown,
        status_icon="❌" if summary.unmatched_players else "✅",
        unmatched_players=unmatched_text,
        name_warnings_section=name_section,
    )


def _format_method_list(methods: tuple[str, ...], labels: dict[str, str]) -> str:
    return "**" + " + ".join(labels[method] for method in methods) + "**"


def _format_unmatched_player_line(
        player: MatchReplayUnmatchedPlayer,
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        labels: dict[str, str],
) -> str:
    keys = I18N.messages.match_replays.uploaded
    details = []
    for method in player.missing_methods:
        detected = player.platform if method == "platform" else player.platform_id
        registered = player.registered_platform if method == "platform" else player.registered_platform_id
        details.append(localizer.translate(
            keys.roster_field_mismatch,
            locale=locale,
            field=labels[method],
            detected=_format_inline_code(detected) if detected
            else localizer.translate(keys.roster_missing_value, locale=locale),
            registered=_format_inline_code(registered) if registered
            else localizer.translate(
                keys.roster_missing_value if any((player.registered_platform, player.registered_platform_id,
                                                  player.registered_epic_name))
                else keys.roster_no_unique_record, locale=locale,
            ),
        ))
    if player.resolution_status == "ambiguous":
        details.append(localizer.translate(keys.roster_ambiguous_account, locale=locale))
    return localizer.translate(
        keys.roster_unmatched_player,
        locale=locale,
        team=_escape_discord_markdown(player.team_name),
        player=_format_inline_code(player.player_name),
        methods=_format_method_list(player.missing_methods, labels),
        details="; ".join(details),
    )


def _format_inline_code(value: str) -> str:
    if "`" not in value:
        return f"`{value}`"
    escaped_value = value.replace("`", "'")
    return f"`{escaped_value}`"


def _escape_discord_markdown(value: str) -> str:
    return discord.utils.escape_markdown(value, as_needed=True)
