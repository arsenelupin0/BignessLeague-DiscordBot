#  Copyright (c) 2026. Bigness League.
#  Licensed under the GNU General Public License v3.0
#  https://www.gnu.org/licenses/gpl-3.0.html
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import discord

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.team_profile_image_drawing import (
    _accumulate_boundaries,
    _build_row_rects,
    _draw_box,
    _draw_cell_text,
    _draw_horizontal_line,
    _draw_vertical_line,
    _load_team_profile_font_context,
)
from bigness_league_bot.infrastructure.discord.team_profile_layout import (
    ANSI_COLOR_TO_RGB,
    ANSI_GREEN,
    ANSI_MAGENTA,
    ANSI_RED,
    ANSI_WHITE,
    ANSI_YELLOW,
    DISCORD_WIDTH,
    EPIC_WIDTH,
    MMR_LEFT_PADDING,
    MMR_RIGHT_PADDING,
    MMR_WIDTH,
    PLAYER_WIDTH,
    POSITION_WIDTH,
    ROCKET_WIDTH,
    ROLE_WIDTH,
    TEAM_PROFILE_IMAGE_BACKGROUND,
    TEAM_PROFILE_IMAGE_PADDING_X,
    TEAM_PROFILE_IMAGE_PADDING_Y,
    TEAM_PROFILE_IMAGE_SECTION_SPACING,
    TEXT_COLUMN_LEFT_PADDING,
    translate_header,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService


def _render_team_profile_image(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        font_path: Path | None = None,
) -> bytes:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise CommandUserError(
            localize(I18N.errors.team_profile.image_dependencies_missing)
        ) from exc

    font, unit_width, row_height = _load_team_profile_font_context(
        ImageFont,
        font_path=font_path,
    )

    position_width = POSITION_WIDTH * unit_width
    player_width = PLAYER_WIDTH * unit_width
    discord_width = DISCORD_WIDTH * unit_width
    epic_width = EPIC_WIDTH * unit_width
    rocket_width = ROCKET_WIDTH * unit_width
    mmr_width = MMR_WIDTH * unit_width
    role_width = ROLE_WIDTH * unit_width

    main_column_widths = (
        position_width,
        player_width,
        discord_width,
        epic_width,
        rocket_width,
        mmr_width,
    )
    main_table_width = sum(main_column_widths)
    technical_staff_extra_width = main_table_width - (
            role_width + discord_width + epic_width + rocket_width
    )
    technical_staff_discord_extra_width = technical_staff_extra_width // 2
    technical_staff_epic_extra_width = technical_staff_extra_width - technical_staff_discord_extra_width
    technical_staff_column_widths = (
        role_width,
        discord_width + technical_staff_discord_extra_width,
        epic_width + technical_staff_epic_extra_width,
        rocket_width,
    )

    technical_staff_table_width = sum(technical_staff_column_widths)
    title_block_width = position_width + player_width + discord_width

    title_height = row_height * 2
    main_table_height = row_height * (1 + len(team_profile.players) + 1)
    technical_staff_table_height = 0
    if team_profile.technical_staff:
        technical_staff_table_height = row_height * (
                1 + 1 + len(team_profile.technical_staff)
        )

    image_width = TEAM_PROFILE_IMAGE_PADDING_X * 2 + max(
        main_table_width,
        technical_staff_table_width,
    )
    image_height = (
            TEAM_PROFILE_IMAGE_PADDING_Y * 2
            + title_height
            + main_table_height
    )
    if technical_staff_table_height:
        image_height += (
                TEAM_PROFILE_IMAGE_SECTION_SPACING + technical_staff_table_height
        )

    image = Image.new(
        "RGB",
        (image_width, image_height),
        TEAM_PROFILE_IMAGE_BACKGROUND,
    )
    draw = ImageDraw.Draw(image)
    left_padding_px = TEXT_COLUMN_LEFT_PADDING * unit_width
    mmr_left_padding_px = MMR_LEFT_PADDING * unit_width
    mmr_right_padding_px = MMR_RIGHT_PADDING * unit_width

    positiontranslate_header = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.position,
    )
    playertranslate_header = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.player,
    )
    discordtranslate_header = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.discord,
    )
    epictranslate_header = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.epic_name,
    )
    rockettranslate_header = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.rocket_name,
    )
    mmrtranslate_header = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.mmr,
    )
    roletranslate_header = translate_header(
        localizer,
        locale,
        I18N.messages.team_profile.ansi.headers.role,
    )
    remaining_signings_label = localizer.translate(
        I18N.messages.team_profile.ansi.summary.remaining_signings,
        locale=locale,
    )
    team_average_label = localizer.translate(
        I18N.messages.team_profile.ansi.summary.team_average,
        locale=locale,
    )
    technical_staff_title = localizer.translate(
        I18N.messages.team_profile.ansi.technical_staff.title,
        locale=locale,
    )

    x_origin = TEAM_PROFILE_IMAGE_PADDING_X
    y_origin = TEAM_PROFILE_IMAGE_PADDING_Y

    _draw_horizontal_line(
        draw,
        x_origin,
        x_origin + title_block_width,
        y_origin,
    )
    _draw_horizontal_line(
        draw,
        x_origin,
        x_origin + title_block_width,
        y_origin + title_height,
    )
    _draw_vertical_line(
        draw,
        x_origin,
        y_origin,
        y_origin + title_height,
    )
    _draw_vertical_line(
        draw,
        x_origin + title_block_width,
        y_origin,
        y_origin + title_height,
    )
    _draw_cell_text(
        draw,
        font,
        (x_origin, y_origin, x_origin + title_block_width, y_origin + row_height),
        team_profile.team_name.upper(),
        fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
        align="center",
    )
    _draw_cell_text(
        draw,
        font,
        (
            x_origin,
            y_origin + row_height,
            x_origin + title_block_width,
            y_origin + title_height,
        ),
        team_profile.division_name.upper(),
        fill=ANSI_COLOR_TO_RGB[ANSI_MAGENTA],
        align="center",
    )

    main_table_y = y_origin + title_height
    summary_start_y = main_table_y + row_height * (1 + len(team_profile.players))
    _draw_box(draw, x_origin, main_table_y, main_table_width, main_table_height)
    for row_index in range(1, 1 + len(team_profile.players) + 1):
        _draw_horizontal_line(
            draw,
            x_origin,
            x_origin + main_table_width,
            main_table_y + row_height * row_index,
        )

    main_boundaries = _accumulate_boundaries(x_origin, main_column_widths)
    for boundary in main_boundaries[1:-1]:
        _draw_vertical_line(draw, boundary, main_table_y, summary_start_y)

    summary_boundaries = (
        x_origin + position_width,
        x_origin + position_width + player_width + discord_width,
        x_origin + position_width + player_width + discord_width + epic_width + rocket_width,
    )
    for boundary in summary_boundaries:
        _draw_vertical_line(
            draw,
            boundary,
            summary_start_y,
            main_table_y + main_table_height,
        )

    header_rects = _build_row_rects(
        x_origin,
        main_table_y,
        main_column_widths,
        row_height,
    )
    for rect, text in zip(
            header_rects,
            (
                    positiontranslate_header,
                    playertranslate_header,
                    discordtranslate_header,
                    epictranslate_header,
                    rockettranslate_header,
                    mmrtranslate_header,
            ),
    ):
        _draw_cell_text(
            draw,
            font,
            rect,
            text,
            fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
            align="center",
        )

    for row_index, player in enumerate(team_profile.players, start=1):
        row_rects = _build_row_rects(
            x_origin,
            main_table_y + row_height * row_index,
            main_column_widths,
            row_height,
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[0],
            str(player.position),
            fill=ANSI_COLOR_TO_RGB[ANSI_RED],
            align="center",
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[1],
            player.player_name,
            fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
            left_padding=left_padding_px,
            dash_center=True,
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[2],
            player.discord_name,
            fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
            left_padding=left_padding_px,
            dash_center=True,
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[3],
            player.epic_name,
            fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
            left_padding=left_padding_px,
            dash_center=True,
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[4],
            player.rocket_name,
            fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
            left_padding=left_padding_px,
            dash_center=True,
        )
        _draw_cell_text(
            draw,
            font,
            row_rects[5],
            player.mmr,
            fill=ANSI_COLOR_TO_RGB[ANSI_MAGENTA],
            left_padding=mmr_left_padding_px,
            right_padding=mmr_right_padding_px,
        )

    summary_rects = (
        (x_origin, summary_start_y, x_origin + position_width, summary_start_y + row_height),
        (
            x_origin + position_width,
            summary_start_y,
            x_origin + position_width + player_width + discord_width,
            summary_start_y + row_height,
        ),
        (
            x_origin + position_width + player_width + discord_width,
            summary_start_y,
            x_origin + position_width + player_width + discord_width + epic_width + rocket_width,
            summary_start_y + row_height,
        ),
        (
            x_origin + main_table_width - mmr_width,
            summary_start_y,
            x_origin + main_table_width,
            summary_start_y + row_height,
        ),
    )
    _draw_cell_text(
        draw,
        font,
        summary_rects[0],
        team_profile.remaining_signings,
        fill=ANSI_COLOR_TO_RGB[ANSI_YELLOW],
        align="center",
    )
    _draw_cell_text(
        draw,
        font,
        summary_rects[1],
        remaining_signings_label,
        fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
        left_padding=left_padding_px,
    )
    _draw_cell_text(
        draw,
        font,
        summary_rects[2],
        team_average_label,
        fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
        right_padding=left_padding_px,
        align="right",
    )
    _draw_cell_text(
        draw,
        font,
        summary_rects[3],
        team_profile.top_three_average,
        fill=ANSI_COLOR_TO_RGB[ANSI_YELLOW],
        left_padding=mmr_left_padding_px,
        right_padding=mmr_right_padding_px,
    )

    if technical_staff_table_height:
        staff_y = main_table_y + main_table_height + TEAM_PROFILE_IMAGE_SECTION_SPACING
        _draw_box(
            draw,
            x_origin,
            staff_y,
            technical_staff_table_width,
            technical_staff_table_height,
        )
        _draw_horizontal_line(
            draw,
            x_origin,
            x_origin + technical_staff_table_width,
            staff_y + row_height,
        )
        _draw_horizontal_line(
            draw,
            x_origin,
            x_origin + technical_staff_table_width,
            staff_y + row_height * 2,
        )
        staff_boundaries = _accumulate_boundaries(
            x_origin,
            technical_staff_column_widths,
        )
        for boundary in staff_boundaries[1:-1]:
            _draw_vertical_line(
                draw,
                boundary,
                staff_y + row_height,
                staff_y + technical_staff_table_height,
            )
        for row_index in range(3, 2 + len(team_profile.technical_staff)):
            _draw_horizontal_line(
                draw,
                x_origin,
                x_origin + technical_staff_table_width,
                staff_y + row_height * row_index,
            )

        _draw_cell_text(
            draw,
            font,
            (
                x_origin,
                staff_y,
                x_origin + technical_staff_table_width,
                staff_y + row_height,
            ),
            technical_staff_title,
            fill=ANSI_COLOR_TO_RGB[ANSI_YELLOW],
            align="center",
        )
        stafftranslate_header_rects = _build_row_rects(
            x_origin,
            staff_y + row_height,
            technical_staff_column_widths,
            row_height,
        )
        for rect, text in zip(
                stafftranslate_header_rects,
                (roletranslate_header, discordtranslate_header, epictranslate_header, rockettranslate_header),
        ):
            _draw_cell_text(
                draw,
                font,
                rect,
                text,
                fill=ANSI_COLOR_TO_RGB[ANSI_WHITE],
                align="center",
            )

        for row_index, member in enumerate(team_profile.technical_staff, start=2):
            member_rects = _build_row_rects(
                x_origin,
                staff_y + row_height * row_index,
                technical_staff_column_widths,
                row_height,
            )
            _draw_cell_text(
                draw,
                font,
                member_rects[0],
                member.role_name,
                fill=ANSI_COLOR_TO_RGB[ANSI_RED],
                left_padding=left_padding_px,
            )
            _draw_cell_text(
                draw,
                font,
                member_rects[1],
                member.discord_name,
                fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
                left_padding=left_padding_px,
                dash_center=True,
            )
            _draw_cell_text(
                draw,
                font,
                member_rects[2],
                member.epic_name,
                fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
                left_padding=left_padding_px,
                dash_center=True,
            )
            _draw_cell_text(
                draw,
                font,
                member_rects[3],
                member.rocket_name,
                fill=ANSI_COLOR_TO_RGB[ANSI_GREEN],
                left_padding=left_padding_px,
                dash_center=True,
            )

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
