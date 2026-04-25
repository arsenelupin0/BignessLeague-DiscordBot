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

from bigness_league_bot.application.services.team_signing import (
    TeamSigningBatch,
    TeamTechnicalStaffBatch,
)
from bigness_league_bot.core.localization import TranslationKeyLike
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    TeamRoleAssignmentSummary,
    TeamRoleRemovalSummary,
    TeamStaffRoleEntry,
    TeamStaffRoleSyncSummary,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    TeamSigningRemovalResult,
    TeamSigningWriteResult,
    TeamTechnicalStaffWriteResult,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.i18n.service import LocalizationService

DISCORD_MESSAGE_CONTENT_LIMIT = 2000
TEAM_SIGNING_GUIDE_SPLIT_MARKERS = (
    "Copia la plantilla tal cual",
    "Copy the template exactly",
)


def split_discord_message_content(content: str) -> tuple[str, ...]:
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


def build_team_signing_import_completed_message(
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        division_name: str,
        team_name: str,
        signing_batch: TeamSigningBatch | None,
        technical_staff_batch: TeamTechnicalStaffBatch | None,
        player_result: TeamSigningWriteResult | None,
        technical_staff_result: TeamTechnicalStaffWriteResult | None,
        assignment_summary: TeamRoleAssignmentSummary | None,
        staff_role_sync_summary: TeamStaffRoleSyncSummary | None,
) -> str:
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
            _build_assignment_detail_lines(
                localizer=localizer,
                locale=locale,
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
                _build_assignment_detail_lines(
                    localizer=localizer,
                    locale=locale,
                    assignment_summary=staff_role_sync_summary,
                    unresolved_key=I18N.actions.team_signing.role_assignment_unresolved,
                    ambiguous_key=I18N.actions.team_signing.role_assignment_ambiguous,
                )
            )

    return "\n".join(message_lines)


def build_team_role_sync_message(
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        team_name: str,
        assignment_summary: TeamRoleAssignmentSummary,
        staff_role_sync_summary: TeamStaffRoleSyncSummary,
) -> str:
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
        _build_assignment_detail_lines(
            localizer=localizer,
            locale=locale,
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
        _build_assignment_detail_lines(
            localizer=localizer,
            locale=locale,
            assignment_summary=staff_role_sync_summary,
            unresolved_key=I18N.actions.team_role_assignment.unresolved,
            ambiguous_key=I18N.actions.team_role_assignment.ambiguous,
        )
    )
    return "\n".join(message_lines)


def collect_technical_staff_role_entries(
        technical_staff_batch: TeamTechnicalStaffBatch,
) -> tuple[TeamStaffRoleEntry, ...]:
    return tuple(
        TeamStaffRoleEntry(
            role_name=member.role_name,
            member_name=member.discord_name,
        )
        for member in technical_staff_batch.members
    )


def build_team_signing_removal_completed_message(
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        discord_name: str,
        result: TeamSigningRemovalResult,
) -> str:
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


def format_team_role_removal_message(
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        discord_name: str,
        removal_summary: TeamRoleRemovalSummary,
) -> str:
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


def _build_assignment_detail_lines(
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        assignment_summary: TeamRoleAssignmentSummary | TeamStaffRoleSyncSummary,
        unresolved_key: TranslationKeyLike,
        ambiguous_key: TranslationKeyLike,
) -> list[str]:
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
