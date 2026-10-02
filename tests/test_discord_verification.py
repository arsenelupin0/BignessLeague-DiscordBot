from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from bigness_league_bot.application.services.discord_verification import (
    ExpectedRole, IdentityResolution, MemberSnapshot, VerificationStatus,
    collect_roster_identities, parse_discord_id, verify_team,
)
from bigness_league_bot.application.services.team_profile import (
    TeamProfile, TeamProfilePlayer, TeamProfileStaffMember,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.discord.discord_verification import verify_discord_rosters
from bigness_league_bot.infrastructure.discord.discord_verification_messages import build_verification_pages
from bigness_league_bot.infrastructure.google.team_sheets.models import SheetCell
from bigness_league_bot.infrastructure.google.team_sheets.queries import TeamSheetQueryService
from bigness_league_bot.infrastructure.i18n.service import LocalizationService
from bigness_league_bot.presentation.discord.cogs.discord_verification import DiscordVerificationCog
from bigness_league_bot.presentation.discord.views.discord_verification import DiscordVerificationView

PRESENT_ID = 123456789012345678
MISSING_ID = 234567890123456789


def player(value: str, name: str = "Jugador") -> TeamProfilePlayer:
    return TeamProfilePlayer(1, name, value, "epic", "abc", "epic-name", "1500")


def profile(*values: str, team: str = "Equipo", staff=()) -> TeamProfile:
    return TeamProfile(team, "Gold Division S4", "", "", tuple(player(v) for v in values), tuple(staff))


def localizer() -> LocalizationService:
    return LocalizationService.from_directory(
        directory=Path(__file__).resolve().parents[1] / "aa_resources/locales", default_locale="es-ES",
    )


class VerificationRulesTests(unittest.TestCase):
    def test_id_and_mention_formats(self) -> None:
        for value in (str(PRESENT_ID), f"<@{PRESENT_ID}>", f" <@!{PRESENT_ID}> "):
            self.assertEqual(parse_discord_id(value), PRESENT_ID)
        for value in ("usuario", "123", "1.2345678901234568e17", ""):
            self.assertIsNone(parse_discord_id(value))

    def test_identity_merge_and_unfilled_staff_slots(self) -> None:
        p = profile(str(PRESENT_ID), staff=(
            TeamProfileStaffMember("Coach", "Jugador", f"<@{PRESENT_ID}>", ""),
            TeamProfileStaffMember("Manager", "-", "-", "-"),
            TeamProfileStaffMember("CEO", "Sin ID", "", ""),
        ))
        identities = collect_roster_identities(p)
        self.assertEqual(len(identities), 2)
        self.assertTrue(identities[0].is_player)
        self.assertEqual(identities[0].staff_role_names, ("Coach",))
        self.assertEqual(identities[1].sheet_value, "")

    def test_classification_role_errors_and_alias_deduplication(self) -> None:
        p = profile(str(PRESENT_ID), str(MISSING_ID), "duplicado", "", "alias")
        identities = collect_roster_identities(p)
        team_role = ExpectedRole("Equipo", 1)
        unavailable = ExpectedRole("Coach", None)
        present = MemberSnapshot(PRESENT_ID, frozenset({1}))
        matches = [(present,), (), (present, MemberSnapshot(MISSING_ID, frozenset())), (), (present,)]
        report = verify_team(p, (
            IdentityResolution(i, m, (team_role, ExpectedRole("Jugador", 2), unavailable))
            for i, m in zip(identities, matches)
        ), team_role=team_role)
        self.assertEqual([m.status for m in report.members], [
            VerificationStatus.PRESENT, VerificationStatus.MISSING,
            VerificationStatus.AMBIGUOUS, VerificationStatus.INVALID,
        ])
        self.assertEqual(report.members[0].sheet_values, (str(PRESENT_ID), "alias"))
        self.assertEqual(report.members[0].missing_roles, (ExpectedRole("Jugador", 2),))
        self.assertEqual(report.members[1].member_id, MISSING_ID)
        self.assertEqual(report.unavailable_roles, ("Coach",))


class VerificationAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.roles = {i: SimpleNamespace(id=i, name=name) for i, name in enumerate(
            ("", "Equipo", "Participante", "Jugador", "Coach", "Capitán"),
        ) if i}
        self.settings = SimpleNamespace(
            participant_role_id=2, player_role_id=3, staff_ceo_role_id=10,
            staff_analyst_role_id=11, staff_coach_role_id=4,
            staff_manager_role_id=12, staff_second_manager_role_id=13, staff_captain_role_id=5,
        )
        self.member = SimpleNamespace(
            id=PRESENT_ID, name="usuario", display_name="alias", global_name="Global",
            roles=[self.roles[i] for i in (1, 2, 3)], bot=False,
        )
        self.guild = SimpleNamespace(
            fetch_members=self.fetch_members, get_role=self.roles.get,
            get_member=Mock(return_value=None), members=[],
            fetch_member=AsyncMock(
                side_effect=discord.NotFound(SimpleNamespace(status=404, reason="missing"), "missing")),
        )
        self.catalog = SimpleNamespace(roles=(self.roles[1],))

    async def fetch_members(self, *, limit):
        yield self.member

    async def audit(self, p, catalog=None):
        return (await verify_discord_rosters(
            self.guild, (p,), settings=self.settings, role_catalog=catalog or self.catalog,
        ))[0]

    async def test_rest_snapshot_identifies_members_even_when_cache_is_empty(self) -> None:
        report = await self.audit(profile(str(PRESENT_ID), str(MISSING_ID)))
        self.assertEqual(report.members[0].status, VerificationStatus.PRESENT)
        self.assertEqual(report.members[0].missing_roles, ())
        self.assertEqual(report.members[1].status, VerificationStatus.MISSING)
        self.guild.get_member.assert_not_called()
        self.guild.fetch_member.assert_awaited_once_with(MISSING_ID)

    async def test_numeric_absence_is_confirmed_using_fetch_member(self) -> None:
        self.guild.fetch_member = AsyncMock(return_value=replace_namespace(self.member, id=MISSING_ID))
        report = await self.audit(profile(str(MISSING_ID)))
        self.assertEqual(report.members[0].status, VerificationStatus.PRESENT)

    async def test_fetch_failure_never_falls_back_to_cache(self) -> None:
        async def failing(**kwargs):
            raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Forbidden")
            yield

        self.guild.fetch_members = failing
        with self.assertRaises(CommandUserError) as caught:
            await self.audit(profile(str(MISSING_ID)))
        self.assertEqual(caught.exception.message.key, "errors.discord_verification.members_unavailable")

    async def test_fetch_member_permission_error_is_not_an_absence(self) -> None:
        self.guild.fetch_member.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"),
                                                                "Forbidden")
        with self.assertRaises(CommandUserError):
            await self.audit(profile(str(MISSING_ID)))

    async def test_staff_roles_and_captain_follow_player_affiliation_even_with_aliases(self) -> None:
        report = await self.audit(profile(str(PRESENT_ID), staff=(
            TeamProfileStaffMember("Capitán", "Jugador", "alias", ""),
            TeamProfileStaffMember("Coach", "Jugador", "Global", ""),
        )))
        self.assertEqual(len(report.members), 1)
        self.assertEqual({r.role_id for r in report.members[0].missing_roles}, {4, 5})
        staff_only = await self.audit(profile(staff=(TeamProfileStaffMember("Capitán", "Jugador", "alias", ""),)))
        self.assertEqual(staff_only.members[0].missing_roles, ())

    async def test_team_without_role_is_still_audited(self) -> None:
        report = await self.audit(profile(str(PRESENT_ID)), SimpleNamespace(roles=()))
        self.assertEqual(report.members[0].status, VerificationStatus.PRESENT)
        self.assertEqual(report.unavailable_roles, ("Equipo",))

    async def test_missing_global_roles_are_reported_by_configured_id(self) -> None:
        self.roles.pop(2)
        report = await self.audit(profile(str(PRESENT_ID)))
        self.assertEqual(report.unavailable_roles, ("2",))

    async def test_duplicate_names_are_reported_as_ambiguous(self) -> None:
        async def duplicates(**kwargs):
            yield self.member
            yield replace_namespace(self.member, id=MISSING_ID)

        self.guild.fetch_members = duplicates
        report = await self.audit(profile("usuario"))
        self.assertEqual(report.members[0].status, VerificationStatus.AMBIGUOUS)


