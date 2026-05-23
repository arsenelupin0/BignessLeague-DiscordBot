from __future__ import annotations

from collections.abc import Iterable
from time import monotonic
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.infrastructure.discord.team_change_announcements import (
    TeamChangeAnnouncementSpec,
    TEAM_STAFF_ROLE_REMOVAL_SPEC,
    TEAM_STAFF_ROLE_SIGNING_SPEC,
    build_team_role_sheet_metadata_fallback,
)
from bigness_league_bot.infrastructure.discord.team_change_bulletin import (
    create_team_change_repository,
    load_team_change_metadata,
    resolve_team_change_bulletin_channel,
)
from bigness_league_bot.infrastructure.discord.team_role_change_delivery import (
    ANNOUNCEMENT_SUPPRESSION_WINDOW_SECONDS,
    SentTeamChangeAnnouncement,
    TeamChangeAnnouncementDeduplicator,
    TeamRoleChangeAnnouncementSender,
    wait_for_team_change_announcement,
)
from bigness_league_bot.infrastructure.discord.team_signing_messages import (
    TeamSigningStaffAnnouncementLink,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    TeamRoleSheetMetadata,
)

if TYPE_CHECKING:
    from bigness_league_bot.core.settings import Settings
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


async def send_missing_team_change_announcements(
        *,
        settings: Settings,
        guild: discord.Guild,
        bot: BignessLeagueBot,
        team_role: discord.Role,
        members: Iterable[discord.Member],
        spec: TeamChangeAnnouncementSpec,
        failure_log_code: str,
) -> tuple[SentTeamChangeAnnouncement, ...]:
    channel = await resolve_team_change_bulletin_channel(
        guild=guild,
        channel_id=settings.team_role_removal_announcement_channel_id,
    )
    if channel is None:
        return ()

    sender = _create_sender(bot=bot)
    metadata = await _load_metadata(settings=settings, guild=guild, team_role=team_role)
    announcements: list[SentTeamChangeAnnouncement] = []
    for member in members:
        message = await sender.send_team_role_change_announcement(
            member=member,
            team_role=team_role,
            guild=guild,
            metadata=metadata,
            spec=spec,
            channel=channel,
            failure_log_code=failure_log_code,
            ignore_suppression=True,
        )
        if message is None:
            existing_announcement = await _find_recent_announcement(
                guild=guild,
                member=member,
                team_role=team_role,
                spec=spec,
            )
            if existing_announcement is not None:
                announcements.append(existing_announcement)
            continue

        announcements.append(
            _announcement_from_message(
                guild=guild,
                member=member,
                team_role=team_role,
                spec=spec,
                message=message,
            )
        )

    return tuple(announcements)


async def send_missing_staff_signing_announcement_links(
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

    sender = _create_sender(bot=bot)
    metadata = await _load_metadata(settings=settings, guild=guild, team_role=team_role)
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
            existing_announcement = await _find_recent_announcement(
                guild=guild,
                member=member,
                team_role=team_role,
                spec=TEAM_STAFF_ROLE_SIGNING_SPEC,
                staff_role=staff_role,
            )
            if existing_announcement is not None:
                links.append(
                    TeamSigningStaffAnnouncementLink(
                        staff_role_name=staff_role.name,
                        member_mention=member.mention,
                        url=existing_announcement.jump_url,
                    )
                )
            continue

        links.append(
            TeamSigningStaffAnnouncementLink(
                staff_role_name=staff_role.name,
                member_mention=member.mention,
                url=message.jump_url,
            )
        )

    return tuple(links)


async def send_missing_staff_removal_announcements(
        *,
        settings: Settings,
        guild: discord.Guild,
        bot: BignessLeagueBot,
        team_role: discord.Role,
        member: discord.Member,
        staff_roles: Iterable[discord.Role],
) -> tuple[SentTeamChangeAnnouncement, ...]:
    channel = await resolve_team_change_bulletin_channel(
        guild=guild,
        channel_id=settings.team_role_removal_announcement_channel_id,
    )
    if channel is None:
        return ()

    sender = _create_sender(bot=bot)
    metadata = await _load_metadata(settings=settings, guild=guild, team_role=team_role)
    announcements: list[SentTeamChangeAnnouncement] = []
    for staff_role in staff_roles:
        message = await sender.send_staff_role_change_announcement(
            member=member,
            team_role=team_role,
            staff_role=staff_role,
            guild=guild,
            metadata=metadata,
            spec=TEAM_STAFF_ROLE_REMOVAL_SPEC,
            channel=channel,
            ignore_suppression=True,
        )
        if message is None:
            existing_announcement = await _find_recent_announcement(
                guild=guild,
                member=member,
                team_role=team_role,
                spec=TEAM_STAFF_ROLE_REMOVAL_SPEC,
                staff_role=staff_role,
            )
            if existing_announcement is not None:
                announcements.append(existing_announcement)
            continue

        announcements.append(
            _announcement_from_message(
                guild=guild,
                member=member,
                team_role=team_role,
                spec=TEAM_STAFF_ROLE_REMOVAL_SPEC,
                message=message,
                staff_role=staff_role,
            )
        )

    return tuple(announcements)


def _create_sender(
        *,
        bot: BignessLeagueBot,
) -> TeamRoleChangeAnnouncementSender:
    return TeamRoleChangeAnnouncementSender(
        bot=bot,
        deduplicator=TeamChangeAnnouncementDeduplicator(),
    )


async def _load_metadata(
        *,
        settings: Settings,
        guild: discord.Guild,
        team_role: discord.Role,
) -> TeamRoleSheetMetadata:
    repository = await create_team_change_repository(settings, guild=guild)
    return await load_team_change_metadata(
        repository=repository,
        team_role=team_role,
        fallback=build_team_role_sheet_metadata_fallback(team_role),
        guild=guild,
    )


async def _find_recent_announcement(
        *,
        guild: discord.Guild,
        member: discord.Member,
        team_role: discord.Role,
        spec: TeamChangeAnnouncementSpec,
        staff_role: discord.Role | None = None,
) -> SentTeamChangeAnnouncement | None:
    announcement = await wait_for_team_change_announcement(
        guild_id=guild.id,
        member_id=member.id,
        team_role_id=team_role.id,
        spec=spec,
        staff_role_id=staff_role.id if staff_role is not None else None,
        since=monotonic() - ANNOUNCEMENT_SUPPRESSION_WINDOW_SECONDS,
        timeout=0.1,
    )
    if isinstance(announcement, SentTeamChangeAnnouncement):
        return announcement
    return None


def _announcement_from_message(
        *,
        guild: discord.Guild,
        member: discord.Member,
        team_role: discord.Role,
        spec: TeamChangeAnnouncementSpec,
        message: discord.Message,
        staff_role: discord.Role | None = None,
) -> SentTeamChangeAnnouncement:
    return SentTeamChangeAnnouncement(
        guild_id=guild.id,
        member_id=member.id,
        team_role_id=team_role.id,
        spec_key=_resolve_spec_key(spec),
        staff_role_id=staff_role.id if staff_role is not None else None,
        message_id=message.id,
        channel_id=message.channel.id,
        jump_url=message.jump_url,
        created_at=monotonic(),
    )


def _resolve_spec_key(spec: TeamChangeAnnouncementSpec) -> str:
    content_key = spec.content_key
    if isinstance(content_key, str):
        return content_key
    return content_key.key
