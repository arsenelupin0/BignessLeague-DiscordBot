from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_management import (
    UnsupportedChannelError,
    ensure_allowed_member,
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    assign_team_roles_by_names,
    collect_team_profile_player_names,
    collect_team_profile_staff_role_entries,
    resolve_participant_role,
    resolve_player_role,
    resolve_team_role_by_name,
    sync_team_staff_roles_by_names,
)
from bigness_league_bot.infrastructure.discord.team_signing_imports import (
    parse_player_signing_batch,
    parse_technical_staff_batch,
    resolve_team_signing_import_target,
)
from bigness_league_bot.infrastructure.discord.team_signing_messages import (
    build_team_role_sync_message,
    build_team_signing_import_completed_message,
    build_team_signing_removal_completed_message,
    collect_technical_staff_role_entries,
    split_discord_message_content,
)
from bigness_league_bot.infrastructure.discord.team_signing_role_reconciliation import (
    reconcile_team_role_assignment,
    remove_discord_roles_after_signing_removal,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str
from bigness_league_bot.presentation.discord.ticket_command_mirroring import (
    mirror_ticket_text_command_message,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class TeamSigningCog(commands.Cog):
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot

    @commands.command(
        name="fichaje",
        aliases=("inscripcion",),
    )
    async def signing_guide(self, ctx: commands.Context[BignessLeagueBot]) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.team_signing.guide.content,
        )
        for chunk in split_discord_message_content(content):
            sent_message = await ctx.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
                suppress_embeds=True,
            )
            if ctx.command is not None:
                await mirror_ticket_text_command_message(
                    self.bot,
                    sent_message,
                    command_name=f"!{ctx.command.qualified_name}",
                )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.team_signing.make_signing.name),
        description=localized_locale_str(
            I18N.commands.team_signing.make_signing.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        enlace_jugadores=localized_locale_str(
            I18N.commands.team_signing.make_signing.parameters.message_link.description
        ),
        enlace_staff_tecnico=localized_locale_str(
            I18N.commands.team_signing.make_signing.parameters.technical_staff_message_link.description
        )
    )
    async def make_signing(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            enlace_jugadores: str | None = None,
            enlace_staff_tecnico: str | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        ensure_allowed_member(interaction.user)
        if enlace_jugadores is None and enlace_staff_tecnico is None:
            raise CommandUserError(
                localize(I18N.errors.team_signing.no_import_payload_provided)
            )

        await interaction.response.defer(thinking=True)
        settings = interaction.client.settings
        role_catalog = get_channel_access_role_catalog(
            guild,
            settings.channel_access_range_start_role_id,
            settings.channel_access_range_end_role_id,
        )
        signing_batch = await parse_player_signing_batch(
            interaction.client,
            guild=guild,
            message_link=enlace_jugadores,
        )
        technical_staff_batch = await parse_technical_staff_batch(
            interaction.client,
            guild=guild,
            message_link=enlace_staff_tecnico,
        )
        division_name, team_name = resolve_team_signing_import_target(
            signing_batch=signing_batch,
            technical_staff_batch=technical_staff_batch,
        )

        repository = GoogleSheetsTeamRepository(interaction.client.settings)
        team_role = resolve_team_role_by_name(team_name, role_catalog)
        participant_role = resolve_participant_role(guild, settings.participant_role_id)
        player_result = None
        assignment_summary = None
        if signing_batch is not None:
            player_role = resolve_player_role(guild, settings.player_role_id)
            player_result = await repository.register_team_signings(signing_batch)
            assignment_summary = await assign_team_roles_by_names(
                guild,
                team_role=team_role,
                common_roles=(participant_role, player_role),
                actor=interaction.user,
                member_names=(player.discord_name for player in signing_batch.players),
            )

        technical_staff_result = None
        staff_role_sync_summary = None
        if technical_staff_batch is not None:
            technical_staff_result = await repository.register_team_technical_staff(
                technical_staff_batch
            )
            staff_role_sync_summary = await sync_team_staff_roles_by_names(
                guild,
                team_role=team_role,
                participant_role=participant_role,
                ceo_role_id=settings.staff_ceo_role_id,
                analyst_role_id=settings.staff_analyst_role_id,
                coach_role_id=settings.staff_coach_role_id,
                manager_role_id=settings.staff_manager_role_id,
                second_manager_role_id=settings.staff_second_manager_role_id,
                captain_role_id=settings.staff_captain_role_id,
                actor=interaction.user,
                staff_entries=collect_technical_staff_role_entries(
                    technical_staff_batch
                ),
            )

        await interaction.followup.send(
            build_team_signing_import_completed_message(
                localizer=interaction.client.localizer,
                locale=interaction.locale,
                division_name=division_name,
                team_name=team_name,
                signing_batch=signing_batch,
                technical_staff_batch=technical_staff_batch,
                player_result=player_result,
                technical_staff_result=technical_staff_result,
                assignment_summary=assignment_summary,
                staff_role_sync_summary=staff_role_sync_summary,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.team_signing.remove_signing.name),
        description=localized_locale_str(
            I18N.commands.team_signing.remove_signing.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        discord_jugador=localized_locale_str(
            I18N.commands.team_signing.remove_signing.parameters.discord_name.description
        )
    )
    async def remove_signing(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            discord_jugador: str,
    ) -> None:
        await self._remove_signing(
            interaction,
            discord_name=discord_jugador,
            removal_scope="all",
        )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.team_signing.remove_player_signing.name),
        description=localized_locale_str(
            I18N.commands.team_signing.remove_player_signing.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        discord_jugador=localized_locale_str(
            I18N.commands.team_signing.remove_player_signing.parameters.discord_name.description
        )
    )
    async def remove_player_signing(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            discord_jugador: str,
    ) -> None:
        await self._remove_signing(
            interaction,
            discord_name=discord_jugador,
            removal_scope="player",
        )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.team_signing.remove_staff_signing.name),
        description=localized_locale_str(
            I18N.commands.team_signing.remove_staff_signing.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        discord_staff=localized_locale_str(
            I18N.commands.team_signing.remove_staff_signing.parameters.discord_name.description
        )
    )
    async def remove_staff_signing(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            discord_staff: str,
    ) -> None:
        await self._remove_signing(
            interaction,
            discord_name=discord_staff,
            removal_scope="staff",
        )

    @staticmethod
    async def _remove_signing(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            discord_name: str,
            removal_scope: str,
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        ensure_allowed_member(interaction.user)
        await interaction.response.defer(thinking=True)
        repository = GoogleSheetsTeamRepository(interaction.client.settings)
        if removal_scope == "player":
            result = await repository.remove_team_player_by_discord(discord_name)
        elif removal_scope == "staff":
            result = await repository.remove_team_staff_by_discord(discord_name)
        else:
            result = await repository.remove_team_member_by_discord(discord_name)

        role_removal_message = await remove_discord_roles_after_signing_removal(
            interaction,
            discord_name=discord_name,
            result=result,
        )
        followup_message = build_team_signing_removal_completed_message(
            localizer=interaction.client.localizer,
            locale=interaction.locale,
            discord_name=discord_name,
            result=result,
        )
        if role_removal_message:
            followup_message = f"{followup_message}\n{role_removal_message}"

        await interaction.followup.send(
            followup_message,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(
        name=localized_locale_str(I18N.commands.team_role_assignment.sync_team_role.name),
        description=localized_locale_str(
            I18N.commands.team_role_assignment.sync_team_role.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        equipo=localized_locale_str(
            I18N.commands.team_role_assignment.sync_team_role.parameters.team_role.description
        )
    )
    async def sync_team_role_assignment(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            equipo: discord.Role,
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        ensure_allowed_member(interaction.user)
        settings = interaction.client.settings
        role_catalog = get_channel_access_role_catalog(
            guild,
            settings.channel_access_range_start_role_id,
            settings.channel_access_range_end_role_id,
        )
        if equipo.id not in {role.id for role in role_catalog.roles}:
            raise CommandUserError(
                localize(
                    I18N.errors.match_channel_creation.team_role_out_of_range,
                    role_name=equipo.name,
                    range_start=role_catalog.range_start.name,
                    range_end=role_catalog.range_end.name,
                )
            )

        participant_role = resolve_participant_role(
            guild,
            settings.participant_role_id,
        )
        player_role = resolve_player_role(
            guild,
            settings.player_role_id,
        )
        await interaction.response.defer(thinking=True)
        repository = GoogleSheetsTeamRepository(settings)
        team_profile = await repository.find_team_profile_for_role(equipo)
        assignment_summary = await assign_team_roles_by_names(
            guild,
            team_role=equipo,
            common_roles=(participant_role, player_role),
            actor=interaction.user,
            member_names=collect_team_profile_player_names(team_profile),
        )
        staff_role_sync_summary = await sync_team_staff_roles_by_names(
            guild,
            team_role=equipo,
            participant_role=participant_role,
            ceo_role_id=settings.staff_ceo_role_id,
            analyst_role_id=settings.staff_analyst_role_id,
            coach_role_id=settings.staff_coach_role_id,
            manager_role_id=settings.staff_manager_role_id,
            second_manager_role_id=settings.staff_second_manager_role_id,
            captain_role_id=settings.staff_captain_role_id,
            actor=interaction.user,
            staff_entries=collect_team_profile_staff_role_entries(team_profile),
        )
        await reconcile_team_role_assignment(
            bot=self.bot,
            guild=guild,
            actor=interaction.user,
            team_role=equipo,
            participant_role=participant_role,
            player_role=player_role,
            team_profile=team_profile,
        )
        await interaction.followup.send(
            build_team_role_sync_message(
                localizer=interaction.client.localizer,
                locale=interaction.locale,
                team_name=equipo.name,
                assignment_summary=assignment_summary,
                staff_role_sync_summary=staff_role_sync_summary,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

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
            await interaction.followup.send(message)
            return

        await interaction.response.send_message(message)


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(TeamSigningCog(bot))
