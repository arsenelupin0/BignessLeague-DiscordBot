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

import discord

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.infrastructure.discord.team_profile_layout import (
    ANSI_BLUE,
    ANSI_GREEN,
    ANSI_MAGENTA,
    ANSI_RED,
    ANSI_RESET,
    ANSI_WHITE,
    ANSI_YELLOW,
    BOX_BOTTOM_LEFT,
    BOX_BOTTOM_RIGHT,
    BOX_BOTTOM_T,
    BOX_CROSS,
    BOX_HORIZONTAL,
    BOX_LEFT_T,
    BOX_RIGHT_T,
    BOX_TOP_LEFT,
    BOX_TOP_RIGHT,
    BOX_TOP_T,
    BOX_VERTICAL,
    DISCORD_MESSAGE_LIMIT,
    DISCORD_WIDTH,
    EPIC_WIDTH,
    MMR_LEFT_PADDING,
    MMR_RIGHT_PADDING,
    MMR_WIDTH,
    PLAYER_WIDTH,
    POSITION_WIDTH,
    ROCKET_WIDTH,
    ROLE_WIDTH,
    TECHNICAL_STAFF_TABLE_WIDTH,
    TEXT_COLUMN_LEFT_PADDING,
    TITLE_BLOCK_WIDTH,
    build_team_profile_file_name,
    fit_text,
    sanitize_text,
    translate_header,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService


def _ansi_cell(
        text: str,
        width: int,
        *,
        color: str,
        align: str = "left",
) -> str:
    return f"{color}{fit_text(text, width, align=align)}"


def _ansi_padded_cell(
        text: str,
        width: int,
        *,
        color: str,
        left_padding: int = 0,
        right_padding: int = 0,
        align: str = "left",
) -> str:
    content_width = max(0, width - left_padding - right_padding)
    rendered_text = (
            " " * left_padding
            + fit_text(text, content_width, align=align)
            + " " * right_padding
    )
    return f"{color}{rendered_text}"


def _ansi_dash_aware_cell(
        text: str,
        width: int,
        *,
        color: str,
        left_padding: int = 0,
        right_padding: int = 0,
) -> str:
    normalized_text = sanitize_text(text)
    if normalized_text == "-":
        return _ansi_padded_cell(
            normalized_text,
            width,
            color=color,
            left_padding=left_padding,
            right_padding=right_padding,
            align="center",
        )

    return _ansi_padded_cell(
        normalized_text,
        width,
        color=color,
        left_padding=left_padding,
        right_padding=right_padding,
    )


def _ansi_block(lines: list[str]) -> str:
    return "```ansi\n" + "\n".join(lines) + f"{ANSI_RESET}\n```"


def build_team_profile_ansi_sections(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> tuple[str, ...]:
    return _wrap_ansi_blocks(
        list(
            _build_team_profile_ansi_lines(
                team_profile=team_profile,
                localizer=localizer,
                locale=locale,
            )
        )
    )


def build_team_profile_ansi_message(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> str:
    return "\n\n".join(
        build_team_profile_ansi_sections(
            team_profile=team_profile,
            localizer=localizer,
            locale=locale,
        )
    )


def build_team_profile_ansi_file(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> discord.File:
    content = build_team_profile_ansi_message(
        team_profile=team_profile,
        localizer=localizer,
        locale=locale,
    )
    file_name = build_team_profile_file_name(team_profile.team_name)
    return discord.File(
        BytesIO(content.encode("utf-8")),
        filename=file_name,
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


def _build_team_profile_ansi_lines(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> tuple[str, ...]:
    title_lines = _build_title_lines(team_profile)
    roster_lines = _build_roster_lines(
        team_profile,
        localizer=localizer,
        locale=locale,
    )
    technical_staff_lines = _build_technical_staff_lines(
        team_profile,
        localizer=localizer,
        locale=locale,
    )
    lines = title_lines + roster_lines
    if technical_staff_lines:
        lines += [""] + technical_staff_lines

    return tuple(lines)


def _build_title_lines(team_profile: TeamProfile) -> list[str]:
    return [
        f"{ANSI_BLUE}{BOX_TOP_LEFT}{BOX_HORIZONTAL * TITLE_BLOCK_WIDTH}{BOX_TOP_RIGHT}",
        (
            f"{ANSI_BLUE}{BOX_VERTICAL}{ANSI_WHITE}"
            f"{fit_text(team_profile.team_name.upper(), TITLE_BLOCK_WIDTH, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
        ),
        (
            f"{ANSI_BLUE}{BOX_VERTICAL}{ANSI_MAGENTA}"
            f"{fit_text(team_profile.division_name.upper(), TITLE_BLOCK_WIDTH, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
        ),
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
    header_player = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.player,
    )
    header_discord = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.discord,
    )
    header_epic = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.epic_name,
    )
    header_rocket = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.rocket_name,
    )
    header_mmr = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.mmr,
    )

    lines = [
        (
            f"{ANSI_BLUE}{BOX_LEFT_T}{BOX_HORIZONTAL * POSITION_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * PLAYER_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * MMR_WIDTH}{BOX_TOP_RIGHT}"
        ),
        (
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(translate_header(localizer, locale, I18N.messages.team_profile.ansi.headers.position), POSITION_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_player, PLAYER_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_discord, DISCORD_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_epic, EPIC_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_rocket, ROCKET_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_mmr, MMR_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
        ),
        (
            f"{ANSI_BLUE}{BOX_LEFT_T}{BOX_HORIZONTAL * POSITION_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * PLAYER_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * MMR_WIDTH}{BOX_RIGHT_T}"
        ),
    ]

    for player in team_profile.players:
        lines.append(
            (
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_cell(str(player.position), POSITION_WIDTH, color=ANSI_RED, align='center')}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(player.player_name, PLAYER_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(player.discord_name, DISCORD_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(player.epic_name, EPIC_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(player.rocket_name, ROCKET_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(player.mmr, MMR_WIDTH, color=ANSI_MAGENTA, left_padding=MMR_LEFT_PADDING, right_padding=MMR_RIGHT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
            )
        )

    left_span_width = PLAYER_WIDTH + DISCORD_WIDTH + 1
    right_span_width = EPIC_WIDTH + ROCKET_WIDTH + 1
    lines.extend(
        [
            (
                f"{ANSI_BLUE}{BOX_LEFT_T}{BOX_HORIZONTAL * POSITION_WIDTH}{BOX_CROSS}"
                f"{BOX_HORIZONTAL * PLAYER_WIDTH}{BOX_BOTTOM_T}"
                f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_CROSS}"
                f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_BOTTOM_T}"
                f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_CROSS}"
                f"{BOX_HORIZONTAL * MMR_WIDTH}{BOX_RIGHT_T}"
            ),
            (
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_cell(team_profile.remaining_signings, POSITION_WIDTH, color=ANSI_YELLOW, align='center')}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(remaining_signings_label, left_span_width, color=ANSI_WHITE, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(team_average_label, right_span_width, color=ANSI_WHITE, right_padding=1, align='right')}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(team_profile.top_three_average, MMR_WIDTH, color=ANSI_YELLOW, left_padding=MMR_LEFT_PADDING, right_padding=MMR_RIGHT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
            ),
            (
                f"{ANSI_BLUE}{BOX_BOTTOM_LEFT}{BOX_HORIZONTAL * POSITION_WIDTH}{BOX_BOTTOM_T}"
                f"{BOX_HORIZONTAL * left_span_width}{BOX_BOTTOM_T}"
                f"{BOX_HORIZONTAL * right_span_width}{BOX_BOTTOM_T}"
                f"{BOX_HORIZONTAL * MMR_WIDTH}{BOX_BOTTOM_RIGHT}"
            ),
        ]
    )
    return lines


def _build_technical_staff_lines(
        team_profile: TeamProfile,
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> list[str]:
    if not team_profile.technical_staff:
        return []

    title = localizer.translate(
        I18N.messages.team_profile.ansi.technical_staff.title,
        locale=locale,
    )
    header_role = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.role,
    )
    header_discord = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.discord,
    )
    header_epic = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.epic_name,
    )
    header_rocket = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.rocket_name,
    )

    lines = [
        f"{ANSI_BLUE}{BOX_TOP_LEFT}{BOX_HORIZONTAL * TECHNICAL_STAFF_TABLE_WIDTH}{BOX_TOP_RIGHT}",
        (
            f"{ANSI_BLUE}{BOX_VERTICAL}{ANSI_YELLOW}"
            f"{fit_text(title, TECHNICAL_STAFF_TABLE_WIDTH, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
        ),
        (
            f"{ANSI_BLUE}{BOX_LEFT_T}{BOX_HORIZONTAL * ROLE_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_TOP_T}"
            f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_RIGHT_T}"
        ),
        (
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_role, ROLE_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_discord, DISCORD_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_epic, EPIC_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
            f"{_ansi_cell(header_rocket, ROCKET_WIDTH, color=ANSI_WHITE, align='center')}"
            f"{ANSI_BLUE}{BOX_VERTICAL}"
        ),
        (
            f"{ANSI_BLUE}{BOX_LEFT_T}{BOX_HORIZONTAL * ROLE_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_CROSS}"
            f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_RIGHT_T}"
        ),
    ]

    for member in team_profile.technical_staff:
        lines.append(
            (
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_padded_cell(member.role_name, ROLE_WIDTH, color=ANSI_RED, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(member.discord_name, DISCORD_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(member.epic_name, EPIC_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
                f"{_ansi_dash_aware_cell(member.rocket_name, ROCKET_WIDTH, color=ANSI_GREEN, left_padding=TEXT_COLUMN_LEFT_PADDING)}"
                f"{ANSI_BLUE}{BOX_VERTICAL}"
            )
        )

    lines.append(
        f"{ANSI_BLUE}{BOX_BOTTOM_LEFT}{BOX_HORIZONTAL * ROLE_WIDTH}{BOX_BOTTOM_T}"
        f"{BOX_HORIZONTAL * DISCORD_WIDTH}{BOX_BOTTOM_T}"
        f"{BOX_HORIZONTAL * EPIC_WIDTH}{BOX_BOTTOM_T}"
        f"{BOX_HORIZONTAL * ROCKET_WIDTH}{BOX_BOTTOM_RIGHT}"
    )
    return lines
