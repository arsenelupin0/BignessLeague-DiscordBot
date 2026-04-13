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

from bigness_league_bot.infrastructure.discord.channel_management import (
    apply_matchday_closed,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class _ConfirmMatchdayCloseButton(discord.ui.Button["ChannelMatchdayCloseConfirmationView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.danger)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, ChannelMatchdayCloseConfirmationView):
            return

        await view.confirm_matchday_close(interaction)


class _CancelMatchdayCloseButton(discord.ui.Button["ChannelMatchdayCloseConfirmationView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, ChannelMatchdayCloseConfirmationView):
            return

        await view.cancel_matchday_close(interaction)


class ChannelMatchdayCloseConfirmationView(discord.ui.View):
    def __init__(
            self,
            *,
            channel: discord.TextChannel,
            actor: discord.Member,
            localizer: LocalizationService,
            locale: str | discord.Locale,
            timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.channel = channel
        self.actor = actor
        self.localizer = localizer
        self.locale = locale
        self.message: discord.InteractionMessage | None = None
        self.add_item(
            _ConfirmMatchdayCloseButton(
                label=self.localizer.translate(
                    I18N.messages.channel_matchday_close_confirmation.buttons.confirm,
                    locale=self.locale,
                )
            )
        )
        self.add_item(
            _CancelMatchdayCloseButton(
                label=self.localizer.translate(
                    I18N.messages.channel_matchday_close_confirmation.buttons.cancel,
                    locale=self.locale,
                )
            )
        )

    async def interaction_check(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> bool:
        if interaction.user.id == self.actor.id:
            return True

        await interaction.response.send_message(
            self.localizer.translate(
                I18N.messages.channel_matchday_close_confirmation.only_actor,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        self._disable_children()
        if self.message is not None:
            await self.message.edit(
                content=self.localizer.translate(
                    I18N.messages.channel_matchday_close_confirmation.timeout,
                    locale=self.locale,
                ),
                view=self,
            )

    async def confirm_matchday_close(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        self._disable_children()
        await interaction.response.edit_message(
            content=self.localizer.translate(
                I18N.messages.channel_matchday_close_confirmation.closing,
                locale=interaction.locale,
            ),
            view=self,
        )
        action_result = await apply_matchday_closed(self.channel, self.actor)
        if self.message is not None:
            await self.message.edit(
                content=self.localizer.render(
                    action_result.summary,
                    locale=interaction.locale,
                ),
                view=self,
            )
        self.stop()

    async def cancel_matchday_close(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        self._disable_children()
        await interaction.response.edit_message(
            content=self.localizer.translate(
                I18N.messages.channel_matchday_close_confirmation.cancelled,
                locale=interaction.locale,
            ),
            view=self,
        )
        self.stop()

    def _disable_children(self) -> None:
        for child in self.children:
            child.disabled = True
