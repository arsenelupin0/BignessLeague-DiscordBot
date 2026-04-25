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

from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.ticket_ai import (
    ConversationRole,
    TicketAiConversationTurn,
    TicketAiReply,
)
from bigness_league_bot.infrastructure.discord.ticket_relay_messages import (
    is_participant_dm_relay_message,
    is_staff_dm_relay_message,
    looks_like_bot_command_relay_message,
    looks_like_staff_relay_message,
    looks_like_user_relay_message,
    relay_embed_description_for_ai,
    truncate_relay_text,
    yes_no,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.i18n.service import LocalizationService


async def build_ticket_ai_conversation(
        *,
        localizer: LocalizationService,
        channel: discord.abc.Messageable,
        excluded_message_id: int,
        max_context_messages: int,
) -> tuple[TicketAiConversationTurn, ...]:
    turns: list[TicketAiConversationTurn] = []
    async for history_message in channel.history(
            limit=max_context_messages + 8,
            oldest_first=False,
    ):
        if history_message.id == excluded_message_id:
            continue
        body = ticket_ai_message_body(localizer=localizer, message=history_message)
        if body is None:
            continue
        role = ticket_ai_message_role(history_message)
        if role is None:
            continue

        turns.append(
            TicketAiConversationTurn(
                role=role,
                content=body,
            )
        )

    turns.reverse()
    return tuple(turns[-max_context_messages:])


def build_ticket_ai_thread_message(
        *,
        localizer: LocalizationService,
        ai_reply: TicketAiReply,
) -> str:
    used_entry_ids = ", ".join(ai_reply.used_entry_ids) or "-"
    return truncate_relay_text(
        localizer.translate(
            I18N.messages.tickets.ai.thread_response,
            answer=ai_reply.answer,
            confidence=str(ai_reply.confidence),
            should_escalate=yes_no(ai_reply.should_escalate),
            reason=ai_reply.reason,
            used_entry_ids=used_entry_ids,
        )
    )


def ticket_ai_message_body(
        *,
        localizer: LocalizationService,
        message: discord.Message,
) -> str | None:
    content = message.content.strip()
    if not content:
        embed_description = relay_embed_description_for_ai(message)
        if embed_description is not None:
            content = embed_description
    attachment_lines = [
        f"- {attachment.url}"
        for attachment in message.attachments
    ]
    if attachment_lines:
        attachments = localizer.translate(
            I18N.messages.tickets.relay.attachments,
            urls="\n".join(attachment_lines),
        )
        content = f"{content}\n\n{attachments}" if content else attachments

    return content or None


def ticket_ai_message_role(message: discord.Message) -> ConversationRole | None:
    if not message.author.bot:
        return "user"
    if is_participant_dm_relay_message(message):
        return "user"
    if is_staff_dm_relay_message(message):
        return "staff"
    if looks_like_user_relay_message(message.content):
        return "user"
    if looks_like_staff_relay_message(message.content):
        return "staff"
    if looks_like_bot_command_relay_message(message.content):
        return "staff"

    return None
