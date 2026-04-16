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
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.ticket_ai import (
    TicketAiConversationTurn,
    TicketAiReply,
    create_ticket_ai_chat_client,
)
from bigness_league_bot.application.services.tickets import (
    TicketRecord,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str
from bigness_league_bot.infrastructure.ticket_ai.ollama import OllamaClientError
from bigness_league_bot.presentation.discord.views.ticket_panel import TicketPanelView
from bigness_league_bot.presentation.discord.views.ticket_thread_controls import (
    TicketThreadControlsView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)
MAX_RELAY_MESSAGE_LENGTH = 1_900


class TicketsCog(commands.Cog):
    def __init__(self, bot: BignessLeagueBot, store: TicketStateStore) -> None:
        self.bot = bot
        self.store = store

    @app_commands.command(
        name=localized_locale_str(I18N.commands.tickets.publish_panel.name),
        description=localized_locale_str(
            I18N.commands.tickets.publish_panel.description
        ),
    )
    @app_commands.guild_only()
    async def publish_ticket_panel(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            raise CommandUserError(localize(I18N.errors.channel_management.server_only))

        if not self._member_has_ceo_role(interaction.user):
            raise CommandUserError(localize(I18N.errors.tickets.ceo_only))

        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise CommandUserError(localize(I18N.errors.channel_management.text_only))

        await interaction.response.defer(ephemeral=True, thinking=True)
        await channel.send(
            content=interaction.client.localizer.translate(
                I18N.messages.tickets.panel.content,
                locale=interaction.locale,
            ),
            view=TicketPanelView(self.store),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await interaction.followup.send(
            interaction.client.localizer.translate(
                I18N.messages.tickets.panel.published,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.tickets.ai_status.name),
        description=localized_locale_str(
            I18N.commands.tickets.ai_status.description
        ),
    )
    @app_commands.guild_only()
    async def ai_status(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            raise CommandUserError(localize(I18N.errors.channel_management.server_only))

        if not self._member_has_ceo_role(interaction.user):
            raise CommandUserError(localize(I18N.errors.tickets.ceo_only))

        await interaction.response.defer(ephemeral=True, thinking=True)
        backend_reachable = await self._ping_ticket_ai_backend()
        await interaction.followup.send(
            interaction.client.localizer.translate(
                I18N.messages.tickets.ai.status.result,
                locale=interaction.locale,
                loaded=self._yes_no(self.bot.ticket_ai is not None),
                enabled=self._yes_no(self.bot.settings.ticket_ai_enabled),
                auto_reply=self._yes_no(self.bot.settings.ticket_ai_auto_reply_enabled),
                provider=self.bot.settings.ticket_ai_provider,
                model=self.bot.settings.ticket_ai_model,
                base_url=self.bot.settings.ticket_ai_base_url,
                backend_reachable=self._yes_no(backend_reachable),
                categories=(
                        ", ".join(self.bot.settings.ticket_ai_autoreply_categories)
                        or "-"
                ),
                knowledge_base_file=str(self.bot.settings.ticket_ai_knowledge_base_file),
                system_prompt_file=str(self.bot.settings.ticket_ai_system_prompt_file),
            ),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        if message.guild is None:
            await self._relay_user_dm_to_ticket(message)
            return

        if isinstance(message.channel, discord.Thread):
            await self._relay_staff_message_to_user(message)

    async def _relay_user_dm_to_ticket(self, message: discord.Message) -> None:
        record = self.store.active_for_user(message.author.id)
        if record is None:
            return

        thread = await self._resolve_ticket_thread(record)
        if thread is None:
            self.store.remove_thread(record.thread_id)
            await message.author.send(
                self.bot.localizer.translate(
                    I18N.messages.tickets.relay.thread_missing_for_user,
                )
            )
            return

        await thread.send(
            self._build_user_relay_message(message),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self._maybe_auto_reply_to_user_ticket(
            message=message,
            record=record,
            thread=thread,
        )

    async def _relay_staff_message_to_user(self, message: discord.Message) -> None:
        record = self.store.active_for_thread(message.channel.id)
        if record is None:
            return

        try:
            ticket_user = await self.bot.fetch_user(record.user_id)
            await ticket_user.send(
                self._build_staff_relay_message(message),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            await message.channel.send(
                self.bot.localizer.translate(
                    I18N.messages.tickets.relay.dm_failed_for_staff,
                    user_id=str(record.user_id),
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            LOGGER.exception(
                "TICKET_STAFF_RELAY_FAILED thread=%s user_id=%s",
                message.channel.id,
                record.user_id,
            )

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

    def _build_user_relay_message(self, message: discord.Message) -> str:
        author_label = f"{message.author} ({message.author.id})"
        body = self._message_body(message)
        return self._truncate(
            self.bot.localizer.translate(
                I18N.messages.tickets.relay.from_user,
                author=author_label,
                body=body,
            )
        )

    def _build_staff_relay_message(self, message: discord.Message) -> str:
        member_name = (
            message.author.display_name
            if isinstance(message.author, discord.Member)
            else str(message.author)
        )
        body = self._message_body(message)
        return self._truncate(
            self.bot.localizer.translate(
                I18N.messages.tickets.relay.from_staff,
                author=member_name,
                body=body,
            )
        )

    def _message_body(self, message: discord.Message) -> str:
        content = message.content.strip()
        attachment_lines = [
            f"- {attachment.url}"
            for attachment in message.attachments
        ]
        if attachment_lines:
            attachments = self.bot.localizer.translate(
                I18N.messages.tickets.relay.attachments,
                urls="\n".join(attachment_lines),
            )
            content = f"{content}\n\n{attachments}" if content else attachments

        return content or self.bot.localizer.translate(
            I18N.messages.tickets.relay.empty_body
        )

    async def _maybe_auto_reply_to_user_ticket(
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
            return

        latest_user_message = self._message_body_for_ai(message)
        if latest_user_message is None:
            return

        conversation = await self._build_ai_conversation(
            channel=message.channel,
            excluded_message_id=message.id,
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
            self._build_ai_thread_message(ai_reply),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        fallback_required = (
                ai_reply.should_escalate
                or ai_reply.confidence < self.bot.settings.ticket_ai_auto_reply_min_confidence
        )
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
        if (
                fallback_required
        ):
            await message.author.send(
                self.bot.localizer.translate(
                    I18N.messages.tickets.ai.user_fallback,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        await message.author.send(
            self._truncate(ai_reply.answer),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _build_ai_conversation(
            self,
            *,
            channel: discord.abc.Messageable,
            excluded_message_id: int,
    ) -> tuple[TicketAiConversationTurn, ...]:
        turns: list[TicketAiConversationTurn] = []
        async for history_message in channel.history(
                limit=self.bot.settings.ticket_ai_max_context_messages + 8,
                oldest_first=False,
        ):
            if history_message.id == excluded_message_id:
                continue
            body = self._message_body_for_ai(history_message)
            if body is None:
                continue

            turns.append(
                TicketAiConversationTurn(
                    role=("assistant" if history_message.author.bot else "user"),
                    content=body,
                )
            )

        turns.reverse()
        return tuple(turns[-self.bot.settings.ticket_ai_max_context_messages:])

    def _build_ai_thread_message(self, ai_reply: TicketAiReply) -> str:
        used_entry_ids = ", ".join(ai_reply.used_entry_ids) or "-"
        return self._truncate(
            self.bot.localizer.translate(
                I18N.messages.tickets.ai.thread_response,
                answer=ai_reply.answer,
                confidence=str(ai_reply.confidence),
                should_escalate=("si" if ai_reply.should_escalate else "no"),
                reason=ai_reply.reason,
                used_entry_ids=used_entry_ids,
            )
        )

    def _message_body_for_ai(
            self,
            message: discord.Message,
    ) -> str | None:
        content = message.content.strip()
        attachment_lines = [
            f"- {attachment.url}"
            for attachment in message.attachments
        ]
        if attachment_lines:
            attachments = self.bot.localizer.translate(
                I18N.messages.tickets.relay.attachments,
                urls="\n".join(attachment_lines),
            )
            content = f"{content}\n\n{attachments}" if content else attachments

        return content or None

    async def _ping_ticket_ai_backend(self) -> bool:
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

    @staticmethod
    def _member_has_ceo_role(member: discord.Member) -> bool:
        return any(role.name.casefold() == "ceo" for role in member.roles)

    @staticmethod
    def _truncate(value: str) -> str:
        if len(value) <= MAX_RELAY_MESSAGE_LENGTH:
            return value

        return f"{value[:MAX_RELAY_MESSAGE_LENGTH]}...<truncated>"

    @staticmethod
    def _yes_no(value: bool) -> str:
        return "si" if value else "no"

    async def cog_app_command_error(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            error: app_commands.AppCommandError,
    ) -> None:
        error_details = classify_app_command_error(error)
        message = interaction.client.localizer.render(
            error_details.user_message,
            locale=interaction.locale,
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
            return

        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: BignessLeagueBot) -> None:
    store = TicketStateStore(bot.settings.ticket_state_file)
    bot.add_view(TicketPanelView(store))
    bot.add_view(TicketThreadControlsView(store))
    await bot.add_cog(TicketsCog(bot, store))
