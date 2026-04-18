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

from bigness_league_bot.application.services.tickets import (
    TICKET_CATEGORIES,
    TicketRecord,
    build_dm_message_link,
    current_utc_timestamp,
    require_ticket_category,
)
from bigness_league_bot.infrastructure.discord.tickets import (
    TicketIntegrationError,
    TicketStateStore,
    build_thread_tags_with_status,
    build_ticket_thread_name,
    resolve_forum_tag,
    resolve_ticket_status_tag,
    resolve_ticket_forum_channel,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.presentation.discord.views.ticket_message_embeds import (
    build_ticket_open_message_content,
    build_ticket_opening_notice,
    build_ticket_open_embed,
    resolve_success_emoji,
)
from bigness_league_bot.presentation.discord.views.ticket_thread_controls import (
    TicketThreadControlsView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)


class _TicketCategorySelect(discord.ui.Select["TicketPanelView"]):
    def __init__(self) -> None:
        super().__init__(
            custom_id="bigness_league:tickets:category",
            placeholder=I18N.messages.tickets.panel.select_placeholder.default,
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=category.label,
                    value=category.key,
                    emoji=category.emoji,
                )
                for category in TICKET_CATEGORIES
            ],
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TicketPanelView):
            return

        await view.open_ticket(interaction, self.values[0])


