from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord.ext import tasks

from bigness_league_bot.application.services.tickets import (
    TicketRecord,
    current_utc_timestamp,
    parse_utc_timestamp,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.presentation.discord.ticket_thread_closure import (
    close_ticket_thread,
)
from bigness_league_bot.presentation.discord.views.ticket_message_embeds import (
    build_ticket_inactivity_embed,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)

TICKET_INACTIVITY_NOTICE_INTERVAL = timedelta(hours=8)
TICKET_INACTIVITY_NOTICE_MAX_COUNT = 5
TICKET_INACTIVITY_CHECK_SECONDS = 300


class TicketInactivityMonitor:
    def __init__(
            self,
            *,
            bot: BignessLeagueBot,
            store: TicketStateStore,
    ) -> None:
        self.bot = bot
        self.store = store

    def start(self) -> None:
        if not self._check_inactive_tickets.is_running():
            self._check_inactive_tickets.start()

    def stop(self) -> None:
        self._check_inactive_tickets.cancel()

    @tasks.loop(seconds=TICKET_INACTIVITY_CHECK_SECONDS)
    async def _check_inactive_tickets(self) -> None:
        now = parse_utc_timestamp(current_utc_timestamp())
        for record in self.store.active_records():
            last_activity_at = record.last_activity_at or record.created_at
            if now - parse_utc_timestamp(last_activity_at) < TICKET_INACTIVITY_NOTICE_INTERVAL:
                continue

            await self._send_notice_or_close(record)

    @_check_inactive_tickets.before_loop
    async def _before_check_inactive_tickets(self) -> None:
        await self.bot.wait_until_ready()

    async def _send_notice_or_close(self, record: TicketRecord) -> None:
        thread = await self._resolve_ticket_thread(record)
        if thread is None:
            self.store.remove_thread(record.thread_id)
            return

        if record.inactivity_notice_count >= TICKET_INACTIVITY_NOTICE_MAX_COUNT:
            await self._close_for_inactivity(record, thread)
            return

        notice_number = record.inactivity_notice_count + 1
        sent_at = current_utc_timestamp()
        inactivity_embed = build_ticket_inactivity_embed(
            bot=self.bot,
            locale=None,
            guild=thread.guild,
            notice_number=notice_number,
            inactive_hours=int(TICKET_INACTIVITY_NOTICE_INTERVAL.total_seconds() // 3600),
            sent_at=sent_at,
        )
        notice_sent = await self._send_inactivity_notice(record, thread, inactivity_embed)
        if not notice_sent:
            return

        updated_record = self.store.active_for_thread(record.thread_id)
        if updated_record is None:
            return

        updated_record = updated_record.mark_inactivity_notice(sent_at=sent_at)
        self.store.update(updated_record)
        if notice_number >= TICKET_INACTIVITY_NOTICE_MAX_COUNT:
            await self._close_for_inactivity(updated_record, thread)

    async def _send_inactivity_notice(
            self,
            record: TicketRecord,
            thread: discord.Thread,
            inactivity_embed: discord.Embed,
    ) -> bool:
        try:
            await thread.send(
                embed=inactivity_embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            LOGGER.exception("TICKET_INACTIVITY_THREAD_NOTICE_FAILED thread=%s", thread.id)
            return False

        for participant in record.participants:
            try:
                ticket_user = await self.bot.fetch_user(participant.user_id)
                await ticket_user.send(embed=inactivity_embed)
            except discord.HTTPException:
                LOGGER.warning(
                    "TICKET_INACTIVITY_DM_NOTICE_FAILED ticket=%s user=%s",
                    record.thread_id,
                    participant.user_id,
                )
        return True

    async def _close_for_inactivity(
            self,
            record: TicketRecord,
            thread: discord.Thread,
    ) -> None:
        bot_user = self.bot.user
        if bot_user is None:
            return

        try:
            await close_ticket_thread(
                bot=self.bot,
                store=self.store,
                thread=thread,
                record=record,
                closed_by=bot_user,
                locale=None,
                close_reason=self.bot.localizer.translate(
                    I18N.messages.tickets.inactivity.close_reason,
                ),
            )
        except discord.HTTPException:
            LOGGER.exception("TICKET_INACTIVITY_CLOSE_FAILED thread=%s", thread.id)

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
