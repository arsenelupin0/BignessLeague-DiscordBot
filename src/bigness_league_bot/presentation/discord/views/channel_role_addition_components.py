from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot
    from bigness_league_bot.presentation.discord.views.channel_role_addition import (
        ChannelRoleAdditionView,
    )


class ChannelRoleSelect(discord.ui.Select["ChannelRoleAdditionView"]):
    def __init__(self, *, placeholder: str, empty_label: str) -> None:
        super().__init__(
            placeholder=placeholder,
            min_values=0,
            max_values=1,
            options=[discord.SelectOption(label=empty_label, value="0")],
            row=0,
        )

    def refresh(
            self,
            *,
            roles: tuple[discord.Role, ...],
            selected_role_ids: set[int],
            page_index: int,
            page_count: int,
            localizer: LocalizationService,
            locale: str | discord.Locale,
    ) -> None:
        if not roles:
            self.options = [
                discord.SelectOption(
                    label=localizer.translate(
                        I18N.messages.channel_role_addition.no_results_label,
                        locale=locale,
                    ),
                    value="0",
                )
            ]
            self.max_values = 1
            self.placeholder = localizer.translate(
                I18N.messages.channel_role_addition.no_results_placeholder,
                locale=locale,
            )
            self.disabled = True
            return

        self.options = [
            discord.SelectOption(
                label=role.name,
                value=str(role.id),
                default=role.id in selected_role_ids,
            )
            for role in roles
        ]
        self.max_values = len(roles)
        self.placeholder = localizer.translate(
            I18N.messages.channel_role_addition.select_placeholder,
            locale=locale,
            page=page_index + 1,
            page_count=page_count,
        )
        self.disabled = False

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if view is None:
            return

        await view.update_page_selection(
            interaction,
            {int(role_id) for role_id in self.values},
        )


class PageButton(discord.ui.Button["ChannelRoleAdditionView"]):
    def __init__(
            self,
            *,
            label: str,
            delta: int,
            row: int,
            style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ) -> None:
        super().__init__(label=label, style=style, row=row)
        self.delta = delta

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if view is None:
            return

        await view.change_page(interaction, self.delta)


class ConfirmButton(discord.ui.Button["ChannelRoleAdditionView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.success,
            row=2,
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if view is None:
            return

        await view.confirm_selection(interaction)


class CancelButton(discord.ui.Button["ChannelRoleAdditionView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=2,
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if view is None:
            return

        await view.cancel_selection(interaction)


class SearchButton(discord.ui.Button["ChannelRoleAdditionView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            row=1,
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if view is None:
            return

        await interaction.response.send_modal(RoleSearchModal(view))


class ClearFilterButton(discord.ui.Button["ChannelRoleAdditionView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=1,
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if view is None:
            return

        await view.clear_search_query(interaction)


class RoleSearchModal(discord.ui.Modal):
    search_query = discord.ui.TextInput(
        label=I18N.messages.channel_role_addition.modal.query_label.default,
        placeholder=I18N.messages.channel_role_addition.modal.query_placeholder.default,
        max_length=100,
        required=False,
    )

    def __init__(self, view: "ChannelRoleAdditionView") -> None:
        self.channel_role_addition_view = view
        super().__init__(
            title=view.localizer.translate(
                I18N.messages.channel_role_addition.modal.title,
                locale=view.locale,
            )
        )
        self.search_query.label = view.localizer.translate(
            I18N.messages.channel_role_addition.modal.query_label,
            locale=view.locale,
        )
        self.search_query.placeholder = view.localizer.translate(
            I18N.messages.channel_role_addition.modal.query_placeholder,
            locale=view.locale,
        )

    async def on_submit(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        await self.channel_role_addition_view.apply_search_query(
            interaction,
            self.search_query.value,
        )
