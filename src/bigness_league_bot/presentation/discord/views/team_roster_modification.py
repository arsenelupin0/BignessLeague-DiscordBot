from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.team_profile import (
    TeamProfile,
    TeamProfilePlayer,
    TeamProfileStaffMember,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.discord.team_roster_modification import (
    build_player_roster_update,
    build_staff_roster_modification_batch,
    current_staff_role_keys,
)
from bigness_league_bot.infrastructure.discord.team_signing_workflow import (
    handle_team_signing_import,
)
from bigness_league_bot.infrastructure.discord.team_staff_interactive import (
    INTERACTIVE_STAFF_ROLE_LABELS,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class PlayerRosterModificationModal(discord.ui.Modal):
    def __init__(
            self,
            *,
            team_profile: TeamProfile,
            player: TeamProfilePlayer,
            localizer: LocalizationService,
            locale: str | discord.Locale,
    ) -> None:
        super().__init__(
            title=localizer.translate(
                I18N.messages.team_signing.roster_modification.player_modal_title,
                locale=locale,
            )
        )
        self.team_profile = team_profile
        self.player = player
        self.localizer = localizer
        self.player_name = discord.ui.TextInput(
            label=localizer.translate(
                I18N.messages.team_signing.roster_modification.player_name_label,
                locale=locale,
            ),
            default=player.player_name,
            max_length=100,
        )
        self.tracker_url = discord.ui.TextInput(
            label=localizer.translate(
                I18N.messages.team_signing.roster_modification.tracker_label,
                locale=locale,
            ),
            default=player.tracker_url or "",
            required=False,
            max_length=300,
        )
        self.epic_name = discord.ui.TextInput(
            label=localizer.translate(
                I18N.messages.team_signing.roster_modification.epic_name_label,
                locale=locale,
            ),
            default=player.epic_name,
            max_length=100,
        )
        self.rocket_name = discord.ui.TextInput(
            label=localizer.translate(
                I18N.messages.team_signing.roster_modification.rocket_name_label,
                locale=locale,
            ),
            default=player.rocket_name,
            max_length=100,
        )
        self.mmr = discord.ui.TextInput(
            label=localizer.translate(
                I18N.messages.team_signing.roster_modification.mmr_label,
                locale=locale,
            ),
            default=player.mmr,
            max_length=20,
        )
        self.add_item(self.player_name)
        self.add_item(self.tracker_url)
        self.add_item(self.epic_name)
        self.add_item(self.rocket_name)
        self.add_item(self.mmr)

    async def on_submit(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            repository = GoogleSheetsTeamRepository(interaction.client.settings)
            result = await repository.update_team_roster_player(
                build_player_roster_update(
                    self.team_profile,
                    discord_name=self.player.discord_name,
                    player_name=str(self.player_name.value),
                    tracker_url=str(self.tracker_url.value),
                    epic_name=str(self.epic_name.value),
                    rocket_name=str(self.rocket_name.value),
                    mmr=str(self.mmr.value),
                )
            )
        except CommandUserError as exc:
            await interaction.followup.send(
                self.localizer.render(exc.message, locale=interaction.locale),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            interaction.client.localizer.translate(
                I18N.actions.team_signing.roster_player_modified,
                locale=interaction.locale,
                discord_name=result.discord_name,
                team_name=result.team_name,
                division_name=result.worksheet_title,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )


class StaffRosterModificationModal(discord.ui.Modal):
    def __init__(
            self,
            *,
            bot: BignessLeagueBot,
            guild: discord.Guild,
            team_profile: TeamProfile,
            discord_name: str,
            selected_role_keys: tuple[str, ...],
            staff_member: TeamProfileStaffMember,
            localizer: LocalizationService,
            locale: str | discord.Locale,
    ) -> None:
        super().__init__(
            title=localizer.translate(
                I18N.messages.team_signing.roster_modification.staff_modal_title,
                locale=locale,
            )
        )
        self.bot = bot
        self.guild = guild
        self.team_profile = team_profile
        self.discord_name = discord_name
        self.selected_role_keys = selected_role_keys
        self.localizer = localizer
        self.epic_name = discord.ui.TextInput(
            label=localizer.translate(
                I18N.messages.team_signing.roster_modification.epic_name_label,
                locale=locale,
            ),
            default=staff_member.epic_name,
            max_length=100,
        )
        self.rocket_name = discord.ui.TextInput(
            label=localizer.translate(
                I18N.messages.team_signing.roster_modification.rocket_name_label,
                locale=locale,
            ),
            default=staff_member.rocket_name,
            max_length=100,
        )
        self.add_item(self.epic_name)
        self.add_item(self.rocket_name)

    async def on_submit(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            technical_staff_batch = build_staff_roster_modification_batch(
                self.team_profile,
                discord_name=self.discord_name,
                selected_role_keys=self.selected_role_keys,
                epic_name=str(self.epic_name.value),
                rocket_name=str(self.rocket_name.value),
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


class _OpenPlayerModalButton(discord.ui.Button["PlayerRosterModificationView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, PlayerRosterModificationView):
            return

        await interaction.response.send_modal(
            PlayerRosterModificationModal(
                team_profile=view.team_profile,
                player=view.player,
                localizer=view.localizer,
                locale=interaction.locale,
            )
        )
        view.stop()


class PlayerRosterModificationView(discord.ui.View):
    def __init__(
            self,
            *,
            actor: discord.Member,
            team_profile: TeamProfile,
            player: TeamProfilePlayer,
            localizer: LocalizationService,
            locale: str | discord.Locale,
            timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.actor = actor
        self.team_profile = team_profile
        self.player = player
        self.localizer = localizer
        self.locale = locale
        self.message: discord.InteractionMessage | discord.WebhookMessage | None = None
        self.add_item(
            _OpenPlayerModalButton(
                label=localizer.translate(
                    I18N.messages.team_signing.roster_modification.open_modal,
                    locale=locale,
                )
            )
        )

    async def interaction_check(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> bool:
        return await _only_actor(interaction, self.actor, self.localizer)


class _StaffRoleSelect(discord.ui.Select["StaffRosterModificationView"]):
    def __init__(
            self,
            *,
            current_role_keys: tuple[str, ...],
            placeholder: str,
    ) -> None:
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=len(INTERACTIVE_STAFF_ROLE_LABELS),
            options=[
                discord.SelectOption(
                    label=label,
                    value=role_key,
                    default=role_key in current_role_keys,
                )
                for role_key, label in INTERACTIVE_STAFF_ROLE_LABELS.items()
            ],
        )

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, StaffRosterModificationView):
            return

        view.selected_role_keys = tuple(self.values)
        await interaction.response.defer()


class _OpenStaffModalButton(discord.ui.Button["StaffRosterModificationView"]):
    def __init__(self, *, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary)

    async def callback(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        view = self.view
        if not isinstance(view, StaffRosterModificationView):
            return

        await interaction.response.send_modal(
            StaffRosterModificationModal(
                bot=view.bot,
                guild=view.guild,
                team_profile=view.team_profile,
                discord_name=view.discord_name,
                selected_role_keys=view.selected_role_keys,
                staff_member=view.staff_members[0],
                localizer=view.localizer,
                locale=interaction.locale,
            )
        )
        view.stop()


class StaffRosterModificationView(discord.ui.View):
    def __init__(
            self,
            *,
            bot: BignessLeagueBot,
            guild: discord.Guild,
            actor: discord.Member,
            team_profile: TeamProfile,
            discord_name: str,
            staff_members: tuple[TeamProfileStaffMember, ...],
            localizer: LocalizationService,
            locale: str | discord.Locale,
            timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild = guild
        self.actor = actor
        self.team_profile = team_profile
        self.discord_name = discord_name
        self.staff_members = staff_members
        self.localizer = localizer
        self.locale = locale
        self.selected_role_keys = current_staff_role_keys(staff_members)
        self.message: discord.InteractionMessage | discord.WebhookMessage | None = None
        self.add_item(
            _StaffRoleSelect(
                current_role_keys=self.selected_role_keys,
                placeholder=localizer.translate(
                    I18N.messages.team_signing.roster_modification.staff_roles_placeholder,
                    locale=locale,
                ),
            )
        )
        self.add_item(
            _OpenStaffModalButton(
                label=localizer.translate(
                    I18N.messages.team_signing.roster_modification.open_modal,
                    locale=locale,
                )
            )
        )

    async def interaction_check(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> bool:
        return await _only_actor(interaction, self.actor, self.localizer)


async def _only_actor(
        interaction: discord.Interaction[BignessLeagueBot],
        actor: discord.Member,
        localizer: LocalizationService,
) -> bool:
    if interaction.user.id == actor.id:
        return True

    await interaction.response.send_message(
        localizer.translate(
            I18N.messages.team_signing.roster_modification.only_actor,
            locale=interaction.locale,
        ),
        ephemeral=True,
    )
    return False
