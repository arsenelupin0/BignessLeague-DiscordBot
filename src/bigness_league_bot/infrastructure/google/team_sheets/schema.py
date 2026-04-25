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

TEAM_BLOCK_HEADERS = (
    "Jugador",
    "Discord",
    "Epic Name",
    "Rocket In-Game Name",
    "MMR",
)
TEAM_BLOCK_HEADERS_NORMALIZED = tuple(header.casefold() for header in TEAM_BLOCK_HEADERS)
TEAM_BLOCK_HEADER_ROW_OFFSET = 1
TEAM_BLOCK_PLAYERS_ROW_OFFSET = 2
TEAM_BLOCK_MAX_PLAYERS = 6
TEAM_BLOCK_SUMMARY_ROW_OFFSET = TEAM_BLOCK_PLAYERS_ROW_OFFSET + TEAM_BLOCK_MAX_PLAYERS
TEAM_BLOCK_TECHNICAL_STAFF_ROW_OFFSET = TEAM_BLOCK_SUMMARY_ROW_OFFSET + 1
TEAM_BLOCK_MAX_TECHNICAL_STAFF = 6
TEAM_BLOCK_COLUMN_COUNT = len(TEAM_BLOCK_HEADERS)
TECHNICAL_STAFF_TITLE_NORMALIZED = "staff tecnico"
TECHNICAL_STAFF_HEADERS_NORMALIZED = (
    "rol",
    "discord",
    "epic name",
    "rocket in-game name",
)
PLACEHOLDER_CELL_VALUE = "-"
PLACEHOLDER_MEMBER_NAMES = {"", PLACEHOLDER_CELL_VALUE}
