from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Coroutine

import discord

from bigness_league_bot.application.services.tickets import TicketRecord
from bigness_league_bot.infrastructure.discord.ticket_command_mirror import (
    TicketCommandMirror,
)
from bigness_league_bot.infrastructure.discord.ticket_participant_messenger import (
    TicketParticipantMessenger,
)
from bigness_league_bot.infrastructure.discord.ticket_relay_messages import (
    should_relay_bot_thread_message,
)
from bigness_league_bot.infrastructure.discord.ticket_thread_relay import (
    TicketThreadRelay,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.presentation.discord.ticket_ai_interactions import (
    TicketAiInteractions,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

SendDm = Callable[..., Coroutine[Any, Any, discord.Message]]


class TicketMessageRelay:
    def __init__(
            self,
            *,
            bot: BignessLeagueBot,
            store: TicketStateStore,
            thread_relay: TicketThreadRelay,
            participant_messenger: TicketParticipantMessenger,
            command_mirror: TicketCommandMirror,
            ticket_ai_interactions: TicketAiInteractions,
            send_dm: SendDm,
    ) -> None:
        self.bot = bot
        self.store = store
        self.thread_relay = thread_relay
        self.participant_messenger = participant_messenger
        self.command_mirror = command_mirror
        self.ticket_ai_interactions = ticket_ai_interactions
        self._send_dm = send_dm
        self._pending_initial_command_mirror_tasks: dict[int, asyncio.Task[None]] = {}

    async def handle_message(self, message: discord.Message) -> None:
        if message.guild is None:
            if message.author.bot:
                return
            await self._relay_user_dm_to_ticket(message)
            return

        if isinstance(message.channel, discord.Thread):
            if (
                    message.webhook_id is not None
                    and not should_relay_bot_thread_message(message)
            ):
                return
            if message.id in self.thread_relay.message_ids:
                return
            if message.author.bot:
                await self._schedule_initial_bot_thread_message_to_user(message)
                return
            await self._relay_staff_message_to_user(message)

    async def handle_message_edit(
            self,
            after: discord.Message,
    ) -> None:
        if after.guild is None:
            if after.author.bot:
                return
            await self._relay_user_dm_edit_to_ticket(after)
            return

        if not isinstance(after.channel, discord.Thread):
            return
        bot_user = self.bot.user
        if bot_user is None:
            return

        if after.author.id != bot_user.id:
            if after.webhook_id is None and not after.author.bot:
                await self._relay_staff_message_edit_to_user(after)
            return

        pending_initial_task = self._pending_initial_command_mirror_tasks.get(after.id)
        if (
                pending_initial_task is not None
                and not pending_initial_task.done()
                and not self.command_mirror.has_thread_message(after.id)
        ):
            return
        if (
                not self.command_mirror.has_thread_message(after.id)
                and not should_relay_bot_thread_message(after)
        ):
            return

        await self.command_mirror.mirror_thread_command_message_edit(after)

    async def handle_message_delete(self, message: discord.Message) -> None:
        if message.guild is None:
            if message.author.bot:
                return
            await self._mark_deleted_user_dm_in_ticket_thread(message)
            return

        if not isinstance(message.channel, discord.Thread):
            return

        await self._mark_deleted_thread_message_for_participants(message)

    async def _relay_user_dm_to_ticket(self, message: discord.Message) -> None:
        record = self.store.active_for_user(message.author.id)
        if record is None:
            return

        thread = await self._resolve_ticket_thread(record)
        if thread is None:
            self.store.remove_thread(record.thread_id)
            await self._send_dm(
                message.author,
                self.bot.localizer.translate(
                    I18N.messages.tickets.relay.thread_missing_for_user,
                ),
            )
            return

        record = self.store.mark_activity(record.thread_id) or record
        await self.thread_relay.relay_user_message_to_thread(
            record=record,
            thread=thread,
            message=message,
        )
        record = self.store.active_for_thread(record.thread_id) or record
        await self.participant_messenger.relay_user_message_to_other_participants(
            record=record,
            thread=thread,
            message=message,
        )
        await self.ticket_ai_interactions.maybe_auto_reply_to_user_ticket(
            message=message,
            record=record,
            thread=thread,
        )

    async def _relay_user_dm_edit_to_ticket(self, message: discord.Message) -> None:
        record = self.store.active_for_user(message.author.id)
        if record is None:
            return

        thread = await self._resolve_ticket_thread(record)
        if thread is None:
            return

        await self.thread_relay.edit_user_relay_message_in_thread(
            record=record,
            thread=thread,
            message=message,
        )
        await self.participant_messenger.edit_user_message_for_other_participants(
            record=record,
            message=message,
            notification_channel=thread,
        )

    async def _mark_deleted_user_dm_in_ticket_thread(
            self,
            message: discord.Message,
    ) -> None:
        record = self.store.active_for_user(message.author.id)
        if record is None:
            return

        thread = await self._resolve_ticket_thread(record)
        if thread is None:
            return

        await self.thread_relay.mark_user_relay_message_deleted(
            record=record,
            thread=thread,
            message=message,
        )
        await self.participant_messenger.delete_message_for_participants(
            record=record,
            thread=thread,
            source_message_id=message.id,
        )

    async def _relay_staff_message_to_user(self, message: discord.Message) -> None:
        record = self.store.active_for_thread(message.channel.id)
        if record is None:
            return

        record = self.store.mark_activity(record.thread_id) or record
        await self.participant_messenger.relay_staff_message_to_participants(
            record=record,
            message=message,
        )

    async def _relay_staff_message_edit_to_user(self, message: discord.Message) -> None:
        record = self.store.active_for_thread(message.channel.id)
        if record is None:
            return

        await self.participant_messenger.edit_staff_message_for_participants(
            record=record,
            message=message,
        )

    async def _mark_deleted_thread_message_for_participants(
            self,
            message: discord.Message,
    ) -> None:
        thread = message.channel
        if not isinstance(thread, discord.Thread):
            return

        record = self.store.active_for_thread(thread.id)
        if record is None:
            return

        source_dm_message_id = record.dm_message_id_for_thread_relay(message.id)
        if source_dm_message_id is not None:
            await self.participant_messenger.delete_message_for_participants(
                record=record,
                thread=thread,
                source_message_id=source_dm_message_id,
            )
            return

        if self.command_mirror.has_thread_message(message.id):
            await self.command_mirror.delete_thread_command_message_for_participants(message)
            return

        if message.author.bot:
            await self.participant_messenger.delete_message_for_participants(
                record=record,
                thread=thread,
                source_message_id=message.id,
            )
            return

        if message.webhook_id is not None:
            return

        await self.participant_messenger.delete_message_for_participants(
            record=record,
            thread=thread,
            source_message_id=message.id,
        )

    async def _schedule_initial_bot_thread_message_to_user(
            self,
            message: discord.Message,
    ) -> None:
        bot_user = self.bot.user
        if bot_user is None or message.author.id != bot_user.id:
            return
        if not should_relay_bot_thread_message(message):
            return
        if self.command_mirror.has_thread_message(message.id):
            return

        pending_task = self._pending_initial_command_mirror_tasks.get(message.id)
        if pending_task is not None and not pending_task.done():
            return

        task = asyncio.create_task(
            self._mirror_initial_bot_thread_message_to_user(message),
            name=f"ticket-command-relay-{message.id}",
        )
        self._pending_initial_command_mirror_tasks[message.id] = task

    async def _mirror_initial_bot_thread_message_to_user(
            self,
            message: discord.Message,
    ) -> None:
        try:
            await asyncio.sleep(0.75)
            latest_message = await self._fetch_thread_message_snapshot(message)
            await self.command_mirror.mirror_thread_command_message(latest_message)
        except asyncio.CancelledError:
            raise
        finally:
            self._pending_initial_command_mirror_tasks.pop(message.id, None)

    @staticmethod
    async def _fetch_thread_message_snapshot(
            message: discord.Message,
    ) -> discord.Message:
        channel = message.channel
        if not hasattr(channel, "fetch_message"):
            return message

        try:
            return await channel.fetch_message(message.id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return message

    async def _resolve_ticket_thread(
            self,
            record: TicketRecord,
    ) -> discord.Thread | None:
        channel = self.bot.get_channel(record.thread_id)
        if isinstance(channel, discord.Thread):
            return channel

        try:
            fetched_channel = await self.bot.fetch_channel(record.thread_id)
        except discord.HTTPException:
            return None

        if isinstance(fetched_channel, discord.Thread):
            return fetched_channel

        return None
