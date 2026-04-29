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

from bigness_league_bot.core.errors import CommandUserError


class TeamSheetError(CommandUserError):
    """Base error for expected team sheet lookup failures."""


class GoogleSheetsNotConfiguredError(TeamSheetError):
    """Raised when Google Sheets settings are missing."""


class GoogleSheetsDependencyError(TeamSheetError):
    """Raised when Google API dependencies are not installed."""


class TeamSheetEmptyError(TeamSheetError):
    """Raised when the configured sheet is empty."""


class TeamSheetLayoutError(TeamSheetError):
    """Raised when the configured sheet does not match the expected layout."""


class TeamSheetRowNotFoundError(TeamSheetError):
    """Raised when a team block cannot be found for the Discord role."""


class TeamSheetRequestError(TeamSheetError):
    """Raised when Google Sheets rejects the request."""


class TeamSheetDivisionNotFoundError(TeamSheetError):
    """Raised when the requested division sheet cannot be found."""


class TeamSheetNoFreeBlockError(TeamSheetError):
    """Raised when there is no free team block left in the selected sheet."""


class TeamSheetWriteError(TeamSheetError):
    """Raised when Google Sheets rejects a write operation."""


class TeamSheetRosterFullError(TeamSheetError):
    """Raised when the target team block does not have enough free slots."""


class TeamSheetNewTeamMinimumPlayersError(TeamSheetError):
    """Raised when a new team is registered with too few players."""


class TeamSheetRemainingSigningsExceededError(TeamSheetError):
    """Raised when the requested signings exceed the remaining signing quota."""


class TeamSheetPlayerNotFoundError(TeamSheetError):
    """Raised when a player cannot be found by Discord name."""


class TeamSheetDuplicatePlayerError(TeamSheetError):
    """Raised when more than one player matches the same Discord name."""


class TeamSheetTechnicalStaffRoleNotFoundError(TeamSheetError):
    """Raised when a requested technical staff role does not exist in the block."""


class TeamSheetTechnicalStaffPlayerNotFoundError(TeamSheetError):
    """Raised when staff data cannot be completed from the roster."""


class TeamSheetTechnicalStaffPlayerDuplicateError(TeamSheetError):
    """Raised when staff data completion finds multiple roster players."""
