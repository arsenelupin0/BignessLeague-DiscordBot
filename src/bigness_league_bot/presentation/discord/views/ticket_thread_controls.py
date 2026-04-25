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

from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService
from bigness_league_bot.presentation.discord.ticket_thread_closure import (
    execute_ticket_close,
    resolve_close_context,
    send_interaction_message,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


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
        await execute_ticket_close(
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

        await send_interaction_message(
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
        await execute_ticket_close(
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
        resolved_context = await resolve_close_context(
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
