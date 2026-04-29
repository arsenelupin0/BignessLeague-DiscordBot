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
    archive_text_channel,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class _ConfirmArchiveButton(discord.ui.Button["ChannelArchiveConfirmationView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.danger)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, ChannelArchiveConfirmationView):
            return

        await view.confirm_archive(interaction)


class _CancelArchiveButton(discord.ui.Button["ChannelArchiveConfirmationView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, ChannelArchiveConfirmationView):
            return

        await view.cancel_archive(interaction)


class ChannelArchiveConfirmationView(discord.ui.View):
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
            _ConfirmArchiveButton(
                label=self.localizer.translate(
                    I18N.messages.channel_archive_confirmation.buttons.confirm,
                    locale=self.locale,
                )
            )
        )
        self.add_item(
            _CancelArchiveButton(
                label=self.localizer.translate(
                    I18N.messages.channel_archive_confirmation.buttons.cancel,
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
                I18N.messages.channel_archive_confirmation.only_actor,
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
                    I18N.messages.channel_archive_confirmation.timeout,
                    locale=self.locale,
                ),
                view=self,
            )

    async def confirm_archive(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        self._disable_children()
        await interaction.response.edit_message(
            content=self.localizer.translate(
                I18N.messages.channel_archive_confirmation.processing,
                locale=interaction.locale,
            ),
            view=self,
        )
        self.stop()
        action_result = await archive_text_channel(
            self.channel,
            self.actor,
            interaction.client.settings,
        )
        await interaction.edit_original_response(
            content=self.localizer.render(
                action_result.summary,
                locale=interaction.locale,
            ),
            view=self,
        )

    async def cancel_archive(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        self._disable_children()
        await interaction.response.edit_message(
            content=self.localizer.translate(
                I18N.messages.channel_archive_confirmation.cancelled,
                locale=interaction.locale,
            ),
            view=self,
        )
        self.stop()

    def _disable_children(self) -> None:
        for child in self.children:
            child.disabled = True
