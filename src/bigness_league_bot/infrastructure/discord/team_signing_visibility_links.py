from __future__ import annotations

from collections.abc import Iterable

import discord

from bigness_league_bot.infrastructure.discord.team_role_change_delivery import (
    SentTeamChangeAnnouncement,
)
from bigness_league_bot.infrastructure.discord.team_signing_messages import (
    PlayerRemovalAnnouncementLink,
    StaffRemovalAnnouncementLink,
    TeamRemovalAnnouncementLink,
    TeamSigningStaffAnnouncementLink,
    TeamSigningTeamAnnouncementLink,
)


def deduplicate_team_links(
        links: Iterable[TeamSigningTeamAnnouncementLink],
) -> tuple[TeamSigningTeamAnnouncementLink, ...]:
    deduplicated_links: dict[str, TeamSigningTeamAnnouncementLink] = {}
    for link in links:
        deduplicated_links.setdefault(link.url, link)
    return tuple(deduplicated_links.values())


def team_links_from_announcements(
        announcements: Iterable[SentTeamChangeAnnouncement | None],
) -> tuple[TeamSigningTeamAnnouncementLink, ...]:
    links: list[TeamSigningTeamAnnouncementLink] = []
    for announcement in announcements:
        if not isinstance(announcement, SentTeamChangeAnnouncement):
            continue

        links.append(TeamSigningTeamAnnouncementLink(url=announcement.jump_url))

    return deduplicate_team_links(links)


def staff_links_from_announcements(
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

    return deduplicate_staff_links(links)


def team_removal_links_from_announcements(
        announcements: Iterable[SentTeamChangeAnnouncement | None],
) -> tuple[TeamRemovalAnnouncementLink, ...]:
    links: list[TeamRemovalAnnouncementLink] = []
    for announcement in announcements:
        if not isinstance(announcement, SentTeamChangeAnnouncement):
            continue

        links.append(TeamRemovalAnnouncementLink(url=announcement.jump_url))

    return deduplicate_team_removal_links(links)


def player_removal_links_from_announcements(
        *,
        member: discord.Member,
        announcements: Iterable[SentTeamChangeAnnouncement | None],
) -> tuple[PlayerRemovalAnnouncementLink, ...]:
    links: list[PlayerRemovalAnnouncementLink] = []
    for announcement in announcements:
        if not isinstance(announcement, SentTeamChangeAnnouncement):
            continue

        links.append(
            PlayerRemovalAnnouncementLink(
                member_mention=member.mention,
                url=announcement.jump_url,
            )
        )

    return deduplicate_player_removal_links(links)


def staff_removal_links_from_announcements(
        *,
        member: discord.Member,
        link_specs: Iterable[discord.Role],
        announcements: Iterable[SentTeamChangeAnnouncement | None],
) -> tuple[StaffRemovalAnnouncementLink, ...]:
    links: list[StaffRemovalAnnouncementLink] = []
    for staff_role, announcement in zip(link_specs, announcements, strict=True):
        if not isinstance(announcement, SentTeamChangeAnnouncement):
            continue

        links.append(
            StaffRemovalAnnouncementLink(
                staff_role_name=staff_role.name,
                member_mention=member.mention,
                url=announcement.jump_url,
            )
        )

    return deduplicate_staff_removal_links(links)


def staff_sync_removal_links_from_announcements(
        *,
        link_specs: Iterable[tuple[discord.Role, discord.Member]],
        announcements: Iterable[SentTeamChangeAnnouncement | None],
) -> tuple[StaffRemovalAnnouncementLink, ...]:
    links: list[StaffRemovalAnnouncementLink] = []
    for (staff_role, member), announcement in zip(
            link_specs,
            announcements,
            strict=True,
    ):
        if not isinstance(announcement, SentTeamChangeAnnouncement):
            continue

        links.append(
            StaffRemovalAnnouncementLink(
                staff_role_name=staff_role.name,
                member_mention=member.mention,
                url=announcement.jump_url,
            )
        )

    return deduplicate_staff_removal_links(links)


def deduplicate_staff_links(
        links: Iterable[TeamSigningStaffAnnouncementLink],
) -> tuple[TeamSigningStaffAnnouncementLink, ...]:
    deduplicated_links: dict[str, TeamSigningStaffAnnouncementLink] = {}
    for link in links:
        deduplicated_links.setdefault(link.url, link)
    return tuple(deduplicated_links.values())


def deduplicate_team_removal_links(
        links: Iterable[TeamRemovalAnnouncementLink],
) -> tuple[TeamRemovalAnnouncementLink, ...]:
    deduplicated_links: dict[str, TeamRemovalAnnouncementLink] = {}
    for link in links:
        deduplicated_links.setdefault(link.url, link)
    return tuple(deduplicated_links.values())


def deduplicate_player_removal_links(
        links: Iterable[PlayerRemovalAnnouncementLink],
) -> tuple[PlayerRemovalAnnouncementLink, ...]:
    deduplicated_links: dict[str, PlayerRemovalAnnouncementLink] = {}
    for link in links:
        deduplicated_links.setdefault(link.url, link)
    return tuple(deduplicated_links.values())


def deduplicate_staff_removal_links(
        links: Iterable[StaffRemovalAnnouncementLink],
) -> tuple[StaffRemovalAnnouncementLink, ...]:
    deduplicated_links: dict[str, StaffRemovalAnnouncementLink] = {}
    for link in links:
        deduplicated_links.setdefault(link.url, link)
    return tuple(deduplicated_links.values())
