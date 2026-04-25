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
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.ticket_ai import (
    create_ticket_ai_chat_client,
)
from bigness_league_bot.application.services.tickets import (
    format_ticket_number,
    TicketRecord,
    require_ticket_category,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_management import (
    ChannelManagementError,
    ensure_allowed_member,
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.ticket_ai_messages import (
    build_ticket_ai_conversation,
    build_ticket_ai_thread_message,
    ticket_ai_message_body,
)
from bigness_league_bot.infrastructure.discord.ticket_relay_messages import (
    PARTICIPANT_DM_RELAY_COLOR,
    STAFF_DM_RELAY_COLOR,
    attachment_signature,
    author_avatar_url,
    build_ticket_command_relay_message,
    build_ticket_dm_relay_embed,
    build_ticket_user_relay_message,
    clone_message_attachments_as_files,
    clone_message_embeds,
    looks_like_user_relay_message,
    message_body,
    relay_visual_username,
    should_relay_bot_thread_message,
    should_retry_discord_http_error,
    thread_relay_display_name,
    truncate_relay_text,
    yes_no,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str
from bigness_league_bot.infrastructure.ticket_ai.ollama import OllamaClientError
from bigness_league_bot.presentation.discord.views.ticket_message_embeds import (
    build_ticket_message_content,
    build_ticket_open_embed,
)
from bigness_league_bot.presentation.discord.views.ticket_panel import TicketPanelView
from bigness_league_bot.presentation.discord.views.ticket_thread_controls import (
    TicketThreadControlsView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)
THREAD_RELAY_WEBHOOK_NAME = "Bigness League Tickets Relay"


class TicketsCog(commands.Cog):
    def __init__(self, bot: BignessLeagueBot, store: TicketStateStore) -> None:
        self.bot = bot
        self.store = store
        self._interaction_command_names: dict[int, str] = {}
        self._thread_to_dm_command_message_ids: dict[int, dict[int, int]] = {}
        self._thread_to_dm_command_message_locks: dict[int, asyncio.Lock] = {}
        self._thread_command_name_overrides: dict[int, str] = {}
        self._thread_to_dm_command_message_signatures: dict[int, tuple[object, ...]] = {}
        self._pending_initial_command_mirror_tasks: dict[int, asyncio.Task[None]] = {}
        self._dm_retry_delays: tuple[float, ...] = (0.75, 1.5)
        self._forum_relay_webhooks: dict[int, discord.Webhook] = {}
        self._forum_relay_webhook_locks: dict[int, asyncio.Lock] = {}
        self._thread_user_relay_message_ids: set[int] = set()
        self._thread_user_relay_message_authors: dict[int, int] = {}

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
        name=localized_locale_str(I18N.commands.tickets.add_to_ticket.name),
        description=localized_locale_str(
            I18N.commands.tickets.add_to_ticket.description
        ),
    )
    @app_commands.describe(
        usuario_1=localized_locale_str(
            I18N.commands.tickets.add_to_ticket.parameters.user_1.description
        ),
        usuario_2=localized_locale_str(
            I18N.commands.tickets.add_to_ticket.parameters.user_2.description
        ),
        usuario_3=localized_locale_str(
            I18N.commands.tickets.add_to_ticket.parameters.user_3.description
        ),
        usuario_4=localized_locale_str(
            I18N.commands.tickets.add_to_ticket.parameters.user_4.description
        ),
        usuario_5=localized_locale_str(
            I18N.commands.tickets.add_to_ticket.parameters.user_5.description
        ),
    )
    @app_commands.guild_only()
    async def add_to_ticket(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            usuario_1: discord.Member,
            usuario_2: discord.Member | None = None,
            usuario_3: discord.Member | None = None,
            usuario_4: discord.Member | None = None,
            usuario_5: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise CommandUserError(localize(I18N.errors.channel_management.server_only))

        try:
            ensure_allowed_member(interaction.user)
        except ChannelManagementError as error:
            raise CommandUserError(error.message) from error

        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            raise CommandUserError(localize(I18N.messages.tickets.participants.only_ticket_thread))

        record = self.store.active_for_thread(thread.id)
        if record is None:
            raise CommandUserError(localize(I18N.messages.tickets.close.not_active))

        await interaction.response.defer(ephemeral=True, thinking=True)
        requested_members = tuple(
            dict.fromkeys(
                member
                for member in (
                    usuario_1,
                    usuario_2,
                    usuario_3,
                    usuario_4,
                    usuario_5,
                )
                if member is not None
            )
        )
        await self._add_members_to_ticket(
            interaction=interaction,
            thread=thread,
            record=record,
            requested_members=requested_members,
        )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.tickets.add_team_to_ticket.name),
        description=localized_locale_str(
            I18N.commands.tickets.add_team_to_ticket.description
        ),
    )
    @app_commands.describe(
        equipo=localized_locale_str(
            I18N.commands.tickets.add_team_to_ticket.parameters.team_role.description
        ),
    )
    @app_commands.guild_only()
    async def add_team_to_ticket(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            equipo: discord.Role,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise CommandUserError(localize(I18N.errors.channel_management.server_only))

        try:
            ensure_allowed_member(interaction.user)
        except ChannelManagementError as error:
            raise CommandUserError(error.message) from error

        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            raise CommandUserError(localize(I18N.messages.tickets.participants.only_ticket_thread))

        record = self.store.active_for_thread(thread.id)
        if record is None:
            raise CommandUserError(localize(I18N.messages.tickets.close.not_active))

        role_catalog = get_channel_access_role_catalog(
            interaction.guild,
            interaction.client.settings.channel_access_range_start_role_id,
            interaction.client.settings.channel_access_range_end_role_id,
        )
        if equipo.id not in {role.id for role in role_catalog.roles}:
            raise CommandUserError(
                localize(
                    I18N.errors.match_channel_creation.team_role_out_of_range,
                    role_name=equipo.name,
                    range_start=role_catalog.range_start.name,
                    range_end=role_catalog.range_end.name,
                )
            )

        requested_members = tuple(
            dict.fromkeys(
                member
                for member in equipo.members
                if not member.bot
            )
        )

        if not requested_members:
            raise CommandUserError(
                localize(I18N.messages.tickets.participants.team_role_empty)
            )

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self._add_members_to_ticket(
            interaction=interaction,
            thread=thread,
            record=record,
            requested_members=requested_members,
        )

    async def _add_members_to_ticket(
            self,
            *,
            interaction: discord.Interaction[BignessLeagueBot],
            thread: discord.Thread,
            record: TicketRecord,
            requested_members: tuple[discord.Member, ...],
    ) -> None:
        members_to_add: list[discord.Member] = []
        already_present: list[discord.Member] = []
        blocked_by_other_ticket: list[discord.Member] = []
        dm_failed: list[discord.Member] = []

        for member in requested_members:
            if member.bot:
                dm_failed.append(member)
                continue

            if record.includes_user(member.id):
                already_present.append(member)
                continue

            active_ticket = self.store.active_for_user(member.id)
            if active_ticket is not None and active_ticket.thread_id != record.thread_id:
                blocked_by_other_ticket.append(member)
                continue

            members_to_add.append(member)

        if not members_to_add and not already_present and not blocked_by_other_ticket:
            await interaction.followup.send(
                interaction.client.localizer.translate(
                    I18N.messages.tickets.participants.none_added,
                    locale=interaction.locale,
                ),
                ephemeral=True,
            )
            return

        owner = await self._resolve_ticket_user(record.user_id)
        if owner is None:
            await interaction.followup.send(
                interaction.client.localizer.translate(
                    I18N.messages.tickets.participants.owner_unavailable,
                    locale=interaction.locale,
                ),
                ephemeral=True,
            )
            return

        category = require_ticket_category(record.category_key)
        successfully_added: list[discord.Member] = []
        updated_record = record

        for member in members_to_add:
            dm_message = await self._send_ticket_participant_welcome(
                member=member,
                owner=owner,
                record=updated_record,
                category_label=category.label,
                locale=interaction.locale,
                guild=interaction.guild,
            )
            if dm_message is None:
                dm_failed.append(member)
                continue

            updated_record = updated_record.with_added_participants((member.id,))
            updated_record = updated_record.with_participant_dm(
                user_id=member.id,
                dm_channel_id=dm_message.channel.id,
                dm_start_message_id=dm_message.id,
            )
            await self._sync_ticket_history_to_participant(
                record=updated_record,
                participant_id=member.id,
                thread=thread,
            )
            successfully_added.append(member)

        if updated_record != record:
            self.store.update(updated_record)

        if successfully_added:
            await thread.send(
                interaction.client.localizer.translate(
                    I18N.messages.tickets.participants.added_thread,
                    locale=interaction.locale,
                    users=", ".join(member.mention for member in successfully_added),
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                    replied_user=False,
                ),
            )

        await interaction.followup.send(
            self._build_add_participants_summary(
                interaction=interaction,
                added=successfully_added,
                already_present=already_present,
                blocked_by_other_ticket=blocked_by_other_ticket,
                dm_failed=dm_failed,
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

    @commands.Cog.listener()
    async def on_interaction(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        if interaction.type != discord.InteractionType.application_command:
            return

        command = interaction.command
        if command is None:
            return

        qualified_name = getattr(command, "qualified_name", None)
        if isinstance(qualified_name, str) and qualified_name.strip():
            self._interaction_command_names[interaction.id] = qualified_name.strip()
            return

        name = getattr(command, "name", None)
        if isinstance(name, str) and name.strip():
            self._interaction_command_names[interaction.id] = name.strip()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
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
            if message.id in self._thread_user_relay_message_ids:
                return
            if message.author.bot:
                await self._schedule_initial_bot_thread_message_to_user(message)
                return
            await self._relay_staff_message_to_user(message)

    @commands.Cog.listener()
    async def on_message_edit(
            self,
            before: discord.Message,
            after: discord.Message,
    ) -> None:
        del before
        if not isinstance(after.channel, discord.Thread):
            return
        if self.bot.user is None or after.author.id != self.bot.user.id:
            return
        pending_initial_task = self._pending_initial_command_mirror_tasks.get(after.id)
        if (
                pending_initial_task is not None
                and not pending_initial_task.done()
                and after.id not in self._thread_to_dm_command_message_ids
        ):
            return
        if (
                after.id not in self._thread_to_dm_command_message_ids
                and not should_relay_bot_thread_message(after)
        ):
            return

        await self.mirror_thread_command_message_edit(after)

    async def _relay_user_dm_to_ticket(self, message: discord.Message) -> None:
        record = self.store.active_for_user(message.author.id)
        if record is None:
            return

        thread = await self._resolve_ticket_thread(record)
        if thread is None:
            self.store.remove_thread(record.thread_id)
            await self._send_dm_with_retry(
                message.author,
                self.bot.localizer.translate(
                    I18N.messages.tickets.relay.thread_missing_for_user,
                ),
            )
            return

        await self._relay_user_message_to_thread(
            record=record,
            thread=thread,
            message=message,
        )
        await self._relay_user_message_to_other_participants(
            record=record,
            message=message,
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

        failed_user_ids: list[int] = []
        for participant_id in record.participant_ids:
            if participant_id == message.author.id:
                continue
            try:
                ticket_user = await self._resolve_ticket_user(participant_id)
                if ticket_user is None:
                    failed_user_ids.append(participant_id)
                    continue
                await self._send_staff_relay_to_dm_participant(
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

        if not failed_user_ids:
            return

        await message.channel.send(
            self.bot.localizer.translate(
                I18N.messages.tickets.relay.dm_failed_for_staff,
                user_id=", ".join(str(user_id) for user_id in failed_user_ids),
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _relay_user_message_to_other_participants(
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
                await self._send_user_relay_to_dm_participant(
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

        if not failed_user_ids:
            return

        thread = await self._resolve_ticket_thread(record)
        if thread is None:
            return

        await thread.send(
            self.bot.localizer.translate(
                I18N.messages.tickets.relay.dm_failed_for_staff,
                user_id=", ".join(str(user_id) for user_id in failed_user_ids),
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _send_ticket_dm_message_to_participants(
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
                await self._send_dm_with_retry(
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

    async def _schedule_initial_bot_thread_message_to_user(
            self,
            message: discord.Message,
    ) -> None:
        if self.bot.user is None or message.author.id != self.bot.user.id:
            return
        if not should_relay_bot_thread_message(message):
            return
        if message.id in self._thread_to_dm_command_message_ids:
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
            await self.mirror_thread_command_message(latest_message)
        except asyncio.CancelledError:
            raise
        finally:
            self._pending_initial_command_mirror_tasks.pop(message.id, None)

    async def _fetch_thread_message_snapshot(
            self,
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

    async def _relay_user_message_to_thread(
            self,
            *,
            record: TicketRecord,
            thread: discord.Thread,
            message: discord.Message,
    ) -> None:
        webhook = await self._get_thread_relay_webhook(thread)
        if webhook is None:
            relay_message = await thread.send(
                build_ticket_user_relay_message(
                    localizer=self.bot.localizer,
                    message=message,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            self._thread_user_relay_message_authors[relay_message.id] = message.author.id
            updated_record = record.with_thread_relay_message_author(
                thread_message_id=relay_message.id,
                user_id=message.author.id,
            )
            self.store.update(updated_record)
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
            await thread.send(
                build_ticket_user_relay_message(
                    localizer=self.bot.localizer,
                    message=message,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        self._thread_user_relay_message_ids.add(webhook_message.id)
        self._thread_user_relay_message_authors[webhook_message.id] = message.author.id
        updated_record = record.with_thread_relay_message_author(
            thread_message_id=webhook_message.id,
            user_id=message.author.id,
        )
        self.store.update(updated_record)

    async def _get_thread_relay_webhook(
            self,
            thread: discord.Thread,
    ) -> discord.Webhook | None:
        parent = thread.parent
        if not isinstance(parent, discord.ForumChannel):
            return None

        cached_webhook = self._forum_relay_webhooks.get(parent.id)
        if cached_webhook is not None and cached_webhook.token is not None:
            return cached_webhook

        async with self._forum_relay_webhook_lock(parent.id):
            cached_webhook = self._forum_relay_webhooks.get(parent.id)
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

            self._forum_relay_webhooks[parent.id] = webhook
            return webhook

    def _forum_relay_webhook_lock(self, forum_channel_id: int) -> asyncio.Lock:
        lock = self._forum_relay_webhook_locks.get(forum_channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self._forum_relay_webhook_locks[forum_channel_id] = lock
        return lock

    async def _send_staff_relay_to_dm_participant(
            self,
            *,
            ticket_user: discord.User,
            message: discord.Message,
    ) -> None:
        await self._send_dm_with_retry(
            ticket_user,
            embed=build_ticket_dm_relay_embed(
                localizer=self.bot.localizer,
                message=message,
                color=STAFF_DM_RELAY_COLOR,
                is_staff=True,
                mention_line=(
                        self._relay_clickable_mention(message)
                        or relay_visual_username(message)
                ),
                avatar_url=author_avatar_url(message.author),
            ),
            files=await clone_message_attachments_as_files(message),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _send_user_relay_to_dm_participant(
            self,
            *,
            ticket_user: discord.User,
            message: discord.Message,
    ) -> None:
        await self._send_dm_with_retry(
            ticket_user,
            embed=build_ticket_dm_relay_embed(
                localizer=self.bot.localizer,
                message=message,
                color=PARTICIPANT_DM_RELAY_COLOR,
                is_staff=False,
                mention_line=(
                        self._relay_clickable_mention(message)
                        or relay_visual_username(message)
                ),
                avatar_url=author_avatar_url(message.author),
            ),
            files=await clone_message_attachments_as_files(message),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    def _relay_clickable_mention(self, message: discord.Message) -> str | None:
        if message.webhook_id is not None:
            original_user_id = self._thread_user_relay_message_authors.get(message.id)
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
        if (
                fallback_required
        ):
            await self._send_ticket_dm_message_to_participants(
                record=record,
                content=self.bot.localizer.translate(
                    I18N.messages.tickets.ai.user_escalated,
                ),
            )
            return

        await self._send_ticket_dm_message_to_participants(
            record=record,
            content=ai_reply.answer,
        )

    def _interaction_command_name(self, message: discord.Message) -> str | None:
        interaction_metadata = message.interaction_metadata
        if interaction_metadata is None:
            return None

        interaction_id = getattr(interaction_metadata, "id", None)
        if isinstance(interaction_id, int):
            resolved_name = self._interaction_command_names.get(interaction_id)
            if resolved_name:
                return resolved_name

        name = getattr(interaction_metadata, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()

        return None

    async def mirror_thread_command_message(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        async with self._command_message_mirror_lock(message.id):
            return await self._mirror_thread_command_message_locked(
                message,
                command_name=command_name,
            )

    async def _mirror_thread_command_message_locked(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        self._remember_command_name_override(message, command_name=command_name)
        record = self.store.active_for_thread(message.channel.id)
        if record is None:
            return None
        if message.id in self._thread_to_dm_command_message_ids:
            return await self._mirror_thread_command_message_edit_locked(
                message,
                command_name=command_name,
            )

        relay_signature = self._build_command_relay_signature(
            message,
            command_name=command_name,
        )

        dm_message_ids = self._thread_to_dm_command_message_ids.setdefault(message.id, {})
        latest_dm_message: discord.Message | None = None
        failed_user_ids: list[int] = []
        for participant_id in record.participant_ids:
            try:
                ticket_user = await self._resolve_ticket_user(participant_id)
                if ticket_user is None:
                    failed_user_ids.append(participant_id)
                    continue
                dm_message = await self._send_dm_with_retry(
                    ticket_user,
                    **await self._build_command_dm_send_kwargs(
                        message,
                        command_name=command_name,
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                dm_message_ids[participant_id] = dm_message.id
                latest_dm_message = dm_message
            except discord.Forbidden:
                failed_user_ids.append(participant_id)
            except discord.HTTPException:
                LOGGER.exception(
                    "TICKET_BOT_COMMAND_RELAY_FAILED thread=%s user_id=%s message=%s",
                    message.channel.id,
                    participant_id,
                    message.id,
                )

        if failed_user_ids:
            await message.channel.send(
                self.bot.localizer.translate(
                    I18N.messages.tickets.relay.dm_failed_for_staff,
                    user_id=", ".join(str(user_id) for user_id in failed_user_ids),
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        if latest_dm_message is None:
            return None

        self._thread_to_dm_command_message_signatures[message.id] = relay_signature
        return latest_dm_message

    async def mirror_thread_command_message_edit(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        async with self._command_message_mirror_lock(message.id):
            return await self._mirror_thread_command_message_edit_locked(
                message,
                command_name=command_name,
            )

    async def _mirror_thread_command_message_edit_locked(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        self._remember_command_name_override(message, command_name=command_name)
        record = self.store.active_for_thread(message.channel.id)
        if record is None:
            return None

        dm_message_ids = self._thread_to_dm_command_message_ids.get(message.id)
        if not dm_message_ids:
            return await self._mirror_thread_command_message_locked(
                message,
                command_name=command_name,
            )

        relay_signature = self._build_command_relay_signature(
            message,
            command_name=command_name,
        )
        previous_signature = self._thread_to_dm_command_message_signatures.get(message.id)

        latest_dm_message: discord.Message | None = None
        failed_user_ids: list[int] = []
        for participant in record.participants:
            try:
                ticket_user = await self._resolve_ticket_user(participant.user_id)
                if ticket_user is None:
                    failed_user_ids.append(participant.user_id)
                    continue
                dm_channel = await ticket_user.create_dm()
                dm_message_id = dm_message_ids.get(participant.user_id)
                if previous_signature == relay_signature and dm_message_id is not None:
                    fetched_dm_message = await dm_channel.fetch_message(dm_message_id)
                    latest_dm_message = fetched_dm_message
                    continue
                if dm_message_id is None:
                    sent_dm_message = await self._send_dm_with_retry(
                        ticket_user,
                        **await self._build_command_dm_send_kwargs(
                            message,
                            command_name=command_name,
                        ),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    dm_message_ids[participant.user_id] = sent_dm_message.id
                    latest_dm_message = sent_dm_message
                    continue
                dm_message = await dm_channel.fetch_message(dm_message_id)
                await dm_message.edit(
                    **await self._build_command_dm_edit_kwargs(
                        message,
                        dm_message=dm_message,
                        command_name=command_name,
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                    view=None,
                )
                latest_dm_message = dm_message
            except discord.NotFound:
                dm_message_ids.pop(participant.user_id, None)
                replacement_dm_message = await self._send_command_result_to_participant(
                    record=record,
                    participant_id=participant.user_id,
                    message=message,
                    command_name=command_name,
                )
                if replacement_dm_message is not None:
                    dm_message_ids[participant.user_id] = replacement_dm_message.id
                    latest_dm_message = replacement_dm_message
            except discord.Forbidden:
                failed_user_ids.append(participant.user_id)
            except discord.HTTPException:
                LOGGER.exception(
                    "TICKET_BOT_COMMAND_RELAY_EDIT_FAILED thread=%s user_id=%s message=%s dm_message=%s",
                    message.channel.id,
                    participant.user_id,
                    message.id,
                    dm_message_ids.get(participant.user_id),
                )

        if failed_user_ids:
            await message.channel.send(
                self.bot.localizer.translate(
                    I18N.messages.tickets.relay.dm_failed_for_staff,
                    user_id=", ".join(str(user_id) for user_id in failed_user_ids),
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        if latest_dm_message is None:
            return None

        self._thread_to_dm_command_message_signatures[message.id] = relay_signature
        self._thread_to_dm_command_message_ids[message.id] = dm_message_ids
        return latest_dm_message

    def _command_message_mirror_lock(self, message_id: int) -> asyncio.Lock:
        lock = self._thread_to_dm_command_message_locks.get(message_id)
        if lock is None:
            lock = asyncio.Lock()
            self._thread_to_dm_command_message_locks[message_id] = lock

        return lock

    def _remember_command_name_override(
            self,
            message: discord.Message,
            *,
            command_name: str | None,
    ) -> None:
        if command_name is None:
            return

        normalized_name = command_name.strip()
        if not normalized_name:
            return

        self._thread_command_name_overrides[message.id] = normalized_name

    def _resolved_command_name(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> str:
        if command_name is not None and command_name.strip():
            return command_name.strip()

        overridden_name = self._thread_command_name_overrides.get(message.id)
        if overridden_name:
            return overridden_name

        return self._interaction_command_name(message) or "comando"

    def _build_command_relay_signature(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> tuple[object, ...]:
        return (
            self._resolved_command_name(message, command_name=command_name),
            message_body(
                localizer=self.bot.localizer,
                message=message,
                attachment_mode="names",
            ),
            tuple(embed.to_dict() for embed in message.embeds),
            attachment_signature(message.attachments),
        )

    async def _build_command_dm_send_kwargs(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "content": build_ticket_command_relay_message(
                localizer=self.bot.localizer,
                message=message,
                command_name=self._resolved_command_name(
                    message,
                    command_name=command_name,
                ),
            ),
            "embeds": clone_message_embeds(message),
        }
        files = await clone_message_attachments_as_files(message)
        if files:
            payload["files"] = files

        return payload

    async def _build_command_dm_edit_kwargs(
            self,
            message: discord.Message,
            *,
            dm_message: discord.Message,
            command_name: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "content": build_ticket_command_relay_message(
                localizer=self.bot.localizer,
                message=message,
                command_name=self._resolved_command_name(
                    message,
                    command_name=command_name,
                ),
            ),
            "embeds": clone_message_embeds(message),
        }
        source_attachments = attachment_signature(message.attachments)
        mirrored_attachments = attachment_signature(dm_message.attachments)
        if not source_attachments:
            payload["attachments"] = []
        elif source_attachments != mirrored_attachments:
            payload["attachments"] = await clone_message_attachments_as_files(message)

        return payload

    async def _resolve_ticket_user(
            self,
            user_id: int,
    ) -> discord.User | None:
        cached_user = self.bot.get_user(user_id)
        if cached_user is not None:
            return cached_user

        try:
            return await self.bot.fetch_user(user_id)
        except discord.HTTPException:
            return None

    async def _send_command_result_to_participant(
            self,
            *,
            record: TicketRecord,
            participant_id: int,
            message: discord.Message,
            command_name: str | None = None,
    ) -> discord.Message | None:
        ticket_user = await self._resolve_ticket_user(participant_id)
        if ticket_user is None:
            return None

        try:
            return await self._send_dm_with_retry(
                ticket_user,
                **await self._build_command_dm_send_kwargs(
                    message,
                    command_name=command_name,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            await message.channel.send(
                self.bot.localizer.translate(
                    I18N.messages.tickets.relay.dm_failed_for_staff,
                    user_id=str(participant_id),
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return None
        except discord.HTTPException:
            LOGGER.exception(
                "TICKET_BOT_COMMAND_RELAY_FAILED thread=%s user_id=%s message=%s",
                record.thread_id,
                participant_id,
                message.id,
            )
            return None

    async def _send_ticket_participant_welcome(
            self,
            *,
            member: discord.Member,
            owner: discord.abc.User | discord.Member,
            record: TicketRecord,
            category_label: str,
            locale: str | discord.Locale | None,
            guild: discord.Guild,
    ) -> discord.Message | None:
        try:
            return await self._send_dm_with_retry(
                member,
                content=(
                    f"{build_ticket_message_content(member)}\n\n"
                    f"{self.bot.localizer.translate(
                        I18N.messages.tickets.participants.added_dm,
                        locale=locale,
                        ticket_number=format_ticket_number(record.ticket_number),
                        category=category_label,
                    )}"
                ),
                embed=build_ticket_open_embed(
                    bot=self.bot,
                    locale=locale,
                    guild=guild,
                    opened_by=owner,
                    category_label=category_label,
                    ticket_number=record.ticket_number,
                    created_at=record.created_at,
                ),
                view=TicketThreadControlsView(self.store),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                    replied_user=False,
                ),
            )
        except discord.HTTPException:
            return None

    async def _sync_ticket_history_to_participant(
            self,
            *,
            record: TicketRecord,
            participant_id: int,
            thread: discord.Thread,
    ) -> None:
        participant_user = await self._resolve_ticket_user(participant_id)
        if participant_user is None:
            return

        try:
            async for history_message in thread.history(limit=25, oldest_first=True):
                if history_message.id == record.thread_start_message_id:
                    continue

                if should_relay_bot_thread_message(history_message):
                    dm_message = await self._send_command_result_to_participant(
                        record=record,
                        participant_id=participant_id,
                        message=history_message,
                    )
                    if dm_message is None:
                        continue
                    self._thread_to_dm_command_message_ids.setdefault(
                        history_message.id,
                        {},
                    )[participant_id] = dm_message.id
                    self._thread_to_dm_command_message_signatures[history_message.id] = (
                        self._build_command_relay_signature(history_message)
                    )
                    continue

                if (
                        history_message.id in self._thread_user_relay_message_ids
                        or record.relay_message_author_id(history_message.id) is not None
                        or history_message.webhook_id is not None
                ):
                    await self._send_user_relay_to_dm_participant(
                        ticket_user=participant_user,
                        message=history_message,
                    )
                    continue

                if history_message.author.bot:
                    if looks_like_user_relay_message(history_message.content):
                        await self._send_dm_with_retry(
                            participant_user,
                            truncate_relay_text(history_message.content),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    continue

                await self._send_staff_relay_to_dm_participant(
                    ticket_user=participant_user,
                    message=history_message,
                )
        except discord.HTTPException:
            LOGGER.exception(
                "TICKET_HISTORY_SYNC_FAILED thread=%s user_id=%s",
                record.thread_id,
                participant_id,
            )

    async def _send_dm_with_retry(
            self,
            recipient: discord.abc.User | discord.Member | discord.User,
            *args: object,
            **kwargs: object,
    ) -> discord.Message:
        last_error: discord.HTTPException | None = None
        has_files = bool(kwargs.get("file")) or bool(kwargs.get("files"))
        total_attempts = len(self._dm_retry_delays) + 1
        for attempt in range(total_attempts):
            try:
                return await recipient.send(*args, **kwargs)
            except discord.Forbidden:
                raise
            except discord.HTTPException as error:
                last_error = error
                if not should_retry_discord_http_error(error):
                    raise
                if has_files:
                    raise
                if attempt >= len(self._dm_retry_delays):
                    raise
                await asyncio.sleep(self._dm_retry_delays[attempt])

        if last_error is not None:
            raise last_error

        raise RuntimeError("Unexpected DM retry state")

    def _build_add_participants_summary(
            self,
            *,
            interaction: discord.Interaction[BignessLeagueBot],
            added: list[discord.Member],
            already_present: list[discord.Member],
            blocked_by_other_ticket: list[discord.Member],
            dm_failed: list[discord.Member],
    ) -> str:
        sections: list[str] = []
        if added:
            sections.append(
                interaction.client.localizer.translate(
                    I18N.messages.tickets.participants.summary.added,
                    locale=interaction.locale,
                    users=", ".join(member.mention for member in added),
                )
            )
        if already_present:
            sections.append(
                interaction.client.localizer.translate(
                    I18N.messages.tickets.participants.summary.already_present,
                    locale=interaction.locale,
                    users=", ".join(member.mention for member in already_present),
                )
            )
        if blocked_by_other_ticket:
            sections.append(
                interaction.client.localizer.translate(
                    I18N.messages.tickets.participants.summary.blocked_by_other_ticket,
                    locale=interaction.locale,
                    users=", ".join(member.mention for member in blocked_by_other_ticket),
                )
            )
        if dm_failed:
            sections.append(
                interaction.client.localizer.translate(
                    I18N.messages.tickets.participants.summary.dm_failed,
                    locale=interaction.locale,
                    users=", ".join(member.mention for member in dm_failed),
                )
            )

        if not sections:
            return interaction.client.localizer.translate(
                I18N.messages.tickets.participants.none_added,
                locale=interaction.locale,
            )

        return "\n".join(sections)

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
