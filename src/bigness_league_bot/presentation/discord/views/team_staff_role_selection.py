from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.discord.team_signing_workflow import (
    handle_team_signing_import,
)
from bigness_league_bot.infrastructure.discord.team_staff_interactive import (
    InteractiveStaffRoleOption,
    build_interactive_staff_signing_batch,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class _TeamStaffRoleSelect(discord.ui.Select["TeamStaffRoleSelectionView"]):
    def __init__(
            self,
            *,
            options: tuple[InteractiveStaffRoleOption, ...],
            placeholder: str,
    ) -> None:
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=len(options),
            options=[
                discord.SelectOption(label=option.label, value=option.value)
                for option in options
            ],
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TeamStaffRoleSelectionView):
            return

        await view.confirm_roles(interaction, tuple(self.values))


class TeamStaffRoleSelectionView(discord.ui.View):
    def __init__(
            self,
            *,
            bot: BignessLeagueBot,
            guild: discord.Guild,
            actor: discord.Member,
            equipo: str,
            discord_jugador: str,
            role_options: tuple[InteractiveStaffRoleOption, ...],
            localizer: LocalizationService,
            locale: str | discord.Locale,
            timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild = guild
        self.actor = actor
        self.equipo = equipo
        self.discord_jugador = discord_jugador
        self.localizer = localizer
        self.locale = locale
        self.message: discord.InteractionMessage | discord.WebhookMessage | None = None
        self.add_item(
            _TeamStaffRoleSelect(
                options=role_options,
                placeholder=self.localizer.translate(
                    I18N.messages.team_signing.interactive_staff_role_selection.placeholder,
                    locale=self.locale,
                ),
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
                I18N.messages.team_signing.interactive_staff_role_selection.only_actor,
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
                    I18N.messages.team_signing.interactive_staff_role_selection.timeout,
                    locale=self.locale,
                ),
                view=self,
            )

    async def confirm_roles(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            selected_roles: tuple[str, ...],
    ) -> None:
        self.locale = interaction.locale
        self._disable_children()
        await interaction.response.edit_message(
            content=self.localizer.translate(
                I18N.messages.team_signing.interactive_staff_role_selection.processing,
                locale=interaction.locale,
            ),
            view=self,
        )
        try:
            technical_staff_batch = await build_interactive_staff_signing_batch(
                interaction,
                guild=self.guild,
                equipo=self.equipo,
                discord_jugador=self.discord_jugador,
                cargos=selected_roles,
            )
            await handle_team_signing_import(
                interaction,
                bot=self.bot,
                guild=self.guild,
                signing_batch=None,
                technical_staff_batch=technical_staff_batch,
                require_new_team_block=False,
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
