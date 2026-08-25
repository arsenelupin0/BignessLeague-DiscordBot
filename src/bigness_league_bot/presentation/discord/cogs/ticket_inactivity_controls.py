from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.channel_closure import STAFF_ROLE_NAME
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class TicketInactivityControlsCog(commands.Cog):
    def __init__(self, bot: BignessLeagueBot, store: TicketStateStore) -> None:
        self.bot = bot
        self.store = store

    @app_commands.command(
        name=localized_locale_str(I18N.commands.tickets.configure_reminders.name),
        description=localized_locale_str(
            I18N.commands.tickets.configure_reminders.description
        ),
    )
    @app_commands.describe(
        activados=localized_locale_str(
            I18N.commands.tickets.configure_reminders.parameters.enabled.description
        ),
    )
    @app_commands.guild_only()
    async def configure_ticket_reminders(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            activados: bool,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise CommandUserError(localize(I18N.errors.channel_management.server_only))

        self._ensure_staff_member(interaction.user)

        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            raise CommandUserError(
                localize(I18N.messages.tickets.participants.only_ticket_thread)
            )

        record = self.store.active_for_thread(thread.id)
        if record is None:
            raise CommandUserError(localize(I18N.messages.tickets.close.not_active))

        already_configured = record.inactivity_reminders_enabled == activados
        updated_record = self.store.set_inactivity_reminders_enabled(
            thread.id,
            enabled=activados,
        )
        if updated_record is None:
            raise CommandUserError(localize(I18N.messages.tickets.close.not_active))

        if already_configured:
            message_key = (
                I18N.messages.tickets.inactivity.controls.already_enabled
                if activados
                else I18N.messages.tickets.inactivity.controls.already_disabled
            )
        else:
            message_key = (
                I18N.messages.tickets.inactivity.controls.enabled
                if activados
                else I18N.messages.tickets.inactivity.controls.disabled
            )

        await interaction.response.send_message(
            interaction.client.localizer.translate(
                message_key,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name=localized_locale_str(
            I18N.commands.tickets.configure_default_reminders.name
        ),
        description=localized_locale_str(
            I18N.commands.tickets.configure_default_reminders.description
        ),
    )
    @app_commands.describe(
        activados=localized_locale_str(
            I18N.commands.tickets.configure_default_reminders.parameters.enabled.description
        ),
    )
    @app_commands.guild_only()
    async def configure_default_ticket_reminders(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            activados: bool,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise CommandUserError(localize(I18N.errors.channel_management.server_only))

        self._ensure_staff_member(interaction.user)
        changed = self.store.set_default_inactivity_reminders_enabled(activados)
        if changed:
            message_key = (
                I18N.messages.tickets.inactivity.default_controls.enabled
                if activados
                else I18N.messages.tickets.inactivity.default_controls.disabled
            )
        else:
            message_key = (
                I18N.messages.tickets.inactivity.default_controls.already_enabled
                if activados
                else I18N.messages.tickets.inactivity.default_controls.already_disabled
            )

        await interaction.response.send_message(
            interaction.client.localizer.translate(
                message_key,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )

    @staticmethod
    def _ensure_staff_member(member: discord.Member) -> None:
        expected_role_name = STAFF_ROLE_NAME.casefold()
        if any(role.name.casefold() == expected_role_name for role in member.roles):
            return

        raise CommandUserError(localize(I18N.errors.tickets.staff_only))

    async def cog_app_command_error(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            error: app_commands.AppCommandError,
    ) -> None:
        error_details = classify_app_command_error(error)
        message = interaction.client.localizer.render(
            error_details.user_message,
            locale=interaction.locale,
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
            return

        await interaction.response.send_message(message, ephemeral=True)
