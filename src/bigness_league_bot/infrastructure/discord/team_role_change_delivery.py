from __future__ import annotations

import logging
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
    ) -> None:
        announcement_key = self.deduplicator.reserve(
            guild=guild,
            member=member,
            team_role=team_role,
            spec=spec,
        )
        if announcement_key is None:
            return

        try:
            await self._send_announcement(
                member=member,
                team_role=team_role,
                guild=guild,
                metadata=metadata,
                spec=spec,
                channel=channel,
            )
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
    ) -> None:
        announcement_key = self.deduplicator.reserve(
            guild=guild,
            member=member,
            team_role=team_role,
            spec=spec,
            staff_role=staff_role,
        )
        if announcement_key is None:
            return

        try:
            await self._send_announcement(
                member=member,
                team_role=team_role,
                guild=guild,
                metadata=metadata,
                spec=spec,
                channel=channel,
                staff_role_name=staff_role.name,
            )
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
    ) -> None:
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
        await channel.send(**send_kwargs)


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
