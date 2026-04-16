#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import discord
import unicodedata

from bigness_league_bot.application.services.tickets import (
    TicketCategory,
    TicketRecord,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)
TICKET_STATE_VERSION = 1


class TicketIntegrationError(CommandUserError):
    """Raised when the ticket integration cannot complete an expected operation."""


class TicketStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.creation_lock = asyncio.Lock()
        self._records: dict[int, TicketRecord] = self._load_records()

    def next_ticket_number(self) -> int:
        if not self._records:
            return 1

        return max(record.ticket_number for record in self._records.values()) + 1

    def active_for_user(self, user_id: int) -> TicketRecord | None:
        active_records = [
            record
            for record in self._records.values()
            if record.user_id == user_id and record.status == "active"
        ]
        if not active_records:
            return None

        return max(active_records, key=lambda record: record.created_at)

    def active_for_thread(self, thread_id: int) -> TicketRecord | None:
        record = self._records.get(thread_id)
        if record is None or record.status != "active":
            return None

        return record

    def add(self, record: TicketRecord) -> None:
        self._records[record.thread_id] = record
        self._save_records()

    def close_thread(self, thread_id: int) -> TicketRecord | None:
        record = self._records.get(thread_id)
        if record is None:
            return None

        closed_record = record.close()
        self._records[thread_id] = closed_record
        self._save_records()
        return closed_record

    def remove_thread(self, thread_id: int) -> TicketRecord | None:
        record = self._records.pop(thread_id, None)
        if record is None:
            return None

        self._save_records()
        return record

    def _load_records(self) -> dict[int, TicketRecord]:
        if not self.path.exists():
            return {}

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.exception("TICKET_STATE_LOAD_FAILED path=%s", self.path)
            return {}

        raw_tickets = payload.get("tickets", [])
        if not isinstance(raw_tickets, list):
            LOGGER.warning("TICKET_STATE_INVALID path=%s reason=tickets_not_list", self.path)
            return {}

        records: dict[int, TicketRecord] = {}
        for index, raw_ticket in enumerate(raw_tickets, start=1):
            if not isinstance(raw_ticket, dict):
                continue

            try:
                record = TicketRecord.from_dict(
                    raw_ticket,
                    fallback_ticket_number=index,
                )
            except (KeyError, TypeError, ValueError):
                LOGGER.warning("TICKET_STATE_RECORD_INVALID payload=%r", raw_ticket)
                continue

            records[record.thread_id] = record

        return records

    def _save_records(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": TICKET_STATE_VERSION,
            "tickets": [
                record.to_dict()
                for record in sorted(
                    self._records.values(),
                    key=lambda ticket: ticket.created_at,
                )
            ],
        }
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.path)


def _normalized_label(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.casefold().split())


def _slugify(value: str, *, fallback: str) -> str:
    normalized = _normalized_label(value)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or fallback


def build_ticket_thread_name(
        *,
        member: discord.abc.User,
        category: TicketCategory,
) -> str:
    display_name = getattr(member, "display_name", None) or member.name
    user_slug = _slugify(display_name, fallback=f"usuario-{member.id}")
    suffix = str(member.id)[-4:]
    return f"{category.thread_prefix}-{user_slug[:32]}-{suffix}"[:100]


def resolve_forum_tag(
        forum_channel: discord.ForumChannel,
        category: TicketCategory,
) -> discord.ForumTag:
    expected_labels = {
        _normalized_label(category.tag_name),
        _normalized_label(category.label),
    }
    for tag in forum_channel.available_tags:
        if _normalized_label(tag.name) in expected_labels:
            return tag

    raise TicketIntegrationError(
        localize(
            I18N.errors.tickets.forum_tag_missing,
            tag_name=category.tag_name,
            forum_name=forum_channel.name,
        )
    )


async def resolve_ticket_forum_channel(
        bot: BignessLeagueBot,
        guild: discord.Guild,
) -> discord.ForumChannel:
    channel_id = bot.settings.ticket_forum_channel_id
    if channel_id is None:
        raise TicketIntegrationError(
            localize(I18N.errors.tickets.forum_channel_not_configured)
        )

    channel = guild.get_channel(channel_id)
    if channel is None:
        try:
            fetched_channel = await bot.fetch_channel(channel_id)
        except discord.NotFound as exc:
            raise TicketIntegrationError(
                localize(
                    I18N.errors.tickets.forum_channel_not_found,
                    channel_id=str(channel_id),
                )
            ) from exc

        channel = fetched_channel if isinstance(fetched_channel, discord.abc.GuildChannel) else None

    if not isinstance(channel, discord.abc.GuildChannel) or channel.guild.id != guild.id:
        raise TicketIntegrationError(
            localize(
                I18N.errors.tickets.forum_channel_not_in_guild,
                channel_id=str(channel_id),
            )
        )

    if not isinstance(channel, discord.ForumChannel):
        raise TicketIntegrationError(
            localize(
                I18N.errors.tickets.forum_channel_invalid_type,
                channel_id=str(channel_id),
            )
        )

    return channel
