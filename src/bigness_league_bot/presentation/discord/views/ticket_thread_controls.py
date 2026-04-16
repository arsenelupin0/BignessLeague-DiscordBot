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

from bigness_league_bot.application.services.tickets import (
    build_dm_message_link,
    build_guild_message_link,
    require_ticket_category,
)
from bigness_league_bot.infrastructure.discord.channel_management import (
    ChannelManagementError,
    ensure_allowed_member,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.presentation.discord.views.ticket_message_embeds import (
    build_ticket_close_embed,
)

if TYPE_CHECKING:
    from bigness_league_bot.application.services.tickets import TicketRecord
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class _CloseTicketButton(discord.ui.Button["TicketThreadControlsView"]):
    def __init__(self) -> None:
        super().__init__(
            label=I18N.messages.tickets.buttons.close_ticket.default,
            style=discord.ButtonStyle.danger,
            custom_id="bigness_league:tickets:close",
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TicketThreadControlsView):
            return

        await view.close_ticket(interaction)


class TicketThreadControlsView(discord.ui.View):
    def __init__(self, store: TicketStateStore) -> None:
        super().__init__(timeout=None)
        self.store = store
        self.add_item(_CloseTicketButton())

    async def close_ticket(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        is_dm_interaction = interaction.guild is None
        if is_dm_interaction:
            await interaction.response.defer()
            record = self.store.active_for_user(interaction.user.id)
            if record is None:
                await self._send_followup_message(
                    interaction,
                    interaction.client.localizer.translate(
                        I18N.messages.tickets.close.not_active,
                        locale=interaction.locale,
                    ),
                )
                return
            thread = await self._resolve_thread(interaction, record.thread_id)
            if thread is None:
                self.store.remove_thread(record.thread_id)
                await self._send_followup_message(
                    interaction,
                    interaction.client.localizer.translate(
                        I18N.messages.tickets.close.not_active,
                        locale=interaction.locale,
                    ),
                )
                return
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
            if not isinstance(interaction.user, discord.Member):
                await self._send_followup_message(
                    interaction,
                    interaction.client.localizer.translate(
                        I18N.errors.channel_management.server_only,
                        locale=interaction.locale,
                    ),
                    ephemeral=True,
                )
                return

            try:
                ensure_allowed_member(interaction.user)
            except ChannelManagementError as error:
                await self._send_followup_message(
                    interaction,
                    interaction.client.localizer.render(
                        error.message,
                        locale=interaction.locale,
                    ),
                    ephemeral=True,
                )
                return

            thread = interaction.channel
            if not isinstance(thread, discord.Thread):
                await self._send_followup_message(
                    interaction,
                    interaction.client.localizer.translate(
                        I18N.messages.tickets.close.not_ticket_thread,
                        locale=interaction.locale,
                    ),
                    ephemeral=True,
                )
                return

            record = self.store.active_for_thread(thread.id)
            if record is None:
                await self._send_followup_message(
                    interaction,
                    interaction.client.localizer.translate(
                        I18N.messages.tickets.close.not_active,
                        locale=interaction.locale,
                    ),
                    ephemeral=True,
                )
                return

        closed_record = self.store.close_thread(record.thread_id)
        if closed_record is None or closed_record.closed_at is None:
            await self._send_followup_message(
                interaction,
                interaction.client.localizer.translate(
                    I18N.messages.tickets.close.not_active,
                    locale=interaction.locale,
                ),
                ephemeral=not is_dm_interaction,
            )
            return

        category = self._resolve_category_label(closed_record)
        thread_ticket_link = build_guild_message_link(
            guild_id=thread.guild.id,
            channel_id=thread.id,
            message_id=closed_record.thread_start_message_id,
        )
        thread_close_embed = build_ticket_close_embed(
            bot=interaction.client,
            locale=interaction.locale,
            guild=thread.guild,
            closed_by=interaction.user,
            category_label=category,
            ticket_number=closed_record.ticket_number,
            ticket_link=thread_ticket_link,
            created_at=closed_record.created_at,
            closed_at=closed_record.closed_at,
            close_reason=None,
        )
        await thread.send(
            content=None,
            embed=thread_close_embed,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
                replied_user=False,
            ),
        )

        await self._send_close_dm(
            interaction=interaction,
            record=closed_record,
            category_label=category,
            guild=thread.guild,
            is_dm_interaction=is_dm_interaction,
        )

        await thread.edit(
            archived=True,
            locked=True,
            reason=(
                f"{interaction.user} ({interaction.user.id}) cerro "
                f"ticket={thread.id}"
            ),
        )
        if not is_dm_interaction:
            await self._send_followup_message(
                interaction,
                interaction.client.localizer.translate(
                    I18N.messages.tickets.close.closed_ephemeral,
                    locale=interaction.locale,
                ),
                ephemeral=True,
            )

    async def _send_close_dm(
            self,
            *,
            interaction: discord.Interaction[BignessLeagueBot],
            record: TicketRecord,
            category_label: str,
            guild: discord.Guild,
            is_dm_interaction: bool,
    ) -> None:
        dm_ticket_link = build_dm_message_link(
            channel_id=record.dm_channel_id,
            message_id=record.dm_start_message_id,
        )
        close_embed = build_ticket_close_embed(
            bot=interaction.client,
            locale=interaction.locale,
            guild=guild,
            closed_by=interaction.user,
            category_label=category_label,
            ticket_number=record.ticket_number,
            ticket_link=dm_ticket_link,
            created_at=record.created_at,
            closed_at=record.closed_at or record.created_at,
            close_reason=None,
        )
        try:
            if is_dm_interaction and isinstance(interaction.channel, discord.DMChannel):
                await interaction.channel.send(embed=close_embed)
                return

            ticket_user = await interaction.client.fetch_user(record.user_id)
            await ticket_user.send(embed=close_embed)
        except discord.HTTPException:
            pass

    @staticmethod
    def _resolve_category_label(record: TicketRecord) -> str:
        try:
            return require_ticket_category(record.category_key).label
        except ValueError:
            return record.category_key

    @staticmethod
    async def _resolve_thread(
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
    async def _send_followup_message(
            interaction: discord.Interaction[BignessLeagueBot],
            message: str,
            *,
            ephemeral: bool = False,
    ) -> None:
        if interaction.guild is None:
            await interaction.followup.send(message)
            return

        await interaction.followup.send(message, ephemeral=ephemeral)
