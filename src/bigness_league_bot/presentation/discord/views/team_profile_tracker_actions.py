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
    build_team_profile_tracker_markdown,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class _ListTrackersButton(discord.ui.Button["TeamProfileTrackerActionsView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TeamProfileTrackerActionsView):
            return

        await view.list_trackers(interaction)


class _CancelButton(discord.ui.Button["TeamProfileTrackerActionsView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, TeamProfileTrackerActionsView):
            return

        await view.cancel(interaction)


class TeamProfileTrackerActionsView(discord.ui.View):
    def __init__(
            self,
            *,
            actor: discord.Member,
            team_profile: TeamProfile,
            localizer: LocalizationService,
            locale: str | discord.Locale,
            timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.actor = actor
        self.team_profile = team_profile
        self.localizer = localizer
        self.locale = locale
        self.message: discord.InteractionMessage | None = None
        self.add_item(
            _ListTrackersButton(
                label=self.localizer.translate(
                    I18N.messages.team_profile.buttons.list_trackers,
                    locale=self.locale,
                )
            )
        )
        self.add_item(
            _CancelButton(
                label=self.localizer.translate(
                    I18N.messages.team_profile.buttons.cancel,
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
                I18N.messages.team_profile.only_actor,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        await self._clear_view()
        self.stop()

    async def list_trackers(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        content = build_team_profile_tracker_markdown(
            team_profile=self.team_profile,
            localizer=self.localizer,
            locale=interaction.locale,
        )
        await interaction.response.edit_message(
            content=content,
            view=None,
            allowed_mentions=discord.AllowedMentions.none(),
            suppress_embeds=True,
        )
        self.stop()

    async def cancel(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        await interaction.response.edit_message(view=None)
        self.stop()

    async def _clear_view(self) -> None:
        if self.message is None:
            return

        try:
            await self.message.edit(view=None)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
