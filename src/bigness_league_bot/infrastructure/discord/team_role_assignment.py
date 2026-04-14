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


@dataclass(frozen=True, slots=True)
class TeamRoleAssignmentSummary:
    assigned_members: tuple[discord.Member, ...]
    already_configured_members: tuple[discord.Member, ...]
    unresolved_names: tuple[str, ...]
    ambiguous_names: tuple[str, ...]


def collect_team_profile_member_names(team_profile: TeamProfile) -> tuple[str, ...]:
    collected_names: list[str] = []
    seen_names: set[str] = set()
    for member_name in (
            *(player.discord_name for player in team_profile.players),
            *(member.discord_name for member in team_profile.technical_staff),
    ):
        normalized_name = _normalize_member_lookup_text(member_name)
        if normalized_name in PLACEHOLDER_MEMBER_NAMES or normalized_name in seen_names:
            continue

        seen_names.add(normalized_name)
        collected_names.append(member_name)

    return tuple(collected_names)


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
