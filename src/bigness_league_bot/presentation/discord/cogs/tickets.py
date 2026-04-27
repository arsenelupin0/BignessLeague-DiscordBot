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
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.tickets import (
    TicketRecord,
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
from bigness_league_bot.infrastructure.discord.ticket_command_mirror import (
    TicketCommandMirror,
)
from bigness_league_bot.infrastructure.discord.ticket_participant_messenger import (
    TicketParticipantMessenger,
)
from bigness_league_bot.infrastructure.discord.ticket_relay_messages import (
    should_relay_bot_thread_message,
    should_retry_discord_http_error,
)
from bigness_league_bot.infrastructure.discord.ticket_thread_relay import (
    TicketThreadRelay,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str
from bigness_league_bot.presentation.discord.ticket_ai_interactions import (
    TicketAiInteractions,
)
from bigness_league_bot.presentation.discord.ticket_inactivity import (
    TicketInactivityMonitor,
)
from bigness_league_bot.presentation.discord.ticket_participant_addition import (
    TicketParticipantAddition,
)
from bigness_league_bot.presentation.discord.views.ticket_panel import TicketPanelView
from bigness_league_bot.presentation.discord.views.ticket_thread_controls import (
    TicketThreadControlsView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class TicketsCog(commands.Cog):
    def __init__(self, bot: BignessLeagueBot, store: TicketStateStore) -> None:
        self.bot = bot
        self.store = store
        self._pending_initial_command_mirror_tasks: dict[int, asyncio.Task[None]] = {}
        self._dm_retry_delays: tuple[float, ...] = (0.75, 1.5)
        self.thread_relay = TicketThreadRelay(bot=bot, store=store)
        self.command_mirror = TicketCommandMirror(
            bot=bot,
            store=store,
            resolve_ticket_user=self._resolve_ticket_user,
            send_dm=self._send_dm_with_retry,
        )
        self.participant_messenger = TicketParticipantMessenger(
            bot=bot,
            store=store,
            command_mirror=self.command_mirror,
            resolve_ticket_user=self._resolve_ticket_user,
            send_dm=self._send_dm_with_retry,
            relay_mention=self.thread_relay.relay_clickable_mention,
        )
        self.ticket_ai_interactions = TicketAiInteractions(
            bot=bot,
            participant_messenger=self.participant_messenger,
        )
        self.participant_addition = TicketParticipantAddition(
            bot=bot,
            store=store,
            participant_messenger=self.participant_messenger,
            resolve_ticket_user=self._resolve_ticket_user,
            send_dm=self._send_dm_with_retry,
            thread_user_relay_message_ids=self.thread_relay.message_ids,
        )
        self.inactivity_monitor = TicketInactivityMonitor(bot=bot, store=store)

    async def cog_load(self) -> None:
        self.inactivity_monitor.start()

    async def cog_unload(self) -> None:
        self.inactivity_monitor.stop()

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
        await self.participant_addition.add_members_to_ticket(
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
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
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
            guild,
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
        await self.participant_addition.add_members_to_ticket(
            interaction=interaction,
            thread=thread,
            record=record,
            requested_members=requested_members,
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
        await self.ticket_ai_interactions.send_status(interaction)

    @commands.Cog.listener()
    async def on_interaction(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.command_mirror.remember_interaction_command(interaction)

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
            if message.id in self.thread_relay.message_ids:
                return
            if message.author.bot:
                await self._schedule_initial_bot_thread_message_to_user(message)
                return
            await self._relay_staff_message_to_user(message)

    @commands.Cog.listener()
    async def on_message_edit(
            self,
            _before: discord.Message,
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
            await self.mirror_thread_command_message(latest_message)
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

    async def mirror_thread_command_message(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        return await self.command_mirror.mirror_thread_command_message(
            message,
            command_name=command_name,
        )

    async def mirror_thread_command_message_edit(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        return await self.command_mirror.mirror_thread_command_message_edit(
            message,
            command_name=command_name,
        )

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

    async def _send_dm_with_retry(
            self,
            recipient: discord.User | discord.Member,
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
