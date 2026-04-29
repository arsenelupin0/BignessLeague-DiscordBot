from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

import discord
import unicodedata

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import TranslationKeyLike, localize
from bigness_league_bot.infrastructure.i18n.keys import I18N

PLACEHOLDER_MEMBER_NAMES = {"", "-"}
TEAM_STAFF_ROLE_MANAGER_ALIASES = {"manager"}
TEAM_STAFF_ROLE_SECOND_MANAGER_ALIASES = {"segundo manager", "second_manager"}
TEAM_STAFF_ROLE_CEO = "ceo"
TEAM_STAFF_ROLE_COACH_ALIASES = {"coach"}
TEAM_STAFF_ROLE_ANALYST_ALIASES = {"analista", "analyst"}
TEAM_STAFF_ROLE_CAPTAIN_ALIASES = {"capitan", "captain"}
TEAM_STAFF_ROLE_MANAGER = "manager"
TEAM_STAFF_ROLE_SECOND_MANAGER = "second_manager"
TEAM_STAFF_ROLE_COACH = "coach"
TEAM_STAFF_ROLE_ANALYST = "analyst"
TEAM_STAFF_ROLE_CAPTAIN = "captain"


class StaffRoleEntryLike(Protocol):
    @property
    def role_name(self) -> str:
        ...

    @property
    def member_name(self) -> str:
        ...


@dataclass(frozen=True, slots=True)
class CollectedStaffRoleEntry:
    member_name: str
    role_keys: frozenset[str]


def resolve_optional_team_staff_roles(
        guild: discord.Guild,
        *,
        ceo_role_id: int,
        analyst_role_id: int,
        coach_role_id: int,
        manager_role_id: int,
        second_manager_role_id: int,
        captain_role_id: int,
        staff_role_names: Iterable[str],
) -> tuple[discord.Role, ...]:
    requested_role_keys = {
        role_key
        for role_key in (
            _normalize_team_staff_role_name(role_name)
            for role_name in staff_role_names
        )
        if role_key is not None
    }
    resolved_roles: list[discord.Role] = []
    for role_key in requested_role_keys:
        role = _resolve_configured_team_staff_role(
            guild,
            role_key=role_key,
            ceo_role_id=ceo_role_id,
            analyst_role_id=analyst_role_id,
            coach_role_id=coach_role_id,
            manager_role_id=manager_role_id,
            second_manager_role_id=second_manager_role_id,
            captain_role_id=captain_role_id,
        )
        if role is not None:
            resolved_roles.append(role)

    unique_roles: dict[int, discord.Role] = {}
    for role in resolved_roles:
        unique_roles[role.id] = role

    return tuple(unique_roles.values())


def filter_team_staff_role_names_for_player_status(
        staff_role_names: Iterable[str],
        *,
        is_player_in_same_team: bool,
) -> tuple[str, ...]:
    return tuple(
        role_name
        for role_name in staff_role_names
        if (
                is_player_in_same_team
                or _normalize_team_staff_role_name(role_name) != TEAM_STAFF_ROLE_CAPTAIN
        )
    )


def normalize_team_staff_role_name(role_name: str | None) -> str | None:
    return _normalize_team_staff_role_name(role_name)


def resolve_team_staff_role_by_name(
        guild: discord.Guild,
        *,
        role_name: str,
        ceo_role_id: int,
        analyst_role_id: int,
        coach_role_id: int,
        manager_role_id: int,
        second_manager_role_id: int,
        captain_role_id: int,
) -> discord.Role | None:
    role_key = _normalize_team_staff_role_name(role_name)
    if role_key is None:
        return None

    return _resolve_configured_team_staff_role(
        guild,
        role_key=role_key,
        ceo_role_id=ceo_role_id,
        analyst_role_id=analyst_role_id,
        coach_role_id=coach_role_id,
        manager_role_id=manager_role_id,
        second_manager_role_id=second_manager_role_id,
        captain_role_id=captain_role_id,
    )


def resolve_configured_team_staff_roles(
        guild: discord.Guild,
        *,
        ceo_role_id: int,
        analyst_role_id: int,
        coach_role_id: int,
        manager_role_id: int,
        second_manager_role_id: int,
        captain_role_id: int,
) -> dict[str, discord.Role]:
    return {
        role_key: role
        for role_key in (
            TEAM_STAFF_ROLE_CEO,
            TEAM_STAFF_ROLE_ANALYST,
            TEAM_STAFF_ROLE_COACH,
            TEAM_STAFF_ROLE_MANAGER,
            TEAM_STAFF_ROLE_SECOND_MANAGER,
            TEAM_STAFF_ROLE_CAPTAIN,
        )
        if (
               role := _resolve_configured_team_staff_role(
                   guild,
                   role_key=role_key,
                   ceo_role_id=ceo_role_id,
                   analyst_role_id=analyst_role_id,
                   coach_role_id=coach_role_id,
                   manager_role_id=manager_role_id,
                   second_manager_role_id=second_manager_role_id,
                   captain_role_id=captain_role_id,
               )
           ) is not None
    }


