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
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService


def format_match_replay_roster_validation(
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        summary: MatchReplayRosterValidationSummary,
        max_unmatched_players: int = 6,
) -> str:
    method_text = ", ".join(
        f"{item.method}: {item.count}" for item in summary.match_methods
    ) or "-"
    if not summary.unmatched_players:
        return localizer.translate(
            I18N.messages.match_replays.uploaded.roster_validation_all_matched,
            locale=locale,
            matched_unique=summary.matched_unique_players,
            unique_players=summary.unique_players,
            matched_appearances=summary.matched_appearances,
            total_appearances=summary.total_appearances,
            match_methods=method_text,
        )

    visible_unmatched = summary.unmatched_players[:max_unmatched_players]
    unmatched_text = ", ".join(
        f"{player.player_name} ({player.team_name})" for player in visible_unmatched
    )
    remaining = len(summary.unmatched_players) - len(visible_unmatched)
    if remaining > 0:
        unmatched_text += localizer.translate(
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
        unmatched_players=unmatched_text,
    )
