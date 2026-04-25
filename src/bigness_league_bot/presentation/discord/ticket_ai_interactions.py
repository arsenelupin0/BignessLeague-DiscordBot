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
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.ticket_ai import (
    create_ticket_ai_chat_client,
)
from bigness_league_bot.application.services.tickets import TicketRecord
from bigness_league_bot.infrastructure.discord.ticket_ai_messages import (
    build_ticket_ai_conversation,
    build_ticket_ai_thread_message,
    ticket_ai_message_body,
)
from bigness_league_bot.infrastructure.discord.ticket_participant_messenger import (
    TicketParticipantMessenger,
)
from bigness_league_bot.infrastructure.discord.ticket_relay_messages import yes_no
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.ticket_ai.ollama import OllamaClientError

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)


class TicketAiInteractions:
    def __init__(
            self,
            *,
            bot: BignessLeagueBot,
            participant_messenger: TicketParticipantMessenger,
    ) -> None:
        self.bot = bot
        self.participant_messenger = participant_messenger

    async def send_status(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        backend_reachable = await self._ping_backend()
        await interaction.followup.send(
            interaction.client.localizer.translate(
                I18N.messages.tickets.ai.status.result,
                locale=interaction.locale,
                loaded=yes_no(self.bot.ticket_ai is not None),
                enabled=yes_no(self.bot.settings.ticket_ai_enabled),
                auto_reply=yes_no(self.bot.settings.ticket_ai_auto_reply_enabled),
                provider=self.bot.settings.ticket_ai_provider,
                model=self.bot.settings.ticket_ai_model,
                base_url=self.bot.settings.ticket_ai_base_url,
                backend_reachable=yes_no(backend_reachable),
                categories=(
                        ", ".join(self.bot.settings.ticket_ai_autoreply_categories)
                        or "-"
                ),
                knowledge_base_file=str(self.bot.settings.ticket_ai_knowledge_base_file),
                system_prompt_file=str(self.bot.settings.ticket_ai_system_prompt_file),
            ),
            ephemeral=True,
        )

    async def maybe_auto_reply_to_user_ticket(
            self,
            *,
            message: discord.Message,
            record: TicketRecord,
            thread: discord.Thread,
    ) -> None:
        ticket_ai = self.bot.ticket_ai
        if ticket_ai is None:
            return
        if not ticket_ai.can_auto_reply(record.category_key):
            LOGGER.info(
                "TICKET_AI_AUTOREPLY_SKIPPED user=%s(%s) thread=%s category=%s force_escalate_category=%s allowed_categories=%s",
                message.author,
                message.author.id,
                thread.id,
                record.category_key,
                ticket_ai.is_force_escalate_category(record.category_key),
                ",".join(self.bot.settings.ticket_ai_autoreply_categories) or "-",
            )
            return

        latest_user_message = ticket_ai_message_body(
            localizer=self.bot.localizer,
            message=message,
        )
        if latest_user_message is None:
            return

        conversation = await build_ticket_ai_conversation(
            localizer=self.bot.localizer,
            channel=message.channel,
            excluded_message_id=message.id,
            max_context_messages=self.bot.settings.ticket_ai_max_context_messages,
        )
        try:
            ai_reply = await ticket_ai.generate_reply(
                category_key=record.category_key,
                latest_user_message=latest_user_message,
                conversation=conversation,
            )
        except OllamaClientError as error:
            LOGGER.warning(
                "TICKET_AI_UNAVAILABLE user=%s(%s) thread=%s details=%s",
                message.author,
                message.author.id,
                thread.id,
                error,
            )
            await thread.send(
                self.bot.localizer.translate(
                    I18N.messages.tickets.ai.unavailable_thread,
                    details=str(error),
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        await thread.send(
            build_ticket_ai_thread_message(
                localizer=self.bot.localizer,
                ai_reply=ai_reply,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        fallback_required = ai_reply.should_escalate
        LOGGER.info(
            "TICKET_AI_DECISION user=%s(%s) thread=%s category=%s confidence=%s threshold=%s escalate=%s fallback=%s used_entry_ids=%s",
            message.author,
            message.author.id,
            thread.id,
            record.category_key,
            ai_reply.confidence,
            self.bot.settings.ticket_ai_auto_reply_min_confidence,
            ai_reply.should_escalate,
            fallback_required,
            ",".join(ai_reply.used_entry_ids) or "-",
        )
        if fallback_required:
            await self.participant_messenger.broadcast_dm_message(
                record=record,
                content=self.bot.localizer.translate(
                    I18N.messages.tickets.ai.user_escalated,
                ),
            )
            return

        await self.participant_messenger.broadcast_dm_message(
            record=record,
            content=ai_reply.answer,
        )

    async def _ping_backend(self) -> bool:
        try:
            client = create_ticket_ai_chat_client(self.bot.settings)
            return await client.ping()
        except OllamaClientError:
            LOGGER.exception(
                "TICKET_AI_STATUS_PING_FAILED provider=%s base_url=%s",
                self.bot.settings.ticket_ai_provider,
                self.bot.settings.ticket_ai_base_url,
            )
            return False
