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

from dataclasses import dataclass
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
from bigness_league_bot.infrastructure.discord.tickets import (
    TicketIntegrationError,
    build_thread_tags_with_status,
    resolve_ticket_status_tag,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService
from bigness_league_bot.presentation.discord.views.ticket_message_embeds import (
    build_ticket_close_embed,
)

if TYPE_CHECKING:
    from bigness_league_bot.application.services.tickets import (
        TicketParticipant,
        TicketRecord,
    )
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


@dataclass(frozen=True, slots=True)
class _ResolvedTicketCloseContext:
    record: TicketRecord
    thread: discord.Thread
    is_dm_interaction: bool


class _CloseTicketButton(discord.ui.Button["TicketThreadControlsView"]):
    def __init__(self, *, disabled: bool = False) -> None:
        super().__init__(
            label=I18N.messages.tickets.buttons.close_ticket.default,
            style=discord.ButtonStyle.secondary,
            custom_id="bigness_league:tickets:close",
            disabled=disabled,
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TicketThreadControlsView):
            return

        await view.prompt_close_confirmation(
            interaction,
            require_reason=False,
        )


class _CloseWithReasonButton(discord.ui.Button["TicketThreadControlsView"]):
    def __init__(self, *, disabled: bool = False) -> None:
        super().__init__(
            label=I18N.messages.tickets.buttons.close_with_reason.default,
            style=discord.ButtonStyle.danger,
            custom_id="bigness_league:tickets:close_with_reason",
            disabled=disabled,
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TicketThreadControlsView):
            return

        await view.prompt_close_confirmation(
            interaction,
            require_reason=True,
        )


class _ConfirmCloseButton(discord.ui.Button["TicketCloseConfirmationView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.danger)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TicketCloseConfirmationView):
            return

        await view.confirm(interaction)


class _CancelCloseButton(discord.ui.Button["TicketCloseConfirmationView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TicketCloseConfirmationView):
            return

        await view.cancel(interaction)


class TicketCloseReasonModal(discord.ui.Modal):
    def __init__(
            self,
            *,
            store: TicketStateStore,
            confirmation_view: "TicketCloseConfirmationView",
            localizer: LocalizationService,
            locale: str | discord.Locale | None,
    ) -> None:
        super().__init__(
            title=localizer.translate(
                I18N.messages.tickets.close.reason_modal.title,
                locale=locale,
            )
        )
        self.store = store
        self.confirmation_view = confirmation_view
        self.reason = discord.ui.TextInput(
            label=localizer.translate(
                I18N.messages.tickets.close.reason_modal.label,
                locale=locale,
            ),
            placeholder=localizer.translate(
                I18N.messages.tickets.close.reason_modal.placeholder,
                locale=locale,
            ),
            style=discord.TextStyle.paragraph,
            max_length=1_000,
            required=True,
        )
        self.add_item(self.reason)

    async def on_submit(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        await interaction.response.defer()
        await self.confirmation_view.delete_prompt()
        self.confirmation_view.stop()
        await _execute_ticket_close(
            store=self.store,
            interaction=interaction,
            close_reason=self.reason.value.strip(),
        )


class TicketCloseConfirmationView(discord.ui.View):
    def __init__(
            self,
            *,
            store: TicketStateStore,
            actor_id: int,
            localizer: LocalizationService,
            locale: str | discord.Locale | None,
            require_reason: bool,
            timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.store = store
        self.actor_id = actor_id
        self.localizer = localizer
        self.locale = locale
        self.require_reason = require_reason
        self.message: discord.InteractionMessage | None = None
        self.add_item(
            _ConfirmCloseButton(
                label=self.localizer.translate(
                    (
                        I18N.messages.tickets.close.confirm.buttons.add_reason
                        if self.require_reason
                        else I18N.messages.tickets.close.confirm.buttons.confirm
                    ),
                    locale=self.locale,
                )
            )
        )
        self.add_item(
            _CancelCloseButton(
                label=self.localizer.translate(
                    I18N.messages.tickets.close.confirm.buttons.cancel,
                    locale=self.locale,
                )
            )
        )

    async def interaction_check(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> bool:
        if interaction.user.id == self.actor_id:
            return True

        await _send_interaction_message(
            interaction,
            interaction.client.localizer.translate(
                I18N.messages.tickets.close.only_actor,
                locale=interaction.locale,
            ),
            ephemeral=interaction.guild is not None,
        )
        return False

    async def on_timeout(self) -> None:
        self._disable_children()
        if self.message is None:
            return

        try:
            await self.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    async def confirm(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        if self.require_reason:
            await interaction.response.send_modal(
                TicketCloseReasonModal(
                    store=self.store,
                    confirmation_view=self,
                    localizer=self.localizer,
                    locale=interaction.locale,
                )
            )
            return

        await interaction.response.defer()
        await self.delete_prompt(interaction)
        self.stop()
        await _execute_ticket_close(
            store=self.store,
            interaction=interaction,
            close_reason=None,
        )

    async def cancel(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        await interaction.response.defer()
        await self.delete_prompt(interaction)
        self.stop()

    async def delete_prompt(
            self,
            interaction: discord.Interaction[BignessLeagueBot] | None = None,
    ) -> None:
        self._disable_children()
        try:
            if self.message is not None:
                await self.message.delete()
                return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        if interaction is None:
            return

        try:
            await interaction.delete_original_response()
            return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        message = interaction.message
        if message is None:
            return

        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    def _disable_children(self) -> None:
        for child in self.children:
            child.disabled = True


class TicketThreadControlsView(discord.ui.View):
    def __init__(self, store: TicketStateStore, *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.store = store
        self.add_item(_CloseTicketButton(disabled=disabled))
        self.add_item(_CloseWithReasonButton(disabled=disabled))

    async def prompt_close_confirmation(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            require_reason: bool,
    ) -> None:
        resolved_context = await _resolve_close_context(
            store=self.store,
            interaction=interaction,
        )
        if resolved_context is None:
            return

        confirmation_view = TicketCloseConfirmationView(
            store=self.store,
            actor_id=interaction.user.id,
            localizer=interaction.client.localizer,
            locale=interaction.locale,
            require_reason=require_reason,
        )
        await interaction.response.send_message(
            interaction.client.localizer.translate(
                (
                    I18N.messages.tickets.close.confirm_reason_prompt
                    if require_reason
                    else I18N.messages.tickets.close.confirm_prompt
                ),
                locale=interaction.locale,
            ),
            view=confirmation_view,
            ephemeral=not resolved_context.is_dm_interaction,
        )
        try:
            confirmation_view.message = await interaction.original_response()
        except discord.HTTPException:
            confirmation_view.message = None


async def _execute_ticket_close(
        *,
        store: TicketStateStore,
        interaction: discord.Interaction[BignessLeagueBot],
        close_reason: str | None,
) -> None:
    resolved_context = await _resolve_close_context(
        store=store,
        interaction=interaction,
    )
    if resolved_context is None:
        return

    closed_record = store.close_thread(resolved_context.record.thread_id)
    if closed_record is None or closed_record.closed_at is None:
        await _send_interaction_message(
            interaction,
            interaction.client.localizer.translate(
                I18N.messages.tickets.close.not_active,
                locale=interaction.locale,
            ),
            ephemeral=interaction.guild is not None,
        )
        return

    category_label = _resolve_category_label(closed_record)
    thread_ticket_link = build_guild_message_link(
        guild_id=resolved_context.thread.guild.id,
        channel_id=resolved_context.thread.id,
        message_id=closed_record.thread_start_message_id,
    )
    thread_close_embed = build_ticket_close_embed(
        bot=interaction.client,
        locale=interaction.locale,
        guild=resolved_context.thread.guild,
        closed_by=interaction.user,
        category_label=category_label,
        ticket_number=closed_record.ticket_number,
        ticket_link=thread_ticket_link,
        created_at=closed_record.created_at,
        closed_at=closed_record.closed_at,
        close_reason=close_reason,
    )
    await resolved_context.thread.send(
        embed=thread_close_embed,
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
            replied_user=False,
        ),
    )

    await _send_close_dm(
        interaction=interaction,
        record=closed_record,
        category_label=category_label,
        guild=resolved_context.thread.guild,
        is_dm_interaction=resolved_context.is_dm_interaction,
        close_reason=close_reason,
    )
    await _disable_ticket_start_controls(
        store=store,
        interaction=interaction,
        record=closed_record,
        thread=resolved_context.thread,
    )

    await resolved_context.thread.edit(
        applied_tags=_build_closed_thread_tags(resolved_context.thread),
        archived=True,
        locked=True,
        reason=(
            f"{interaction.user} ({interaction.user.id}) cerro "
            f"ticket={resolved_context.thread.id}"
        ),
    )
    if not resolved_context.is_dm_interaction:
        await _send_interaction_message(
            interaction,
            interaction.client.localizer.translate(
                I18N.messages.tickets.close.closed_ephemeral,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )


async def _resolve_close_context(
        *,
        store: TicketStateStore,
        interaction: discord.Interaction[BignessLeagueBot],
) -> _ResolvedTicketCloseContext | None:
    if interaction.guild is None:
        record = store.active_for_user(interaction.user.id)
        if record is None:
            await _send_interaction_message(
                interaction,
                interaction.client.localizer.translate(
                    I18N.messages.tickets.close.not_active,
                    locale=interaction.locale,
                ),
            )
            return None

        thread = await _resolve_thread(interaction, record.thread_id)
        if thread is None:
            store.remove_thread(record.thread_id)
            await _send_interaction_message(
                interaction,
                interaction.client.localizer.translate(
                    I18N.messages.tickets.close.not_active,
                    locale=interaction.locale,
                ),
            )
            return None

        return _ResolvedTicketCloseContext(
            record=record,
            thread=thread,
            is_dm_interaction=True,
        )

    if not isinstance(interaction.user, discord.Member):
        await _send_interaction_message(
            interaction,
            interaction.client.localizer.translate(
                I18N.errors.channel_management.server_only,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return None

    try:
        ensure_allowed_member(interaction.user)
    except ChannelManagementError as error:
        await _send_interaction_message(
            interaction,
            interaction.client.localizer.render(
                error.message,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return None

    thread = interaction.channel
    if not isinstance(thread, discord.Thread):
        await _send_interaction_message(
            interaction,
            interaction.client.localizer.translate(
                I18N.messages.tickets.close.not_ticket_thread,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return None

    record = store.active_for_thread(thread.id)
    if record is None:
        await _send_interaction_message(
            interaction,
            interaction.client.localizer.translate(
                I18N.messages.tickets.close.not_active,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return None

    return _ResolvedTicketCloseContext(
        record=record,
        thread=thread,
        is_dm_interaction=False,
    )


async def _send_close_dm(
        *,
        interaction: discord.Interaction[BignessLeagueBot],
        record: TicketRecord,
        category_label: str,
        guild: discord.Guild,
        is_dm_interaction: bool,
        close_reason: str | None,
) -> None:
    for participant in record.participants:
        try:
            dm_ticket_link = build_dm_message_link(
                channel_id=participant.dm_channel_id,
                message_id=participant.dm_start_message_id,
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
                close_reason=close_reason,
            )
            if (
                    is_dm_interaction
                    and interaction.user.id == participant.user_id
                    and isinstance(interaction.channel, discord.DMChannel)
            ):
                await interaction.channel.send(embed=close_embed)
                continue

            ticket_user = await interaction.client.fetch_user(participant.user_id)
            await ticket_user.send(embed=close_embed)
        except discord.HTTPException:
            continue


async def _disable_ticket_start_controls(
        *,
        store: TicketStateStore,
        interaction: discord.Interaction[BignessLeagueBot],
        record: TicketRecord,
        thread: discord.Thread,
) -> None:
    await _disable_message_controls(
        channel=thread,
        message_id=record.thread_start_message_id,
        store=store,
    )
    for participant in record.participants:
        dm_channel = await _resolve_dm_channel(
            interaction=interaction,
            participant=participant,
        )
        if dm_channel is None:
            continue

        await _disable_message_controls(
            channel=dm_channel,
            message_id=participant.dm_start_message_id,
            store=store,
        )


async def _resolve_dm_channel(
        *,
        interaction: discord.Interaction[BignessLeagueBot],
        participant: TicketParticipant,
) -> discord.DMChannel | None:
    if participant.dm_channel_id is not None:
        cached_channel = interaction.client.get_channel(participant.dm_channel_id)
        if isinstance(cached_channel, discord.DMChannel):
            return cached_channel

    try:
        ticket_user = await interaction.client.fetch_user(participant.user_id)
        return await ticket_user.create_dm()
    except discord.HTTPException:
        return None


async def _disable_message_controls(
        *,
        channel: discord.abc.Messageable,
        message_id: int | None,
        store: TicketStateStore,
) -> None:
    if message_id is None:
        return

    try:
        message = await channel.fetch_message(message_id)
        await message.edit(view=TicketThreadControlsView(store, disabled=True))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        return


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


def _resolve_category_label(record: TicketRecord) -> str:
    try:
        return require_ticket_category(record.category_key).label
    except ValueError:
        return record.category_key


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


async def _send_interaction_message(
        interaction: discord.Interaction[BignessLeagueBot],
        message: str,
        *,
        ephemeral: bool = False,
) -> None:
    if interaction.response.is_done():
        if interaction.guild is None:
            await interaction.followup.send(message)
            return

        await interaction.followup.send(message, ephemeral=ephemeral)
        return

    if interaction.guild is None:
        await interaction.response.send_message(message)
        return

    await interaction.response.send_message(message, ephemeral=ephemeral)
