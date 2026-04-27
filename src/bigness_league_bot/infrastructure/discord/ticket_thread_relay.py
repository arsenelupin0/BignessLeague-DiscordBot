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
import logging
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.tickets import TicketRecord
from bigness_league_bot.infrastructure.discord.ticket_relay_messages import (
    author_avatar_url,
    build_ticket_user_relay_message,
    clone_message_attachments_as_files,
    thread_relay_display_name,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)
THREAD_RELAY_WEBHOOK_NAME = "Bigness League Tickets Relay"


class TicketThreadRelay:
    def __init__(
            self,
            *,
            bot: BignessLeagueBot,
            store: TicketStateStore,
    ) -> None:
        self.bot = bot
        self.store = store
        self.message_ids: set[int] = set()
        self._message_authors: dict[int, int] = {}
        self._forum_webhooks: dict[int, discord.Webhook] = {}
        self._forum_webhook_locks: dict[int, asyncio.Lock] = {}

    async def relay_user_message_to_thread(
            self,
            *,
            record: TicketRecord,
            thread: discord.Thread,
            message: discord.Message,
    ) -> None:
        reply_target = await self._resolve_thread_reply_target(
            record=record,
            thread=thread,
            message=message,
        )
        if reply_target is not None:
            try:
                relay_message = await reply_target.reply(
                    build_ticket_user_relay_message(
                        localizer=self.bot.localizer,
                        message=message,
                    ),
                    files=await clone_message_attachments_as_files(message),
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                self._remember_user_relay(
                    record=record,
                    source_message=message,
                    relay_message=relay_message,
                )
                return
            except discord.HTTPException:
                LOGGER.exception(
                    "TICKET_THREAD_REPLY_RELAY_FAILED thread=%s user=%s(%s)",
                    record.thread_id,
                    message.author,
                    message.author.id,
                )

        webhook = await self._get_thread_relay_webhook(thread)
        if webhook is None:
            relay_message = await thread.send(
                build_ticket_user_relay_message(
                    localizer=self.bot.localizer,
                    message=message,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            self._remember_user_relay(
                record=record,
                source_message=message,
                relay_message=relay_message,
            )
            return

        files = await clone_message_attachments_as_files(message)
        content = message.content.strip()
        try:
            webhook_message = await webhook.send(
                content=(content if content else discord.utils.MISSING),
                files=(files if files else discord.utils.MISSING),
                username=thread_relay_display_name(thread, message.author),
                avatar_url=author_avatar_url(message.author),
                allowed_mentions=discord.AllowedMentions.none(),
                thread=thread,
                wait=True,
            )
        except (discord.HTTPException, ValueError):
            LOGGER.exception(
                "TICKET_THREAD_WEBHOOK_RELAY_FAILED thread=%s user=%s(%s)",
                record.thread_id,
                message.author,
                message.author.id,
            )
            relay_message = await thread.send(
                build_ticket_user_relay_message(
                    localizer=self.bot.localizer,
                    message=message,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            self._remember_user_relay(
                record=record,
                source_message=message,
                relay_message=relay_message,
            )
            return

        self.message_ids.add(webhook_message.id)
        self._remember_user_relay(
            record=record,
            source_message=message,
            relay_message=webhook_message,
        )

    async def edit_user_relay_message_in_thread(
            self,
            *,
            record: TicketRecord,
            thread: discord.Thread,
            message: discord.Message,
    ) -> None:
        thread_message_id = record.thread_relay_message_id_for_dm(message.id)
        if thread_message_id is None:
            return

        try:
            thread_message = await thread.fetch_message(thread_message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

        content = message.content.strip()
        if thread_message.webhook_id is not None:
            webhook = await self._get_thread_relay_webhook(thread)
            if webhook is None:
                return
            try:
                await webhook.edit_message(
                    thread_message.id,
                    content=(content if content else None),
                    allowed_mentions=discord.AllowedMentions.none(),
                    thread=thread,
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
                LOGGER.exception(
                    "TICKET_THREAD_WEBHOOK_RELAY_EDIT_FAILED thread=%s user=%s(%s) message=%s",
                    record.thread_id,
                    message.author,
                    message.author.id,
                    thread_message.id,
                )
            return

        try:
            await thread_message.edit(
                content=build_ticket_user_relay_message(
                    localizer=self.bot.localizer,
                    message=message,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            LOGGER.exception(
                "TICKET_THREAD_RELAY_EDIT_FAILED thread=%s user=%s(%s) message=%s",
                record.thread_id,
                message.author,
                message.author.id,
                thread_message.id,
            )

    async def _resolve_thread_reply_target(
            self,
            *,
            record: TicketRecord,
            thread: discord.Thread,
            message: discord.Message,
    ) -> discord.Message | None:
        referenced_message_id = _message_reference_id(message)
        if referenced_message_id is None:
            return None

        thread_message_id = record.thread_reply_target_for_dm_reference(
            participant_id=message.author.id,
            referenced_dm_message_id=referenced_message_id,
        )
        if thread_message_id is None:
            return None

        try:
            return await thread.fetch_message(thread_message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    def _remember_user_relay(
            self,
            *,
            record: TicketRecord,
            source_message: discord.Message,
            relay_message: discord.Message,
    ) -> None:
        self._message_authors[relay_message.id] = source_message.author.id
        updated_record = record.with_thread_relay_message_author(
            thread_message_id=relay_message.id,
            user_id=source_message.author.id,
        ).with_dm_thread_relay_message(
            dm_message_id=source_message.id,
            thread_message_id=relay_message.id,
            user_id=source_message.author.id,
        )
        self.store.update(updated_record)

    def relay_clickable_mention(self, message: discord.Message) -> str | None:
        if message.webhook_id is not None:
            original_user_id = self._message_authors.get(message.id)
            if (
                    original_user_id is None
                    and isinstance(message.channel, discord.Thread)
            ):
                record = self.store.active_for_thread(message.channel.id)
                if record is not None:
                    original_user_id = record.relay_message_author_id(message.id)
            if original_user_id is not None:
                return f"<@{original_user_id}>"
            return None
        if isinstance(message.author, (discord.Member, discord.User)):
            return message.author.mention
        return None

    async def _get_thread_relay_webhook(
            self,
            thread: discord.Thread,
    ) -> discord.Webhook | None:
        parent = thread.parent
        if not isinstance(parent, discord.ForumChannel):
            return None

        cached_webhook = self._forum_webhooks.get(parent.id)
        if cached_webhook is not None and cached_webhook.token is not None:
            return cached_webhook

        async with self._forum_webhook_lock(parent.id):
            cached_webhook = self._forum_webhooks.get(parent.id)
            if cached_webhook is not None and cached_webhook.token is not None:
                return cached_webhook

            try:
                existing_webhooks = await parent.webhooks()
            except discord.HTTPException:
                LOGGER.exception(
                    "TICKET_THREAD_WEBHOOK_LIST_FAILED forum=%s",
                    parent.id,
                )
                return None

            for webhook in existing_webhooks:
                if webhook.name != THREAD_RELAY_WEBHOOK_NAME:
                    continue
                try:
                    await webhook.delete(reason="Refreshing ticket relay webhook token")
                except (discord.Forbidden, discord.HTTPException, ValueError):
                    continue

            try:
                webhook = await parent.create_webhook(
                    name=THREAD_RELAY_WEBHOOK_NAME,
                    reason="Ticket relay webhook",
                )
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.exception(
                    "TICKET_THREAD_WEBHOOK_CREATE_FAILED forum=%s",
                    parent.id,
                )
                return None

            self._forum_webhooks[parent.id] = webhook
            return webhook

    def _forum_webhook_lock(self, forum_channel_id: int) -> asyncio.Lock:
        lock = self._forum_webhook_locks.get(forum_channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self._forum_webhook_locks[forum_channel_id] = lock
        return lock


def _message_reference_id(message: discord.Message) -> int | None:
    reference = message.reference
    if reference is None:
        return None

    message_id = reference.message_id
    return message_id if isinstance(message_id, int) else None
