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

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.infrastructure.discord.team_profile import (
    build_team_profile_image_file,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService
from bigness_league_bot.presentation.discord.views.team_profile_tracker_actions import (
    TeamProfileTrackerActionsView,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class _SelectTeamButton(discord.ui.Button["TeamProfileTeamSelectionView"]):
    def __init__(
            self,
            *,
            role: discord.Role,
            row: int,
    ) -> None:
        super().__init__(
            label=role.name,
            style=discord.ButtonStyle.primary,
            row=row,
        )
        self.role = role

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TeamProfileTeamSelectionView):
            return

        await view.select_team(interaction, self.role)


class _CancelButton(discord.ui.Button["TeamProfileTeamSelectionView"]):
    def __init__(self, *, label: str, row: int) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=row,
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TeamProfileTeamSelectionView):
            return

        await view.cancel(interaction)


class TeamProfileTeamSelectionView(discord.ui.View):
    def __init__(
            self,
            *,
            actor: discord.Member,
            team_roles: tuple[discord.Role, ...],
            localizer: LocalizationService,
            locale: str | discord.Locale,
            timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.actor = actor
        self.team_roles = team_roles
        self.localizer = localizer
        self.locale = locale
        self.message: discord.InteractionMessage | None = None

        for index, role in enumerate(team_roles):
            self.add_item(_SelectTeamButton(role=role, row=index // 5))

        cancel_row = min(4, len(team_roles) // 5)
        self.add_item(
            _CancelButton(
                label=self.localizer.translate(
                    I18N.messages.team_profile.buttons.cancel,
                    locale=self.locale,
                ),
                row=cancel_row,
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
                I18N.messages.team_profile.only_actor,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        if self.message is None:
            return

        await self.message.edit(
            content=self.localizer.translate(
                I18N.messages.team_profile.role_selection.timeout,
                locale=self.locale,
            ),
            view=None,
        )
        self.stop()

    async def select_team(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            role: discord.Role,
    ) -> None:
        self.locale = interaction.locale
        repository = GoogleSheetsTeamRepository(interaction.client.settings)
        team_profile = await repository.find_team_profile_for_role(role)
        await self._edit_message_with_team_profile(
            interaction,
            team_profile=team_profile,
        )
        self.stop()

    async def cancel(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        await interaction.response.edit_message(view=None)
        self.stop()

    async def _edit_message_with_team_profile(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            team_profile: TeamProfile,
    ) -> None:
        image_file = build_team_profile_image_file(
            team_profile=team_profile,
            localizer=interaction.client.localizer,
            locale=interaction.locale,
            font_path=interaction.client.settings.team_profile_font_path,
        )
        tracker_view = TeamProfileTrackerActionsView(
            actor=self.actor,
            team_profile=team_profile,
            localizer=interaction.client.localizer,
            locale=interaction.locale,
        )
        await interaction.response.edit_message(
            content=None,
            attachments=[image_file],
            view=tracker_view,
        )
        tracker_view.message = interaction.message
