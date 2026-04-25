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

from bigness_league_bot.application.services.team_profile import TeamProfileStaffMember
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.google.team_sheets.blocks import _collect_team_blocks, _get_cell
from bigness_league_bot.infrastructure.google.team_sheets.cells import (
    _is_free_block_title,
    _is_placeholder_row,
    _normalize_lookup_text,
    _normalize_member_lookup_text,
    _normalize_technical_staff_role_name,
)
from bigness_league_bot.infrastructure.google.team_sheets.errors import TeamSheetPlayerNotFoundError
from bigness_league_bot.infrastructure.google.team_sheets.models import (
    SheetCell,
    TeamMemberSheetAffiliation,
    TeamMemberTeamMatch,
    TeamPlayerMatch,
    TeamTechnicalStaffMatch,
)
from bigness_league_bot.infrastructure.google.team_sheets.parser import (
    _find_technical_staff_start_row,
    _parse_players,
    _parse_technical_staff,
)
from bigness_league_bot.infrastructure.google.team_sheets.schema import (
    PLACEHOLDER_CELL_VALUE,
    TEAM_BLOCK_MAX_TECHNICAL_STAFF,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N


def _find_player_matches(
        normalized_discord_name: str,
        sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
) -> tuple[TeamPlayerMatch, ...]:
    return _find_player_matches_by_discord_name_set(
        frozenset({normalized_discord_name}),
        sheet_grids,
    )


def _find_technical_staff_matches(
        normalized_discord_name: str,
        sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
) -> tuple[TeamTechnicalStaffMatch, ...]:
    matches: list[TeamTechnicalStaffMatch] = []
    for worksheet_title, cell_grid in sheet_grids:
        for block in _collect_team_blocks(cell_grid):
            if _is_free_block_title(block.title):
                continue

            start_row = _find_technical_staff_start_row(
                cell_grid,
                block,
            )
            if start_row is None:
                continue

            for offset in range(TEAM_BLOCK_MAX_TECHNICAL_STAFF):
                row_index = start_row + offset
                role_cell = _get_cell(
                    cell_grid,
                    row_index,
                    block.start_column,
                )
                discord_cell = _get_cell(
                    cell_grid,
                    row_index,
                    block.start_column + 1,
                )
                epic_cell = _get_cell(
                    cell_grid,
                    row_index,
                    block.start_column + 2,
                )
                rocket_cell = _get_cell(
                    cell_grid,
                    row_index,
                    block.start_column + 3,
                )

                row_values = (
                    role_cell.value,
                    discord_cell.value,
                    epic_cell.value,
                    rocket_cell.value,
                )
                if _is_placeholder_row(*row_values):
                    continue

                if _normalize_member_lookup_text(discord_cell.value) != normalized_discord_name:
                    continue

                matches.append(
                    TeamTechnicalStaffMatch(
                        worksheet_title=worksheet_title,
                        block=block,
                        row_index=row_index,
                        member=TeamProfileStaffMember(
                            role_name=role_cell.value,
                            discord_name=discord_cell.value,
                            epic_name=epic_cell.value,
                            rocket_name=rocket_cell.value,
                        ),
                    )
                )

    return tuple(matches)


def _raise_removal_not_found_error(
        discord_name: str,
        *,
        remove_player: bool,
        remove_staff: bool,
) -> None:
    if remove_player and remove_staff:
        raise TeamSheetPlayerNotFoundError(
            localize(
                I18N.errors.team_signing.member_not_found,
                discord_name=discord_name,
            )
        )

    if remove_staff:
        raise TeamSheetPlayerNotFoundError(
            localize(
                I18N.errors.team_signing.technical_staff_member_not_found,
                discord_name=discord_name,
            )
        )

    raise TeamSheetPlayerNotFoundError(
        localize(
            I18N.errors.team_signing.player_not_found,
            discord_name=discord_name,
        )
    )


def _find_player_matches_by_discord_name_set(
        normalized_discord_names: frozenset[str],
        sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
) -> tuple[TeamPlayerMatch, ...]:
    matches: list[TeamPlayerMatch] = []
    seen_matches: set[tuple[str, int, int, str, str]] = set()
    for worksheet_title, cell_grid in sheet_grids:
        for block in _collect_team_blocks(cell_grid):
            if _is_free_block_title(block.title):
                continue

            for player in _parse_players(cell_grid, block):
                normalized_player_discord = _normalize_member_lookup_text(
                    player.discord_name
                )
                if normalized_player_discord not in normalized_discord_names:
                    continue

                match_key = (
                    worksheet_title,
                    block.title_row,
                    block.start_column,
                    normalized_player_discord,
                    player.player_name,
                )
                if match_key in seen_matches:
                    continue
                seen_matches.add(match_key)
                matches.append(
                    TeamPlayerMatch(
                        worksheet_title=worksheet_title,
                        block=block,
                        player=player,
                    )
                )

    return tuple(matches)


def _find_member_affiliations_by_discord_name_set(
        normalized_discord_names: frozenset[str],
        sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
) -> dict[str, TeamMemberSheetAffiliation]:
    player_flags: dict[str, bool] = {}
    staff_role_names: dict[str, set[str]] = {}
    original_names: dict[str, str] = {}

    for _, cell_grid in sheet_grids:
        for block in _collect_team_blocks(cell_grid):
            if _is_free_block_title(block.title):
                continue

            for player in _parse_players(cell_grid, block):
                normalized_player_discord = _normalize_member_lookup_text(
                    player.discord_name
                )
                if normalized_player_discord not in normalized_discord_names:
                    continue

                player_flags[normalized_player_discord] = True
                original_names.setdefault(
                    normalized_player_discord,
                    player.discord_name,
                )

            for staff_member in _parse_technical_staff(
                    cell_grid,
                    block,
            ):
                normalized_staff_discord = _normalize_member_lookup_text(
                    staff_member.discord_name
                )
                if normalized_staff_discord not in normalized_discord_names:
                    continue

                original_names.setdefault(
                    normalized_staff_discord,
                    staff_member.discord_name,
                )
                normalized_staff_role_name = _normalize_technical_staff_role_name(
                    staff_member.role_name
                )
                if not normalized_staff_role_name or normalized_staff_role_name == _normalize_lookup_text(
                        PLACEHOLDER_CELL_VALUE):
                    continue

                staff_role_names.setdefault(
                    normalized_staff_discord,
                    set(),
                ).add(staff_member.role_name)

    return {
        normalized_name: TeamMemberSheetAffiliation(
            discord_name=original_names.get(normalized_name, normalized_name),
            is_player=player_flags.get(normalized_name, False),
            staff_role_names=tuple(
                sorted(staff_role_names.get(normalized_name, set()))
            ),
        )
        for normalized_name in normalized_discord_names
        if player_flags.get(normalized_name, False)
           or staff_role_names.get(normalized_name)
    }


def _find_member_team_matches_by_discord_name_set(
        normalized_discord_names: frozenset[str],
        sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
) -> tuple[TeamMemberTeamMatch, ...]:
    matches: list[TeamMemberTeamMatch] = []
    seen_matches: set[tuple[str, int, int, str]] = set()

    for worksheet_title, cell_grid in sheet_grids:
        for block in _collect_team_blocks(cell_grid):
            if _is_free_block_title(block.title):
                continue

            player_flags: dict[str, bool] = {}
            staff_role_names: dict[str, set[str]] = {}
            original_names: dict[str, str] = {}

            for player in _parse_players(cell_grid, block):
                normalized_player_discord = _normalize_member_lookup_text(
                    player.discord_name
                )
                if normalized_player_discord not in normalized_discord_names:
                    continue

                player_flags[normalized_player_discord] = True
                original_names.setdefault(
                    normalized_player_discord,
                    player.discord_name,
                )

            for staff_member in _parse_technical_staff(
                    cell_grid,
                    block,
            ):
                normalized_staff_discord = _normalize_member_lookup_text(
                    staff_member.discord_name
                )
                if normalized_staff_discord not in normalized_discord_names:
                    continue

                normalized_staff_role_name = _normalize_technical_staff_role_name(
                    staff_member.role_name
                )
                if not normalized_staff_role_name or normalized_staff_role_name == _normalize_lookup_text(
                        PLACEHOLDER_CELL_VALUE):
                    continue

                original_names.setdefault(
                    normalized_staff_discord,
                    staff_member.discord_name,
                )
                staff_role_names.setdefault(
                    normalized_staff_discord,
                    set(),
                ).add(staff_member.role_name)

            matched_names = sorted(
                normalized_name
                for normalized_name in normalized_discord_names
                if player_flags.get(normalized_name, False)
                or staff_role_names.get(normalized_name)
            )
            for normalized_name in matched_names:
                match_key = (
                    worksheet_title,
                    block.title_row,
                    block.start_column,
                    normalized_name,
                )
                if match_key in seen_matches:
                    continue

                seen_matches.add(match_key)
                matches.append(
                    TeamMemberTeamMatch(
                        worksheet_title=worksheet_title,
                        block=block,
                        affiliation=TeamMemberSheetAffiliation(
                            discord_name=original_names.get(
                                normalized_name,
                                normalized_name,
                            ),
                            is_player=player_flags.get(normalized_name, False),
                            staff_role_names=tuple(
                                sorted(staff_role_names.get(normalized_name, set()))
                            ),
                        ),
                    )
                )

    return tuple(matches)
