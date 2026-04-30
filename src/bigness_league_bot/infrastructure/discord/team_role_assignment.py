from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import discord
import unicodedata

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import TranslationKeyLike, localize
from bigness_league_bot.infrastructure.discord.channel_management import (
    ChannelAccessRoleCatalog,
    user_audit_label,
)
from bigness_league_bot.infrastructure.discord.team_change_announcements import (
    TEAM_PLAYER_ROLE_SIGNING_SPEC,
    TEAM_ROLE_SIGNING_SPEC,
    TEAM_STAFF_ROLE_SIGNING_SPEC,
)
from bigness_league_bot.infrastructure.discord.team_role_change_delivery import (
    suppress_team_change_announcement,
)
from bigness_league_bot.infrastructure.discord.team_staff_roles import (
    collect_staff_role_entries_by_member,
    filter_team_staff_role_names_for_player_status,
    resolve_configured_team_staff_roles,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

DISCORD_MEMBER_MENTION_PATTERN = re.compile(r"^<@!?(\d+)>$")
DISCORD_MEMBER_ID_PATTERN = re.compile(r"^\d{15,20}$")
PLACEHOLDER_MEMBER_NAMES = {"", "-"}


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
    assigned_staff_entries: tuple[TeamStaffRoleEntry, ...] = ()


def build_member_lookup_keys(member: discord.Member) -> tuple[str, ...]:
    return tuple(_member_lookup_keys(member))


def normalize_member_lookup_text(value: str | None) -> str:
    return _normalize_member_lookup_text(value)

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


async def sync_team_staff_roles_by_names(
        guild: discord.Guild,
        *,
        team_role: discord.Role,
        participant_role: discord.Role,
        ceo_role_id: int,
        analyst_role_id: int,
        coach_role_id: int,
        manager_role_id: int,
        second_manager_role_id: int,
        captain_role_id: int,
        actor: discord.abc.User,
        staff_entries: Iterable[TeamStaffRoleEntry],
        player_member_names: Iterable[str] = (),
        count_existing_staff_roles_as_assigned: bool = False,
        suppress_staff_signing_announcements: bool = False,
) -> TeamStaffRoleSyncSummary:
    normalized_entries = collect_staff_role_entries_by_member(staff_entries)
    if not normalized_entries:
        return TeamStaffRoleSyncSummary(
            assigned_members=(),
            removed_members=(),
            already_configured_members=(),
            unresolved_names=(),
            ambiguous_names=(),
            assigned_staff_entries=(),
        )

    configured_staff_roles = resolve_configured_team_staff_roles(
        guild,
        ceo_role_id=ceo_role_id,
        analyst_role_id=analyst_role_id,
        coach_role_id=coach_role_id,
        manager_role_id=manager_role_id,
        second_manager_role_id=second_manager_role_id,
        captain_role_id=captain_role_id,
    )
    player_lookup_keys = {
        normalized_name
        for player_member_name in player_member_names
        if (
               normalized_name := _normalize_member_lookup_text(player_member_name)
           ) not in PLACEHOLDER_MEMBER_NAMES
    }
    members = await _load_guild_members(guild)
    members_by_lookup = _index_members_by_lookup_keys(members)
    assigned_members: list[discord.Member] = []
    removed_members: list[discord.Member] = []
    already_configured_members: list[discord.Member] = []
    unresolved_names: list[str] = []
    ambiguous_names: list[str] = []
    assigned_staff_entries: list[TeamStaffRoleEntry] = []

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
        filtered_role_names = filter_team_staff_role_names_for_player_status(
            entry.role_keys,
            is_player_in_same_team=any(
                lookup_key in player_lookup_keys
                for lookup_key in build_member_lookup_keys(member)
            ),
        )
        desired_staff_roles = tuple(
            {
                configured_staff_roles[role_key].id: configured_staff_roles[role_key]
                for role_key in sorted(filtered_role_names)
                if role_key in configured_staff_roles
            }.values()
        )
        base_roles_to_add = tuple(
            role
            for role in (team_role, participant_role)
            if role not in member.roles
        )
        staff_roles_to_add = tuple(
            role
            for role in desired_staff_roles
            if role not in member.roles
        )
        roles_to_remove = tuple(
            {
                role.id: role
                for role in configured_staff_roles.values()
                if role in member.roles and role not in desired_staff_roles
            }.values()
        )

        roles_to_add = tuple(
            {
                role.id: role
                for role in (*base_roles_to_add, *staff_roles_to_add)
            }.values()
        )
        if count_existing_staff_roles_as_assigned:
            assigned_role_keys = {
                role_key
                for role_key in filtered_role_names
                if role_key in configured_staff_roles
            }
        else:
            staff_role_ids_to_add = {role.id for role in staff_roles_to_add}
            assigned_role_keys = {
                role_key
                for role_key in filtered_role_names
                if (
                        role_key in configured_staff_roles
                        and configured_staff_roles[role_key].id in staff_role_ids_to_add
                )
            }
        if suppress_staff_signing_announcements:
            _suppress_staff_signing_announcements(
                guild=guild,
                member=member,
                team_role=team_role,
                configured_staff_roles=configured_staff_roles,
                role_keys=assigned_role_keys,
            )
        if roles_to_add:
            await member.add_roles(
                *roles_to_add,
                reason=(
                    f"{user_audit_label(actor)} sincronizó roles de staff del equipo "
                    f"{team_role.name} para {user_audit_label(member)}"
                ),
            )
        if roles_to_add:
            assigned_members.append(member)
        elif count_existing_staff_roles_as_assigned and desired_staff_roles:
            assigned_members.append(member)
        assigned_staff_entries.extend(
            TeamStaffRoleEntry(role_name=role_key, member_name=entry.member_name)
            for role_key in sorted(assigned_role_keys)
        )
        if roles_to_remove:
            await member.remove_roles(
                *roles_to_remove,
                reason=(
                    f"{user_audit_label(actor)} actualizó roles de staff del equipo "
                    f"{team_role.name} para {user_audit_label(member)}"
                ),
            )
            removed_members.append(member)
        if not base_roles_to_add and not staff_roles_to_add and not roles_to_remove:
            already_configured_members.append(member)

    return TeamStaffRoleSyncSummary(
        assigned_members=tuple(_deduplicate_members(assigned_members)),
        removed_members=tuple(_deduplicate_members(removed_members)),
        already_configured_members=tuple(_deduplicate_members(already_configured_members)),
        unresolved_names=tuple(unresolved_names),
        ambiguous_names=tuple(ambiguous_names),
        assigned_staff_entries=tuple(assigned_staff_entries),
    )


def _suppress_staff_signing_announcements(
        *,
        guild: discord.Guild,
        member: discord.Member,
        team_role: discord.Role,
        configured_staff_roles: dict[str, discord.Role],
        role_keys: Iterable[str],
) -> None:
    for role_key in role_keys:
        staff_role = configured_staff_roles.get(role_key)
        if staff_role is None:
            continue

        suppress_team_change_announcement(
            guild_id=guild.id,
            member_id=member.id,
            team_role_id=team_role.id,
            spec=TEAM_STAFF_ROLE_SIGNING_SPEC,
            staff_role_id=staff_role.id,
        )


async def assign_team_roles_by_names(
        guild: discord.Guild,
        *,
        team_role: discord.Role,
        common_roles: tuple[discord.Role, ...],
        actor: discord.abc.User,
        member_names: Iterable[str],
        suppress_player_signing_announcements: bool = False,
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

        if suppress_player_signing_announcements:
            _suppress_player_signing_announcement(
                guild=guild,
                member=member,
                team_role=team_role,
                roles_to_add=roles_to_add,
            )
        await member.add_roles(
            *roles_to_add,
            reason=(
                f"{user_audit_label(actor)} sincronizó roles automáticos del equipo "
                f"{team_role.name} para {user_audit_label(member)}"
            ),
        )
        assigned_members.append(member)

    return TeamRoleAssignmentSummary(
        assigned_members=tuple(assigned_members),
        already_configured_members=tuple(already_configured_members),
        unresolved_names=tuple(unresolved_names),
        ambiguous_names=tuple(ambiguous_names),
    )


def _suppress_player_signing_announcement(
        *,
        guild: discord.Guild,
        member: discord.Member,
        team_role: discord.Role,
        roles_to_add: tuple[discord.Role, ...],
) -> None:
    added_role_ids = {role.id for role in roles_to_add}
    if team_role.id not in added_role_ids:
        return

    suppress_team_change_announcement(
        guild_id=guild.id,
        member_id=member.id,
        team_role_id=None,
        spec=TEAM_PLAYER_ROLE_SIGNING_SPEC,
    )


def suppress_role_restore_signing_announcements(
        *,
        guild: discord.Guild,
        member: discord.Member,
        team_role: discord.Role,
        roles_to_add: tuple[discord.Role, ...],
        player_role: discord.Role | None = None,
        staff_roles: tuple[discord.Role, ...] = (),
) -> None:
    added_role_ids = {role.id for role in roles_to_add}
    if team_role.id in added_role_ids:
        suppress_team_change_announcement(
            guild_id=guild.id,
            member_id=member.id,
            team_role_id=team_role.id,
            spec=TEAM_ROLE_SIGNING_SPEC,
        )

    if player_role is not None and player_role.id in added_role_ids:
        suppress_team_change_announcement(
            guild_id=guild.id,
            member_id=member.id,
            team_role_id=None,
            spec=TEAM_PLAYER_ROLE_SIGNING_SPEC,
        )

    for staff_role in staff_roles:
        if staff_role.id not in added_role_ids:
            continue

        suppress_team_change_announcement(
            guild_id=guild.id,
            member_id=member.id,
            team_role_id=team_role.id,
            spec=TEAM_STAFF_ROLE_SIGNING_SPEC,
            staff_role_id=staff_role.id,
        )


async def remove_roles_from_member_by_name(
        guild: discord.Guild,
        *,
        actor: discord.abc.User,
        member_name: str,
        roles_to_remove: Iterable[discord.Role],
        before_remove: Callable[[discord.Member, tuple[discord.Role, ...]], None] | None = None,
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
    if before_remove is not None:
        before_remove(member, roles_tuple)
    await member.remove_roles(
        *roles_tuple,
        reason=(
            f"{user_audit_label(actor)} dio de baja a {member_name} y retiró roles de "
            f"{user_audit_label(member)}"
        ),
    )
    return TeamRoleRemovalSummary(
        member=member,
        removed_roles=roles_tuple,
    )


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

    normalized = " ".join(value.split()).strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    normalized = unicodedata.normalize("NFKC", normalized).casefold()
    return normalized