class TicketPanelView(discord.ui.View):
    def __init__(self, store: TicketStateStore) -> None:
        super().__init__(timeout=None)
        self.store = store
        self.add_item(_TicketCategorySelect())

    async def open_ticket(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            category_key: str,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await self._send_interaction_message(
                interaction,
                interaction.client.localizer.translate(
                    I18N.errors.channel_management.server_only,
                    locale=interaction.locale,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self._refresh_panel_message(interaction)
        async with self.store.creation_lock:
            try:
                category = require_ticket_category(category_key)
            except ValueError:
                await interaction.followup.send(
                    interaction.client.localizer.translate(
                        I18N.errors.tickets.category_unknown,
                        locale=interaction.locale,
                    ),
                    ephemeral=True,
                )
                return

            existing_ticket = self.store.active_for_user(interaction.user.id)
            if existing_ticket is not None:
                stale_thread = await self._resolve_existing_ticket_thread(
                    interaction,
                    existing_ticket.thread_id,
                )
                if stale_thread is None:
                    self.store.remove_thread(existing_ticket.thread_id)
                    existing_ticket = None

            if existing_ticket is not None:
                await interaction.followup.send(
                    self._build_existing_ticket_message(
                        interaction,
                        existing_ticket,
                    ),
                    ephemeral=True,
                )
                return

            try:
                ticket_number = self.store.next_ticket_number()
                created_at = current_utc_timestamp()
                forum_channel = await resolve_ticket_forum_channel(
                    interaction.client,
                    interaction.guild,
                )
                forum_tag = resolve_forum_tag(forum_channel, category)
                open_status_tag = resolve_ticket_status_tag(
                    forum_channel,
                    is_closed=False,
                )
                ticket_thread, thread_start_message_id = await self._create_ticket_thread(
                    interaction=interaction,
                    forum_channel=forum_channel,
                    forum_tag=forum_tag,
                    open_status_tag=open_status_tag,
                    category=category,
                    ticket_number=ticket_number,
                    created_at=created_at,
                )
            except TicketIntegrationError as error:
                await interaction.followup.send(
                    interaction.client.localizer.render(
                        error.message,
                        locale=interaction.locale,
                    ),
                    ephemeral=True,
                )
                return
            except discord.HTTPException:
                LOGGER.exception(
                    "TICKET_CREATE_FAILED user=%s(%s) category=%s",
                    interaction.user,
                    interaction.user.id,
                    category.key,
                )
                await interaction.followup.send(
                    interaction.client.localizer.translate(
                        I18N.errors.slash.http_error,
                        locale=interaction.locale,
                    ),
                    ephemeral=True,
                )
                return

            try:
                dm_message = await interaction.user.send(
                    content=build_ticket_open_message_content(),
                    embed=build_ticket_open_embed(
                        bot=interaction.client,
                        locale=interaction.locale,
                        guild=interaction.guild,
                        opened_by=interaction.user,
                        category_label=category.label,
                        ticket_number=ticket_number,
                        created_at=created_at,
                    ),
                    view=TicketThreadControlsView(self.store),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                        replied_user=False,
                    ),
                )
                await interaction.user.send(
                    build_ticket_opening_notice(interaction.user),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                        replied_user=False,
                    ),
                )
            except discord.Forbidden:
                await ticket_thread.send(
                    interaction.client.localizer.translate(
                        I18N.messages.tickets.open.dm_failed_thread,
                        locale=interaction.locale,
                        user=interaction.user.mention,
                    ),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                        replied_user=False,
                    ),
                )
                await ticket_thread.edit(
                    applied_tags=self._build_closed_thread_tags(ticket_thread),
                    archived=True,
                    locked=True,
                    reason=(
                        f"No se pudo abrir DM con {interaction.user} "
                        f"({interaction.user.id})"
                    ),
                )
                await interaction.followup.send(
                    interaction.client.localizer.translate(
                        I18N.messages.tickets.open.dm_failed_ephemeral,
                        locale=interaction.locale,
                    ),
                    ephemeral=True,
                )
                return
            except discord.HTTPException:
                await ticket_thread.edit(
                    applied_tags=self._build_closed_thread_tags(ticket_thread),
                    archived=True,
                    locked=True,
                    reason=(
                        f"Fallo HTTP al abrir DM con {interaction.user} "
                        f"({interaction.user.id})"
                    ),
                )
                LOGGER.exception(
                    "TICKET_DM_CREATE_FAILED user=%s(%s) thread=%s",
                    interaction.user,
                    interaction.user.id,
                    ticket_thread.id,
                )
                await interaction.followup.send(
                    interaction.client.localizer.translate(
                        I18N.errors.slash.http_error,
                        locale=interaction.locale,
                    ),
                    ephemeral=True,
                )
                return

            self.store.add(
                TicketRecord.create(
                    ticket_number=ticket_number,
                    user_id=interaction.user.id,
                    thread_id=ticket_thread.id,
                    forum_channel_id=forum_channel.id,
                    thread_start_message_id=thread_start_message_id,
                    dm_channel_id=dm_message.channel.id,
                    dm_start_message_id=dm_message.id,
                    category_key=category.key,
                    created_at=created_at,
                )
            )
            await interaction.followup.send(
                interaction.client.localizer.translate(
                    I18N.messages.tickets.open.created_ephemeral,
                    locale=interaction.locale,
                    emoji=resolve_success_emoji(interaction.guild),
                    message_link=dm_message.jump_url,
                ),
                ephemeral=True,
            )

    async def _create_ticket_thread(
            self,
            *,
            interaction: discord.Interaction[BignessLeagueBot],
            forum_channel: discord.ForumChannel,
            forum_tag: discord.ForumTag,
            open_status_tag: discord.ForumTag,
            category,
            ticket_number: int,
            created_at: str,
    ) -> tuple[discord.Thread, int]:
        thread_name = build_ticket_thread_name(
            member=interaction.user,
            category=category,
        )
        result = await forum_channel.create_thread(
            name=thread_name,
            content=build_ticket_open_message_content(),
            embed=build_ticket_open_embed(
                bot=interaction.client,
                locale=interaction.locale,
                guild=interaction.guild,
                opened_by=interaction.user,
                category_label=category.label,
                ticket_number=ticket_number,
                created_at=created_at,
            ),
            applied_tags=[forum_tag, open_status_tag],
            view=TicketThreadControlsView(self.store),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
                replied_user=False,
            ),
            reason=(
                f"{interaction.user} ({interaction.user.id}) abrio "
                f"ticket categoria={category.key}"
            ),
        )
        await result.thread.send(
            build_ticket_opening_notice(interaction.user),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
                replied_user=False,
            ),
        )
        return result.thread, result.message.id

    @staticmethod
    def _build_closed_thread_tags(
            thread: discord.Thread,
    ):
        forum_channel = thread.parent
        if not isinstance(forum_channel, discord.ForumChannel):
            return discord.utils.MISSING

        try:
            closed_status_tag = resolve_ticket_status_tag(
                forum_channel,
                is_closed=True,
            )
        except TicketIntegrationError:
            return discord.utils.MISSING

        return build_thread_tags_with_status(
            thread,
            status_tag=closed_status_tag,
        )

    @staticmethod
    async def _resolve_existing_ticket_thread(
            interaction: discord.Interaction[BignessLeagueBot],
            thread_id: int,
    ) -> discord.Thread | None:
        channel = interaction.client.get_channel(thread_id)
        if isinstance(channel, discord.Thread):
            return channel

        try:
            fetched_channel = await interaction.client.fetch_channel(thread_id)
        except discord.HTTPException:
            return None

        if isinstance(fetched_channel, discord.Thread):
            return fetched_channel

        return None

    @staticmethod
    def _build_existing_ticket_message(
            interaction: discord.Interaction[BignessLeagueBot],
            record: TicketRecord,
    ) -> str:
        dm_message_link = build_dm_message_link(
            channel_id=record.dm_channel_id,
            message_id=record.dm_start_message_id,
        )
        if dm_message_link is not None:
            return interaction.client.localizer.translate(
                I18N.messages.tickets.open.already_open_with_link,
                locale=interaction.locale,
                message_link=dm_message_link,
            )

        return interaction.client.localizer.translate(
            I18N.messages.tickets.open.already_open,
            locale=interaction.locale,
            thread_id=str(record.thread_id),
        )

    async def _refresh_panel_message(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        if interaction.message is None:
            return

        try:
            await interaction.message.edit(view=TicketPanelView(self.store))
        except discord.HTTPException:
            LOGGER.exception(
                "TICKET_PANEL_REFRESH_FAILED message=%s user=%s(%s)",
                interaction.message.id,
                interaction.user,
                interaction.user.id,
            )

    @staticmethod
    async def _send_interaction_message(
            interaction: discord.Interaction[BignessLeagueBot],
            message: str,
            *,
            ephemeral: bool = False,
    ) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
            return

        await interaction.response.send_message(message, ephemeral=ephemeral)
