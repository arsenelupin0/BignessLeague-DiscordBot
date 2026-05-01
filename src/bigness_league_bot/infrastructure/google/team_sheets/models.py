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

from dataclasses import dataclass

from bigness_league_bot.application.services.team_profile import (
    TeamProfilePlayer,
    TeamProfileStaffMember,
)


@dataclass(frozen=True, slots=True)
class SheetCell:
    value: str = ""
    hyperlink: str | None = None
    formula: str | None = None


@dataclass(frozen=True, slots=True)
class TeamBlockAnchor:
    title_row: int
    start_column: int
    title: str


@dataclass(frozen=True, slots=True)
class TeamSigningWriteResult:
    worksheet_title: str
    team_name: str
    inserted_count: int
    total_players: int
    created_team_block: bool = False


@dataclass(frozen=True, slots=True)
class TeamSigningRemovalResult:
    worksheet_title: str
    team_name: str
    discord_name: str
    removed_player_name: str | None = None
    total_players: int | None = None
    removed_staff_role_names: tuple[str, ...] = ()
    remaining_staff_role_names: tuple[str, ...] = ()
    is_player_present_after: bool = False
    is_player_present_after_any_team: bool = False
    remaining_staff_role_names_after_any_team: tuple[str, ...] = ()
    has_any_team_affiliation_after: bool = False


@dataclass(frozen=True, slots=True)
class TeamPlayerMatch:
    worksheet_title: str
    block: TeamBlockAnchor
    player: TeamProfilePlayer


@dataclass(frozen=True, slots=True)
class TeamTechnicalStaffMatch:
    worksheet_title: str
    block: TeamBlockAnchor
    row_index: int
    member: TeamProfileStaffMember


@dataclass(frozen=True, slots=True)
class TeamTechnicalStaffWriteResult:
    worksheet_title: str
    team_name: str
    updated_count: int


@dataclass(frozen=True, slots=True)
class TeamRosterPlayerUpdate:
    division_name: str
    team_name: str
    discord_name: str
    player_name: str
    tracker_url: str
    epic_name: str
    rocket_name: str
    mmr: str


@dataclass(frozen=True, slots=True)
class TeamRosterPlayerUpdateResult:
    worksheet_title: str
    team_name: str
    discord_name: str


@dataclass(frozen=True, slots=True)
class TeamRoleSheetMetadata:
    worksheet_title: str
    team_name: str
    team_image_url: str | None = None


@dataclass(frozen=True, slots=True)
class TeamMemberSheetAffiliation:
    discord_name: str
    is_player: bool
    staff_role_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TeamMemberTeamMatch:
    worksheet_title: str
    block: TeamBlockAnchor
    affiliation: TeamMemberSheetAffiliation
