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

import logging
import re
from math import ceil
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ChannelAccessRoleCatalog,
    ChannelManagementError,
    normalize_channel_access_roles,
)
from bigness_league_bot.infrastructure.discord.channel_management import (
    add_roles_to_channel,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService
from bigness_league_bot.presentation.discord.views.channel_role_addition_components import (
    CancelButton,
    ChannelRoleSelect,
    ClearFilterButton,
    ConfirmButton,
    PageButton,
    SearchButton,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)
ROLES_PER_PAGE = 25
ROLE_MENTION_PATTERN = re.compile(r"^<@&(\d+)>$")


class ChannelRoleAdditionView(discord.ui.View):
    def __init__(
            self,
            *,
            channel: discord.TextChannel,
            actor: discord.Member,
            role_catalog: ChannelAccessRoleCatalog,
            localizer: LocalizationService,
            locale: str | discord.Locale,
            timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.channel = channel
        self.actor = actor
        self.role_catalog = role_catalog
        self.localizer = localizer
        self.locale = locale
        self.candidate_roles = role_catalog.roles
        self.role_by_id = {role.id: role for role in self.candidate_roles}
        self.visible_roles = self.candidate_roles
        self.page_index = 0
        self.selected_role_ids: set[int] = set()
        self.search_query: str | None = None
        self.message: discord.InteractionMessage | None = None

        self.role_select = ChannelRoleSelect(
            placeholder=self.localizer.translate(
                I18N.messages.channel_role_addition.loading_placeholder,
                locale=self.locale,
            ),
            empty_label=self.localizer.translate(
                I18N.messages.channel_role_addition.empty_option_label,
                locale=self.locale,
            ),
        )
        self.previous_button = PageButton(
            label=self.localizer.translate(
                I18N.messages.channel_role_addition.buttons.previous,
                locale=self.locale,
            ),
            delta=-1,
            row=1,
        )
        self.next_button = PageButton(
            label=self.localizer.translate(
                I18N.messages.channel_role_addition.buttons.next,
                locale=self.locale,
            ),
            delta=1,
            row=1,
        )
        self.search_button = SearchButton(
            label=self.localizer.translate(
                I18N.messages.channel_role_addition.buttons.search,
                locale=self.locale,
            )
        )
        self.clear_filter_button = ClearFilterButton(
            label=self.localizer.translate(
                I18N.messages.channel_role_addition.buttons.clear_filter,
                locale=self.locale,
            )
        )
        self.confirm_button = ConfirmButton(
            label=self.localizer.translate(
                I18N.messages.channel_role_addition.buttons.confirm,
                locale=self.locale,
            )
        )
        self.cancel_button = CancelButton(
            label=self.localizer.translate(
                I18N.messages.channel_role_addition.buttons.cancel,
                locale=self.locale,
            )
        )

        self.add_item(self.role_select)
        self.add_item(self.previous_button)
        self.add_item(self.next_button)
        self.add_item(self.search_button)
        self.add_item(self.clear_filter_button)
        self.add_item(self.confirm_button)
        self.add_item(self.cancel_button)
        self._refresh_components()

    @property
    def page_count(self) -> int:
        return max(1, ceil(len(self.visible_roles) / ROLES_PER_PAGE))

    def render_content(self) -> str:
        search_query = self.search_query or self.localizer.translate(
            I18N.messages.channel_role_addition.search_none,
            locale=self.locale,
        )
        return self.localizer.translate(
            I18N.messages.channel_role_addition.render_content,
            locale=self.locale,
            range_start=self.role_catalog.range_start.name,
            range_end=self.role_catalog.range_end.name,
            page=self.page_index + 1,
            page_count=self.page_count,
            selected_count=len(self.selected_role_ids),
            visible_count=len(self.visible_roles),
            candidate_count=len(self.candidate_roles),
            search_query=search_query,
        )

    async def interaction_check(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> bool:
        if interaction.user.id == self.actor.id:
            return True

        await self._send_interaction_message(
            interaction,
            self.localizer.translate(
                I18N.messages.channel_role_addition.only_actor,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        self._disable_children()
        if self.message is None:
            return

        await self.message.edit(
            content=self.localizer.translate(
                I18N.messages.channel_role_addition.timeout,
                locale=self.locale,
            ),
            view=self,
        )

    async def update_page_selection(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            selected_role_ids: set[int],
    ) -> None:
        self.locale = interaction.locale
        current_page_role_ids = {role.id for role in self._current_page_roles()}
        self.selected_role_ids.difference_update(current_page_role_ids)
        self.selected_role_ids.update(selected_role_ids)
        self._refresh_components()
        await interaction.response.edit_message(
            content=self.render_content(),
            view=self,
        )

    async def change_page(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            delta: int,
    ) -> None:
        self.locale = interaction.locale
        self.page_index = max(0, min(self.page_index + delta, self.page_count - 1))
        self._refresh_components()
        await interaction.response.edit_message(
            content=self.render_content(),
            view=self,
        )

    async def confirm_selection(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        selected_roles = normalize_channel_access_roles(
            self.channel.guild,
            [
                self.role_by_id.get(role_id)
                for role_id in self._sorted_selected_role_ids()
            ],
        )
        if not selected_roles:
            await self._send_interaction_message(
                interaction,
                self.localizer.translate(
                    I18N.messages.channel_role_addition.select_before_confirm,
                    locale=interaction.locale,
                ),
                ephemeral=True,
            )
            return

        try:
            summary = await add_roles_to_channel(
                self.channel,
                self.actor,
                selected_roles,
            )
        except ChannelManagementError as error:
            LOGGER.warning(
                "CHANNEL_ROLE_SELECTION_REJECTED channel=%s(%s) actor=%s(%s) reason=%s",
                self.channel.name,
                self.channel.id,
                self.actor,
                self.actor.id,
                error,
            )
            await self._send_interaction_message(
                interaction,
                self.localizer.render(error.message, locale=interaction.locale),
                ephemeral=True,
            )
            return
        except discord.Forbidden:
            LOGGER.exception(
                "CHANNEL_ROLE_SELECTION_FORBIDDEN channel=%s(%s) actor=%s(%s)",
                self.channel.name,
                self.channel.id,
                self.actor,
                self.actor.id,
            )
            await self._send_interaction_message(
                interaction,
                self.localizer.translate(
                    I18N.errors.slash.discord_forbidden,
                    locale=interaction.locale,
                ),
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            LOGGER.exception(
                "CHANNEL_ROLE_SELECTION_HTTP_ERROR channel=%s(%s) actor=%s(%s)",
                self.channel.name,
                self.channel.id,
                self.actor,
                self.actor.id,
            )
            await self._send_interaction_message(
                interaction,
                self.localizer.translate(
                    I18N.errors.slash.http_error,
                    locale=interaction.locale,
                ),
                ephemeral=True,
            )
            return

        self._disable_children()
        await interaction.response.edit_message(
            content=self.localizer.render(summary, locale=interaction.locale),
            view=self,
        )
        self.stop()

    async def apply_search_query(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            raw_query: str,
    ) -> None:
        self.locale = interaction.locale
        normalized_query = raw_query.strip()
        if not normalized_query:
            await self.clear_search_query(interaction)
            return

        self.search_query = normalized_query
        self.visible_roles = self._filter_roles(normalized_query)
        self.page_index = 0
        self._refresh_components()
        await interaction.response.edit_message(
            content=self.render_content(),
            view=self,
        )

    async def clear_search_query(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        self.search_query = None
        self.visible_roles = self.candidate_roles
        self.page_index = 0
        self._refresh_components()
        await interaction.response.edit_message(
            content=self.render_content(),
            view=self,
        )

    async def cancel_selection(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        self.locale = interaction.locale
        self._disable_children()
        await interaction.response.edit_message(
            content=self.localizer.translate(
                I18N.messages.channel_role_addition.selection_cancelled,
                locale=interaction.locale,
            ),
            view=self,
        )
        self.stop()

    def _refresh_components(self) -> None:
        page_roles = self._current_page_roles()
        self.role_select.refresh(
            roles=page_roles,
            selected_role_ids=self.selected_role_ids,
            page_index=self.page_index,
            page_count=self.page_count,
            localizer=self.localizer,
            locale=self.locale,
        )
        self.previous_button.disabled = self.page_index == 0
        self.next_button.disabled = self.page_index >= self.page_count - 1
        self.clear_filter_button.disabled = self.search_query is None

    def _current_page_roles(self) -> tuple[discord.Role, ...]:
        start_index = self.page_index * ROLES_PER_PAGE
        end_index = start_index + ROLES_PER_PAGE
        return self.visible_roles[start_index:end_index]

    def _sorted_selected_role_ids(self) -> list[int]:
        return sorted(
            self.selected_role_ids,
            key=lambda role_id: self.role_by_id[role_id].position,
            reverse=True,
        )

    def _filter_roles(self, query: str) -> tuple[discord.Role, ...]:
        exact_role_id = self._extract_role_id(query)
        if exact_role_id is not None:
            role = self.role_by_id.get(exact_role_id)
            return (role,) if role is not None else ()

        normalized_query = query.casefold()
        return tuple(
            role
            for role in self.candidate_roles
            if normalized_query in role.name.casefold()
        )

    def _disable_children(self) -> None:
        for child in self.children:
            child.disabled = True

    @staticmethod
    def _extract_role_id(query: str) -> int | None:
        mention_match = ROLE_MENTION_PATTERN.fullmatch(query)
        if mention_match is not None:
            return int(mention_match.group(1))

        if query.isdigit():
            return int(query)

        return None

    @staticmethod
    async def _send_interaction_message(
            interaction: discord.Interaction[BignessLeagueBot],
            message: str,
            *,
            ephemeral: bool = False,
    ) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
            return

        await interaction.response.send_message(message, ephemeral=ephemeral)
