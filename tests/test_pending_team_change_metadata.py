from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bigness_league_bot.infrastructure.discord import pending_team_signing_resolver as pending
from bigness_league_bot.infrastructure.google.team_sheets.errors import TeamSheetRequestError
from bigness_league_bot.infrastructure.google.team_sheets.models import TeamRoleSheetMetadata


class PendingTeamChangeMetadataTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.guild = SimpleNamespace(id=1, name="Bigness League")
        self.role = SimpleNamespace(id=30, name="Profit")
        self.assignment = SimpleNamespace(
            division_name="SILVER DIVISION S4", team_role_name="Profit",
            team_image_url="https://example.com/expired.png", source="hacer_fichaje",
        )
        self.resolver = pending.PendingTeamSigningAssignmentResolver.__new__(
            pending.PendingTeamSigningAssignmentResolver,
        )
        self.resolver.bot = SimpleNamespace(settings=SimpleNamespace(
            team_role_removal_announcement_channel_id=1555268803984883713,
        ))
        self.sender = SimpleNamespace(
            send_team_role_change_announcement=AsyncMock(return_value=SimpleNamespace(id=40)),
            send_staff_role_change_announcement=AsyncMock(return_value=SimpleNamespace(id=41)),
        )
        self.resolver.announcement_sender = self.sender

    async def send(self, repository):
        with patch.object(pending, "resolve_team_change_bulletin_channel", new=AsyncMock()), \
                patch.object(pending, "create_team_change_repository", new=AsyncMock(return_value=repository)):
            return await self.resolver._send_announcements(
                member=SimpleNamespace(guild=self.guild), assignment=self.assignment,
                team_role=self.role, staff_roles=(SimpleNamespace(id=31, name="Capitán"),),
                added_role_ids={30, 31},
            )

    async def test_pending_announcement_uses_current_sheet_link_for_team_and_staff(self) -> None:
        metadata = TeamRoleSheetMetadata("SILVER DIVISION S4", "Profit", "https://example.com/new.png")
        repository = SimpleNamespace(find_team_sheet_metadata_for_role=AsyncMock(return_value=metadata))
        self.assertEqual(await self.send(repository), (40, 41))
        repository.find_team_sheet_metadata_for_role.assert_awaited_once_with(self.role)
        self.assertIs(self.sender.send_team_role_change_announcement.await_args.kwargs["metadata"], metadata)
        self.assertIs(self.sender.send_staff_role_change_announcement.await_args.kwargs["metadata"], metadata)

    async def test_auto_assignment_without_snapshot_logo_still_reads_current_sheet(self) -> None:
        self.assignment.team_image_url = None
        self.assignment.source = "auto_assign_on_join"
        metadata = TeamRoleSheetMetadata("SILVER DIVISION S4", "Profit", "https://example.com/current.png")
        repository = SimpleNamespace(find_team_sheet_metadata_for_role=AsyncMock(return_value=metadata))
        await self.send(repository)
        self.assertEqual(self.sender.send_team_role_change_announcement.await_args.kwargs["metadata"], metadata)

    async def test_removed_link_does_not_restore_the_assignment_snapshot(self) -> None:
        metadata = TeamRoleSheetMetadata("SILVER DIVISION S4", "Profit", None)
        repository = SimpleNamespace(find_team_sheet_metadata_for_role=AsyncMock(return_value=metadata))
        await self.send(repository)
        self.assertIsNone(self.sender.send_team_role_change_announcement.await_args.kwargs["metadata"].team_image_url)

    async def test_sheet_failure_uses_default_instead_of_old_snapshot(self) -> None:
        repository = SimpleNamespace(find_team_sheet_metadata_for_role=AsyncMock(
            side_effect=TeamSheetRequestError("unavailable"),
        ))
        with self.assertLogs("bigness_league_bot.activity", level="WARNING"):
            await self.send(repository)
        self.assertIsNone(self.sender.send_team_role_change_announcement.await_args.kwargs["metadata"].team_image_url)

    async def test_disabled_sheet_repository_does_not_reuse_snapshot(self) -> None:
        await self.send(None)
        self.assertIsNone(self.sender.send_team_role_change_announcement.await_args.kwargs["metadata"].team_image_url)
