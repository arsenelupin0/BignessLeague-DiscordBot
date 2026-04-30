from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.infrastructure.discord.team_change_announcements import (
    TEAM_PLAYER_ROLE_REMOVAL_SPEC,
    TEAM_ROLE_REMOVAL_SPEC,
    TEAM_ROLE_SIGNING_SPEC,
    TEAM_STAFF_ROLE_REMOVAL_SPEC,
    TEAM_STAFF_ROLE_SIGNING_SPEC,
    build_team_role_sheet_metadata_fallback,
)
from bigness_league_bot.infrastructure.discord.team_change_bulletin import (
    create_team_change_repository,
    load_team_change_metadata,
    resolve_team_change_bulletin_channel,
)
from bigness_league_bot.infrastructure.discord.team_member_lookup import (
    build_member_lookup_keys,
    normalize_member_lookup_text,
)
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    TeamStaffRoleEntry,
)
from bigness_league_bot.infrastructure.discord.team_role_change_delivery import (
    SentTeamChangeAnnouncement,
    TeamChangeAnnouncementDeduplicator,
    TeamRoleChangeAnnouncementSender,
    wait_for_team_change_announcement,
)
from bigness_league_bot.infrastructure.discord.team_signing_messages import (
    PlayerRemovalAnnouncementLink,
    StaffRemovalAnnouncementLink,
    TeamRemovalAnnouncementLink,
    TeamSigningStaffAnnouncementLink,
    TeamSigningTeamAnnouncementLink,
)
from bigness_league_bot.infrastructure.discord.team_signing_visibility_links import (
    deduplicate_staff_links,
    deduplicate_team_links,
    player_removal_links_from_announcements,
    staff_links_from_announcements,
    staff_removal_links_from_announcements,
    staff_sync_removal_links_from_announcements,
    team_links_from_announcements,
    team_removal_links_from_announcements,
)
from bigness_league_bot.infrastructure.discord.team_staff_roles import (
    resolve_team_staff_role_by_name,
)

if TYPE_CHECKING:
    from bigness_league_bot.application.services.team_signing import (
        TeamTechnicalStaffBatch,
    )
    from bigness_league_bot.core.settings import Settings
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot
    from bigness_league_bot.infrastructure.discord.team_role_assignment import (
        TeamRoleAssignmentSummary,
        TeamRoleRemovalSummary,
        TeamStaffRoleSyncSummary,
    )
    from bigness_league_bot.infrastructure.google.team_sheet_repository import (
        TeamSigningRemovalResult,
    )

DISCORD_MEMBER_REFERENCE_PATTERN = re.compile(r"^<@!?(\d+)>$|^(\d{15,20})$")


@dataclass(frozen=True, slots=True)
class TeamSigningVisibilityLinks:
    team_links: tuple[TeamSigningTeamAnnouncementLink, ...]
    staff_links: tuple[TeamSigningStaffAnnouncementLink, ...]
    staff_removal_links: tuple[StaffRemovalAnnouncementLink, ...] = ()


@dataclass(frozen=True, slots=True)
class TeamSigningRemovalVisibilityLinks:
    team_links: tuple[TeamRemovalAnnouncementLink, ...]
    player_links: tuple[PlayerRemovalAnnouncementLink, ...]
    staff_links: tuple[StaffRemovalAnnouncementLink, ...]


async def collect_team_signing_visibility_links(
        *,
        settings: Settings,
        guild: discord.Guild,
        bot: BignessLeagueBot,
        team_role: discord.Role,
        assignment_summary: TeamRoleAssignmentSummary | None,
        technical_staff_batch: TeamTechnicalStaffBatch | None,
        staff_sync_summary: TeamStaffRoleSyncSummary | None,
        since: float,
) -> TeamSigningVisibilityLinks:
    team_links, staff_team_links, staff_links, staff_removal_links = await asyncio.gather(
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
            bot=bot,
            team_role=team_role,
            technical_staff_batch=technical_staff_batch,
            staff_sync_summary=staff_sync_summary,
            since=since,
        ),
        _collect_staff_sync_removal_announcement_links(
            settings=settings,
            guild=guild,
            team_role=team_role,
            staff_sync_summary=staff_sync_summary,
            since=since,
        ),
    )
    return TeamSigningVisibilityLinks(
        team_links=deduplicate_team_links((*team_links, *staff_team_links)),
        staff_links=staff_links,
        staff_removal_links=staff_removal_links,
    )


