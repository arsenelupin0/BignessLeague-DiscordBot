from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

import discord
import unicodedata

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import TranslationKeyLike, localize
from bigness_league_bot.infrastructure.discord.channel_management import (
    ChannelAccessRoleCatalog,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

DISCORD_MEMBER_MENTION_PATTERN = re.compile(r"^<@!?(\d+)>$")
DISCORD_MEMBER_ID_PATTERN = re.compile(r"^\d{15,20}$")
PLACEHOLDER_MEMBER_NAMES = {"", "-"}
TEAM_STAFF_ROLE_MANAGER_ALIASES = {"manager"}
TEAM_STAFF_ROLE_SECOND_MANAGER_ALIASES = {"segundo manager"}
TEAM_STAFF_ROLE_CEO = "ceo"
TEAM_STAFF_ROLE_COACH_ALIASES = {"coach"}
TEAM_STAFF_ROLE_ANALYST_ALIASES = {"analista"}
TEAM_STAFF_ROLE_CAPTAIN_ALIASES = {"capitan", "captain"}
TEAM_STAFF_ROLE_MANAGER = "manager"
TEAM_STAFF_ROLE_SECOND_MANAGER = "second_manager"
TEAM_STAFF_ROLE_COACH = "coach"
TEAM_STAFF_ROLE_ANALYST = "analyst"
TEAM_STAFF_ROLE_CAPTAIN = "captain"


@dataclass(frozen=True, slots=True)
class TeamRoleAssignmentSummary:
    assigned_members: tuple[discord.Member, ...]
    already_configured_members: tuple[discord.Member, ...]
    unresolved_names: tuple[str, ...]
    ambiguous_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TeamRoleRemovalSummary:
    member: discord.Member | None
    removed_roles: tuple[discord.Role, ...]
    unresolved: bool = False
    ambiguous: bool = False


@dataclass(frozen=True, slots=True)
class TeamStaffRoleEntry:
    role_name: str
    member_name: str


@dataclass(frozen=True, slots=True)
class TeamStaffRoleSyncSummary:
    assigned_members: tuple[discord.Member, ...]
    removed_members: tuple[discord.Member, ...]
    already_configured_members: tuple[discord.Member, ...]
    unresolved_names: tuple[str, ...]
    ambiguous_names: tuple[str, ...]


def build_member_lookup_keys(member: discord.Member) -> tuple[str, ...]:
    return tuple(_member_lookup_keys(member))


def collect_team_profile_player_names(team_profile: TeamProfile) -> tuple[str, ...]:
    return _deduplicate_member_names(player.discord_name for player in team_profile.players)


def collect_team_profile_staff_role_entries(
        team_profile: TeamProfile,
) -> tuple[TeamStaffRoleEntry, ...]:
    return tuple(
        TeamStaffRoleEntry(
            role_name=member.role_name,
            member_name=member.discord_name,
        )
        for member in team_profile.technical_staff
        if _normalize_member_lookup_text(member.discord_name) not in PLACEHOLDER_MEMBER_NAMES
    )


def resolve_team_role_by_name(
        team_name: str,
        role_catalog: ChannelAccessRoleCatalog,
) -> discord.Role:
    normalized_team_name = _normalize_member_lookup_text(team_name)
    for role in role_catalog.roles:
        if _normalize_member_lookup_text(role.name) == normalized_team_name:
            return role

    raise CommandUserError(
        localize(
            I18N.errors.team_role_assignment.team_role_not_found,
            team_name=team_name,
        )
    )


def resolve_participant_role(
        guild: discord.Guild,
        participant_role_id: int,
) -> discord.Role:
    return _resolve_required_role(
        guild,
        role_id=participant_role_id,
        error_key=I18N.errors.team_role_assignment.participant_role_missing,
    )


def resolve_player_role(
        guild: discord.Guild,
        player_role_id: int,
) -> discord.Role:
    return _resolve_required_role(
        guild,
        role_id=player_role_id,
        error_key=I18N.errors.team_role_assignment.player_role_missing,
    )


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
    if TEAM_STAFF_ROLE_CEO in requested_role_keys:
        resolved_roles.append(
            _resolve_required_role(
                guild,
                role_id=ceo_role_id,
                error_key=I18N.errors.team_role_assignment.staff_ceo_role_missing,
            )
        )
    if TEAM_STAFF_ROLE_ANALYST in requested_role_keys:
        resolved_roles.append(
            _resolve_required_role(
                guild,
                role_id=analyst_role_id,
                error_key=I18N.errors.team_role_assignment.staff_analyst_role_missing,
            )
        )
    if TEAM_STAFF_ROLE_COACH in requested_role_keys:
        resolved_roles.append(
            _resolve_required_role(
                guild,
                role_id=coach_role_id,
                error_key=I18N.errors.team_role_assignment.staff_coach_role_missing,
            )
        )
    if TEAM_STAFF_ROLE_MANAGER in requested_role_keys:
        resolved_roles.append(
            _resolve_required_role(
                guild,
                role_id=manager_role_id,
                error_key=I18N.errors.team_role_assignment.staff_manager_role_missing,
            )
        )
    if TEAM_STAFF_ROLE_SECOND_MANAGER in requested_role_keys:
        resolved_roles.append(
            _resolve_required_role(
                guild,
                role_id=second_manager_role_id,
                error_key=I18N.errors.team_role_assignment.staff_second_manager_role_missing,
            )
        )
    if TEAM_STAFF_ROLE_CAPTAIN in requested_role_keys:
        resolved_roles.append(
            _resolve_required_role(
                guild,
                role_id=captain_role_id,
                error_key=I18N.errors.team_role_assignment.staff_captain_role_missing,
            )
        )

    unique_roles: dict[int, discord.Role] = {}
    for role in resolved_roles:
        unique_roles[role.id] = role

    return tuple(unique_roles.values())


async def sync_team_staff_roles_by_names(
        guild: discord.Guild,
        *,
        team_role: discord.Role,
        ceo_role_id: int,
        analyst_role_id: int,
        coach_role_id: int,
        manager_role_id: int,
        second_manager_role_id: int,
        captain_role_id: int,
        actor: discord.abc.User,
        staff_entries: Iterable[TeamStaffRoleEntry],
) -> TeamStaffRoleSyncSummary:
    normalized_entries = _collect_staff_role_entries_by_member(staff_entries)
    if not normalized_entries:
        return TeamStaffRoleSyncSummary(
            assigned_members=(),
            removed_members=(),
            already_configured_members=(),
            unresolved_names=(),
            ambiguous_names=(),
        )

    configured_staff_roles = _resolve_configured_team_staff_roles(
        guild,
        ceo_role_id=ceo_role_id,
        analyst_role_id=analyst_role_id,
        coach_role_id=coach_role_id,
        manager_role_id=manager_role_id,
        second_manager_role_id=second_manager_role_id,
        captain_role_id=captain_role_id,
    )
    members = await _load_guild_members(guild)
    members_by_lookup = _index_members_by_lookup_keys(members)
    assigned_members: list[discord.Member] = []
    removed_members: list[discord.Member] = []
    already_configured_members: list[discord.Member] = []
    unresolved_names: list[str] = []
    ambiguous_names: list[str] = []

    for entry in normalized_entries.values():
        matches = _resolve_members_for_name(
            entry.member_name,
            members_by_lookup,
            guild,
        )
        if not matches:
            unresolved_names.append(entry.member_name)
            continue

        if len(matches) > 1:
            ambiguous_names.append(entry.member_name)
            continue

        member = matches[0]
        desired_staff_roles = tuple(
            {
                configured_staff_roles[role_key].id: configured_staff_roles[role_key]
                for role_key in sorted(entry.role_keys)
                if role_key in configured_staff_roles
            }.values()
        )
        desired_roles = (team_role, *desired_staff_roles)
        roles_to_add = tuple(
            role
            for role in desired_roles
            if role not in member.roles
        )
        roles_to_remove = tuple(
            {
                role.id: role
                for role in configured_staff_roles.values()
                if role in member.roles and role not in desired_staff_roles
            }.values()
        )

        if roles_to_add:
            await member.add_roles(
                *roles_to_add,
                reason=(
                    f"{actor} ({actor.id}) sincronizo roles de staff del equipo "
                    f"{team_role.name} para {member} ({member.id})"
                ),
            )
            assigned_members.append(member)
        if roles_to_remove:
            await member.remove_roles(
                *roles_to_remove,
                reason=(
                    f"{actor} ({actor.id}) actualizo roles de staff del equipo "
                    f"{team_role.name} para {member} ({member.id})"
                ),
            )
            removed_members.append(member)
        if not roles_to_add and not roles_to_remove:
            already_configured_members.append(member)

    return TeamStaffRoleSyncSummary(
        assigned_members=tuple(_deduplicate_members(assigned_members)),
        removed_members=tuple(_deduplicate_members(removed_members)),
        already_configured_members=tuple(_deduplicate_members(already_configured_members)),
        unresolved_names=tuple(unresolved_names),
        ambiguous_names=tuple(ambiguous_names),
    )


async def assign_team_roles_by_names(
        guild: discord.Guild,
        *,
        team_role: discord.Role,
        common_roles: tuple[discord.Role, ...],
        actor: discord.abc.User,
        member_names: Iterable[str],
) -> TeamRoleAssignmentSummary:
    members = await _load_guild_members(guild)
    members_by_lookup = _index_members_by_lookup_keys(members)
    assigned_members: list[discord.Member] = []
    already_configured_members: list[discord.Member] = []
    unresolved_names: list[str] = []
    ambiguous_names: list[str] = []
    processed_member_ids: set[int] = set()

    for raw_name in member_names:
        normalized_name = _normalize_member_lookup_text(raw_name)
        if normalized_name in PLACEHOLDER_MEMBER_NAMES:
            continue

        matches = _resolve_members_for_name(raw_name, members_by_lookup, guild)
        if not matches:
            unresolved_names.append(raw_name)
            continue

        if len(matches) > 1:
            ambiguous_names.append(raw_name)
            continue

        member = matches[0]
        if member.id in processed_member_ids:
            continue

        processed_member_ids.add(member.id)
        roles_to_add = tuple(
            role
            for role in (*common_roles, team_role)
            if role not in member.roles
        )
        if not roles_to_add:
            already_configured_members.append(member)
            continue

        await member.add_roles(
            *roles_to_add,
            reason=(
                f"{actor} ({actor.id}) sincronizo roles automaticos del equipo "
                f"{team_role.name} para {member} ({member.id})"
            ),
        )
        assigned_members.append(member)

    return TeamRoleAssignmentSummary(
        assigned_members=tuple(assigned_members),
        already_configured_members=tuple(already_configured_members),
        unresolved_names=tuple(unresolved_names),
        ambiguous_names=tuple(ambiguous_names),
    )


async def remove_roles_from_member_by_name(
        guild: discord.Guild,
        *,
        actor: discord.abc.User,
        member_name: str,
        roles_to_remove: Iterable[discord.Role],
) -> TeamRoleRemovalSummary:
    members = await _load_guild_members(guild)
    members_by_lookup = _index_members_by_lookup_keys(members)
    matches = _resolve_members_for_name(member_name, members_by_lookup, guild)
    if not matches:
        return TeamRoleRemovalSummary(
            member=None,
            removed_roles=(),
            unresolved=True,
        )
    if len(matches) > 1:
        return TeamRoleRemovalSummary(
            member=None,
            removed_roles=(),
            ambiguous=True,
        )

    member = matches[0]
    unique_roles_to_remove: dict[int, discord.Role] = {}
    for role in roles_to_remove:
        if role in member.roles:
            unique_roles_to_remove[role.id] = role

    if not unique_roles_to_remove:
        return TeamRoleRemovalSummary(
            member=member,
            removed_roles=(),
        )

    roles_tuple = tuple(unique_roles_to_remove.values())
    await member.remove_roles(
        *roles_tuple,
        reason=(
            f"{actor} ({actor.id}) dio de baja a {member_name} y retiro roles de "
            f"{member} ({member.id})"
        ),
    )
    return TeamRoleRemovalSummary(
        member=member,
        removed_roles=roles_tuple,
    )


@dataclass(frozen=True, slots=True)
class _CollectedStaffRoleEntry:
    member_name: str
    role_keys: frozenset[str]


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


def _resolve_configured_team_staff_roles(
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
        TEAM_STAFF_ROLE_CEO: _resolve_required_role(
            guild,
            role_id=ceo_role_id,
            error_key=I18N.errors.team_role_assignment.staff_ceo_role_missing,
        ),
        TEAM_STAFF_ROLE_ANALYST: _resolve_required_role(
            guild,
            role_id=analyst_role_id,
            error_key=I18N.errors.team_role_assignment.staff_analyst_role_missing,
        ),
        TEAM_STAFF_ROLE_COACH: _resolve_required_role(
            guild,
            role_id=coach_role_id,
            error_key=I18N.errors.team_role_assignment.staff_coach_role_missing,
        ),
        TEAM_STAFF_ROLE_MANAGER: _resolve_required_role(
            guild,
            role_id=manager_role_id,
            error_key=I18N.errors.team_role_assignment.staff_manager_role_missing,
        ),
        TEAM_STAFF_ROLE_SECOND_MANAGER: _resolve_required_role(
            guild,
            role_id=second_manager_role_id,
            error_key=I18N.errors.team_role_assignment.staff_second_manager_role_missing,
        ),
        TEAM_STAFF_ROLE_CAPTAIN: _resolve_required_role(
            guild,
            role_id=captain_role_id,
            error_key=I18N.errors.team_role_assignment.staff_captain_role_missing,
        ),
    }


def _collect_staff_role_entries_by_member(
        staff_entries: Iterable[TeamStaffRoleEntry],
) -> dict[str, _CollectedStaffRoleEntry]:
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
        normalized_name: _CollectedStaffRoleEntry(
            member_name=member_names_by_lookup[normalized_name],
            role_keys=frozenset(role_keys),
        )
        for normalized_name, role_keys in role_keys_by_lookup.items()
    }


