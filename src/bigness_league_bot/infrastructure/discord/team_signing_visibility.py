from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.infrastructure.discord.team_change_announcements import (
    TEAM_ROLE_SIGNING_SPEC,
    TEAM_STAFF_ROLE_SIGNING_SPEC,
)
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    build_member_lookup_keys,
    normalize_member_lookup_text,
)
from bigness_league_bot.infrastructure.discord.team_role_change_delivery import (
    SentTeamChangeAnnouncement,
    wait_for_team_change_announcement,
)
from bigness_league_bot.infrastructure.discord.team_signing_messages import (
    TeamSigningStaffAnnouncementLink,
    TeamSigningTeamAnnouncementLink,
)
from bigness_league_bot.infrastructure.discord.team_staff_roles import (
    resolve_team_staff_role_by_name,
)

if TYPE_CHECKING:
    from bigness_league_bot.application.services.team_signing import (
        TeamTechnicalStaffBatch,
    )
    from bigness_league_bot.core.settings import Settings
    from bigness_league_bot.infrastructure.discord.team_role_assignment import (
        TeamRoleAssignmentSummary,
        TeamStaffRoleSyncSummary,
    )

DISCORD_MEMBER_REFERENCE_PATTERN = re.compile(r"^<@!?(\d+)>$|^(\d{15,20})$")


@dataclass(frozen=True, slots=True)
class TeamSigningVisibilityLinks:
    team_links: tuple[TeamSigningTeamAnnouncementLink, ...]
    staff_links: tuple[TeamSigningStaffAnnouncementLink, ...]


async def collect_team_signing_visibility_links(
        *,
        settings: Settings,
        guild: discord.Guild,
        team_role: discord.Role,
        assignment_summary: TeamRoleAssignmentSummary | None,
        technical_staff_batch: TeamTechnicalStaffBatch | None,
        staff_sync_summary: TeamStaffRoleSyncSummary | None,
        since: float,
) -> TeamSigningVisibilityLinks:
    team_links, staff_team_links, staff_links = await asyncio.gather(
        _collect_player_team_links(
            guild=guild,
            team_role=team_role,
            assignment_summary=assignment_summary,
            since=since,
        ),
        _collect_staff_team_links(
            guild=guild,
            team_role=team_role,
            staff_sync_summary=staff_sync_summary,
            since=since,
        ),
        _collect_staff_announcement_links(
            settings=settings,
            guild=guild,
            team_role=team_role,
            technical_staff_batch=technical_staff_batch,
            staff_sync_summary=staff_sync_summary,
            since=since,
        ),
    )
    return TeamSigningVisibilityLinks(
        team_links=_deduplicate_team_links((*team_links, *staff_team_links)),
        staff_links=staff_links,
    )


async def _collect_player_team_links(
        *,
        guild: discord.Guild,
        team_role: discord.Role,
        assignment_summary: TeamRoleAssignmentSummary | None,
        since: float,
) -> tuple[TeamSigningTeamAnnouncementLink, ...]:
    if assignment_summary is None or not assignment_summary.assigned_members:
        return ()

    tasks: tuple[Awaitable[SentTeamChangeAnnouncement | None], ...] = tuple(
        wait_for_team_change_announcement(
            guild_id=guild.id,
            member_id=member.id,
            team_role_id=team_role.id,
            spec=TEAM_ROLE_SIGNING_SPEC,
            since=since,
        )
        for member in assignment_summary.assigned_members
    )
    if not tasks:
        return ()

    announcements = await asyncio.gather(*tasks)
    return _team_links_from_announcements(announcements)


async def _collect_staff_team_links(
        *,
        guild: discord.Guild,
        team_role: discord.Role,
        staff_sync_summary: TeamStaffRoleSyncSummary | None,
        since: float,
) -> tuple[TeamSigningTeamAnnouncementLink, ...]:
    if staff_sync_summary is None or not staff_sync_summary.assigned_members:
        return ()

    tasks: tuple[Awaitable[SentTeamChangeAnnouncement | None], ...] = tuple(
        wait_for_team_change_announcement(
            guild_id=guild.id,
            member_id=member.id,
            team_role_id=team_role.id,
            spec=TEAM_ROLE_SIGNING_SPEC,
            since=since,
        )
        for member in staff_sync_summary.assigned_members
    )
    if not tasks:
        return ()

    announcements = await asyncio.gather(*tasks)
    return _team_links_from_announcements(announcements)


