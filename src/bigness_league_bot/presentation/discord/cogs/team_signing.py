from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.team_signing import (
    TeamSigningParseError,
    parse_team_signing_message,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import TranslationKeyLike, localize
from bigness_league_bot.infrastructure.discord.channel_management import (
    UnsupportedChannelError,
    ensure_allowed_member,
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    TeamRoleAssignmentSummary,
    TeamRoleRemovalSummary,
    assign_team_roles_by_names,
    collect_team_profile_member_names,
    remove_roles_from_member_by_name,
    resolve_optional_team_staff_roles,
    resolve_participant_role,
    resolve_player_role,
    resolve_team_role_by_name,
)
from bigness_league_bot.infrastructure.discord.team_signing import (
    fetch_linked_message,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class TeamSigningCog(commands.Cog):
    @app_commands.command(
        name=localized_locale_str(I18N.commands.team_signing.make_signing.name),
        description=localized_locale_str(
            I18N.commands.team_signing.make_signing.description
        ),
    )
    @app_commands.guild_only()
    @app_commands.describe(
        enlace_mensaje=localized_locale_str(
            I18N.commands.team_signing.make_signing.parameters.message_link.description
        )
    )
    async def make_signing(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            enlace_mensaje: str,
    ) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        ensure_allowed_member(interaction.user)

        await interaction.response.defer(thinking=True)
        settings = interaction.client.settings
        role_catalog = get_channel_access_role_catalog(
            guild,
            settings.channel_access_range_start_role_id,
            settings.channel_access_range_end_role_id,
        )
        linked_message = await fetch_linked_message(
            interaction.client,
            guild,
            enlace_mensaje,
        )
        try:
            signing_batch = parse_team_signing_message(linked_message.content)
        except TeamSigningParseError as exc:
            raise CommandUserError(
                localize(
                    I18N.errors.team_signing.invalid_message_format,
                    details=str(exc),
                )
            ) from exc

        team_role = resolve_team_role_by_name(signing_batch.team_name, role_catalog)
        participant_role = resolve_participant_role(
            guild,
            settings.participant_role_id,
        )
        player_role = resolve_player_role(
            guild,
            settings.player_role_id,
        )
        repository = GoogleSheetsTeamRepository(interaction.client.settings)
        result = await repository.register_team_signings(signing_batch)
        assignment_summary = await assign_team_roles_by_names(
            guild,
            team_role=team_role,
            common_roles=(participant_role, player_role),
            actor=interaction.user,
            member_names=(player.discord_name for player in signing_batch.players),
        )
        await interaction.followup.send(
            self._build_signing_completed_message(
                interaction,
                division_name=result.worksheet_title,
                team_name=result.team_name,
                inserted_count=result.inserted_count,
                total_players=result.total_players,
                assignment_summary=assignment_summary,
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
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise UnsupportedChannelError(
                localize(I18N.errors.channel_management.server_only)
            )

        ensure_allowed_member(interaction.user)
        await interaction.response.defer(thinking=True)
        repository = GoogleSheetsTeamRepository(interaction.client.settings)
        result = await repository.remove_team_player_by_discord(discord_jugador)
        role_removal_message = await self._remove_discord_roles_after_signing_removal(
            interaction,
            discord_name=discord_jugador,
            team_name=result.team_name,
            technical_staff_role_names=result.technical_staff_role_names,
        )
        followup_message = interaction.client.localizer.translate(
            I18N.actions.team_signing.removed,
            locale=interaction.locale,
            discord_name=discord_jugador,
            player_name=result.removed_player_name,
            team_name=result.team_name,
            division_name=result.worksheet_title,
            total_players=str(result.total_players),
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
            member_names=collect_team_profile_member_names(team_profile),
        )
        await interaction.followup.send(
            self._build_team_role_sync_message(
                interaction,
                team_name=equipo.name,
                assignment_summary=assignment_summary,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @staticmethod
    def _build_signing_completed_message(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            division_name: str,
            team_name: str,
            inserted_count: int,
            total_players: int,
            assignment_summary: TeamRoleAssignmentSummary,
    ) -> str:
        localizer = interaction.client.localizer
        locale = interaction.locale
        message_lines = [
            localizer.translate(
                I18N.actions.team_signing.completed,
                locale=locale,
                division_name=division_name,
                team_name=team_name,
                inserted_count=str(inserted_count),
                total_players=str(total_players),
            ),
            localizer.translate(
                I18N.actions.team_signing.role_assignment_summary,
                locale=locale,
                assigned_count=str(len(assignment_summary.assigned_members)),
                already_count=str(len(assignment_summary.already_configured_members)),
                unresolved_count=str(len(assignment_summary.unresolved_names)),
                ambiguous_count=str(len(assignment_summary.ambiguous_names)),
            ),
        ]
        message_lines.extend(
            TeamSigningCog._build_assignment_detail_lines(
                interaction,
                assignment_summary=assignment_summary,
                unresolved_key=I18N.actions.team_signing.role_assignment_unresolved,
                ambiguous_key=I18N.actions.team_signing.role_assignment_ambiguous,
            )
        )
        return "\n".join(message_lines)

    @staticmethod
    def _build_team_role_sync_message(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            team_name: str,
            assignment_summary: TeamRoleAssignmentSummary,
    ) -> str:
        localizer = interaction.client.localizer
        locale = interaction.locale
        message_lines = [
            localizer.translate(
                I18N.actions.team_role_assignment.completed,
                locale=locale,
                team_name=team_name,
                assigned_count=str(len(assignment_summary.assigned_members)),
                already_count=str(len(assignment_summary.already_configured_members)),
                unresolved_count=str(len(assignment_summary.unresolved_names)),
                ambiguous_count=str(len(assignment_summary.ambiguous_names)),
            )
        ]
        message_lines.extend(
            TeamSigningCog._build_assignment_detail_lines(
                interaction,
                assignment_summary=assignment_summary,
                unresolved_key=I18N.actions.team_role_assignment.unresolved,
                ambiguous_key=I18N.actions.team_role_assignment.ambiguous,
            )
        )
        return "\n".join(message_lines)

    @staticmethod
    def _build_assignment_detail_lines(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            assignment_summary: TeamRoleAssignmentSummary,
            unresolved_key: TranslationKeyLike,
            ambiguous_key: TranslationKeyLike,
    ) -> list[str]:
        localizer = interaction.client.localizer
        locale = interaction.locale
        message_lines: list[str] = []
        if assignment_summary.unresolved_names:
            message_lines.append(
                localizer.translate(
                    unresolved_key,
                    locale=locale,
                    names=", ".join(assignment_summary.unresolved_names),
                )
            )
        if assignment_summary.ambiguous_names:
            message_lines.append(
                localizer.translate(
                    ambiguous_key,
                    locale=locale,
                    names=", ".join(assignment_summary.ambiguous_names),
                )
            )
        return message_lines

    @staticmethod
    async def _remove_discord_roles_after_signing_removal(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            discord_name: str,
            team_name: str,
            technical_staff_role_names: tuple[str, ...],
    ) -> str | None:
        guild = interaction.guild
        if guild is None:
            return None

        settings = interaction.client.settings
        role_catalog = get_channel_access_role_catalog(
            guild,
            settings.channel_access_range_start_role_id,
            settings.channel_access_range_end_role_id,
        )
        localizer = interaction.client.localizer
        locale = interaction.locale
        try:
            team_role = resolve_team_role_by_name(team_name, role_catalog)
            participant_role = resolve_participant_role(
                guild,
                settings.participant_role_id,
            )
            player_role = resolve_player_role(
                guild,
                settings.player_role_id,
            )
            staff_roles = resolve_optional_team_staff_roles(
                guild,
                ceo_role_id=settings.staff_ceo_role_id,
                coach_role_id=settings.staff_coach_role_id,
                manager_role_id=settings.staff_manager_role_id,
                captain_role_id=settings.staff_captain_role_id,
                staff_role_names=technical_staff_role_names,
            )
            removal_summary = await remove_roles_from_member_by_name(
                guild,
                actor=interaction.user,
                member_name=discord_name,
                roles_to_remove=(participant_role, player_role, team_role, *staff_roles),
            )
        except (CommandUserError, discord.Forbidden, discord.HTTPException) as exc:
            return localizer.translate(
                I18N.actions.team_signing.role_removal_failed,
                locale=locale,
                details=str(exc),
            )

        return TeamSigningCog._format_role_removal_message(
            interaction,
            discord_name=discord_name,
            removal_summary=removal_summary,
        )

    @staticmethod
    def _format_role_removal_message(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            discord_name: str,
            removal_summary: TeamRoleRemovalSummary,
    ) -> str:
        localizer = interaction.client.localizer
        locale = interaction.locale
        if removal_summary.unresolved:
            return localizer.translate(
                I18N.actions.team_signing.role_removal_unresolved,
                locale=locale,
                discord_name=discord_name,
            )
        if removal_summary.ambiguous:
            return localizer.translate(
                I18N.actions.team_signing.role_removal_ambiguous,
                locale=locale,
                discord_name=discord_name,
            )
        if not removal_summary.removed_roles:
            member_label = (
                str(removal_summary.member)
                if removal_summary.member is not None
                else discord_name
            )
            return localizer.translate(
                I18N.actions.team_signing.role_removal_no_changes,
                locale=locale,
                member_name=member_label,
            )

        return localizer.translate(
            I18N.actions.team_signing.role_removal_completed,
            locale=locale,
            member_name=str(removal_summary.member),
            roles=", ".join(role.name for role in removal_summary.removed_roles),
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
    await bot.add_cog(TeamSigningCog())
