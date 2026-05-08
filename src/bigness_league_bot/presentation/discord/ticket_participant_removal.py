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
    TicketRecord,
    build_dm_message_link,
    build_guild_message_link,
    current_utc_timestamp,
    require_ticket_category,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.presentation.discord.views.ticket_message_embeds import (
    build_ticket_close_embed,
)
from bigness_league_bot.presentation.discord.views.ticket_thread_controls import (
    TicketThreadControlsView,
)

if TYPE_CHECKING:
    from bigness_league_bot.application.services.tickets import TicketParticipant
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class TicketParticipantRemoval:
    def __init__(
            self,
            *,
            bot: BignessLeagueBot,
            store: TicketStateStore,
    ) -> None:
        self.bot = bot
        self.store = store

    async def close_ticket_for_member(
            self,
            *,
            interaction: discord.Interaction[BignessLeagueBot],
            thread: discord.Thread,
            record: TicketRecord,
            member: discord.Member,
            reason: str,
    ) -> None:
        participant = record.participant_for_user(member.id)
        if participant is None:
            await interaction.followup.send(
                interaction.client.localizer.translate(
                    I18N.messages.tickets.participants.close_for_user.not_in_ticket,
                    locale=interaction.locale,
                    user=member.mention,
                ),
                ephemeral=True,
            )
            return

        if len(record.active_participants) <= 1:
            await interaction.followup.send(
                interaction.client.localizer.translate(
                    I18N.messages.tickets.participants.close_for_user.last_participant,
                    locale=interaction.locale,
                ),
                ephemeral=True,
            )
            return

        closed_at = current_utc_timestamp()
        updated_record = record.with_closed_participant(
            user_id=member.id,
            close_reason=reason,
            closed_at=closed_at,
        )
        self.store.update(updated_record)

        category_label = _resolve_category_label(record)
        thread_ticket_link = build_guild_message_link(
            guild_id=thread.guild.id,
            channel_id=thread.id,
            message_id=record.thread_start_message_id,
        )
        await thread.send(
            embed=build_ticket_close_embed(
                bot=self.bot,
                locale=interaction.locale,
                guild=thread.guild,
                closed_by=interaction.user,
                category_label=category_label,
                ticket_number=record.ticket_number,
                ticket_link=thread_ticket_link,
                created_at=record.created_at,
                closed_at=closed_at,
                close_reason=reason,
            ),
            content=interaction.client.localizer.translate(
                I18N.messages.tickets.participants.close_for_user.thread_notice,
                locale=interaction.locale,
                user=member.mention,
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
                replied_user=False,
            ),
        )

        await self._send_member_close_dm(
            member=member,
            record=record,
            category_label=category_label,
            closed_by=interaction.user,
            locale=interaction.locale,
            guild=thread.guild,
            closed_at=closed_at,
            reason=reason,
        )
        await self._disable_participant_controls(participant=participant)

        await interaction.followup.send(
            interaction.client.localizer.translate(
                I18N.messages.tickets.participants.close_for_user.closed_ephemeral,
                locale=interaction.locale,
                user=member.mention,
            ),
            ephemeral=True,
        )

    async def _send_member_close_dm(
            self,
            *,
            member: discord.Member,
            record: TicketRecord,
            category_label: str,
            closed_by: discord.abc.User | discord.Member,
            locale: str | discord.Locale | None,
            guild: discord.Guild,
            closed_at: str,
            reason: str,
    ) -> None:
        participant = record.participant_for_user(member.id)
        if participant is None:
            return

        try:
            await member.send(
                embed=build_ticket_close_embed(
                    bot=self.bot,
                    locale=locale,
                    guild=guild,
                    closed_by=closed_by,
                    category_label=category_label,
                    ticket_number=record.ticket_number,
                    ticket_link=build_dm_message_link(
                        channel_id=participant.dm_channel_id,
                        message_id=participant.dm_start_message_id,
                    ),
                    created_at=record.created_at,
                    closed_at=closed_at,
                    close_reason=reason,
                ),
            )
        except discord.HTTPException:
            await self._notify_dm_failed(member=member, record=record)

    async def _disable_participant_controls(
            self,
            *,
            participant: TicketParticipant,
    ) -> None:
        if participant.dm_start_message_id is None:
            return

        dm_channel = await self._resolve_dm_channel(participant)
        if dm_channel is None:
            return

        try:
            message = await dm_channel.fetch_message(participant.dm_start_message_id)
            await message.edit(view=TicketThreadControlsView(self.store, disabled=True))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    async def _resolve_dm_channel(
            self,
            participant: TicketParticipant,
    ) -> discord.DMChannel | None:
        if participant.dm_channel_id is not None:
            cached_channel = self.bot.get_channel(participant.dm_channel_id)
            if isinstance(cached_channel, discord.DMChannel):
                return cached_channel

        try:
            ticket_user = await self.bot.fetch_user(participant.user_id)
            return await ticket_user.create_dm()
        except discord.HTTPException:
            return None

    async def _notify_dm_failed(
            self,
            *,
            member: discord.Member,
            record: TicketRecord,
    ) -> None:
        thread = self.bot.get_channel(record.thread_id)
        if not isinstance(thread, discord.Thread):
            return

        await thread.send(
            self.bot.localizer.translate(
                I18N.messages.tickets.relay.dm_failed_for_staff,
                user_id=str(member.id),
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )


def _resolve_category_label(record: TicketRecord) -> str:
    try:
        return require_ticket_category(record.category_key).label
    except ValueError:
        return record.category_key
