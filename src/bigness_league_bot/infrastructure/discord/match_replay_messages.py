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

from bigness_league_bot.application.services.match_replay_identity import (
    normalize_replay_name, normalize_replay_platform, normalize_replay_platform_id,
)
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
        split_at = -1
        for boundary in ("\n\n### ", "\n\n## ", "\n\n", "\n"):
            candidate = remaining.rfind(boundary, 0, limit)
            if candidate > 0:
                split_at = candidate + (2 if boundary.startswith("\n\n") else 1)
                break
        if split_at <= 0:
            split_at = limit
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
    evaluated_counts = {
        item.method: item.evaluated_count if item.evaluated_count is not None else summary.unique_players
        for item in summary.match_methods}
    labels = {
        "platform": localizer.translate(keys.roster_platform_label, locale=locale),
        "platform_id": localizer.translate(keys.roster_platform_id_label, locale=locale),
    }
    method_lines = []
    for method in ROSTER_VALIDATION_METHODS:
        count = method_counts.get(method, 0)
        evaluated = evaluated_counts.get(method, 0)
        pending = summary.unique_players - evaluated
        # An unidentified account must not turn its platform into a warning.
        # Show this breakdown only when every player has a platform reference.
        if method == "platform" and pending:
            continue
        icon = "❌" if evaluated > count else ("⚠️" if pending or not summary.unique_players else "✅")
        unlinked = min(pending, sum(
            method in player.unevaluated_methods and not _has_registered_record(player)
            for player in summary.unmatched_players
        ))
        suffix = (localizer.translate(keys.roster_unlinked_count, locale=locale, count=unlinked)
                  if unlinked else "")
        if pending > unlinked:
            suffix += localizer.translate(keys.roster_unevaluated_count, locale=locale, count=pending - unlinked)
        method_lines.append(f"  - {labels[method]}: **{count}/{summary.unique_players}** {icon}{suffix}")
    method_breakdown = "\n".join(method_lines)
    unresolved_keys = {_identity(player) for player in summary.unmatched_players}
    verified_name_warnings = tuple(
        player for player in summary.epic_name_unmatched_players
        if player.registered_epic_name and _identity(player) not in unresolved_keys
    )
    name_section = ""
    if verified_name_warnings:
        warnings = "\n\n".join(
            localizer.translate(
                keys.roster_name_warning_player, locale=locale,
                team=_escape_discord_markdown(player.team_name),
                player=_format_inline_code(player.registered_player_name or player.player_name),
                replay_name=_format_inline_code(player.player_name),
                registered_name=_format_inline_code(player.registered_epic_name),
            )
            for player in verified_name_warnings
        )
        name_section = localizer.translate(keys.roster_name_warnings, locale=locale, players=warnings)
    unmatched_text = "\n\n".join(
        _format_unmatched_player_line(player, localizer=localizer, locale=locale, labels=labels)
        for player in summary.unmatched_players
    )
    return localizer.translate(
        keys.roster_validation_with_unmatched if summary.unmatched_players
        else keys.roster_validation_all_matched,
        locale=locale,
        matched_unique=summary.matched_unique_players,
        unique_players=summary.unique_players,
        method_breakdown=method_breakdown,
        status_icon=("❌" if any(player.missing_methods for player in summary.unmatched_players)
                     else ("⚠️" if summary.unmatched_players else "✅")),
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
    if not _has_registered_record(player):
        if player.resolution_status == "ambiguous":
            reason_key = keys.roster_ambiguous_account
            result_key = keys.roster_ambiguous_result
        elif player.platform_id.strip() in {"", "-"}:
            reason_key = keys.roster_replay_id_missing
            result_key = keys.roster_replay_id_missing_result
        else:
            reason_key = keys.roster_record_missing_explanation
            result_key = keys.roster_account_not_found_result
        return localizer.translate(
            keys.roster_unidentified_player, locale=locale,
            team=_escape_discord_markdown(player.team_name),
            player=_format_inline_code(player.player_name),
            platform_id=_format_value(player.platform_id, localizer=localizer, locale=locale),
            reason=localizer.translate(reason_key, locale=locale),
            result=localizer.translate(result_key, locale=locale),
        )

    comparisons = []
    for method in ROSTER_VALIDATION_METHODS:
        pending = method in player.unevaluated_methods
        failed = method in player.missing_methods
        if not pending and not failed:
            continue
        detected = player.platform if method == "platform" else player.platform_id
        registered = player.registered_platform if method == "platform" else player.registered_platform_id
        formatter = _format_platform if method == "platform" else _format_value
        comparisons.append(localizer.translate(
            keys.roster_field_comparison, locale=locale, field=labels[method],
            icon="⚠️" if pending else ("❌" if failed else "✅"),
            status=localizer.translate(keys.roster_status_pending if pending else keys.roster_status_different,
                                       locale=locale),
            detected=formatter(detected, localizer=localizer, locale=locale),
            registered=formatter(registered, localizer=localizer, locale=locale),
        ))
    if (player.registered_epic_name
            and normalize_replay_name(player.player_name) != normalize_replay_name(player.registered_epic_name)):
        comparisons.append(localizer.translate(
            keys.roster_inline_name_notice, locale=locale,
            detected=_format_inline_code(player.player_name),
            registered=_format_inline_code(player.registered_epic_name),
        ))
    if player.resolution_status == "ambiguous":
        result = localizer.translate(keys.roster_ambiguous_account, locale=locale)
    elif player.missing_methods:
        result = localizer.translate(keys.roster_review_fields, locale=locale,
                                     fields=_format_method_list(player.missing_methods, labels))
    else:
        result = localizer.translate(keys.roster_incomplete_comparison, locale=locale)
    return localizer.translate(
        keys.roster_unmatched_player, locale=locale,
        team=_escape_discord_markdown(player.team_name),
        player=_format_inline_code(player.registered_player_name or player.player_name),
        comparisons="\n\n".join(comparisons), result=result,
    )


def _has_registered_record(player: MatchReplayUnmatchedPlayer) -> bool:
    return any((player.registered_player_name, player.registered_platform,
                player.registered_platform_id, player.registered_epic_name))


def _identity(player: MatchReplayUnmatchedPlayer) -> tuple[str, str]:
    if player.platform_id.strip():
        return normalize_replay_platform(player.platform), normalize_replay_platform_id(player.platform_id)
    return "name", normalize_replay_name(player.player_name)


def _format_value(value: str, *, localizer: LocalizationService, locale: str | discord.Locale | None) -> str:
    return _format_inline_code(value) if value.strip() and value.strip() != "-" else localizer.translate(
        I18N.messages.match_replays.uploaded.roster_missing_value, locale=locale,
    )


def _format_platform(value: str, *, localizer: LocalizationService, locale: str | discord.Locale | None) -> str:
    return _format_value(normalize_replay_platform(value), localizer=localizer, locale=locale)


def _format_inline_code(value: str) -> str:
    value = value.replace("\r", " ").replace("\n", " ")
    if "`" not in value:
        return f"`{value}`"
    escaped_value = value.replace("`", "'")
    return f"`{escaped_value}`"


def _escape_discord_markdown(value: str) -> str:
    return discord.utils.escape_markdown(value, as_needed=True)
