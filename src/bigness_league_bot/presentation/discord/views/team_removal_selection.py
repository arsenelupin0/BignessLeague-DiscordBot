from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.discord.team_removal_interactive import (
    InteractiveRemovalMemberOption,
    collect_interactive_removal_member_options,
)
from bigness_league_bot.infrastructure.discord.team_signing_removal_workflow import (
    TeamSigningRemovalScope,
    handle_team_signing_removal,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

if TYPE_CHECKING:
    from bigness_league_bot.application.services.team_profile import TeamProfile
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class _RemovalScopeSelect(discord.ui.Select["TeamRemovalSelectionView"]):
    def __init__(
            self,
            *,
            localizer: LocalizationService,
            locale: str | discord.Locale,
    ) -> None:
        super().__init__(
            placeholder=localizer.translate(
                I18N.messages.team_signing.interactive_removal_selection.scope_placeholder,
                locale=locale,
            ),
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=localizer.translate(
                        I18N.messages.team_signing.interactive_removal_selection.scope_all,
                        locale=locale,
                    ),
                    value="all",
                ),
                discord.SelectOption(
                    label=localizer.translate(
                        I18N.messages.team_signing.interactive_removal_selection.scope_player,
                        locale=locale,
                    ),
                    value="player",
                ),
                discord.SelectOption(
                    label=localizer.translate(
                        I18N.messages.team_signing.interactive_removal_selection.scope_staff,
                        locale=locale,
                    ),
                    value="staff",
                ),
            ],
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TeamRemovalSelectionView):
            return

        await view.select_scope(interaction, self.values[0])


class _RemovalMemberSelect(discord.ui.Select["TeamRemovalSelectionView"]):
    def __init__(
            self,
            *,
            options: tuple[InteractiveRemovalMemberOption, ...],
            placeholder: str,
    ) -> None:
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=option.label,
                    value=option.value,
                    description=option.description,
                )
                for option in options
            ],
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TeamRemovalSelectionView):
            return

        await view.confirm_member(interaction, self.values[0])


class TeamRemovalSelectionView(discord.ui.View):
    def __init__(
            self,
            *,
            guild: discord.Guild,
            actor: discord.Member,
            team_role: discord.Role,
            team_profile: TeamProfile,
            localizer: LocalizationService,
            locale: str | discord.Locale,
            timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.guild = guild
        self.actor = actor
        self.team_role = team_role
        self.team_profile = team_profile
        self.localizer = localizer
        self.locale = locale
        self.removal_scope: TeamSigningRemovalScope | None = None
        self.message: discord.InteractionMessage | discord.WebhookMessage | None = None
        self.add_item(_RemovalScopeSelect(localizer=localizer, locale=locale))

    async def interaction_check(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> bool:
        if interaction.user.id == self.actor.id:
            return True

        await interaction.response.send_message(
            self.localizer.translate(
                I18N.messages.team_signing.interactive_removal_selection.only_actor,
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
                    I18N.messages.team_signing.interactive_removal_selection.timeout,
                    locale=self.locale,
                ),
                view=self,
            )

    async def select_scope(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            raw_scope: str,
    ) -> None:
        self.locale = interaction.locale
        removal_scope = _parse_removal_scope(raw_scope)
        member_options = collect_interactive_removal_member_options(
            self.team_profile,
            removal_scope=removal_scope,
        )
        if not member_options:
            await interaction.response.send_message(
                self.localizer.translate(
                    I18N.messages.team_signing.interactive_removal_selection.no_members,
                    locale=interaction.locale,
                ),
                ephemeral=True,
            )
            return

        self.removal_scope = removal_scope
        self.clear_items()
        self.add_item(
            _RemovalMemberSelect(
                options=member_options,
                placeholder=self.localizer.translate(
                    I18N.messages.team_signing.interactive_removal_selection.member_placeholder,
                    locale=interaction.locale,
                ),
            )
        )
        await interaction.response.edit_message(
            content=self.localizer.translate(
                I18N.messages.team_signing.interactive_removal_selection.member_prompt,
                locale=interaction.locale,
            ),
            view=self,
        )

    async def confirm_member(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            discord_name: str,
    ) -> None:
        if self.removal_scope is None:
            return

        self.locale = interaction.locale
        self._disable_children()
        await interaction.response.edit_message(
            content=self.localizer.translate(
                I18N.messages.team_signing.interactive_removal_selection.processing,
                locale=interaction.locale,
            ),
            view=self,
        )
        try:
            await handle_team_signing_removal(
                interaction,
                guild=self.guild,
                discord_name=discord_name,
                team_role=self.team_role,
                removal_scope=self.removal_scope,
            )
        except CommandUserError as exc:
            await interaction.followup.send(
                self.localizer.render(exc.message, locale=interaction.locale),
                ephemeral=True,
            )
            self.stop()
            return

        self.stop()

    def _disable_children(self) -> None:
        for child in self.children:
            child.disabled = True


def _parse_removal_scope(raw_scope: str) -> TeamSigningRemovalScope:
    if raw_scope == "player":
        return "player"
    if raw_scope == "staff":
        return "staff"
    return "all"
