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
import time
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.tickets import TicketRecord
from bigness_league_bot.infrastructure.discord.ticket_relay_messages import (
    author_avatar_url,
    build_ticket_deleted_user_relay_message,
    build_ticket_user_relay_message,
    clone_message_attachments_as_files,
    thread_relay_display_name,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)
THREAD_RELAY_WEBHOOK_NAME = "Bigness League Tickets Relay"
WEBHOOK_LOOKUP_RETRY_SECONDS = 300.0
WEBHOOK_CREATE_RETRY_SECONDS = 300.0


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
        self._forum_webhook_lookup_retry_after: dict[int, float] = {}
        self._forum_webhook_create_retry_after: dict[int, float] = {}

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

        webhook = await self._get_thread_relay_webhook(thread, allow_existing_lookup=False)
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
            webhook = await self._get_thread_relay_webhook(thread, allow_existing_lookup=True)
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

    async def mark_user_relay_message_deleted(
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

        deleted_content = build_ticket_deleted_user_relay_message(
            localizer=self.bot.localizer,
            message=message,
        )
        if thread_message.webhook_id is not None:
            webhook = await self._get_thread_relay_webhook(thread, allow_existing_lookup=True)
            if webhook is None:
                return
            try:
                await webhook.edit_message(
                    thread_message.id,
                    content=deleted_content,
                    attachments=[],
                    allowed_mentions=discord.AllowedMentions.none(),
                    thread=thread,
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
                LOGGER.exception(
                    "TICKET_THREAD_WEBHOOK_RELAY_DELETE_MARK_FAILED thread=%s user=%s(%s) message=%s",
                    record.thread_id,
                    message.author,
                    message.author.id,
                    thread_message.id,
                )
            return

        try:
            await thread_message.edit(
                content=deleted_content,
                attachments=[],
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            LOGGER.exception(
                "TICKET_THREAD_RELAY_DELETE_MARK_FAILED thread=%s user=%s(%s) message=%s",
                record.thread_id,
                message.author,
                message.author.id,
                thread_message.id,
            )

    @staticmethod
    async def _resolve_thread_reply_target(
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
            *,
            allow_existing_lookup: bool,
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

            if allow_existing_lookup:
                existing_webhook = await self._find_thread_relay_webhook(parent)
                if existing_webhook is not None:
                    self._forum_webhooks[parent.id] = existing_webhook
                    return existing_webhook

            if self._is_webhook_create_on_cooldown(parent.id):
                return None

            try:
                webhook = await parent.create_webhook(
                    name=THREAD_RELAY_WEBHOOK_NAME,
                    reason="Ticket relay webhook",
                )
            except discord.Forbidden:
                LOGGER.exception("TICKET_THREAD_WEBHOOK_CREATE_FORBIDDEN forum=%s", parent.id)
                self._set_webhook_create_cooldown(parent.id)
                return None
            except discord.HTTPException as error:
                self._set_webhook_create_cooldown(parent.id)
                if _is_rate_limited(error):
                    LOGGER.warning(
                        "TICKET_THREAD_WEBHOOK_CREATE_RATE_LIMITED forum=%s retry_seconds=%.0f",
                        parent.id,
                        WEBHOOK_CREATE_RETRY_SECONDS,
                    )
                else:
                    LOGGER.exception("TICKET_THREAD_WEBHOOK_CREATE_FAILED forum=%s", parent.id)
                return None

            self._forum_webhooks[parent.id] = webhook
            return webhook

    async def _find_thread_relay_webhook(
            self,
            parent: discord.ForumChannel,
    ) -> discord.Webhook | None:
        if self._is_webhook_lookup_on_cooldown(parent.id):
            return None

        try:
            existing_webhooks = await parent.webhooks()
        except discord.Forbidden:
            LOGGER.exception("TICKET_THREAD_WEBHOOK_LIST_FORBIDDEN forum=%s", parent.id)
            self._set_webhook_lookup_cooldown(parent.id)
            return None
        except discord.HTTPException as error:
            self._set_webhook_lookup_cooldown(parent.id)
            if _is_rate_limited(error):
                LOGGER.warning(
                    "TICKET_THREAD_WEBHOOK_LIST_RATE_LIMITED forum=%s retry_seconds=%.0f",
                    parent.id,
                    WEBHOOK_LOOKUP_RETRY_SECONDS,
                )
            else:
                LOGGER.exception("TICKET_THREAD_WEBHOOK_LIST_FAILED forum=%s", parent.id)
            return None

        for webhook in existing_webhooks:
            if webhook.name == THREAD_RELAY_WEBHOOK_NAME and webhook.token is not None:
                return webhook
        return None

    def _forum_webhook_lock(self, forum_channel_id: int) -> asyncio.Lock:
        lock = self._forum_webhook_locks.get(forum_channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self._forum_webhook_locks[forum_channel_id] = lock
        return lock

    def _is_webhook_lookup_on_cooldown(self, forum_channel_id: int) -> bool:
        return self._forum_webhook_lookup_retry_after.get(forum_channel_id, 0.0) > time.monotonic()

    def _is_webhook_create_on_cooldown(self, forum_channel_id: int) -> bool:
        return self._forum_webhook_create_retry_after.get(forum_channel_id, 0.0) > time.monotonic()

    def _set_webhook_lookup_cooldown(self, forum_channel_id: int) -> None:
        self._forum_webhook_lookup_retry_after[forum_channel_id] = (
                time.monotonic() + WEBHOOK_LOOKUP_RETRY_SECONDS
        )

    def _set_webhook_create_cooldown(self, forum_channel_id: int) -> None:
        self._forum_webhook_create_retry_after[forum_channel_id] = (
                time.monotonic() + WEBHOOK_CREATE_RETRY_SECONDS
        )


def _message_reference_id(message: discord.Message) -> int | None:
    reference = message.reference
    if reference is None:
        return None

    message_id = reference.message_id
    return message_id if isinstance(message_id, int) else None


def _is_rate_limited(error: discord.HTTPException) -> bool:
    return getattr(error, "status", None) == 429
