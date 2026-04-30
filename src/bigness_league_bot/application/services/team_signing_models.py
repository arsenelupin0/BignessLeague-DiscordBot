from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

MAX_TEAM_SIGNING_PLAYERS = 6
MIN_TEAM_SIGNING_PLAYERS = 3
MAX_TEAM_TECHNICAL_STAFF_MEMBERS = 6
MMR_DIGITS_PATTERN = re.compile(r"\d+")


class TeamSigningParseError(ValueError):
    """Raised when the imported signing message does not follow the expected format."""


class TeamSigningCapacityError(ValueError):
    """Raised when the roster cannot fit the requested signings."""

    def __init__(self, *, capacity: int, existing_count: int, requested_count: int) -> None:
        super().__init__("team_signing_capacity_exceeded")
        self.capacity = capacity
        self.existing_count = existing_count
        self.requested_count = requested_count

    @property
    def available_slots(self) -> int:
        return max(self.capacity - self.existing_count, 0)


def _parse_mmr_sort_value(value: str) -> int:
    matches = MMR_DIGITS_PATTERN.findall(value)
    if not matches:
        return -1

    return int("".join(matches))


@dataclass(frozen=True, slots=True)
class TeamSigningPlayer:
    player_name: str
    tracker_url: str
    discord_name: str
    epic_name: str
    rocket_name: str
    mmr: str

    @property
    def mmr_sort_value(self) -> int:
        return _parse_mmr_sort_value(self.mmr)


@dataclass(frozen=True, slots=True)
class TeamSigningBatch:
    division_name: str
    team_name: str
    team_logo_url: str | None
    players: tuple[TeamSigningPlayer, ...]


@dataclass(frozen=True, slots=True)
class TeamTechnicalStaffMember:
    role_name: str
    discord_name: str
    epic_name: str
    rocket_name: str


@dataclass(frozen=True, slots=True)
class TeamTechnicalStaffBatch:
    division_name: str
    team_name: str
    members: tuple[TeamTechnicalStaffMember, ...]


def sort_team_signing_players(
        players: Iterable[TeamSigningPlayer],
) -> tuple[TeamSigningPlayer, ...]:
    return tuple(
        sorted(
            players,
            key=lambda player: (
                player.mmr_sort_value,
                player.player_name.casefold(),
            ),
            reverse=True,
        )
    )


def merge_team_signing_players(
        existing_players: Iterable[TeamSigningPlayer],
        incoming_players: Iterable[TeamSigningPlayer],
        *,
        capacity: int = MAX_TEAM_SIGNING_PLAYERS,
) -> tuple[TeamSigningPlayer, ...]:
    existing = tuple(existing_players)
    incoming = tuple(incoming_players)
    merged_players = (*existing, *incoming)
    if len(merged_players) > capacity:
        raise TeamSigningCapacityError(
            capacity=capacity,
            existing_count=len(existing),
            requested_count=len(incoming),
        )

    return sort_team_signing_players(merged_players)
