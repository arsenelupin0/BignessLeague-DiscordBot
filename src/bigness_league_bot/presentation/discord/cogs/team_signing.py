from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bigness_league_bot.application.services.team_signing import (
    TeamSigningParseError,
    TeamTechnicalStaffBatch,
    TeamSigningBatch,
    parse_team_signing_message,
    parse_team_technical_staff_message,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import TranslationKeyLike, localize
from bigness_league_bot.infrastructure.discord.channel_management import (
    UnsupportedChannelError,
    ensure_allowed_member,
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.emojis import (
    TEAM_ROLE_REMOVAL_WARNING_EMOJI,
    render_custom_emoji,
)
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.team_change_announcements import (
    TEAM_ROLE_SIGNING_SPEC,
    build_team_change_content,
    build_team_change_embed,
    build_team_role_sheet_metadata_fallback,
)
from bigness_league_bot.infrastructure.discord.team_change_bulletin import (
    create_team_change_repository,
    load_team_change_metadata,
    resolve_team_change_bulletin_channel,
)
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    TeamStaffRoleEntry,
    TeamStaffRoleSyncSummary,
    TeamRoleAssignmentSummary,
    TeamRoleRemovalSummary,
    assign_team_roles_by_names,
    collect_team_profile_player_names,
    collect_team_profile_staff_role_entries,
    remove_roles_from_member_by_name,
    resolve_optional_team_staff_roles,
    resolve_participant_role,
    resolve_player_role,
    resolve_team_role_by_name,
    sync_team_staff_roles_by_names,
)
from bigness_league_bot.infrastructure.discord.team_signing import (
    fetch_linked_message,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
    TeamSigningWriteResult,
    TeamTechnicalStaffWriteResult,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class TeamSigningCog(commands.Cog):
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot

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
        signing_batch = await self._parse_player_signing_batch(
            interaction,
            guild=guild,
            message_link=enlace_jugadores,
        )
        technical_staff_batch = await self._parse_technical_staff_batch(
            interaction,
            guild=guild,
            message_link=enlace_staff_tecnico,
        )
        division_name, team_name = self._resolve_import_target(
            signing_batch=signing_batch,
            technical_staff_batch=technical_staff_batch,
        )

        repository = GoogleSheetsTeamRepository(interaction.client.settings)
        team_role = resolve_team_role_by_name(team_name, role_catalog)
        player_result = None
        assignment_summary = None
        if signing_batch is not None:
            participant_role = resolve_participant_role(guild, settings.participant_role_id)
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
                ceo_role_id=settings.staff_ceo_role_id,
                coach_role_id=settings.staff_coach_role_id,
                manager_role_id=settings.staff_manager_role_id,
                captain_role_id=settings.staff_captain_role_id,
                actor=interaction.user,
                staff_entries=self._collect_technical_staff_role_entries(
                    technical_staff_batch
                ),
            )

        await interaction.followup.send(
            self._build_import_completed_message(
                interaction,
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
        if assignment_summary is not None:
            await self._publish_signing_bulletins(
                interaction,
                team_role=team_role,
                assigned_members=assignment_summary.assigned_members,
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
            member_names=collect_team_profile_player_names(team_profile),
        )
        staff_role_sync_summary = await sync_team_staff_roles_by_names(
            guild,
            team_role=equipo,
            ceo_role_id=settings.staff_ceo_role_id,
            coach_role_id=settings.staff_coach_role_id,
            manager_role_id=settings.staff_manager_role_id,
            captain_role_id=settings.staff_captain_role_id,
            actor=interaction.user,
            staff_entries=collect_team_profile_staff_role_entries(team_profile),
        )
        await interaction.followup.send(
            self._build_team_role_sync_message(
                interaction,
                team_name=equipo.name,
                assignment_summary=assignment_summary,
                staff_role_sync_summary=staff_role_sync_summary,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @staticmethod
    async def _parse_player_signing_batch(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            guild: discord.Guild,
            message_link: str | None,
    ) -> TeamSigningBatch | None:
        if message_link is None:
            return None

        linked_message = await fetch_linked_message(
            interaction.client,
            guild,
            message_link,
        )
        try:
            return parse_team_signing_message(linked_message.content)
        except TeamSigningParseError as exc:
            raise CommandUserError(
                localize(
                    I18N.errors.team_signing.invalid_message_format,
                    details=str(exc),
                )
            ) from exc

    @staticmethod
    async def _parse_technical_staff_batch(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            guild: discord.Guild,
            message_link: str | None,
    ) -> TeamTechnicalStaffBatch | None:
        if message_link is None:
            return None

        linked_message = await fetch_linked_message(
            interaction.client,
            guild,
            message_link,
        )
        try:
            return parse_team_technical_staff_message(linked_message.content)
        except TeamSigningParseError as exc:
            raise CommandUserError(
                localize(
                    I18N.errors.team_signing.invalid_technical_staff_message_format,
                    details=str(exc),
                )
            ) from exc

    @staticmethod
    def _resolve_import_target(
            *,
            signing_batch: TeamSigningBatch | None,
            technical_staff_batch: TeamTechnicalStaffBatch | None,
    ) -> tuple[str, str]:
        primary_batch = signing_batch or technical_staff_batch
        if primary_batch is None:
            raise CommandUserError(
                localize(I18N.errors.team_signing.no_import_payload_provided)
            )

        division_name = primary_batch.division_name
        team_name = primary_batch.team_name
        if (
                signing_batch is not None
                and technical_staff_batch is not None
                and (
                signing_batch.division_name != technical_staff_batch.division_name
                or signing_batch.team_name != technical_staff_batch.team_name
        )
        ):
            raise CommandUserError(
                localize(
                    I18N.errors.team_signing.import_payload_mismatch,
                    player_division=signing_batch.division_name,
                    player_team=signing_batch.team_name,
                    staff_division=technical_staff_batch.division_name,
                    staff_team=technical_staff_batch.team_name,
                )
            )

        return division_name, team_name

    @staticmethod
    def _build_import_completed_message(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            division_name: str,
            team_name: str,
            signing_batch: TeamSigningBatch | None,
            technical_staff_batch: TeamTechnicalStaffBatch | None,
            player_result: TeamSigningWriteResult | None,
            technical_staff_result: TeamTechnicalStaffWriteResult | None,
            assignment_summary: TeamRoleAssignmentSummary | None,
            staff_role_sync_summary: TeamStaffRoleSyncSummary | None,
    ) -> str:
        localizer = interaction.client.localizer
        locale = interaction.locale
        message_lines: list[str] = []
        if player_result is not None and signing_batch is not None and assignment_summary is not None:
            message_lines.append(
                localizer.translate(
                    I18N.actions.team_signing.completed,
                    locale=locale,
                    division_name=division_name,
                    team_name=team_name,
                    inserted_count=str(player_result.inserted_count),
                    total_players=str(player_result.total_players),
                )
            )
            message_lines.append(
                localizer.translate(
                    I18N.actions.team_signing.role_assignment_summary,
                    locale=locale,
                    assigned_count=str(len(assignment_summary.assigned_members)),
                    already_count=str(len(assignment_summary.already_configured_members)),
                    unresolved_count=str(len(assignment_summary.unresolved_names)),
                    ambiguous_count=str(len(assignment_summary.ambiguous_names)),
                )
            )
            message_lines.extend(
                TeamSigningCog._build_assignment_detail_lines(
                    interaction,
                    assignment_summary=assignment_summary,
                    unresolved_key=I18N.actions.team_signing.role_assignment_unresolved,
                    ambiguous_key=I18N.actions.team_signing.role_assignment_ambiguous,
                )
            )

        if technical_staff_result is not None and technical_staff_batch is not None:
            message_lines.append(
                localizer.translate(
                    I18N.actions.team_signing.technical_staff_completed,
                    locale=locale,
                    division_name=division_name,
                    team_name=team_name,
                    updated_count=str(technical_staff_result.updated_count),
                )
            )
            if staff_role_sync_summary is not None:
                message_lines.append(
                    localizer.translate(
                        I18N.actions.team_signing.staff_role_sync_summary,
                        locale=locale,
                        assigned_count=str(len(staff_role_sync_summary.assigned_members)),
                        removed_count=str(len(staff_role_sync_summary.removed_members)),
                        already_count=str(len(staff_role_sync_summary.already_configured_members)),
                        unresolved_count=str(len(staff_role_sync_summary.unresolved_names)),
                        ambiguous_count=str(len(staff_role_sync_summary.ambiguous_names)),
                    )
                )
                message_lines.extend(
                    TeamSigningCog._build_assignment_detail_lines(
                        interaction,
                        assignment_summary=staff_role_sync_summary,
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
            staff_role_sync_summary: TeamStaffRoleSyncSummary,
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
        message_lines.append(
            localizer.translate(
                I18N.actions.team_role_assignment.staff_role_sync_summary,
                locale=locale,
                assigned_count=str(len(staff_role_sync_summary.assigned_members)),
                removed_count=str(len(staff_role_sync_summary.removed_members)),
                already_count=str(len(staff_role_sync_summary.already_configured_members)),
                unresolved_count=str(len(staff_role_sync_summary.unresolved_names)),
                ambiguous_count=str(len(staff_role_sync_summary.ambiguous_names)),
            )
        )
        message_lines.extend(
            TeamSigningCog._build_assignment_detail_lines(
                interaction,
                assignment_summary=staff_role_sync_summary,
                unresolved_key=I18N.actions.team_role_assignment.unresolved,
                ambiguous_key=I18N.actions.team_role_assignment.ambiguous,
            )
        )
        return "\n".join(message_lines)

    @staticmethod
    def _build_assignment_detail_lines(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            assignment_summary: TeamRoleAssignmentSummary | TeamStaffRoleSyncSummary,
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
    def _collect_technical_staff_role_entries(
            technical_staff_batch: TeamTechnicalStaffBatch,
    ) -> tuple[TeamStaffRoleEntry, ...]:
        return tuple(
            TeamStaffRoleEntry(
                role_name=member.role_name,
                member_name=member.discord_name,
            )
            for member in technical_staff_batch.members
        )

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

    async def _publish_signing_bulletins(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            team_role: discord.Role,
            assigned_members: tuple[discord.Member, ...],
    ) -> None:
        if not assigned_members:
            return

        guild = interaction.guild
        if guild is None:
            return

        channel = await resolve_team_change_bulletin_channel(
            guild=guild,
            channel_id=interaction.client.settings.team_role_removal_announcement_channel_id,
        )
        if channel is None:
            return

        repository = await create_team_change_repository(
            interaction.client.settings,
            guild=guild,
        )
        metadata = await load_team_change_metadata(
            repository=repository,
            team_role=team_role,
            fallback=build_team_role_sheet_metadata_fallback(team_role),
            guild=guild,
        )
        description = self._build_team_change_description(guild)
        for member in assigned_members:
            content = build_team_change_content(
                bot=interaction.client,
                spec=TEAM_ROLE_SIGNING_SPEC,
                member=member,
                team_role=team_role,
                guild=guild,
            )
            embed, image_file = build_team_change_embed(
                bot=interaction.client,
                spec=TEAM_ROLE_SIGNING_SPEC,
                member=member,
                team_role=team_role,
                guild=guild,
                metadata=metadata,
                description=description,
            )
            allowed_mentions = discord.AllowedMentions(
                everyone=False,
                replied_user=False,
                users=[member],
                roles=[team_role],
            )
            try:
                send_kwargs: dict[str, object] = {
                    "content": content,
                    "embed": embed,
                    "allowed_mentions": allowed_mentions,
                }
                if image_file is not None:
                    send_kwargs["file"] = image_file
                await channel.send(**send_kwargs)
            except (discord.Forbidden, discord.HTTPException):
                continue

    def _build_team_change_description(self, guild: discord.Guild) -> str:
        warning_emoji = render_custom_emoji(
            guild=guild,
            bot=self.bot,
            emoji=TEAM_ROLE_REMOVAL_WARNING_EMOJI,
        )
        return (
            "## "
            f"{warning_emoji} {warning_emoji} {warning_emoji} {warning_emoji}"
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