async def _collect_staff_announcement_links(
        *,
        settings: Settings,
        guild: discord.Guild,
        team_role: discord.Role,
        technical_staff_batch: TeamTechnicalStaffBatch | None,
        staff_sync_summary: TeamStaffRoleSyncSummary | None,
        since: float,
) -> tuple[TeamSigningStaffAnnouncementLink, ...]:
    if (
            technical_staff_batch is None
            or staff_sync_summary is None
            or not staff_sync_summary.assigned_members
    ):
        return ()

    tasks: list[Awaitable[SentTeamChangeAnnouncement | None]] = []
    link_specs: list[tuple[discord.Role, discord.Member]] = []
    for staff_member in technical_staff_batch.members:
        member = _resolve_synced_member(
            staff_member.discord_name,
            staff_sync_summary.assigned_members,
        )
        if member is None:
            continue

        staff_role = resolve_team_staff_role_by_name(
            guild,
            role_name=staff_member.role_name,
            ceo_role_id=settings.staff_ceo_role_id,
            analyst_role_id=settings.staff_analyst_role_id,
            coach_role_id=settings.staff_coach_role_id,
            manager_role_id=settings.staff_manager_role_id,
            second_manager_role_id=settings.staff_second_manager_role_id,
            captain_role_id=settings.staff_captain_role_id,
        )
        if staff_role is None:
            continue

        link_specs.append((staff_role, member))
        tasks.append(
            wait_for_team_change_announcement(
                guild_id=guild.id,
                member_id=member.id,
                team_role_id=team_role.id,
                spec=TEAM_STAFF_ROLE_SIGNING_SPEC,
                staff_role_id=staff_role.id,
                since=since,
            )
        )

    if not tasks:
        return ()

    announcements = await asyncio.gather(*tasks)
    return _staff_links_from_announcements(
        link_specs=link_specs,
        announcements=announcements,
    )


def _resolve_synced_member(
        raw_member_name: str,
        synced_members: tuple[discord.Member, ...],
) -> discord.Member | None:
    member_id = _parse_member_reference_id(raw_member_name)
    if member_id is not None:
        return next(
            (member for member in synced_members if member.id == member_id),
            None,
        )

    normalized_name = normalize_member_lookup_text(raw_member_name)
    return next(
        (
            member
            for member in synced_members
            if normalized_name in build_member_lookup_keys(member)
        ),
        None,
    )


def _parse_member_reference_id(value: str) -> int | None:
    match = DISCORD_MEMBER_REFERENCE_PATTERN.fullmatch(value.strip())
    if match is None:
        return None

    raw_member_id = match.group(1) or match.group(2)
    return int(raw_member_id)


def _deduplicate_team_links(
        links: Iterable[TeamSigningTeamAnnouncementLink],
) -> tuple[TeamSigningTeamAnnouncementLink, ...]:
    deduplicated_links: dict[str, TeamSigningTeamAnnouncementLink] = {}
    for link in links:
        deduplicated_links.setdefault(link.url, link)
    return tuple(deduplicated_links.values())


def _team_links_from_announcements(
        announcements: Iterable[SentTeamChangeAnnouncement | None],
) -> tuple[TeamSigningTeamAnnouncementLink, ...]:
    links: list[TeamSigningTeamAnnouncementLink] = []
    for announcement in announcements:
        if not isinstance(announcement, SentTeamChangeAnnouncement):
            continue

        links.append(TeamSigningTeamAnnouncementLink(url=announcement.jump_url))

    return _deduplicate_team_links(links)


def _staff_links_from_announcements(
        *,
        link_specs: Iterable[tuple[discord.Role, discord.Member]],
        announcements: Iterable[SentTeamChangeAnnouncement | None],
) -> tuple[TeamSigningStaffAnnouncementLink, ...]:
    links: list[TeamSigningStaffAnnouncementLink] = []
    for (staff_role, member), announcement in zip(
            link_specs,
            announcements,
            strict=True,
    ):
        if not isinstance(announcement, SentTeamChangeAnnouncement):
            continue

        links.append(
            TeamSigningStaffAnnouncementLink(
                staff_role_name=staff_role.name,
                member_mention=member.mention,
                url=announcement.jump_url,
            )
        )

    return _deduplicate_staff_links(links)


def _deduplicate_staff_links(
        links: Iterable[TeamSigningStaffAnnouncementLink],
) -> tuple[TeamSigningStaffAnnouncementLink, ...]:
    deduplicated_links: dict[str, TeamSigningStaffAnnouncementLink] = {}
    for link in links:
        deduplicated_links.setdefault(link.url, link)
    return tuple(deduplicated_links.values())
