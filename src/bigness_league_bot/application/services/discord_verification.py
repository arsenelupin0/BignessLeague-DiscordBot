from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

import unicodedata

from bigness_league_bot.application.services.team_profile import TeamProfile


def normalize_identity(value: str) -> str:
    return unicodedata.normalize("NFKC", " ".join(value.split()).lstrip("@")).casefold()


def parse_discord_id(value: str) -> int | None:
    match = re.fullmatch(r"(?:<@!?(\d{15,20})>|(\d{15,20}))", value.strip())
    return int(match.group(1) or match.group(2)) if match else None


@dataclass(frozen=True, slots=True)
class RosterIdentity:
    sheet_value: str
    player_name: str
    is_player: bool
    staff_role_names: tuple[str, ...]


def collect_roster_identities(profile: TeamProfile) -> tuple[RosterIdentity, ...]:
    identities: dict[str, RosterIdentity] = {}
    rows = (
        *((p.discord_id, p.player_name, True, "", p.has_content) for p in profile.players),
        *((s.discord_id, s.player_name, False, s.role_name,
           any(v.strip() not in {"", "-"} for v in (s.discord_id, s.player_name, s.epic_name)))
          for s in profile.technical_staff),
    )
    for index, (value, name, is_player, staff_role, populated) in enumerate(rows):
        if not populated:
            continue
        # Empty IDs are separate data errors; placeholders for vacant staff are ignored.
        key = str(parse_discord_id(value) or normalize_identity(value))
        if key in {"", "-"}:
            key = f"empty:{index}"
        previous = identities.get(key)
        identities[key] = RosterIdentity(
            sheet_value=previous.sheet_value if previous else value,
            player_name=(previous.player_name if previous else name),
            is_player=is_player or bool(previous and previous.is_player),
            staff_role_names=tuple(sorted({
                *(previous.staff_role_names if previous else ()),
                *((staff_role,) if staff_role else ()),
            })),
        )
    return tuple(identities.values())


class VerificationStatus(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ExpectedRole:
    name: str
    role_id: int | None


@dataclass(frozen=True, slots=True)
class MemberSnapshot:
    member_id: int
    role_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    identity: RosterIdentity
    matches: tuple[MemberSnapshot, ...]
    expected_roles: tuple[ExpectedRole, ...]


@dataclass(frozen=True, slots=True)
class MemberVerification:
    sheet_values: tuple[str, ...]
    player_name: str
    status: VerificationStatus
    member_id: int | None
    candidate_ids: tuple[int, ...] = ()
    missing_roles: tuple[ExpectedRole, ...] = ()


@dataclass(frozen=True, slots=True)
class TeamVerification:
    team_name: str
    division_name: str
    members: tuple[MemberVerification, ...]
    unavailable_roles: tuple[str, ...]


def verify_team(
        profile: TeamProfile,
        resolutions: Iterable[IdentityResolution],
        *,
        team_role: ExpectedRole,
) -> TeamVerification:
    # A player and staff row can identify the same member using different aliases.
    grouped: dict[str, list[IdentityResolution]] = {}
    for index, resolution in enumerate(resolutions):
        matches = resolution.matches
        key = str(matches[0].member_id) if len(matches) == 1 else f"row:{index}"
        grouped.setdefault(key, []).append(resolution)
    unavailable = {team_role.name} if team_role.role_id is None else set()
    members: list[MemberVerification] = []
    for entries in grouped.values():
        entry = entries[0]
        value = entry.identity.sheet_value.strip()
        expected = {role for e in entries for role in e.expected_roles}
        unavailable.update(role.name for role in expected if role.role_id is None)
        member_id = parse_discord_id(value)
        if value in {"", "-"}:
            status = VerificationStatus.INVALID
        elif len(entry.matches) > 1:
            status = VerificationStatus.AMBIGUOUS
        elif not entry.matches:
            status = VerificationStatus.MISSING
        else:
            status = VerificationStatus.PRESENT
            member_id = entry.matches[0].member_id
        missing_roles = tuple(sorted(
            (role for role in expected if role.role_id is not None
             and status == VerificationStatus.PRESENT
             and role.role_id not in entry.matches[0].role_ids),
            key=lambda role: role.name,
        ))
        members.append(MemberVerification(
            sheet_values=tuple(dict.fromkeys(e.identity.sheet_value for e in entries)),
            player_name=entry.identity.player_name,
            status=status,
            member_id=member_id,
            candidate_ids=tuple(m.member_id for m in entry.matches) if len(entry.matches) > 1 else (),
            missing_roles=missing_roles,
        ))
    return TeamVerification(profile.team_name, profile.division_name, tuple(members), tuple(sorted(unavailable)))
