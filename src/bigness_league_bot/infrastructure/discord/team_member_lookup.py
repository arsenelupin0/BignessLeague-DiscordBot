from __future__ import annotations

import re
from collections.abc import Iterable

import discord
import unicodedata

DISCORD_MEMBER_MENTION_PATTERN = re.compile(r"^<@!?(\d+)>$")
DISCORD_MEMBER_ID_PATTERN = re.compile(r"^\d{15,20}$")
PLACEHOLDER_MEMBER_NAMES = {"", "-"}


def build_member_lookup_keys(member: discord.Member) -> tuple[str, ...]:
    return tuple(_member_lookup_keys(member))


def normalize_member_lookup_text(value: str | None) -> str:
    if value is None:
        return ""

    normalized = " ".join(value.split()).strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    normalized = unicodedata.normalize("NFKC", normalized).casefold()
    return normalized


def deduplicate_member_names(member_names: Iterable[str]) -> tuple[str, ...]:
    collected_names: list[str] = []
    seen_names: set[str] = set()
    for member_name in member_names:
        normalized_name = normalize_member_lookup_text(member_name)
        if normalized_name in PLACEHOLDER_MEMBER_NAMES or normalized_name in seen_names:
            continue

        seen_names.add(normalized_name)
        collected_names.append(member_name)

    return tuple(collected_names)


def deduplicate_members(
        members: Iterable[discord.Member],
) -> tuple[discord.Member, ...]:
    deduplicated_members: dict[int, discord.Member] = {}
    for member in members:
        deduplicated_members[member.id] = member

    return tuple(deduplicated_members.values())


async def load_guild_members(guild: discord.Guild) -> tuple[discord.Member, ...]:
    try:
        fetched_members = [
            member
            async for member in guild.fetch_members(limit=None)
            if not member.bot
        ]
    except discord.HTTPException:
        return tuple(member for member in guild.members if not member.bot)

    return tuple(fetched_members)


def index_members_by_lookup_keys(
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


def resolve_members_for_name(
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

    return members_by_lookup.get(normalize_member_lookup_text(raw_name), ())


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
            normalize_member_lookup_text(value)
            for value in candidate_values
        )
        if normalized not in PLACEHOLDER_MEMBER_NAMES
    }
