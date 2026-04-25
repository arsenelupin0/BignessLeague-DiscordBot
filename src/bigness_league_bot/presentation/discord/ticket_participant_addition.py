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

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.tickets import (
    format_ticket_number,
    TicketRecord,
    require_ticket_category,
)
from bigness_league_bot.infrastructure.discord.ticket_participant_messenger import (
    TicketParticipantMessenger,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.presentation.discord.views.ticket_message_embeds import (
    build_ticket_message_content,
    build_ticket_open_embed,
)
from bigness_league_bot.presentation.discord.views.ticket_thread_controls import (
    TicketThreadControlsView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

ResolveTicketUser = Callable[[int], Awaitable[discord.User | None]]
SendDm = Callable[..., Awaitable[discord.Message]]


class TicketParticipantAddition:
    def __init__(
            self,
            *,
            bot: BignessLeagueBot,
            store: TicketStateStore,
            participant_messenger: TicketParticipantMessenger,
            resolve_ticket_user: ResolveTicketUser,
            send_dm: SendDm,
            thread_user_relay_message_ids: set[int],
    ) -> None:
        self.bot = bot
        self.store = store
        self.participant_messenger = participant_messenger
        self._resolve_ticket_user = resolve_ticket_user
        self._send_dm = send_dm
        self._thread_user_relay_message_ids = thread_user_relay_message_ids

    async def add_members_to_ticket(
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
            dm_message = await self._send_welcome_dm(
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
            await self.participant_messenger.sync_history_to_participant(
                record=updated_record,
                participant_id=member.id,
                thread=thread,
                thread_user_relay_message_ids=self._thread_user_relay_message_ids,
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
            self._build_summary(
                interaction=interaction,
                added=successfully_added,
                already_present=already_present,
                blocked_by_other_ticket=blocked_by_other_ticket,
                dm_failed=dm_failed,
            ),
            ephemeral=True,
        )

    async def _send_welcome_dm(
            self,
            *,
            member: discord.Member,
            owner: discord.abc.User | discord.Member,
            record: TicketRecord,
            category_label: str,
            locale: str | discord.Locale | None,
            guild: discord.Guild | None,
    ) -> discord.Message | None:
        if guild is None:
            return None

        try:
            return await self._send_dm(
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

    @staticmethod
    def _build_summary(
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
