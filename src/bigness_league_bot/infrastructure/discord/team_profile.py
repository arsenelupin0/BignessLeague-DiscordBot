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

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.core.localization import TranslationKeyLike
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

ANSI_BLUE = "\u001b[1;34m"
ANSI_WHITE = "\u001b[1;37m"
ANSI_RED = "\u001b[1;31m"
ANSI_GREEN = "\u001b[1;32m"
ANSI_YELLOW = "\u001b[1;33m"
ANSI_MAGENTA = "\u001b[1;35m"
ANSI_RESET = "\u001b[0m"

TITLE_WIDTH = 43
POSITION_WIDTH = 5
PLAYER_WIDTH = 16
DISCORD_WIDTH = 22
EPIC_WIDTH = 17
ROCKET_WIDTH = 26
MMR_WIDTH = 7
TRACKER_WIDTH = 80
DISCORD_MESSAGE_LIMIT = 2_000


def _sanitize_text(value: str) -> str:
    return " ".join(value.split())


def _fit_text(value: str, width: int, *, align: str = "left") -> str:
    normalized_value = _sanitize_text(value)
    if len(normalized_value) > width:
        normalized_value = normalized_value[: max(0, width - 1)] + "…"

    if align == "center":
        return normalized_value.center(width)
    if align == "right":
        return normalized_value.rjust(width)
    return normalized_value.ljust(width)


def _ansi_cell(
        text: str,
        width: int,
        *,
        color: str,
        align: str = "left",
) -> str:
    return f"{color}{_fit_text(text, width, align=align)}"


def _ansi_block(lines: list[str]) -> str:
    return "```ansi\n" + "\n".join(lines) + f"{ANSI_RESET}\n```"


