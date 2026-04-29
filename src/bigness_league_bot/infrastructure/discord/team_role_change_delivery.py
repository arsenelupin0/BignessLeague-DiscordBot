from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic
from typing import Any

import discord

from bigness_league_bot.infrastructure.discord.emojis import (
    TEAM_ROLE_REMOVAL_WARNING_EMOJI,
    render_custom_emoji,
)
from bigness_league_bot.infrastructure.discord.team_change_announcements import (
    TeamChangeAnnouncementSpec,
    build_team_change_content,
    build_team_change_embed,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import TeamRoleSheetMetadata

LOGGER = logging.getLogger("bigness_league_bot.activity")
ANNOUNCEMENT_DEDUPLICATION_WINDOW_SECONDS = 3.0
ANNOUNCEMENT_REGISTRY_RETENTION_SECONDS = 30.0
ANNOUNCEMENT_SUPPRESSION_WINDOW_SECONDS = 8.0


@dataclass(frozen=True, slots=True)
class SentTeamChangeAnnouncement:
    guild_id: int
    member_id: int
    team_role_id: int
    spec_key: str
    message_id: int
    channel_id: int
    jump_url: str
    created_at: float
    staff_role_id: int | None = None


_sent_announcements: list[SentTeamChangeAnnouncement] = []
_sent_announcements_condition = asyncio.Condition()
_suppressed_announcement_keys: dict[tuple[object, ...], float] = {}


async def wait_for_team_change_announcement(
        *,
        guild_id: int,
        member_id: int,
        team_role_id: int,
        spec: TeamChangeAnnouncementSpec,
        since: float,
        staff_role_id: int | None = None,
        timeout: float = 3.0,
) -> SentTeamChangeAnnouncement | None:
    spec_key = _resolve_announcement_spec_key(spec)

    async with _sent_announcements_condition:
        found_announcement = _find_sent_announcement(
            guild_id=guild_id,
            member_id=member_id,
            team_role_id=team_role_id,
            spec_key=spec_key,
            staff_role_id=staff_role_id,
            since=since,
        )
        if found_announcement is not None:
            return found_announcement

        try:
            await asyncio.wait_for(
                _sent_announcements_condition.wait_for(
                    lambda: _find_sent_announcement(
                        guild_id=guild_id,
                        member_id=member_id,
                        team_role_id=team_role_id,
                        spec_key=spec_key,
                        staff_role_id=staff_role_id,
                        since=since,
                    ) is not None
                ),
                timeout=timeout,
            )
        except TimeoutError:
            return None

        return _find_sent_announcement(
            guild_id=guild_id,
            member_id=member_id,
            team_role_id=team_role_id,
            spec_key=spec_key,
            staff_role_id=staff_role_id,
            since=since,
        )


def suppress_team_change_announcement(
        *,
        guild_id: int,
        member_id: int,
        team_role_id: int | None,
        spec: TeamChangeAnnouncementSpec,
        staff_role_id: int | None = None,
) -> None:
    current_timestamp = monotonic()
    _prune_suppressed_announcements(current_timestamp)
    _suppressed_announcement_keys[
        (
            guild_id,
            member_id,
            team_role_id,
            _resolve_announcement_spec_key(spec),
            staff_role_id,
        )
    ] = current_timestamp


class TeamChangeAnnouncementDeduplicator:
    def __init__(self) -> None:
        self._recent_announcement_keys: dict[tuple[object, ...], float] = {}

    def reserve(
            self,
            *,
            guild: discord.Guild,
            member: discord.Member,
            team_role: discord.Role,
            spec: TeamChangeAnnouncementSpec,
            staff_role: discord.Role | None = None,
            ignore_suppression: bool = False,
    ) -> tuple[object, ...] | None:
        current_timestamp = monotonic()
        self._prune_recent_announcements(current_timestamp)
        announcement_key = (
            guild.id,
            member.id,
            team_role.id,
            _resolve_announcement_spec_key(spec),
            staff_role.id if staff_role is not None else None,
        )
        previous_timestamp = self._recent_announcement_keys.get(announcement_key)
        if (
                not ignore_suppression
                and _is_announcement_suppressed(announcement_key, current_timestamp)
        ):
            LOGGER.info(
                "TEAM_CHANGE_ANNOUNCEMENT_SUPPRESSED guild=%s(%s) user=%s(%s) team_role=%s(%s) spec=%s staff_role=%s",
                guild.name,
                guild.id,
                member,
                member.id,
                team_role.name,
                team_role.id,
                announcement_key[3],
                (
                    f"{staff_role.name}({staff_role.id})"
                    if staff_role is not None
                    else "-"
                ),
            )
            return None
        if previous_timestamp is not None:
            LOGGER.info(
                "TEAM_CHANGE_ANNOUNCEMENT_DUPLICATE_SKIPPED guild=%s(%s) user=%s(%s) team_role=%s(%s) spec=%s staff_role=%s",
                guild.name,
                guild.id,
                member,
                member.id,
                team_role.name,
                team_role.id,
                announcement_key[3],
                (
                    f"{staff_role.name}({staff_role.id})"
                    if staff_role is not None
                    else "-"
                ),
            )
            return None

        self._recent_announcement_keys[announcement_key] = current_timestamp
        return announcement_key

    def release(self, announcement_key: tuple[object, ...]) -> None:
        self._recent_announcement_keys.pop(announcement_key, None)

    def _prune_recent_announcements(self, current_timestamp: float) -> None:
        stale_keys = tuple(
            announcement_key
            for announcement_key, timestamp in self._recent_announcement_keys.items()
            if current_timestamp - timestamp >= ANNOUNCEMENT_DEDUPLICATION_WINDOW_SECONDS
        )
        for stale_key in stale_keys:
            self._recent_announcement_keys.pop(stale_key, None)


class TeamRoleChangeAnnouncementSender:
    def __init__(
            self,
            *,
            bot: Any,
            deduplicator: TeamChangeAnnouncementDeduplicator,
    ) -> None:
        self.bot = bot
        self.deduplicator = deduplicator

    async def send_team_role_change_announcement(
            self,
            *,
            member: discord.Member,
            team_role: discord.Role,
            guild: discord.Guild,
            metadata: TeamRoleSheetMetadata,
            spec: TeamChangeAnnouncementSpec,
            channel: discord.abc.Messageable,
            failure_log_code: str,
            ignore_suppression: bool = False,
    ) -> discord.Message | None:
        announcement_key = self.deduplicator.reserve(
            guild=guild,
            member=member,
            team_role=team_role,
            spec=spec,
            ignore_suppression=ignore_suppression,
        )
        if announcement_key is None:
            return None

        try:
            message = await self._send_announcement(
                member=member,
                team_role=team_role,
                guild=guild,
                metadata=metadata,
                spec=spec,
                channel=channel,
            )
            await _remember_sent_announcement(
                guild=guild,
                member=member,
                team_role=team_role,
                spec=spec,
                message=message,
            )
            return message
        except (discord.Forbidden, discord.HTTPException) as exc:
            self.deduplicator.release(announcement_key)
            LOGGER.warning(
                "%s guild=%s(%s) user=%s(%s) role=%s(%s) details=%s",
                failure_log_code,
                guild.name,
                guild.id,
                member,
                member.id,
                team_role.name,
                team_role.id,
                exc,
            )
            return None
        except Exception:
            self.deduplicator.release(announcement_key)
            raise

    async def send_staff_role_change_announcement(
            self,
            *,
            member: discord.Member,
            team_role: discord.Role,
            staff_role: discord.Role,
            guild: discord.Guild,
            metadata: TeamRoleSheetMetadata,
            spec: TeamChangeAnnouncementSpec,
            channel: discord.abc.Messageable,
            ignore_suppression: bool = False,
    ) -> discord.Message | None:
        announcement_key = self.deduplicator.reserve(
            guild=guild,
            member=member,
            team_role=team_role,
            spec=spec,
            staff_role=staff_role,
            ignore_suppression=ignore_suppression,
        )
        if announcement_key is None:
            return None

        try:
            message = await self._send_announcement(
                member=member,
                team_role=team_role,
                guild=guild,
                metadata=metadata,
                spec=spec,
                channel=channel,
                staff_role_name=staff_role.name,
            )
            await _remember_sent_announcement(
                guild=guild,
                member=member,
                team_role=team_role,
                spec=spec,
                message=message,
                staff_role=staff_role,
            )
            return message
        except (discord.Forbidden, discord.HTTPException) as exc:
            self.deduplicator.release(announcement_key)
            LOGGER.warning(
                "TEAM_STAFF_ROLE_ANNOUNCEMENT_SEND_FAILED guild=%s(%s) user=%s(%s) team_role=%s(%s) staff_role=%s(%s) details=%s",
                guild.name,
                guild.id,
                member,
                member.id,
                team_role.name,
                team_role.id,
                staff_role.name,
                staff_role.id,
                exc,
            )
            return None
        except Exception:
            self.deduplicator.release(announcement_key)
            raise

    async def _send_announcement(
            self,
            *,
            member: discord.Member,
            team_role: discord.Role,
            guild: discord.Guild,
            metadata: TeamRoleSheetMetadata,
            spec: TeamChangeAnnouncementSpec,
            channel: discord.abc.Messageable,
            staff_role_name: str | None = None,
    ) -> discord.Message:
        content = build_team_change_content(
            bot=self.bot,
            spec=spec,
            member=member,
            team_role=team_role,
            staff_role_name=staff_role_name,
        )
        embed, image_file = build_team_change_embed(
            bot=self.bot,
            spec=spec,
            member=member,
            team_role=team_role,
            guild=guild,
            metadata=metadata,
            description=_build_role_removal_description(guild=guild, bot=self.bot),
        )
        allowed_mentions = discord.AllowedMentions(
            everyone=False,
            replied_user=False,
            users=[member],
            roles=[team_role],
        )
        send_kwargs: dict[str, object] = {
            "content": content,
            "embed": embed,
            "allowed_mentions": allowed_mentions,
        }
        if image_file is not None:
            send_kwargs["file"] = image_file
        return await channel.send(**send_kwargs)


async def _remember_sent_announcement(
        *,
        guild: discord.Guild,
        member: discord.Member,
        team_role: discord.Role,
        spec: TeamChangeAnnouncementSpec,
        message: discord.Message,
        staff_role: discord.Role | None = None,
) -> None:
    current_timestamp = monotonic()
    announcement = SentTeamChangeAnnouncement(
        guild_id=guild.id,
        member_id=member.id,
        team_role_id=team_role.id,
        spec_key=_resolve_announcement_spec_key(spec),
        staff_role_id=staff_role.id if staff_role is not None else None,
        message_id=message.id,
        channel_id=message.channel.id,
        jump_url=message.jump_url,
        created_at=current_timestamp,
    )
    async with _sent_announcements_condition:
        _prune_sent_announcements(current_timestamp)
        _sent_announcements.append(announcement)
        _sent_announcements_condition.notify_all()


def _find_sent_announcement(
        *,
        guild_id: int,
        member_id: int,
        team_role_id: int,
        spec_key: str,
        staff_role_id: int | None,
        since: float,
) -> SentTeamChangeAnnouncement | None:
    for announcement in reversed(_sent_announcements):
        if announcement.created_at < since:
            continue
        if (
                announcement.guild_id == guild_id
                and announcement.member_id == member_id
                and announcement.team_role_id == team_role_id
                and announcement.spec_key == spec_key
                and announcement.staff_role_id == staff_role_id
        ):
            return announcement
    return None


def _prune_sent_announcements(current_timestamp: float) -> None:
    retained_announcements = [
        announcement
        for announcement in _sent_announcements
        if current_timestamp - announcement.created_at < ANNOUNCEMENT_REGISTRY_RETENTION_SECONDS
    ]
    _sent_announcements[:] = retained_announcements


def _is_announcement_suppressed(
        announcement_key: tuple[object, ...],
        current_timestamp: float,
) -> bool:
    _prune_suppressed_announcements(current_timestamp)
    if announcement_key in _suppressed_announcement_keys:
        return True

    guild_id, member_id, _, spec_key, staff_role_id = announcement_key
    wildcard_team_key = (guild_id, member_id, None, spec_key, staff_role_id)
    return wildcard_team_key in _suppressed_announcement_keys


def _prune_suppressed_announcements(current_timestamp: float) -> None:
    stale_keys = tuple(
        announcement_key
        for announcement_key, timestamp in _suppressed_announcement_keys.items()
        if current_timestamp - timestamp >= ANNOUNCEMENT_SUPPRESSION_WINDOW_SECONDS
    )
    for stale_key in stale_keys:
        _suppressed_announcement_keys.pop(stale_key, None)


def _build_role_removal_description(*, guild: discord.Guild, bot: Any) -> str:
    warning_emoji = render_custom_emoji(
        guild=guild,
        bot=bot,
        emoji=TEAM_ROLE_REMOVAL_WARNING_EMOJI,
    )
    return (
        "# "
        f"{warning_emoji} {warning_emoji} {warning_emoji} {warning_emoji}"
    )


def _resolve_announcement_spec_key(spec: TeamChangeAnnouncementSpec) -> str:
    content_key = spec.content_key
    if isinstance(content_key, str):
        return content_key

    return content_key.key
