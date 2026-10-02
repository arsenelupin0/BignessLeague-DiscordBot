from __future__ import annotations

import discord

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ChannelManagementError, ensure_allowed_member,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import GoogleSheetsTeamRepository
from bigness_league_bot.infrastructure.google.team_sheets.models import TeamRoleSheetMetadata
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService


async def _check_actor(interaction: discord.Interaction, actor_id: int, guild_id: int) -> bool:
    try:
        if (interaction.user.id != actor_id or interaction.guild_id != guild_id
                or not isinstance(interaction.user, discord.Member)):
            raise CommandUserError(localize(I18N.errors.slash.forbidden))
        ensure_allowed_member(interaction.user)
    except (CommandUserError, ChannelManagementError) as exc:
        await interaction.response.send_message(
            interaction.client.localizer.render(exc.message, locale=interaction.locale), ephemeral=True,
        )
        return False
    return True


class TeamLogoModificationModal(discord.ui.Modal):
    def __init__(
            self, *, actor_id: int, guild_id: int, metadata: TeamRoleSheetMetadata,
            localizer: LocalizationService, locale: str | discord.Locale,
    ) -> None:
        super().__init__(title=localizer.translate(
            I18N.messages.team_signing.logo_modification.modal_title, locale=locale,
        ))
        self.actor_id = actor_id
        self.guild_id = guild_id
        self.metadata = metadata
        self.localizer = localizer
        self.logo_url = discord.ui.TextInput(
            label=localizer.translate(I18N.messages.team_signing.logo_modification.url_label, locale=locale),
            placeholder=(metadata.team_image_url or localizer.translate(
                I18N.messages.team_signing.logo_modification.url_placeholder, locale=locale,
            ))[:100],
            required=True, max_length=2000,
        )
        self.add_item(self.logo_url)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _check_actor(interaction, self.actor_id, self.guild_id)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await _check_actor(interaction, self.actor_id, self.guild_id):
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            repository = GoogleSheetsTeamRepository(interaction.client.settings)
            result = await repository.update_team_logo(
                self.metadata.worksheet_title, self.metadata.team_name, str(self.logo_url.value),
            )
        except CommandUserError as exc:
            await interaction.followup.send(
                self.localizer.render(exc.message, locale=interaction.locale), ephemeral=True,
            )
            return
        await interaction.followup.send(
            self.localizer.translate(
                I18N.actions.team_signing.logo_modified, locale=interaction.locale,
                team_name=result.team_name, division_name=result.worksheet_title,
            ), ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await super().on_error(interaction, error)
        message = self.localizer.translate(I18N.errors.slash.unexpected, locale=interaction.locale)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class TeamLogoModificationView(discord.ui.View):
    def __init__(
            self, *, actor_id: int, guild_id: int, metadata: TeamRoleSheetMetadata,
            localizer: LocalizationService, locale: str | discord.Locale,
    ) -> None:
        super().__init__(timeout=60)
        self.actor_id = actor_id
        self.guild_id = guild_id
        self.metadata = metadata
        self.localizer = localizer
        button = discord.ui.Button(label=localizer.translate(
            I18N.messages.team_signing.logo_modification.open_modal, locale=locale,
        ), style=discord.ButtonStyle.primary)
        button.callback = self.open_modal
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _check_actor(interaction, self.actor_id, self.guild_id)

    async def open_modal(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TeamLogoModificationModal(
            actor_id=self.actor_id, guild_id=self.guild_id, metadata=self.metadata,
            localizer=self.localizer, locale=interaction.locale,
        ))
        self.stop()