def replace_namespace(value, **changes):
    return SimpleNamespace(**(vars(value) | changes))


class SheetRosterQueryTests(unittest.TestCase):
    def grid(self, title, value):
        rows = {
            0: [title],
            1: ["Jugador", "Discord ID", "Platform", "Platform ID", "Epic Name", "MMR"],
            2: ["Jugador", value, "epic", "id", "epic", "1500"],
            9: ["STAFF TÉCNICO"], 10: ["Rol", "Jugador", "Discord ID", "Epic Name"],
            11: ["Coach", "Staff", "staff-name", "Epic"],
        }
        return {row: {col: SheetCell(value=v) for col, v in enumerate(values)} for row, values in rows.items()}

    def test_all_divisions_free_blocks_and_staff_without_summary_dependency(self) -> None:
        client = Mock()
        client.fetch_sheet_grids.return_value = ("scope", (
            ("Gold Division S4", self.grid("Equipo", str(PRESENT_ID))),
            ("Silver Division S4", self.grid("Otro", str(MISSING_ID))),
            ("Libre", self.grid("-", "-")),
        ))
        profiles = TeamSheetQueryService(client).list_team_profiles_sync()
        self.assertEqual([p.team_name for p in profiles], ["Equipo", "Otro"])
        self.assertEqual(profiles[1].division_name, "Silver Division S4")
        self.assertEqual(profiles[0].players[0].discord_id, str(PRESENT_ID))
        self.assertEqual(profiles[0].technical_staff[0].discord_id, "staff-name")
        client.build_service.assert_called_once_with(read_only=True)
        client.fetch_sheet_grids.assert_called_once()


class VerificationMessagesTests(unittest.TestCase):
    def report(self):
        p = profile(str(PRESENT_ID), str(MISSING_ID))
        identities = collect_roster_identities(p)
        return verify_team(p, (
            IdentityResolution(identities[0], (MemberSnapshot(PRESENT_ID, frozenset()),), (ExpectedRole("Equipo", 1),)),
            IdentityResolution(identities[1], (), (ExpectedRole("Equipo", 1),)),
        ), team_role=ExpectedRole("Equipo", 1))

    def test_mentions_ids_roles_and_grouping_in_both_locales(self) -> None:
        for locale in ("es-ES", "en-US"):
            pages = build_verification_pages((self.report(),), localizer=localizer(), locale=locale)
            text = "\n".join(pages)
            self.assertIn(f"<@{MISSING_ID}>", text)
            self.assertIn(f"`{MISSING_ID}`", text)
            self.assertIn("<@&1>", text)
            self.assertIn("## Gold Division S4 · Equipo", text)

    def test_filtered_detail_contains_only_missing_members(self) -> None:
        text = "\n".join(build_verification_pages(
            (self.report(),), localizer=localizer(), locale="es-ES", missing_only=True,
        ))
        self.assertIn(str(MISSING_ID), text)
        self.assertNotIn(str(PRESENT_ID), text)
        self.assertNotIn("<@&1>", text)

    def test_missing_members_appear_before_present_members(self) -> None:
        text = "\n".join(build_verification_pages((self.report(),), localizer=localizer(), locale="es-ES"))
        self.assertLess(text.index(str(MISSING_ID)), text.index(str(PRESENT_ID)))

    def test_large_reports_paginate_without_losing_members(self) -> None:
        reports = [replace(self.report(), team_name=f"Equipo {n}") for n in range(50)]
        pages = build_verification_pages(reports, localizer=localizer(), locale="es-ES")
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(p) <= 1900 for p in pages))
        text = "\n".join(pages)
        self.assertEqual(text.count(f"<@{MISSING_ID}>"), 50)

    def test_extreme_labels_remain_within_message_limit(self) -> None:
        report = self.report()
        member = replace(report.members[0], player_name="*" * 200, sheet_values=("*" * 200,) * 12)
        report = replace(report, team_name="*" * 200, division_name="*" * 200, members=(member,))
        pages = build_verification_pages((report,), localizer=localizer(), locale="es-ES")
        self.assertTrue(all(len(p) <= 1900 for p in pages))

    def test_single_message_uses_full_limit_and_paginates_only_when_exceeded(self) -> None:
        report = self.report()
        members = tuple(replace(report.members[1], player_name=f"Jugador {i}", member_id=MISSING_ID + i)
                        for i in range(14))
        report = replace(report, members=members)
        local = localizer()

        def render(value):
            return build_verification_pages((value,), localizer=local, locale="es-ES", missing_only=True)

        pages = render(report)
        self.assertEqual(len(pages), 1)
        padding = 2000 - len(pages[0])
        self.assertTrue(0 <= padding <= 150)
        last = replace(members[-1], player_name=members[-1].player_name + "x" * padding)
        exact_limit = replace(report, members=members[:-1] + (last,))
        self.assertEqual([len(page) for page in render(exact_limit)], [2000])

        overflow = replace(exact_limit, members=members[:-1] + (replace(last, player_name=last.player_name + "x"),))
        pages = render(overflow)
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page) <= 1900 for page in pages))


class VerificationCommandTests(unittest.IsolatedAsyncioTestCase):
    async def send_using_discord_library(self, profiles, equipo=None):
        # Exercise discord.py's real validation and serialization. Only its HTTP
        # transport and response construction are replaced; no messages are sent.
        from discord.webhook.async_ import async_context

        adapter = SimpleNamespace(execute_webhook=AsyncMock(return_value={}))
        state = SimpleNamespace(allowed_mentions=None, store_view=Mock())
        webhook = discord.Webhook(
            {"id": "123", "type": 3, "token": "test-token"}, session=Mock(), state=state,
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=42, roles=[SimpleNamespace(name="Staff")]),
            guild=SimpleNamespace(), locale=discord.Locale.spain_spanish,
            response=SimpleNamespace(defer=AsyncMock()), followup=webhook,
            client=SimpleNamespace(settings=SimpleNamespace(channel_access_range_start_role_id=1,
                                                            channel_access_range_end_role_id=2), localizer=localizer()),
        )
        repository = SimpleNamespace(list_team_profiles=AsyncMock(return_value=tuple(profiles)))

        async def reports_for_profiles(guild, selected, **kwargs):
            return tuple(verify_team(p, (
                IdentityResolution(i, (), ()) for i in collect_roster_identities(p)
            ), team_role=ExpectedRole(p.team_name, 1)) for p in selected)

        module = "bigness_league_bot.presentation.discord.cogs.discord_verification"
        token = async_context.set(adapter)
        try:
            with patch(module + ".GoogleSheetsTeamRepository", return_value=repository), \
                    patch(module + ".get_channel_access_role_catalog"), \
                    patch(module + ".verify_discord_rosters", side_effect=reports_for_profiles), \
                    patch.object(discord.Webhook, "_create_message", return_value=SimpleNamespace(id=123)):
                await DiscordVerificationCog.verification.callback(DiscordVerificationCog(), interaction, equipo)
        finally:
            async_context.reset(token)
        return adapter, state

    async def test_filtered_single_page_passes_real_webhook_validation(self) -> None:
        adapter, state = await self.send_using_discord_library((
            profile(str(MISSING_ID), team="Equipo"), profile(str(PRESENT_ID), team="Otro"),
        ), equipo="Equipo")
        adapter.execute_webhook.assert_awaited_once()
        self.assertFalse(adapter.execute_webhook.call_args.kwargs["with_components"])
        payload = adapter.execute_webhook.call_args.kwargs["payload"]
        self.assertNotIn("attachments", payload)
        self.assertNotIn("Página", payload["content"])
        self.assertNotIn("archivo adjunto", payload["content"])
        state.store_view.assert_not_called()

    async def test_unfiltered_single_page_passes_real_webhook_validation(self) -> None:
        adapter, state = await self.send_using_discord_library((profile(str(MISSING_ID)),))
        self.assertFalse(adapter.execute_webhook.call_args.kwargs["with_components"])
        payload = adapter.execute_webhook.call_args.kwargs["payload"]
        self.assertNotIn("attachments", payload)
        self.assertNotIn("Página", payload["content"])
        state.store_view.assert_not_called()

    async def test_multiple_pages_keep_interactive_view(self) -> None:
        adapter, state = await self.send_using_discord_library(tuple(
            profile(str(MISSING_ID), team=f"Equipo {index}") for index in range(30)
        ))
        self.assertTrue(adapter.execute_webhook.call_args.kwargs["with_components"])
        sent_files = adapter.execute_webhook.call_args.kwargs["files"]
        self.assertEqual([file.filename for file in sent_files], ["verificacion_discord.md"])
        view = state.store_view.call_args.args[0]
        self.assertGreater(len(view.pages), 1)
        self.assertIn("Página 1/", view.content())
        view.stop()

    async def test_optional_team_parameter_registration(self) -> None:
        command = DiscordVerificationCog.verification
        self.assertEqual(command.name, "verificacion_discord")
        self.assertFalse(command.parameters[0].required)
        self.assertTrue(command.parameters[0].autocomplete)

    async def test_filter_uses_sheet_names_and_never_includes_other_teams(self) -> None:
        local = localizer()
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=42, roles=[SimpleNamespace(name="Staff")]),
            guild=SimpleNamespace(), locale=discord.Locale.spain_spanish,
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()),
            client=SimpleNamespace(settings=SimpleNamespace(channel_access_range_start_role_id=1,
                                                            channel_access_range_end_role_id=2), localizer=local),
        )
        repository = SimpleNamespace(list_team_profiles=AsyncMock(return_value=(
            profile(str(MISSING_ID), team="Equipo"), profile(str(PRESENT_ID), team="Otro"),
        )))
        module = "bigness_league_bot.presentation.discord.cogs.discord_verification"
        with patch(module + ".GoogleSheetsTeamRepository", return_value=repository), \
                patch(module + ".get_channel_access_role_catalog"), \
                patch(module + ".verify_discord_rosters", new=AsyncMock(return_value=())) as audit:
            await DiscordVerificationCog.verification.callback(DiscordVerificationCog(), interaction, " EQUIPO ")
        self.assertEqual([p.team_name for p in audit.call_args.args[1]], ["Equipo"])
        sent = interaction.followup.send.call_args.kwargs
        self.assertEqual(sent["allowed_mentions"].to_dict(), {"parse": []})
        self.assertNotIn("file", sent)
        self.assertNotIn("view", sent)
        self.assertNotIn("Página", sent["content"])

    async def test_unauthorized_user_cannot_read_sheets(self) -> None:
        interaction = SimpleNamespace(user=SimpleNamespace(roles=[]))
        with self.assertRaises(CommandUserError):
            await DiscordVerificationCog.verification.callback(DiscordVerificationCog(), interaction)

    async def test_view_navigation_disables_mentions_and_restricts_actor(self) -> None:
        view = DiscordVerificationView(pages=("First", "Second"), actor_id=42,
                                       localizer=localizer(), locale="es-ES")
        interaction = SimpleNamespace(user=SimpleNamespace(id=99), locale="es-ES",
                                      response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()))
        self.assertFalse(await view.interaction_check(interaction))
        interaction.user.id = 42
        self.assertTrue(await view.interaction_check(interaction))
        await view._show(interaction, 1)
        self.assertTrue(view.next_page.disabled)
        self.assertFalse(view.previous.disabled)
        kwargs = interaction.response.edit_message.call_args.kwargs
        self.assertEqual(kwargs["allowed_mentions"].to_dict(), {"parse": []})
        self.assertIn("Second", kwargs["content"])
        self.assertLessEqual(len(kwargs["content"]), 2000)
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        self.assertTrue(view.previous.disabled)
        self.assertTrue(view.next_page.disabled)
        self.assertEqual(view.message.edit.call_args.kwargs["allowed_mentions"].to_dict(), {"parse": []})