def _deduplicate_member_names(member_names: Iterable[str]) -> tuple[str, ...]:
    collected_names: list[str] = []
    seen_names: set[str] = set()
    for member_name in member_names:
        normalized_name = _normalize_member_lookup_text(member_name)
        if normalized_name in PLACEHOLDER_MEMBER_NAMES or normalized_name in seen_names:
            continue

        seen_names.add(normalized_name)
        collected_names.append(member_name)

    return tuple(collected_names)


def _deduplicate_members(
        members: Iterable[discord.Member],
) -> tuple[discord.Member, ...]:
    deduplicated_members: dict[int, discord.Member] = {}
    for member in members:
        deduplicated_members[member.id] = member

    return tuple(deduplicated_members.values())


async def _load_guild_members(guild: discord.Guild) -> tuple[discord.Member, ...]:
    try:
        fetched_members = [
            member
            async for member in guild.fetch_members(limit=None)
            if not member.bot
        ]
    except discord.HTTPException:
        return tuple(member for member in guild.members if not member.bot)

    return tuple(fetched_members)


def _index_members_by_lookup_keys(
        members: Iterable[discord.Member],
) -> dict[str, tuple[discord.Member, ...]]:
    indexed_members: dict[str, dict[int, discord.Member]] = {}
    for member in members:
        for key in _member_lookup_keys(member):
            indexed_members.setdefault(key, {})[member.id] = member

    return {
        key: tuple(value.values())
        for key, value in indexed_members.items()
    }


