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

from bigness_league_bot.application.services.team_profile import TeamProfilePlayer, TeamProfileStaffMember
from bigness_league_bot.application.services.team_signing import TeamSigningPlayer, TeamTechnicalStaffMember
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.google.team_sheets.blocks import _get_cell, _get_cell_value
from bigness_league_bot.infrastructure.google.team_sheets.cells import (
    _build_hyperlink_cell_value,
    _build_player_cell_value,
    _is_placeholder_row,
    _normalize_lookup_text,
    _normalize_member_lookup_text,
    _normalize_technical_staff_role_name,
    _parse_integer_cell_value,
)
from bigness_league_bot.infrastructure.google.team_sheets.errors import (
    TeamSheetLayoutError,
    TeamSheetTechnicalStaffPlayerDuplicateError,
    TeamSheetTechnicalStaffPlayerNotFoundError,
)
from bigness_league_bot.infrastructure.google.team_sheets.models import SheetCell, TeamBlockAnchor
from bigness_league_bot.infrastructure.google.team_sheets.schema import (
    PLACEHOLDER_CELL_VALUE,
    TEAM_BLOCK_COLUMN_COUNT,
    TEAM_BLOCK_MAX_PLAYERS,
    TEAM_BLOCK_MAX_TECHNICAL_STAFF,
    TEAM_BLOCK_PLAYERS_ROW_OFFSET,
    TEAM_BLOCK_SUMMARY_ROW_OFFSET,
    TEAM_BLOCK_TECHNICAL_STAFF_ROW_OFFSET,
    TECHNICAL_STAFF_HEADER_VARIANTS_NORMALIZED,
    TECHNICAL_STAFF_HEADERS_NORMALIZED,
    TECHNICAL_STAFF_TITLE_NORMALIZED,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

TECHNICAL_STAFF_ROLE_HEADER = "rol"
TECHNICAL_STAFF_PLAYER_HEADERS = {"player", "jugador"}
TECHNICAL_STAFF_DISCORD_HEADER = "discord id"
TECHNICAL_STAFF_EPIC_HEADER = "epic name"


def _resolve_technical_staff_column_offsets(
        cell_grid: dict[int, dict[int, SheetCell]],
        block: TeamBlockAnchor,
        *,
        start_row: int | None = None,
) -> tuple[int, int, int, int]:
    if start_row is None:
        start_row = _find_technical_staff_start_row(cell_grid, block)
    if start_row is None:
        return 0, 1, 2, 3

    header_row = start_row - 1
    header_by_offset = {
        offset: _normalize_lookup_text(
            _get_cell_value(cell_grid, header_row, block.start_column + offset)
        )
        for offset in range(TEAM_BLOCK_COLUMN_COUNT)
    }
    role_offset = _find_header_offset(
        header_by_offset,
        {TECHNICAL_STAFF_ROLE_HEADER},
        fallback=0,
    )
    player_offset = _find_header_offset(
        header_by_offset,
        TECHNICAL_STAFF_PLAYER_HEADERS,
        fallback=1,
    )
    discord_offset = _find_header_offset(
        header_by_offset,
        {TECHNICAL_STAFF_DISCORD_HEADER},
        fallback=2,
    )
    epic_offset = _find_header_offset(
        header_by_offset,
        {TECHNICAL_STAFF_EPIC_HEADER},
        fallback=3,
    )
    return role_offset, player_offset, discord_offset, epic_offset


def _find_header_offset(
        header_by_offset: dict[int, str],
        accepted_headers: set[str],
        *,
        fallback: int,
) -> int:
    for offset, header in header_by_offset.items():
        if header in accepted_headers:
            return offset

    return fallback


def _build_player_values_grid(
        players: tuple[TeamSigningPlayer, ...],
) -> list[list[str]]:
    rows: list[list[str]] = []
    for player in players:
        rows.append(
            [
                _build_player_cell_value(player.player_name),
                player.discord_id,
                player.platform,
                player.platform_id,
                _build_hyperlink_cell_value(player.epic_name, player.tracker_url),
                player.mmr,
            ]
        )

    while len(rows) < TEAM_BLOCK_MAX_PLAYERS:
        rows.append([PLACEHOLDER_CELL_VALUE] * TEAM_BLOCK_COLUMN_COUNT)

    return rows


def _to_team_signing_player(player: TeamProfilePlayer) -> TeamSigningPlayer:
    return TeamSigningPlayer(
        player_name=player.player_name,
        tracker_url=player.tracker_url or "",
        discord_id=player.discord_id,
        platform=player.platform,
        platform_id=player.platform_id,
        epic_name=player.epic_name,
        mmr=player.mmr,
    )


def _parse_players(
        cell_grid: dict[int, dict[int, SheetCell]],
        block: TeamBlockAnchor,
) -> tuple[TeamProfilePlayer, ...]:
    players: list[TeamProfilePlayer] = []
    for offset in range(TEAM_BLOCK_MAX_PLAYERS):
        row_index = block.title_row + TEAM_BLOCK_PLAYERS_ROW_OFFSET + offset
        player_cell = _get_cell(
            cell_grid,
            row_index,
            block.start_column,
        )
        discord_cell = _get_cell(
            cell_grid,
            row_index,
            block.start_column + 1,
        )
        platform_cell = _get_cell(
            cell_grid,
            row_index,
            block.start_column + 2,
        )
        platform_id_cell = _get_cell(
            cell_grid,
            row_index,
            block.start_column + 3,
        )
        epic_cell = _get_cell(
            cell_grid,
            row_index,
            block.start_column + 4,
        )
        mmr_cell = _get_cell(
            cell_grid,
            row_index,
            block.start_column + 5,
        )

        row_values = (
            player_cell.value,
            discord_cell.value,
            platform_cell.value,
            platform_id_cell.value,
            epic_cell.value,
            mmr_cell.value,
        )
        if _is_placeholder_row(*row_values):
            continue

        players.append(
            TeamProfilePlayer(
                position=len(players) + 1,
                player_name=player_cell.value,
                discord_id=discord_cell.value,
                platform=platform_cell.value,
                platform_id=platform_id_cell.value,
                epic_name=epic_cell.value,
                mmr=mmr_cell.value,
                tracker_url=epic_cell.hyperlink,
            )
        )

    return tuple(players)


def parse_players(
        cell_grid: dict[int, dict[int, SheetCell]],
        block: TeamBlockAnchor,
) -> tuple[TeamProfilePlayer, ...]:
    return _parse_players(cell_grid, block)


def _parse_summary(
        cell_grid: dict[int, dict[int, SheetCell]],
        block: TeamBlockAnchor,
        *,
        worksheet_name: str,
) -> tuple[str, str]:
    summary_row = block.title_row + TEAM_BLOCK_SUMMARY_ROW_OFFSET
    remaining_signings = _get_cell_value(
        cell_grid,
        summary_row,
        block.start_column,
    )
    top_three_average = _get_cell_value(
        cell_grid,
        summary_row,
        block.start_column + 5,
    )
    if not remaining_signings and not top_three_average:
        raise TeamSheetLayoutError(
            localize(
                I18N.errors.team_profile.team_sheet_layout_invalid,
                sheet_name=worksheet_name,
                role_name=block.title,
            )
        )

    return remaining_signings, top_three_average


def _parse_remaining_signings_count(
        cell_grid: dict[int, dict[int, SheetCell]],
        block: TeamBlockAnchor,
        *,
        worksheet_name: str,
) -> int:
    summary_row = block.title_row + TEAM_BLOCK_SUMMARY_ROW_OFFSET
    remaining_signings_value = _get_cell_value(
        cell_grid,
        summary_row,
        block.start_column,
    )
    return _parse_integer_cell_value(
        remaining_signings_value,
        error_message=localize(
            I18N.errors.team_signing.remaining_signings_invalid,
            team_name=block.title,
            sheet_name=worksheet_name,
        ),
    )


def _parse_technical_staff(
        cell_grid: dict[int, dict[int, SheetCell]],
        block: TeamBlockAnchor,
) -> tuple[TeamProfileStaffMember, ...]:
    start_row = _find_technical_staff_start_row(
        cell_grid,
        block,
    )
    if start_row is None:
        return ()

    role_offset, player_offset, discord_offset, epic_offset = _resolve_technical_staff_column_offsets(
        cell_grid,
        block,
        start_row=start_row,
    )
    members: list[TeamProfileStaffMember] = []
    for offset in range(TEAM_BLOCK_MAX_TECHNICAL_STAFF):
        row_index = start_row + offset
        role_cell = _get_cell(
            cell_grid,
            row_index,
            block.start_column + role_offset,
        )
        player_cell = _get_cell(
            cell_grid,
            row_index,
            block.start_column + player_offset,
        )
        discord_cell = _get_cell(
            cell_grid,
            row_index,
            block.start_column + discord_offset,
        )
        epic_cell = _get_cell(
            cell_grid,
            row_index,
            block.start_column + epic_offset,
        )

        row_values = (
            role_cell.value,
            player_cell.value,
            discord_cell.value,
            epic_cell.value,
        )
        if _is_placeholder_row(*row_values):
            continue

        members.append(
            TeamProfileStaffMember(
                role_name=role_cell.value,
                player_name=player_cell.value,
                discord_id=discord_cell.value,
                epic_name=epic_cell.value,
            )
        )

    return tuple(members)


def _find_technical_staff_start_row(
        cell_grid: dict[int, dict[int, SheetCell]],
        block: TeamBlockAnchor,
) -> int | None:
    search_start_row = block.title_row + TEAM_BLOCK_TECHNICAL_STAFF_ROW_OFFSET
    search_end_row = search_start_row + TEAM_BLOCK_MAX_TECHNICAL_STAFF + 4
    for row_index in range(search_start_row, search_end_row):
        title_value = _normalize_lookup_text(
            _get_cell_value(
                cell_grid,
                row_index,
                block.start_column,
            )
        )
        if title_value != TECHNICAL_STAFF_TITLE_NORMALIZED:
            continue

        headers_row = row_index + 1
        header_values = tuple(
            _normalize_lookup_text(
                _get_cell_value(
                    cell_grid,
                    headers_row,
                    block.start_column + offset,
                )
            )
            for offset in range(len(TECHNICAL_STAFF_HEADERS_NORMALIZED))
        )
        if header_values in TECHNICAL_STAFF_HEADER_VARIANTS_NORMALIZED:
            return headers_row + 1
        if _is_technical_staff_header_row(cell_grid, block, headers_row):
            return headers_row + 1

        return row_index + 1

    return None


def _is_technical_staff_header_row(
        cell_grid: dict[int, dict[int, SheetCell]],
        block: TeamBlockAnchor,
        row_index: int,
) -> bool:
    header_values = {
        _normalize_lookup_text(
            _get_cell_value(cell_grid, row_index, block.start_column + offset)
        )
        for offset in range(TEAM_BLOCK_COLUMN_COUNT)
    }
    return (
            TECHNICAL_STAFF_ROLE_HEADER in header_values
            and bool(TECHNICAL_STAFF_PLAYER_HEADERS & header_values)
            and TECHNICAL_STAFF_DISCORD_HEADER in header_values
            and TECHNICAL_STAFF_EPIC_HEADER in header_values
    )


def _find_technical_staff_role_names_by_discord(
        cell_grid: dict[int, dict[int, SheetCell]],
        block: TeamBlockAnchor,
        normalized_discord_name: str,
) -> tuple[str, ...]:
    technical_staff = _parse_technical_staff(
        cell_grid,
        block,
    )
    return tuple(
        member.role_name
        for member in technical_staff
        if _normalize_member_lookup_text(member.discord_id) == normalized_discord_name
    )


def _collect_players_by_discord(
        cell_grid: dict[int, dict[int, SheetCell]],
        block: TeamBlockAnchor,
) -> dict[str, tuple[TeamProfilePlayer, ...]]:
    players_by_discord: dict[str, list[TeamProfilePlayer]] = {}
    for player in _parse_players(cell_grid, block):
        normalized_discord_name = _normalize_member_lookup_text(player.discord_id)
        if not normalized_discord_name:
            continue

        players_by_discord.setdefault(normalized_discord_name, []).append(player)

    return {
        discord_name: tuple(players)
        for discord_name, players in players_by_discord.items()
    }


def _resolve_technical_staff_values(
        member: TeamTechnicalStaffMember,
        players_by_discord: dict[str, tuple[TeamProfilePlayer, ...]],
        *,
        team_name: str,
        worksheet_name: str,
) -> tuple[str, str, str]:
    if member.player_name and member.epic_name:
        return member.player_name, member.discord_id, member.epic_name

    normalized_discord_name = _normalize_member_lookup_text(member.discord_id)
    matching_players = players_by_discord.get(normalized_discord_name, ())
    if not matching_players:
        raise TeamSheetTechnicalStaffPlayerNotFoundError(
            localize(
                I18N.errors.team_signing.technical_staff_player_not_found,
                discord_name=member.discord_id,
                role_name=member.role_name,
                team_name=team_name,
                sheet_name=worksheet_name,
            )
        )
    if len(matching_players) > 1:
        raise TeamSheetTechnicalStaffPlayerDuplicateError(
            localize(
                I18N.errors.team_signing.technical_staff_player_duplicate,
                discord_name=member.discord_id,
                role_name=member.role_name,
                team_name=team_name,
                sheet_name=worksheet_name,
            )
        )

    player = matching_players[0]
    return (
        member.player_name or player.player_name,
        member.discord_id,
        member.epic_name or player.epic_name,
    )


def _collect_technical_staff_rows(
        cell_grid: dict[int, dict[int, SheetCell]],
        block: TeamBlockAnchor,
        *,
        worksheet_name: str,
) -> dict[str, int]:
    start_row = _find_technical_staff_start_row(
        cell_grid,
        block,
    )
    if start_row is None:
        raise TeamSheetLayoutError(
            localize(
                I18N.errors.team_signing.team_sheet_layout_invalid,
                sheet_name=worksheet_name,
            )
        )

    technical_staff_rows: dict[str, int] = {}
    for offset in range(TEAM_BLOCK_MAX_TECHNICAL_STAFF):
        row_index = start_row + offset
        role_name = _get_cell_value(
            cell_grid,
            row_index,
            block.start_column,
        )
        normalized_role_name = _normalize_technical_staff_role_name(role_name)
        if not normalized_role_name or normalized_role_name == _normalize_lookup_text(PLACEHOLDER_CELL_VALUE):
            continue

        technical_staff_rows[normalized_role_name] = row_index

    if not technical_staff_rows:
        raise TeamSheetLayoutError(
            localize(
                I18N.errors.team_signing.team_sheet_layout_invalid,
                sheet_name=worksheet_name,
            )
        )

    return technical_staff_rows