async def collect_team_signing_removal_visibility_links(
        *,
        settings: Settings,
        guild: discord.Guild,
        team_role: discord.Role,
        player_role: discord.Role,
        result: TeamSigningRemovalResult,
        removal_summary: TeamRoleRemovalSummary | None,
        since: float,
) -> TeamSigningRemovalVisibilityLinks:
    if removal_summary is None or removal_summary.member is None:
        return TeamSigningRemovalVisibilityLinks(
            team_links=(),
            player_links=(),
            staff_links=(),
        )

    member = removal_summary.member
    removed_role_ids = {role.id for role in removal_summary.removed_roles}
    if team_role.id in removed_role_ids:
        announcement = await wait_for_team_change_announcement(
            guild_id=guild.id,
            member_id=member.id,
            team_role_id=team_role.id,
            spec=TEAM_ROLE_REMOVAL_SPEC,
            since=since,
        )
        return TeamSigningRemovalVisibilityLinks(
            team_links=team_removal_links_from_announcements((announcement,)),
            player_links=(),
            staff_links=(),
        )

    player_links: tuple[PlayerRemovalAnnouncementLink, ...] = ()
    if result.removed_player_name is not None and player_role.id in removed_role_ids:
        announcement = await wait_for_team_change_announcement(
            guild_id=guild.id,
            member_id=member.id,
            team_role_id=team_role.id,
            spec=TEAM_PLAYER_ROLE_REMOVAL_SPEC,
            since=since,
        )
        player_links = player_removal_links_from_announcements(
            member=member,
            announcements=(announcement,),
        )

    staff_links = await _collect_staff_removal_announcement_links(
        settings=settings,
        guild=guild,
        team_role=team_role,
        member=member,
        removed_role_ids=removed_role_ids,
        removed_staff_role_names=result.removed_staff_role_names,
        since=since,
    )
    return TeamSigningRemovalVisibilityLinks(
        team_links=(),
        player_links=player_links,
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
    return team_links_from_announcements(announcements)


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
    return team_links_from_announcements(announcements)


async def _collect_staff_announcement_links(
        *,
        settings: Settings,
        guild: discord.Guild,
        bot: BignessLeagueBot,
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
    staff_entries = staff_sync_summary.assigned_staff_entries
    if not staff_entries:
        staff_entries = tuple(
            TeamStaffRoleEntry(
                role_name=member.role_name,
                member_name=member.discord_name,
            )
            for member in technical_staff_batch.members
        )

    for staff_member in staff_entries:
        member = _resolve_synced_member(
            staff_member.member_name,
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
    links = list(staff_links_from_announcements(
        link_specs=link_specs,
        announcements=announcements,
    ))
    missing_link_specs = tuple(
        link_spec
        for link_spec, announcement in zip(link_specs, announcements, strict=True)
        if not isinstance(announcement, SentTeamChangeAnnouncement)
    )
    if missing_link_specs:
        links.extend(
            await _send_missing_staff_signing_announcements(
                settings=settings,
                guild=guild,
                bot=bot,
                team_role=team_role,
                link_specs=missing_link_specs,
            )
        )

    return deduplicate_staff_links(links)


async def _send_missing_staff_signing_announcements(
        *,
        settings: Settings,
        guild: discord.Guild,
        bot: BignessLeagueBot,
        team_role: discord.Role,
        link_specs: Iterable[tuple[discord.Role, discord.Member]],
) -> tuple[TeamSigningStaffAnnouncementLink, ...]:
    channel = await resolve_team_change_bulletin_channel(
        guild=guild,
        channel_id=settings.team_role_removal_announcement_channel_id,
    )
    if channel is None:
        return ()

    repository = await create_team_change_repository(settings, guild=guild)
    metadata = await load_team_change_metadata(
        repository=repository,
        team_role=team_role,
        fallback=build_team_role_sheet_metadata_fallback(team_role),
        guild=guild,
    )
    sender = TeamRoleChangeAnnouncementSender(
        bot=bot,
        deduplicator=TeamChangeAnnouncementDeduplicator(),
    )
    links: list[TeamSigningStaffAnnouncementLink] = []
    for staff_role, member in link_specs:
        message = await sender.send_staff_role_change_announcement(
            member=member,
            team_role=team_role,
            staff_role=staff_role,
            guild=guild,
            metadata=metadata,
            spec=TEAM_STAFF_ROLE_SIGNING_SPEC,
            channel=channel,
            ignore_suppression=True,
        )
        if message is None:
            continue

        links.append(
            TeamSigningStaffAnnouncementLink(
                staff_role_name=staff_role.name,
                member_mention=member.mention,
                url=message.jump_url,
            )
        )

    return tuple(links)


async def _collect_staff_removal_announcement_links(
        *,
        settings: Settings,
        guild: discord.Guild,
        team_role: discord.Role,
        member: discord.Member,
        removed_role_ids: set[int],
        removed_staff_role_names: Iterable[str],
        since: float,
) -> tuple[StaffRemovalAnnouncementLink, ...]:
    tasks: list[Awaitable[SentTeamChangeAnnouncement | None]] = []
    link_specs: list[discord.Role] = []
    for staff_role_name in removed_staff_role_names:
        staff_role = resolve_team_staff_role_by_name(
            guild,
            role_name=staff_role_name,
            ceo_role_id=settings.staff_ceo_role_id,
            analyst_role_id=settings.staff_analyst_role_id,
            coach_role_id=settings.staff_coach_role_id,
            manager_role_id=settings.staff_manager_role_id,
            second_manager_role_id=settings.staff_second_manager_role_id,
            captain_role_id=settings.staff_captain_role_id,
        )
        if staff_role is None or staff_role.id not in removed_role_ids:
            continue

        link_specs.append(staff_role)
        tasks.append(
            wait_for_team_change_announcement(
                guild_id=guild.id,
                member_id=member.id,
                team_role_id=team_role.id,
                spec=TEAM_STAFF_ROLE_REMOVAL_SPEC,
                staff_role_id=staff_role.id,
                since=since,
            )
        )

    if not tasks:
        return ()

    announcements = await asyncio.gather(*tasks)
    return staff_removal_links_from_announcements(
        member=member,
        link_specs=link_specs,
        announcements=announcements,
    )


async def _collect_staff_sync_removal_announcement_links(
        *,
        settings: Settings,
        guild: discord.Guild,
        team_role: discord.Role,
        staff_sync_summary: TeamStaffRoleSyncSummary | None,
        since: float,
) -> tuple[StaffRemovalAnnouncementLink, ...]:
    if (
            staff_sync_summary is None
            or not staff_sync_summary.removed_members
            or not staff_sync_summary.removed_staff_entries
    ):
        return ()

    tasks: list[Awaitable[SentTeamChangeAnnouncement | None]] = []
    link_specs: list[tuple[discord.Role, discord.Member]] = []
    for entry in staff_sync_summary.removed_staff_entries:
        member = _resolve_synced_member(
            entry.member_name,
            staff_sync_summary.removed_members,
        )
        if member is None:
            continue

        staff_role = resolve_team_staff_role_by_name(
            guild,
            role_name=entry.role_name,
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
                spec=TEAM_STAFF_ROLE_REMOVAL_SPEC,
                staff_role_id=staff_role.id,
                since=since,
            )
        )

    if not tasks:
        return ()

    announcements = await asyncio.gather(*tasks)
    return staff_sync_removal_links_from_announcements(
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
