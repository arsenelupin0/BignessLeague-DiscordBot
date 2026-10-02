from __future__ import annotations

import discord

from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService


class DiscordVerificationView(discord.ui.View):
    def __init__(self, *, pages: tuple[str, ...], actor_id: int,
                 localizer: LocalizationService, locale: str | discord.Locale) -> None:
        super().__init__(timeout=300)
        self.pages = pages
        self.actor_id = actor_id
        self.localizer = localizer
        self.locale = locale
        self.index = 0
        self.message: discord.WebhookMessage | None = None
        self.previous.label = localizer.translate(I18N.messages.discord_verification.previous, locale=locale)
        self.next_page.label = localizer.translate(I18N.messages.discord_verification.next_page, locale=locale)
        self._update_buttons()

    def content(self) -> str:
        if len(self.pages) == 1:
            return self.pages[0]
        footer = self.localizer.translate(
            I18N.messages.discord_verification.page, locale=self.locale,
            page=self.index + 1, total=len(self.pages),
        )
        return self.pages[self.index] + "\n\n" + footer

    def _update_buttons(self) -> None:
        self.previous.disabled = self.index == 0
        self.next_page.disabled = self.index == len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.actor_id:
            return True
        await interaction.response.send_message(self.localizer.translate(
            I18N.messages.discord_verification.owner_only, locale=interaction.locale,
        ), ephemeral=True)
        return False

    async def _show(self, interaction: discord.Interaction, delta: int) -> None:
        self.index = max(0, min(len(self.pages) - 1, self.index + delta))
        self._update_buttons()
        await interaction.response.edit_message(
            content=self.content(), view=self, allowed_mentions=discord.AllowedMentions.none(),
        )

    async def on_timeout(self) -> None:
        self.previous.disabled = True
        self.next_page.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    @discord.ui.button(style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, -1)

    @discord.ui.button(style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, 1)