def build_team_profile_ansi_sections(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> tuple[str, ...]:
    title_lines = _build_title_lines(team_profile)
    roster_lines = _build_roster_lines(team_profile, localizer=localizer, locale=locale)
    tracker_lines = _build_tracker_lines(team_profile, localizer=localizer, locale=locale)
    return (
            _wrap_ansi_blocks(title_lines)
            + _wrap_ansi_blocks(roster_lines)
            + _wrap_ansi_blocks(tracker_lines)
    )


def _wrap_ansi_blocks(lines: list[str]) -> tuple[str, ...]:
    if not lines:
        return ()

    chunks: list[str] = []
    current_chunk: list[str] = []
    for line in lines:
        candidate_chunk = _ansi_block(current_chunk + [line])
        if current_chunk and len(candidate_chunk) > DISCORD_MESSAGE_LIMIT:
            chunks.append(_ansi_block(current_chunk))
            current_chunk = [line]
            continue

        current_chunk.append(line)

    if current_chunk:
        chunks.append(_ansi_block(current_chunk))

    return tuple(chunks)


def _build_title_lines(team_profile: TeamProfile) -> list[str]:
    title = (
        f"{team_profile.team_name.upper()} · {team_profile.division_name.upper()}"
    )
    return [
        f"{ANSI_BLUE}╔{'═' * TITLE_WIDTH}╗",
        f"{ANSI_BLUE}║{ANSI_WHITE}{_fit_text(title, TITLE_WIDTH, align='center')}{ANSI_BLUE}║",
        f"{ANSI_BLUE}║{ANSI_WHITE}{' ' * TITLE_WIDTH}{ANSI_BLUE}║",
    ]


def _build_roster_lines(
        team_profile: TeamProfile,
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> list[str]:
    remaining_signings_label = localizer.translate(
        I18N.messages.team_profile.ansi.summary.remaining_signings,
        locale=locale,
    )
    team_average_label = localizer.translate(
        I18N.messages.team_profile.ansi.summary.team_average,
        locale=locale,
    )

    lines = [
        (
            f"{ANSI_BLUE}╠{'═' * POSITION_WIDTH}╦{'═' * PLAYER_WIDTH}╦{'═' * DISCORD_WIDTH}"
            f"╬{'═' * EPIC_WIDTH}╦{'═' * ROCKET_WIDTH}╦{'═' * MMR_WIDTH}╗"
        ),
        (
            f"{ANSI_BLUE}║{_ansi_cell(_header(localizer, locale, I18N.messages.team_profile.ansi.headers.position), POSITION_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}║{_ansi_cell(_header(localizer, locale, I18N.messages.team_profile.ansi.headers.player), PLAYER_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}║{_ansi_cell(_header(localizer, locale, I18N.messages.team_profile.ansi.headers.discord), DISCORD_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}║{_ansi_cell(_header(localizer, locale, I18N.messages.team_profile.ansi.headers.epic_name), EPIC_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}║{_ansi_cell(_header(localizer, locale, I18N.messages.team_profile.ansi.headers.rocket_name), ROCKET_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}║{_ansi_cell(_header(localizer, locale, I18N.messages.team_profile.ansi.headers.mmr), MMR_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}║"
        ),
        (
            f"{ANSI_BLUE}╠{'═' * POSITION_WIDTH}╬{'═' * PLAYER_WIDTH}╬{'═' * DISCORD_WIDTH}"
            f"╬{'═' * EPIC_WIDTH}╬{'═' * ROCKET_WIDTH}╬{'═' * MMR_WIDTH}╣"
        ),
    ]

    for player in team_profile.players:
        lines.append(
            (
                f"{ANSI_BLUE}║{_ansi_cell(str(player.position), POSITION_WIDTH, color=ANSI_RED, align='center')}"
                f"{ANSI_BLUE}║{_ansi_cell(player.player_name, PLAYER_WIDTH, color=ANSI_GREEN)}"
                f"{ANSI_BLUE}║{_ansi_cell(player.discord_name, DISCORD_WIDTH, color=ANSI_GREEN)}"
                f"{ANSI_BLUE}║{_ansi_cell(player.epic_name, EPIC_WIDTH, color=ANSI_GREEN)}"
                f"{ANSI_BLUE}║{_ansi_cell(player.rocket_name, ROCKET_WIDTH, color=ANSI_GREEN)}"
                f"{ANSI_BLUE}║{_ansi_cell(player.mmr, MMR_WIDTH, color=ANSI_MAGENTA, align='center')}"
                f"{ANSI_BLUE}║"
            )
        )

    left_span_width = PLAYER_WIDTH + DISCORD_WIDTH + 1
    right_span_width = EPIC_WIDTH + ROCKET_WIDTH + 1
    lines.extend(
        [
            (
                f"{ANSI_BLUE}╠{'═' * POSITION_WIDTH}╬{'═' * PLAYER_WIDTH}╩{'═' * DISCORD_WIDTH}"
                f"╬{'═' * EPIC_WIDTH}╩{'═' * ROCKET_WIDTH}╬{'═' * MMR_WIDTH}╣"
            ),
            (
                f"{ANSI_BLUE}║{_ansi_cell(team_profile.remaining_signings, POSITION_WIDTH, color=ANSI_YELLOW, align='center')}"
                f"{ANSI_BLUE}║{_ansi_cell(remaining_signings_label, left_span_width, color=ANSI_WHITE, align='center')}"
                f"{ANSI_BLUE}║{_ansi_cell(team_average_label, right_span_width, color=ANSI_WHITE, align='center')}"
                f"{ANSI_BLUE}║{_ansi_cell(team_profile.top_three_average, MMR_WIDTH, color=ANSI_YELLOW, align='center')}"
                f"{ANSI_BLUE}║"
            ),
            (
                f"{ANSI_BLUE}╚{'═' * POSITION_WIDTH}╩{'═' * (left_span_width)}"
                f"╩{'═' * (right_span_width)}╩{'═' * MMR_WIDTH}╝"
            ),
        ]
    )
    return lines


def _build_tracker_lines(
        team_profile: TeamProfile,
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> list[str]:
    tracker_title = localizer.translate(
        I18N.messages.team_profile.ansi.tracker.title,
        locale=locale,
    )
    missing_tracker = localizer.translate(
        I18N.messages.team_profile.ansi.tracker.missing_value,
        locale=locale,
    )

    lines = [
        f"{ANSI_BLUE}╔{'═' * POSITION_WIDTH}╦{'═' * TRACKER_WIDTH}╗",
        (
            f"{ANSI_BLUE}║{_ansi_cell(_header(localizer, locale, I18N.messages.team_profile.ansi.headers.position), POSITION_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}║{_ansi_cell(tracker_title, TRACKER_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}║"
        ),
        f"{ANSI_BLUE}╠{'═' * POSITION_WIDTH}╬{'═' * TRACKER_WIDTH}╣",
    ]

    for player in team_profile.players:
        tracker_value = player.tracker_url or missing_tracker
        lines.append(
            (
                f"{ANSI_BLUE}║{_ansi_cell(str(player.position), POSITION_WIDTH, color=ANSI_RED, align='center')}"
                f"{ANSI_BLUE}║{_ansi_cell(tracker_value, TRACKER_WIDTH, color=ANSI_GREEN)}"
                f"{ANSI_BLUE}║"
            )
        )

    lines.append(f"{ANSI_BLUE}╚{'═' * POSITION_WIDTH}╩{'═' * TRACKER_WIDTH}╝")
    return lines


def _header(
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        key: TranslationKeyLike,
) -> str:
    return localizer.translate(key, locale=locale).upper()
