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

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.tickets import TicketRecord
from bigness_league_bot.infrastructure.discord.ticket_command_mirror import (
    TicketCommandMirror,
)
from bigness_league_bot.infrastructure.discord.ticket_relay_messages import (
    PARTICIPANT_DM_RELAY_COLOR,
    STAFF_DM_RELAY_COLOR,
    author_avatar_url,
    build_ticket_dm_relay_embed,
    clone_message_attachments_as_files,
    looks_like_user_relay_message,
    relay_visual_username,
    should_relay_bot_thread_message,
    truncate_relay_text,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)
ResolveTicketUser = Callable[[int], Awaitable[discord.User | None]]
SendDm = Callable[..., Awaitable[discord.Message]]
RelayMention = Callable[[discord.Message], str | None]


class TicketParticipantMessenger:
    def __init__(
            self,
            *,
            bot: BignessLeagueBot,
            command_mirror: TicketCommandMirror,
            resolve_ticket_user: ResolveTicketUser,
            send_dm: SendDm,
            relay_mention: RelayMention,
    ) -> None:
        self.bot = bot
        self.command_mirror = command_mirror
        self._resolve_ticket_user = resolve_ticket_user
        self._send_dm = send_dm
        self._relay_mention = relay_mention

    async def relay_staff_message_to_participants(
            self,
            *,
            record: TicketRecord,
            message: discord.Message,
    ) -> None:
        failed_user_ids: list[int] = []
        for participant_id in record.participant_ids:
            if participant_id == message.author.id:
                continue
            try:
                ticket_user = await self._resolve_ticket_user(participant_id)
                if ticket_user is None:
                    failed_user_ids.append(participant_id)
                    continue
                await self.send_staff_relay_to_participant(
                    ticket_user=ticket_user,
                    message=message,
                )
            except discord.Forbidden:
                failed_user_ids.append(participant_id)
            except discord.HTTPException:
                LOGGER.exception(
                    "TICKET_STAFF_RELAY_FAILED thread=%s user_id=%s",
                    message.channel.id,
                    participant_id,
                )

        if failed_user_ids:
            await self._notify_staff(message.channel, failed_user_ids)

    async def relay_user_message_to_other_participants(
            self,
            *,
            record: TicketRecord,
            thread: discord.Thread,
            message: discord.Message,
    ) -> None:
        failed_user_ids: list[int] = []
        for participant_id in record.participant_ids:
            if participant_id == message.author.id:
                continue
            try:
                ticket_user = await self._resolve_ticket_user(participant_id)
                if ticket_user is None:
                    failed_user_ids.append(participant_id)
                    continue
                await self.send_user_relay_to_participant(
                    ticket_user=ticket_user,
                    message=message,
                )
            except discord.Forbidden:
                failed_user_ids.append(participant_id)
            except discord.HTTPException:
                LOGGER.exception(
                    "TICKET_USER_RELAY_TO_PARTICIPANT_FAILED thread=%s user_id=%s sender=%s(%s)",
                    record.thread_id,
                    participant_id,
                    message.author,
                    message.author.id,
                )

        if failed_user_ids:
            await self._notify_staff(thread, failed_user_ids)

    async def broadcast_dm_message(
            self,
            *,
            record: TicketRecord,
            content: str,
            exclude_user_ids: set[int] | None = None,
    ) -> None:
        skipped_user_ids = exclude_user_ids or set()
        for participant_id in record.participant_ids:
            if participant_id in skipped_user_ids:
                continue
            try:
                ticket_user = await self._resolve_ticket_user(participant_id)
                if ticket_user is None:
                    continue
                await self._send_dm(
                    ticket_user,
                    truncate_relay_text(content),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                LOGGER.exception(
                    "TICKET_PARTICIPANT_DM_BROADCAST_FAILED thread=%s user_id=%s",
                    record.thread_id,
                    participant_id,
                )

    async def sync_history_to_participant(
            self,
            *,
            record: TicketRecord,
            participant_id: int,
            thread: discord.Thread,
            thread_user_relay_message_ids: set[int],
    ) -> None:
        participant_user = await self._resolve_ticket_user(participant_id)
        if participant_user is None:
            return

        try:
            async for history_message in thread.history(limit=25, oldest_first=True):
                if history_message.id == record.thread_start_message_id:
                    continue

                if should_relay_bot_thread_message(history_message):
                    dm_message = await self.command_mirror.send_result_to_participant(
                        record=record,
                        participant_id=participant_id,
                        message=history_message,
                    )
                    if dm_message is None:
                        continue
                    self.command_mirror.remember_participant_message(
                        thread_message_id=history_message.id,
                        participant_id=participant_id,
                        dm_message_id=dm_message.id,
                        message=history_message,
                    )
                    continue

                if (
                        history_message.id in thread_user_relay_message_ids
                        or record.relay_message_author_id(history_message.id) is not None
                        or history_message.webhook_id is not None
                ):
                    await self.send_user_relay_to_participant(
                        ticket_user=participant_user,
                        message=history_message,
                    )
                    continue

                if history_message.author.bot:
                    if looks_like_user_relay_message(history_message.content):
                        await self._send_dm(
                            participant_user,
                            truncate_relay_text(history_message.content),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    continue

                await self.send_staff_relay_to_participant(
                    ticket_user=participant_user,
                    message=history_message,
                )
        except discord.HTTPException:
            LOGGER.exception(
                "TICKET_HISTORY_SYNC_FAILED thread=%s user_id=%s",
                record.thread_id,
                participant_id,
            )

    async def send_staff_relay_to_participant(
            self,
            *,
            ticket_user: discord.User,
            message: discord.Message,
    ) -> None:
        await self._send_dm(
            ticket_user,
            embed=build_ticket_dm_relay_embed(
                localizer=self.bot.localizer,
                message=message,
                color=STAFF_DM_RELAY_COLOR,
                is_staff=True,
                mention_line=(
                        self._relay_mention(message)
                        or relay_visual_username(message)
                ),
                avatar_url=author_avatar_url(message.author),
            ),
            files=await clone_message_attachments_as_files(message),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def send_user_relay_to_participant(
            self,
            *,
            ticket_user: discord.User,
            message: discord.Message,
    ) -> None:
        await self._send_dm(
            ticket_user,
            embed=build_ticket_dm_relay_embed(
                localizer=self.bot.localizer,
                message=message,
                color=PARTICIPANT_DM_RELAY_COLOR,
                is_staff=False,
                mention_line=(
                        self._relay_mention(message)
                        or relay_visual_username(message)
                ),
                avatar_url=author_avatar_url(message.author),
            ),
            files=await clone_message_attachments_as_files(message),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _notify_staff(
            self,
            channel: discord.abc.Messageable,
            failed_user_ids: list[int],
    ) -> None:
        await channel.send(
            self.bot.localizer.translate(
                I18N.messages.tickets.relay.dm_failed_for_staff,
                user_id=", ".join(str(user_id) for user_id in failed_user_ids),
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )
