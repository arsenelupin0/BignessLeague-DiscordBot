from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from bigness_league_bot.application.services.team_signing import (
    TeamSigningBatch,
    TeamSigningPlayer,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.discord import team_signing_workflow as workflow
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    ChannelAccessRoleRangeError,
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.team_role_provisioning import (
    resolve_or_create_team_role,
)


class _GuildStub:
    """Keep gateway state stale until Discord returns the reordered hierarchy."""

    id = 1

    def __init__(self, names: tuple[str, ...]) -> None:
        self._server_roles = [
            {"id": str(index + 1), "name": name, "position": index, "managed": False}
            for index, name in enumerate(names)
        ]
        self._state = SimpleNamespace(http=SimpleNamespace(
            move_role_position=AsyncMock(side_effect=self._move_role_positions),
        ))
        self._roles = {role.id: role for role in self._snapshot()}
        self.default_role = self._roles[self.id]
        self.create_role = AsyncMock(side_effect=self._create_role)
        self.fetch_roles = AsyncMock(side_effect=self._fetch_roles)
        self.edit_role_positions = AsyncMock(side_effect=self._edit_role_positions)

    @property
    def roles(self) -> list[discord.Role]:
        return sorted(self._roles.values())

    def get_role(self, role_id: int) -> discord.Role | None:
        return self._roles.get(role_id)

    def _snapshot(self) -> list[discord.Role]:
        return [
            discord.Role(guild=self, state=self._state, data=dict(data))
            for data in self._server_roles
        ]

    async def _fetch_roles(self) -> list[discord.Role]:
        return self._snapshot()

    async def _create_role(self, *, name: str, colour: discord.Colour,
                           hoist: bool, reason: str) -> discord.Role:
        for data in self._server_roles:
            if data["position"] > 0:
                data["position"] += 1
        data = {"id": "100", "name": name, "position": 1, "managed": False,
                "colors": {"primary_color": colour.value}, "hoist": hoist}
        self._server_roles.append(data)
        return discord.Role(guild=self, state=self._state, data=dict(data))

    async def _move_role_positions(self, guild_id: int, payload: list[dict],
                                   *, reason: str) -> list[dict]:
        original_positions = sorted(data["position"] for data in self._server_roles)
        positions = {str(item["id"]): item["position"] for item in payload}
        for data in self._server_roles:
            if data["id"] in positions:
                data["position"] = positions[data["id"]]
        # A complete insertion must not leave collisions with the separators or
        # unrelated roles, even when the segment had no free position.
        assert sorted(data["position"] for data in self._server_roles) == original_positions
        return [dict(data) for data in self._server_roles]

    async def _edit_role_positions(self, **kwargs) -> list[discord.Role]:
        return await discord.Guild.edit_role_positions(self, **kwargs)


class TeamRoleCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guild = _GuildStub(("@everyone", "inferior", "superior", "bot"))

    def test_selectors_still_reject_an_empty_segment(self) -> None:
        with self.assertRaises(ChannelAccessRoleRangeError) as caught:
            get_channel_access_role_catalog(self.guild, 3, 2)
        self.assertEqual(caught.exception.message.key,
                         "errors.channel_management.range_empty")

    def test_creation_can_resolve_adjacent_separators(self) -> None:
        catalog = get_channel_access_role_catalog(self.guild, 3, 2, allow_empty=True)
        self.assertEqual(catalog.roles, ())
        self.assertEqual((catalog.range_start.id, catalog.range_end.id), (3, 2))

    def test_allow_empty_still_validates_both_separator_ids(self) -> None:
        for start, end in ((999, 2), (3, 999)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ChannelAccessRoleRangeError):
                    get_channel_access_role_catalog(self.guild, start, end, allow_empty=True)


class TeamRoleProvisioningTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_team_is_created_with_colour_and_inserted_between_separators(self) -> None:
        guild = _GuildStub(("@everyone", "ajeno", "inferior", "superior", "bot"))
        catalog = get_channel_access_role_catalog(guild, 4, 3, allow_empty=True)
        result = await resolve_or_create_team_role(
            guild, team_name="Nuevo equipo", role_catalog=catalog,
            actor=SimpleNamespace(name="Staff", id=50), create_if_missing=True,
        )
        self.assertTrue(result.created)
        self.assertGreater(result.role.colour.value, 0)
        self.assertTrue(result.role.hoist)
        self.assertLess(guild.get_role(3), result.role)
        self.assertLess(result.role, guild.get_role(4))
        self.assertEqual([role.name for role in guild.roles],
                         ["@everyone", "ajeno", "inferior", "Nuevo equipo", "superior", "bot"])
        self.assertIs(result.role, guild.get_role(100))

    async def test_new_team_keeps_alphabetical_order_with_existing_teams(self) -> None:
        for start, end in ((6, 3), (3, 6)):
            with self.subTest(start=start, end=end):
                guild = _GuildStub(("@everyone", "ajeno", "inferior", "Zulu", "Alpha", "superior", "bot"))
                catalog = get_channel_access_role_catalog(guild, start, end)
                await resolve_or_create_team_role(
                    guild, team_name="Bravo", role_catalog=catalog,
                    actor=SimpleNamespace(name="Staff", id=50), create_if_missing=True,
                )
                refreshed = get_channel_access_role_catalog(guild, start, end)
                self.assertEqual([role.name for role in refreshed.roles], ["Alpha", "Bravo", "Zulu"])
                self.assertEqual([role.name for role in guild.roles[:3]],
                                 ["@everyone", "ajeno", "inferior"])
                self.assertEqual([role.name for role in guild.roles[-2:]], ["superior", "bot"])

    async def test_existing_role_is_reused_without_creation_or_reordering(self) -> None:
        guild = _GuildStub(("@everyone", "inferior", "Alpha", "superior", "bot"))
        catalog = get_channel_access_role_catalog(guild, 4, 2)
        result = await resolve_or_create_team_role(
            guild, team_name=" ALPHA ", role_catalog=catalog,
            actor=SimpleNamespace(name="Staff", id=50), create_if_missing=True,
        )
        self.assertFalse(result.created)
        self.assertEqual(result.role.id, 3)
        guild.create_role.assert_not_awaited()
        guild.edit_role_positions.assert_not_awaited()

    async def test_roles_above_the_segment_are_not_renumbered_when_positions_are_tied(self) -> None:
        guild = _GuildStub(("@everyone", "inferior", "superior", "admin", "bot"))
        guild._server_roles[-1]["position"] = 3
        guild._roles = {role.id: role for role in guild._snapshot()}
        catalog = get_channel_access_role_catalog(guild, 3, 2, allow_empty=True)
        await resolve_or_create_team_role(
            guild, team_name="Nuevo equipo", role_catalog=catalog,
            actor=SimpleNamespace(name="Staff", id=50), create_if_missing=True,
        )
        moved_ids = {role.id for role in guild.edit_role_positions.await_args.kwargs["positions"]}
        self.assertEqual(moved_ids, {2, 100})
        self.assertEqual(guild.get_role(4).position, 4)
        self.assertEqual(guild.get_role(5).position, 4)


class TeamRegistrationWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.guild = _GuildStub(("@everyone", "inferior", "superior", "Participante", "Jugador", "bot"))
        self.settings = SimpleNamespace(
            channel_access_range_start_role_id=3, channel_access_range_end_role_id=2,
            participant_role_id=4, player_role_id=5,
        )
        self.interaction = SimpleNamespace(
            client=SimpleNamespace(settings=self.settings, localizer=Mock()),
            user=SimpleNamespace(name="Staff", id=50), locale="es-ES",
            followup=SimpleNamespace(send=AsyncMock()),
        )
        self.batch = TeamSigningBatch(
            division_name="GOLD DIVISION S4", team_name="Nuevo equipo",
            team_logo_url="https://example.com/logo.png",
            players=tuple(TeamSigningPlayer(
                player_name=f"Jugador {index}", discord_id=str(1000 + index),
                platform="epic", platform_id=f"player{index}", epic_name=f"player{index}",
                tracker_url=f"https://example.com/player{index}", mmr="1500",
            ) for index in range(3)),
        )
        self.repository = SimpleNamespace(register_team_signings=AsyncMock(
            return_value=SimpleNamespace(created_team_block=True),
        ))
        self.assignment = AsyncMock()
        self.dependencies = patch.multiple(
            workflow,
            GoogleSheetsTeamRepository=Mock(return_value=self.repository),
            assign_team_roles_by_names=self.assignment,
            build_team_signing_import_completed_message=Mock(return_value="Inscrito"),
            build_team_signing_visibility_message=Mock(return_value=""),
            build_team_signing_removal_visibility_message=Mock(return_value=""),
        )
        self.dependencies.start()
        self.addCleanup(self.dependencies.stop)

    async def _import(self, *, registration: bool = True) -> None:
        await workflow.handle_team_signing_import(
            self.interaction, bot=self.interaction.client, guild=self.guild,
            signing_batch=self.batch, technical_staff_batch=None,
            require_new_team_block=registration, publish_announcements=False,
        )

    async def test_registration_reaches_sheets_and_assigns_the_first_team_role(self) -> None:
        await self._import()
        self.repository.register_team_signings.assert_awaited_once_with(
            self.batch, require_new_team_block=True,
        )
        assigned = self.assignment.await_args.kwargs
        self.assertEqual(assigned["team_role"].name, "Nuevo equipo")
        self.assertEqual(tuple(assigned["member_names"]), ("1000", "1001", "1002"))
        self.assertEqual([role.name for role in assigned["common_roles"]], ["Participante", "Jugador"])
        self.interaction.followup.send.assert_awaited_once()

    async def test_failed_sheet_registration_does_not_create_a_discord_role(self) -> None:
        self.repository.register_team_signings.side_effect = RuntimeError("Sheets rejected registration")
        with self.assertRaisesRegex(RuntimeError, "Sheets rejected"):
            await self._import()
        self.guild.create_role.assert_not_awaited()
        self.assignment.assert_not_awaited()

    async def test_existing_sheet_block_does_not_authorize_creation_of_missing_role(self) -> None:
        self.repository.register_team_signings.return_value.created_team_block = False
        with self.assertRaises(CommandUserError):
            await self._import(registration=False)
        self.guild.create_role.assert_not_awaited()

    async def test_player_signing_can_also_create_a_new_team_in_an_empty_segment(self) -> None:
        await self._import(registration=False)
        self.repository.register_team_signings.assert_awaited_once_with(
            self.batch, require_new_team_block=False,
        )
        self.guild.create_role.assert_awaited_once()

    async def test_staff_only_import_keeps_the_empty_segment_validation(self) -> None:
        with self.assertRaises(ChannelAccessRoleRangeError):
            await workflow.handle_team_signing_import(
                self.interaction, bot=self.interaction.client, guild=self.guild,
                signing_batch=None, technical_staff_batch=SimpleNamespace(),
                require_new_team_block=False, publish_announcements=False,
            )
        self.repository.register_team_signings.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
