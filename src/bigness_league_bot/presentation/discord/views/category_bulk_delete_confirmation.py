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
    bulk_delete_category_channels,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class _ConfirmCategoryBulkDeleteButton(discord.ui.Button["CategoryBulkDeleteConfirmationView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.danger)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, CategoryBulkDeleteConfirmationView):
            return

        await view.confirm_bulk_delete(interaction)


class _CancelCategoryBulkDeleteButton(discord.ui.Button["CategoryBulkDeleteConfirmationView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, CategoryBulkDeleteConfirmationView):
            return

        await view.cancel_bulk_delete(interaction)


class CategoryBulkDeleteConfirmationView(discord.ui.View):
    def __init__(
            self,
            *,
            category: discord.CategoryChannel,
            actor: discord.Member,
            localizer: LocalizationService,
            locale: str | discord.Locale,
            timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.category = category
        self.actor = actor
        self.localizer = localizer
        self.locale = locale
        self.message: discord.InteractionMessage | None = None
        self.add_item(
            _ConfirmCategoryBulkDeleteButton(
                label=self.localizer.translate(
                    I18N.messages.category_bulk_delete_confirmation.buttons.confirm,
                    locale=self.locale,
                )
            )
        )
        self.add_item(
            _CancelCategoryBulkDeleteButton(
                label=self.localizer.translate(
                    I18N.messages.category_bulk_delete_confirmation.buttons.cancel,
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
                I18N.messages.category_bulk_delete_confirmation.only_actor,
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
                    I18N.messages.category_bulk_delete_confirmation.timeout,
                    locale=self.locale,
                ),
                view=self,
            )

    async def confirm_bulk_delete(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        self._disable_children()
        await interaction.response.edit_message(
            content=self.localizer.translate(
                I18N.messages.category_bulk_delete_confirmation.processing,
                locale=interaction.locale,
                category_name=self.category.name,
            ),
            view=self,
        )
        result = await bulk_delete_category_channels(self.category, self.actor)
        await interaction.edit_original_response(
            content=self.localizer.translate(
                I18N.actions.channel_management.bulk_delete_summary,
                locale=interaction.locale,
                deleted_count=str(result.deleted_count),
                category_name=result.category_name,
            ),
            view=self,
        )
        self.stop()

    async def cancel_bulk_delete(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        self._disable_children()
        await interaction.response.edit_message(
            content=self.localizer.translate(
                I18N.messages.category_bulk_delete_confirmation.cancelled,
                locale=interaction.locale,
            ),
            view=self,
        )
        self.stop()

    def _disable_children(self) -> None:
        for child in self.children:
            child.disabled = True
