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

from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ChannelManagementError,
)
from bigness_league_bot.infrastructure.discord.match_channel_schedule import (
    apply_match_scheduled,
)
from bigness_league_bot.infrastructure.discord.match_schedule_store import (
    MatchScheduleStore,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class ChannelScheduleModal(discord.ui.Modal):
    def __init__(
            self,
            *,
            channel: discord.TextChannel,
            actor: discord.Member,
            localizer: LocalizationService,
            locale: str | discord.Locale,
    ) -> None:
        super().__init__(
            title=localizer.translate(
                I18N.messages.channel_schedule_modal.title,
                locale=locale,
            )
        )
        self.channel = channel
        self.actor = actor
        self.localizer = localizer
        self.locale = locale
        self.date_input = discord.ui.TextInput(
            label=localizer.translate(
                I18N.messages.channel_schedule_modal.fields.date_label,
                locale=locale,
            ),
            placeholder=localizer.translate(
                I18N.messages.channel_schedule_modal.fields.date_placeholder,
                locale=locale,
            ),
            max_length=10,
            required=True,
        )
        self.time_input = discord.ui.TextInput(
            label=localizer.translate(
                I18N.messages.channel_schedule_modal.fields.time_label,
                locale=locale,
            ),
            placeholder=localizer.translate(
                I18N.messages.channel_schedule_modal.fields.time_placeholder,
                locale=locale,
            ),
            max_length=5,
            required=True,
        )
        self.add_item(self.date_input)
        self.add_item(self.time_input)

    async def on_submit(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        try:
            action_result = await apply_match_scheduled(
                self.channel,
                self.actor,
                date_value=str(self.date_input.value),
                time_value=str(self.time_input.value),
                settings=interaction.client.settings,
                bot=interaction.client,
            )
        except ChannelManagementError as exc:
            await interaction.response.send_message(
                self.localizer.render(
                    exc.message,
                    locale=interaction.locale,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            self.localizer.render(
                action_result.summary,
                locale=interaction.locale,
            ),
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                users=False,
                roles=True,
                replied_user=False,
            ),
        )
        message = await interaction.original_response()
        store = MatchScheduleStore(interaction.client.settings.match_schedule_state_file)
        store.upsert(action_result.entry.with_message_id(message.id))
