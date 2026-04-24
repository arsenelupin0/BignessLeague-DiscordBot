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
from bigness_league_bot.infrastructure.discord.error_handling import (
    classify_app_command_error,
)
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    TeamStaffRoleEntry,
    TeamStaffRoleSyncSummary,
    TeamRoleAssignmentSummary,
    TeamRoleRemovalSummary,
    assign_team_roles_by_names,
    build_member_lookup_keys,
    collect_team_profile_player_names,
    collect_team_profile_staff_role_entries,
    normalize_member_lookup_text,
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
    TeamMemberSheetAffiliation,
    TeamSigningRemovalResult,
    TeamSigningWriteResult,
    TeamTechnicalStaffWriteResult,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import localized_locale_str
from bigness_league_bot.presentation.discord.ticket_command_mirroring import (
    mirror_ticket_text_command_message,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

DISCORD_MESSAGE_CONTENT_LIMIT = 2000
TEAM_SIGNING_GUIDE_SPLIT_MARKERS = (
    "Copia la plantilla tal cual",
    "Copy the template exactly",
)


def _split_discord_message_content(content: str) -> tuple[str, ...]:
    chunks: list[str] = []
    remaining = content.strip()
    preferred_separators = ("\n## ", "\n\n", "\n")

    split_marker_start = min(
        (
            marker_start_index
            for marker in TEAM_SIGNING_GUIDE_SPLIT_MARKERS
            if (marker_start_index := remaining.find(marker)) >= 0
        ),
        default=-1,
    )
    split_marker_index = -1
    if split_marker_start >= 0:
        closing_bold_index = remaining.find("**", split_marker_start)
        if closing_bold_index >= 0:
            split_marker_index = closing_bold_index + len("**")

    if 0 < split_marker_index <= DISCORD_MESSAGE_CONTENT_LIMIT:
        return (
            remaining[:split_marker_index].strip(),
            remaining[split_marker_index:].strip(),
        )

    while len(remaining) > DISCORD_MESSAGE_CONTENT_LIMIT:
        split_at = -1
        for separator in preferred_separators:
            candidate = remaining.rfind(
                separator,
                0,
                DISCORD_MESSAGE_CONTENT_LIMIT + 1,
            )
            if candidate > 0:
                split_at = candidate
                break

        if split_at <= 0:
            split_at = DISCORD_MESSAGE_CONTENT_LIMIT

        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return tuple(chunks)


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
        for chunk in _split_discord_message_content(content):
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

    async def _remove_signing(
            self,
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

        role_removal_message = await self._remove_discord_roles_after_signing_removal(
            interaction,
            discord_name=discord_name,
            result=result,
        )
        followup_message = self._build_removal_completed_message(
            interaction,
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
        await self._reconcile_team_role_assignment(
            guild,
            actor=interaction.user,
            team_role=equipo,
            participant_role=participant_role,
            player_role=player_role,
            team_profile=team_profile,
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
    def _build_removal_completed_message(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            discord_name: str,
            result: TeamSigningRemovalResult,
    ) -> str:
        localizer = interaction.client.localizer
        locale = interaction.locale
        message_lines: list[str] = []
        if result.removed_player_name is not None and result.total_players is not None:
            message_lines.append(
                localizer.translate(
                    I18N.actions.team_signing.removed,
                    locale=locale,
                    discord_name=discord_name,
                    player_name=result.removed_player_name,
                    team_name=result.team_name,
                    division_name=result.worksheet_title,
                    total_players=str(result.total_players),
                )
            )

        if result.removed_staff_role_names:
            message_lines.append(
                localizer.translate(
                    I18N.actions.team_signing.technical_staff_removed,
                    locale=locale,
                    discord_name=discord_name,
                    team_name=result.team_name,
                    division_name=result.worksheet_title,
                    staff_roles=", ".join(result.removed_staff_role_names),
                )
            )

        return "\n".join(message_lines)

    @staticmethod
    async def _remove_discord_roles_after_signing_removal(
            interaction: discord.Interaction[BignessLeagueBot],
            *,
            discord_name: str,
            result: TeamSigningRemovalResult,
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
            team_role = resolve_team_role_by_name(result.team_name, role_catalog)
            participant_role = resolve_participant_role(
                guild,
                settings.participant_role_id,
            )
            player_role = resolve_player_role(
                guild,
                settings.player_role_id,
            )
            has_team_affiliation_after = (
                    result.is_player_present_after
                    or bool(result.remaining_staff_role_names)
            )
            roles_to_remove: list[discord.Role] = []
            if result.removed_player_name is not None:
                roles_to_remove.append(player_role)

            staff_roles = resolve_optional_team_staff_roles(
                guild,
                ceo_role_id=settings.staff_ceo_role_id,
                analyst_role_id=settings.staff_analyst_role_id,
                coach_role_id=settings.staff_coach_role_id,
                manager_role_id=settings.staff_manager_role_id,
                second_manager_role_id=settings.staff_second_manager_role_id,
                captain_role_id=settings.staff_captain_role_id,
                staff_role_names=result.removed_staff_role_names,
            )
            roles_to_remove.extend(staff_roles)
            if not has_team_affiliation_after:
                roles_to_remove.extend((participant_role, team_role))

            removal_summary = await remove_roles_from_member_by_name(
                guild,
                actor=interaction.user,
                member_name=discord_name,
                roles_to_remove=roles_to_remove,
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

    async def _reconcile_team_role_assignment(
            self,
            guild: discord.Guild,
            *,
            actor: discord.Member,
            team_role: discord.Role,
            participant_role: discord.Role,
            player_role: discord.Role,
            team_profile,
    ) -> None:
        current_team_members = await self._load_current_team_members(
            guild,
            team_role=team_role,
        )
        if not current_team_members:
            return

        affiliations_by_lookup = self._build_team_profile_affiliations(team_profile)
        configured_staff_roles = self._resolve_configured_staff_roles(
            guild,
        )
        for member in current_team_members:
            member_affiliation = self._resolve_member_affiliation(
                member,
                affiliations_by_lookup=affiliations_by_lookup,
            )
            desired_staff_roles = ()
            if member_affiliation is not None and member_affiliation.staff_role_names:
                desired_staff_roles = resolve_optional_team_staff_roles(
                    guild,
                    ceo_role_id=self.bot.settings.staff_ceo_role_id,
                    analyst_role_id=self.bot.settings.staff_analyst_role_id,
                    coach_role_id=self.bot.settings.staff_coach_role_id,
                    manager_role_id=self.bot.settings.staff_manager_role_id,
                    second_manager_role_id=self.bot.settings.staff_second_manager_role_id,
                    captain_role_id=self.bot.settings.staff_captain_role_id,
                    staff_role_names=member_affiliation.staff_role_names,
                )

            roles_to_remove: dict[int, discord.Role] = {}
            if member_affiliation is None and team_role in member.roles:
                roles_to_remove[team_role.id] = team_role

            if member_affiliation is None:
                if participant_role in member.roles:
                    roles_to_remove[participant_role.id] = participant_role
                if player_role in member.roles:
                    roles_to_remove[player_role.id] = player_role
            elif not member_affiliation.is_player:
                if player_role in member.roles:
                    roles_to_remove[player_role.id] = player_role

            desired_staff_role_ids = {role.id for role in desired_staff_roles}
            for configured_staff_role in configured_staff_roles:
                if (
                        configured_staff_role in member.roles
                        and configured_staff_role.id not in desired_staff_role_ids
                ):
                    roles_to_remove[configured_staff_role.id] = configured_staff_role

            if not roles_to_remove:
                continue

            await member.remove_roles(
                *roles_to_remove.values(),
                reason=(
                    f"{actor} ({actor.id}) sincronizo completamente el equipo "
                    f"{team_role.name} segun Google Sheets para {member} ({member.id})"
                ),
            )

    @staticmethod
    async def _load_current_team_members(
            guild: discord.Guild,
            *,
            team_role: discord.Role,
    ) -> tuple[discord.Member, ...]:
        try:
            members = tuple([
                member
                async for member in guild.fetch_members(limit=None)
                if not member.bot and team_role in member.roles
            ])
        except discord.HTTPException:
            members = tuple(
                member
                for member in guild.members
                if not member.bot and team_role in member.roles
            )

        return members

    def _resolve_configured_staff_roles(
            self,
            guild: discord.Guild,
    ) -> tuple[discord.Role, ...]:
        configured_roles: dict[int, discord.Role] = {}
        for role_id in (
                self.bot.settings.staff_ceo_role_id,
                self.bot.settings.staff_analyst_role_id,
                self.bot.settings.staff_coach_role_id,
                self.bot.settings.staff_manager_role_id,
                self.bot.settings.staff_second_manager_role_id,
                self.bot.settings.staff_captain_role_id,
        ):
            role = guild.get_role(role_id)
            if role is not None:
                configured_roles[role.id] = role

        return tuple(configured_roles.values())

    @staticmethod
    def _resolve_member_affiliation(
            member: discord.Member,
            *,
            affiliations_by_lookup: dict[str, TeamMemberSheetAffiliation],
    ) -> TeamMemberSheetAffiliation | None:
        matched_affiliations: list[TeamMemberSheetAffiliation] = []
        for lookup_key in build_member_lookup_keys(member):
            affiliation = affiliations_by_lookup.get(lookup_key)
            if affiliation is not None:
                matched_affiliations.append(affiliation)

        if not matched_affiliations:
            return None

        merged_staff_role_names = tuple(
            sorted(
                {
                    role_name
                    for affiliation in matched_affiliations
                    for role_name in affiliation.staff_role_names
                }
            )
        )
        return TeamMemberSheetAffiliation(
            discord_name=matched_affiliations[0].discord_name,
            is_player=any(affiliation.is_player for affiliation in matched_affiliations),
            staff_role_names=merged_staff_role_names,
        )

    @staticmethod
    def _build_team_profile_affiliations(
            team_profile,
    ) -> dict[str, TeamMemberSheetAffiliation]:
        collected_affiliations: dict[str, TeamMemberSheetAffiliation] = {}

        for player in team_profile.players:
            normalized_discord_name = normalize_member_lookup_text(player.discord_name)
            if normalized_discord_name in {"", "-"}:
                continue

            existing_affiliation = collected_affiliations.get(normalized_discord_name)
            collected_affiliations[normalized_discord_name] = TeamMemberSheetAffiliation(
                discord_name=player.discord_name,
                is_player=True,
                staff_role_names=existing_affiliation.staff_role_names if existing_affiliation is not None else (),
            )

        for staff_member in team_profile.technical_staff:
            normalized_discord_name = normalize_member_lookup_text(staff_member.discord_name)
            if normalized_discord_name in {"", "-"}:
                continue

            existing_affiliation = collected_affiliations.get(normalized_discord_name)
            staff_role_names = set(
                existing_affiliation.staff_role_names if existing_affiliation is not None else ()
            )
            staff_role_names.add(staff_member.role_name)
            collected_affiliations[normalized_discord_name] = TeamMemberSheetAffiliation(
                discord_name=staff_member.discord_name,
                is_player=existing_affiliation.is_player if existing_affiliation is not None else False,
                staff_role_names=tuple(sorted(staff_role_names)),
            )

        return collected_affiliations

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