def _resolve_members_for_name(
        raw_name: str,
        members_by_lookup: dict[str, tuple[discord.Member, ...]],
        guild: discord.Guild,
) -> tuple[discord.Member, ...]:
    member_id = _parse_member_id(raw_name)
    if member_id is not None:
        member = guild.get_member(member_id)
        if member is None or member.bot:
            return ()
        return (member,)

    return members_by_lookup.get(_normalize_member_lookup_text(raw_name), ())


def _parse_member_id(value: str) -> int | None:
    stripped_value = value.strip()
    mention_match = DISCORD_MEMBER_MENTION_PATTERN.fullmatch(stripped_value)
    if mention_match is not None:
        return int(mention_match.group(1))

    if DISCORD_MEMBER_ID_PATTERN.fullmatch(stripped_value):
        return int(stripped_value)

    return None


def _member_lookup_keys(member: discord.Member) -> set[str]:
    candidate_values = {
        member.name,
        member.display_name,
        str(member),
    }
    global_name = getattr(member, "global_name", None)
    if isinstance(global_name, str):
        candidate_values.add(global_name)

    return {
        normalized
        for normalized in (
            _normalize_member_lookup_text(value)
            for value in candidate_values
        )
        if normalized not in PLACEHOLDER_MEMBER_NAMES
    }


def _normalize_member_lookup_text(value: str | None) -> str:
    if value is None:
        return ""

    normalized = " ".join(str(value).split()).strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    normalized = unicodedata.normalize("NFKC", normalized).casefold()
    return normalized


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
