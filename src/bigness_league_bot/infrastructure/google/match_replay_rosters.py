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

import unicodedata

from bigness_league_bot.application.services.match_replays import MatchReplayRosterPlayer
from bigness_league_bot.infrastructure.google.team_sheets.blocks import collect_team_blocks
from bigness_league_bot.infrastructure.google.team_sheets.cells import is_free_block_title
from bigness_league_bot.infrastructure.google.team_sheets.models import SheetCell
from bigness_league_bot.infrastructure.google.team_sheets.parser import parse_players


def list_division_roster_players_from_grids(
        division_name: str,
        sheet_grids: tuple[tuple[str, dict[int, dict[int, SheetCell]]], ...],
) -> tuple[MatchReplayRosterPlayer, ...]:
    requested_division = normalize_worksheet_title(division_name)
    requested_division_key = division_key(requested_division)
    roster_players: list[MatchReplayRosterPlayer] = []

    for worksheet_title, cell_grid in sheet_grids:
        normalized_worksheet = normalize_worksheet_title(worksheet_title)
        if requested_division_key is not None:
            if requested_division_key not in normalized_worksheet:
                continue
        elif requested_division not in normalized_worksheet:
            continue

        for team_block in collect_team_blocks(cell_grid):
            if is_free_block_title(team_block.title):
                continue

            for player in parse_players(cell_grid, team_block):
                roster_players.append(
                    MatchReplayRosterPlayer(
                        division_name=worksheet_title,
                        team_name=team_block.title,
                        player_name=player.player_name,
                        discord_name=player.discord_name,
                        epic_name=player.epic_name,
                        rocket_name=player.rocket_name,
                        tracker_url=player.tracker_url,
                    )
                )
        break

    return tuple(roster_players)


def normalize_worksheet_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold().strip())
    without_accents = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(without_accents.split())


def division_key(normalized_division_name: str) -> str | None:
    if "gold" in normalized_division_name:
        return "gold"
    if "silver" in normalized_division_name:
        return "silver"
    return None