def collect_staff_role_entries_by_member(
        staff_entries: Iterable[StaffRoleEntryLike],
) -> dict[str, CollectedStaffRoleEntry]:
    member_names_by_lookup: dict[str, str] = {}
    role_keys_by_lookup: dict[str, set[str]] = {}
    for staff_entry in staff_entries:
        normalized_member_name = _normalize_member_lookup_text(staff_entry.member_name)
        if normalized_member_name in PLACEHOLDER_MEMBER_NAMES:
            continue

        role_key = _normalize_team_staff_role_name(staff_entry.role_name)
        if role_key is None:
            continue

        member_names_by_lookup.setdefault(normalized_member_name, staff_entry.member_name)
        role_keys_by_lookup.setdefault(normalized_member_name, set()).add(role_key)

    return {
        normalized_name: CollectedStaffRoleEntry(
            member_name=member_names_by_lookup[normalized_name],
            role_keys=frozenset(role_keys),
        )
        for normalized_name, role_keys in role_keys_by_lookup.items()
    }


def _resolve_configured_team_staff_role(
        guild: discord.Guild,
        *,
        role_key: str,
        ceo_role_id: int,
        analyst_role_id: int,
        coach_role_id: int,
        manager_role_id: int,
        second_manager_role_id: int,
        captain_role_id: int,
) -> discord.Role | None:
    role_configs = {
        TEAM_STAFF_ROLE_CEO: (
            ceo_role_id,
            I18N.errors.team_role_assignment.staff_ceo_role_missing,
        ),
        TEAM_STAFF_ROLE_ANALYST: (
            analyst_role_id,
            I18N.errors.team_role_assignment.staff_analyst_role_missing,
        ),
        TEAM_STAFF_ROLE_COACH: (
            coach_role_id,
            I18N.errors.team_role_assignment.staff_coach_role_missing,
        ),
        TEAM_STAFF_ROLE_MANAGER: (
            manager_role_id,
            I18N.errors.team_role_assignment.staff_manager_role_missing,
        ),
        TEAM_STAFF_ROLE_SECOND_MANAGER: (
            second_manager_role_id,
            I18N.errors.team_role_assignment.staff_second_manager_role_missing,
        ),
        TEAM_STAFF_ROLE_CAPTAIN: (
            captain_role_id,
            I18N.errors.team_role_assignment.staff_captain_role_missing,
        ),
    }
    role_config = role_configs.get(role_key)
    if role_config is None:
        return None

    role_id, error_key = role_config
    return _resolve_required_role(guild, role_id=role_id, error_key=error_key)


def _resolve_required_role(
        guild: discord.Guild,
        *,
        role_id: int,
        error_key: TranslationKeyLike,
) -> discord.Role:
    role = guild.get_role(role_id)
    if role is not None:
        return role

    raise CommandUserError(
        localize(
            error_key,
            role_id=str(role_id),
        )
    )


def _normalize_team_staff_role_name(role_name: str | None) -> str | None:
    normalized_role_name = _normalize_member_lookup_text(role_name)
    if not normalized_role_name:
        return None
    normalized_role_name = "".join(
        character
        for character in unicodedata.normalize("NFKD", normalized_role_name)
        if not unicodedata.combining(character)
    )
    if normalized_role_name == TEAM_STAFF_ROLE_CEO:
        return TEAM_STAFF_ROLE_CEO
    if normalized_role_name in TEAM_STAFF_ROLE_ANALYST_ALIASES:
        return TEAM_STAFF_ROLE_ANALYST
    if normalized_role_name in TEAM_STAFF_ROLE_COACH_ALIASES:
        return TEAM_STAFF_ROLE_COACH
    if normalized_role_name in TEAM_STAFF_ROLE_SECOND_MANAGER_ALIASES:
        return TEAM_STAFF_ROLE_SECOND_MANAGER
    if normalized_role_name in TEAM_STAFF_ROLE_MANAGER_ALIASES:
        return TEAM_STAFF_ROLE_MANAGER
    if normalized_role_name in TEAM_STAFF_ROLE_CAPTAIN_ALIASES:
        return TEAM_STAFF_ROLE_CAPTAIN
    return None


def _normalize_member_lookup_text(value: str | None) -> str:
    if value is None:
        return ""

    normalized = " ".join(value.split()).strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    return unicodedata.normalize("NFKC", normalized).casefold()
