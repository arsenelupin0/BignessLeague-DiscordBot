from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from bigness_league_bot.application.services.team_divisions import division_names_match
from bigness_league_bot.application.services.team_signing import (
    TeamSigningBatch, TeamSigningPlayer, TeamTechnicalStaffBatch, TeamTechnicalStaffMember,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.discord import pending_team_signing_resolver as pending
from bigness_league_bot.infrastructure.discord import team_signing_visibility as visibility
from bigness_league_bot.infrastructure.discord.team_change_announcements import TEAM_ROLE_SIGNING_SPEC
from bigness_league_bot.infrastructure.discord.team_signing_imports import resolve_team_signing_import_target
from bigness_league_bot.infrastructure.discord.team_signing_messages import (
    TeamSigningTeamAnnouncementLink, build_team_signing_visibility_message,
)
from bigness_league_bot.infrastructure.discord.ticket_relay_messages import (
    build_ticket_command_relay_message, clone_message_embeds,
)
from bigness_league_bot.infrastructure.google.team_sheets.blocks import _find_division_sheet
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.errors import (
    TeamSheetDivisionAmbiguousError, TeamSheetDivisionNotFoundError,
    TeamSheetNoFreeBlockError, TeamSheetTeamAlreadyRegisteredError,
    TeamSheetTechnicalStaffPlayerNotFoundError, TeamSheetTechnicalStaffRoleNotFoundError,
    TeamSheetRemainingSigningsExceededError,
)
from bigness_league_bot.infrastructure.google.team_sheets.models import SheetCell
from bigness_league_bot.infrastructure.google.team_sheets.player_signing_mutations import register_team_signings_sync
from bigness_league_bot.infrastructure.google.team_sheets.staff_signing_mutations import \
    register_team_technical_staff_sync
from bigness_league_bot.infrastructure.google.team_sheets.team_registration import register_team_sync
from bigness_league_bot.infrastructure.i18n.service import LocalizationService


def _batch() -> TeamSigningBatch:
    return TeamSigningBatch('Gold Division', 'Equipo nuevo', 'https://example.com/logo.png', tuple(
        TeamSigningPlayer(f'Jugador {index}', str(1000 + index), 'epic', f'id{index}',
                          f'epic{index}', f'https://example.com/{index}', str(1500 + index))
        for index in range(3)
    ))


def _staff() -> TeamTechnicalStaffBatch:
    return TeamTechnicalStaffBatch('Gold Division S4', 'Equipo nuevo', (
        TeamTechnicalStaffMember('CEO', '', '1000', ''),
    ))


def _grid(title: str = '-') -> dict[int, dict[int, SheetCell]]:
    rows = {
        0: [title],
        1: ['Jugador', 'Discord ID', 'Platform', 'Platform ID', 'Epic Name', 'MMR'],
        8: ['3'], 9: ['STAFF TÉCNICO'],
        10: ['Rol', 'Jugador', 'Discord ID', 'Epic Name'],
    }
    rows.update({row: ['-'] * 6 for row in range(2, 8)})
    rows.update({11 + index: [role, 'Anterior', '9999', 'Anterior'] for index, role in enumerate(
        ('CEO', 'Manager', 'Segundo Manager', 'Coach', 'Analista', 'Capitán'),
    )})
    return {row: {column: SheetCell(value=value) for column, value in enumerate(values)}
            for row, values in rows.items()}


def _localizer() -> LocalizationService:
    return LocalizationService.from_directory(directory=Path('aa_resources/locales'), default_locale='es-ES')


class DivisionLookupTests(unittest.TestCase):
    def test_season_is_optional_for_both_divisions_and_environment_suffixes(self) -> None:
        for title in ('Gold Division S4', 'Silver Division S4', 'GOLD DIVISIÓN S4 TEST',
                      'Gold Division S4 DEV', 'Gold Division S4 DEVELOPMENT'):
            base = 'Silver Division' if title.startswith('Silver') else 'Gold Division'
            for division in (base, base + ' S4'):
                with self.subTest(title=title, division=division):
                    self.assertEqual(_find_division_sheet(division, ((title, {}),))[0], title)

    def test_explicit_season_never_matches_a_different_season(self) -> None:
        with self.assertRaises(TeamSheetDivisionNotFoundError):
            _find_division_sheet('Gold Division S3', (('Gold Division S4', {}),))

    def test_ambiguous_seasonless_division_is_rejected(self) -> None:
        sheets = (('Gold Division S3', {}), ('Gold Division S4', {}))
        with self.assertRaises(TeamSheetDivisionAmbiguousError):
            _find_division_sheet('Gold Division', sheets)
        self.assertEqual(_find_division_sheet('Gold Division S4', sheets)[0], 'Gold Division S4')

    def test_player_and_staff_templates_can_differ_only_in_optional_season(self) -> None:
        self.assertEqual(resolve_team_signing_import_target(signing_batch=_batch(), technical_staff_batch=_staff()),
                         ('Gold Division', 'Equipo nuevo'))
        self.assertFalse(division_names_match('Gold Division S3', 'Gold Division S4'))
        with self.assertRaises(CommandUserError):
            resolve_team_signing_import_target(signing_batch=replace(_batch(), division_name='Gold Division S3'),
                                               technical_staff_batch=_staff())


class RegistrationSheetWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = Mock()
        self.grid = _grid()
        self.client = Mock()
        self.client.build_service.return_value = self.service
        self.client.fetch_sheet_grids.return_value = ('S4', (('Gold Division S4', self.grid),))
        self.config = TeamSheetLookupConfig('document', ('Gold Division S4',), Path('unused.json'))
        self.writer = self.service.spreadsheets.return_value.values.return_value.batchUpdate

    def test_players_and_staff_are_validated_and_written_together_with_logo(self) -> None:
        player_result, staff_result = register_team_sync(self.client, self.config, _batch(), _staff())
        self.assertTrue(player_result.created_team_block)
        self.assertEqual(staff_result.updated_count, 1)
        self.writer.assert_called_once()
        updates = {item['range']: item['values'] for item in self.writer.call_args.kwargs['body']['data']}
        self.assertIn('HYPERLINK', updates["'Gold Division S4'!A1:A1"][0][0])
        self.assertEqual(updates["'Gold Division S4'!B12:B12"], [['Jugador 0']])
        self.assertEqual(updates["'Gold Division S4'!C12:C12"], [['1000']])
        self.assertEqual(updates["'Gold Division S4'!D12:D12"], [['epic0']])
        self.assertEqual(updates["'Gold Division S4'!C13:C13"], [['-']])
        self.assertEqual(updates["'Gold Division S4'!A3:F8"][-1], ['-'] * 6)
        self.assertEqual(self.grid[0][0].value, '-')

    def test_full_division_does_not_write_anything(self) -> None:
        self.client.fetch_sheet_grids.return_value = ('S4', (('Gold Division S4', _grid('Otro equipo')),))
        with self.assertRaises(TeamSheetNoFreeBlockError):
            register_team_sync(self.client, self.config, _batch(), _staff())
        self.writer.assert_not_called()

    def test_registered_team_does_not_overwrite_an_existing_block(self) -> None:
        grid = _grid('Equipo nuevo')
        # Keep a separate free block so duplicate-team validation is exercised.
        for row, cells in _grid().items():
            grid[row].update({column + 8: cell for column, cell in cells.items()})
        self.client.fetch_sheet_grids.return_value = ('S4', (('Gold Division S4', grid),))
        with self.assertRaises(TeamSheetTeamAlreadyRegisteredError):
            register_team_sync(self.client, self.config, _batch(), _staff())
        self.writer.assert_not_called()

    def test_invalid_staff_does_not_partially_register_players(self) -> None:
        for member, error in (
                (TeamTechnicalStaffMember('CEO', '', 'missing', ''), TeamSheetTechnicalStaffPlayerNotFoundError),
                (TeamTechnicalStaffMember('Unknown', '', '1000', ''), TeamSheetTechnicalStaffRoleNotFoundError),
        ):
            with self.subTest(member=member):
                with self.assertRaises(error):
                    register_team_sync(self.client, self.config, _batch(), replace(_staff(), members=(member,)))
                self.writer.assert_not_called()

    def test_signing_an_existing_team_keeps_its_title_and_decrements_remaining_signings(self) -> None:
        grid = _grid('Equipo nuevo')
        self.client.fetch_sheet_grids.return_value = ('S4', (('Gold Division S4', grid),))
        result = register_team_signings_sync(self.client, self.config, replace(_batch(), team_logo_url=None))
        self.assertFalse(result.created_team_block)
        updates = {item['range']: item['values'] for item in self.writer.call_args.kwargs['body']['data']}
        self.assertNotIn("'Gold Division S4'!A1:A1", updates)
        self.assertEqual(updates["'Gold Division S4'!A9:A9"], [['0']])

    def test_signing_limit_is_still_checked_before_writing(self) -> None:
        grid = _grid('Equipo nuevo')
        grid[8][0] = SheetCell(value='2')
        self.client.fetch_sheet_grids.return_value = ('S4', (('Gold Division S4', grid),))
        with self.assertRaises(TeamSheetRemainingSigningsExceededError):
            register_team_signings_sync(self.client, self.config, replace(_batch(), team_logo_url=None))
        self.writer.assert_not_called()

    def test_staff_signing_does_not_reset_other_staff_roles(self) -> None:
        staff = replace(_staff(), members=(TeamTechnicalStaffMember('CEO', 'Jugador', '1000', 'epic'),))
        register_team_technical_staff_sync(self.client, self.config, staff)
        updates = {item['range']: item['values'] for item in self.writer.call_args.kwargs['body']['data']}
        self.assertEqual(updates["'Gold Division S4'!C12:C12"], [['1000']])
        self.assertNotIn("'Gold Division S4'!C13:C13", updates)


class RegistrationAnnouncementTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_sends_only_one_team_announcement_per_member(self) -> None:
        player, staff_only = SimpleNamespace(id=10), SimpleNamespace(id=20)
        players = SimpleNamespace(assigned_members=(player,), already_configured_members=())
        staff = SimpleNamespace(team_role_assigned_members=(staff_only,), assigned_members=(player, staff_only),
                                already_configured_members=())
        with patch.object(visibility, 'send_missing_team_change_announcements', new_callable=AsyncMock) as send, \
                patch.object(visibility, '_collect_staff_announcement_links', new_callable=AsyncMock) as staff_send:
            send.return_value = ()
            links = await visibility.collect_team_signing_visibility_links(
                settings=SimpleNamespace(team_role_removal_announcement_channel_id=1555268803984883713),
                guild=SimpleNamespace(id=1), bot=Mock(), team_role=SimpleNamespace(id=30),
                assignment_summary=players, technical_staff_batch=_staff(), staff_sync_summary=staff,
                since=0, registration=True,
            )
        self.assertEqual(send.await_args.kwargs['members'], (player, staff_only))
        self.assertIs(send.await_args.kwargs['spec'], TEAM_ROLE_SIGNING_SPEC)
        self.assertEqual(links.staff_links, ())
        staff_send.assert_not_awaited()

    async def test_pending_registration_staff_does_not_publish_a_new_cargo(self) -> None:
        sender = SimpleNamespace(send_team_role_change_announcement=AsyncMock(return_value=SimpleNamespace(id=40)),
                                 send_staff_role_change_announcement=AsyncMock(return_value=SimpleNamespace(id=41)))
        resolver = pending.PendingTeamSigningAssignmentResolver.__new__(pending.PendingTeamSigningAssignmentResolver)
        resolver.bot = SimpleNamespace(
            settings=SimpleNamespace(team_role_removal_announcement_channel_id=1555268803984883713))
        resolver.announcement_sender = sender
        assignment = SimpleNamespace(division_name='Gold Division S4', team_role_name='Equipo nuevo',
                                     team_image_url=None, source='hacer_inscripcion')
        with patch.object(pending, 'resolve_team_change_bulletin_channel', new_callable=AsyncMock):
            result = await resolver._send_announcements(
                member=SimpleNamespace(guild=SimpleNamespace(id=1)), assignment=assignment,
                team_role=SimpleNamespace(id=30), staff_roles=(SimpleNamespace(id=31),), added_role_ids={30, 31},
            )
        self.assertEqual(result, (40,))
        sender.send_staff_role_change_announcement.assert_not_awaited()
        assignment.source = 'hacer_fichaje'
        with patch.object(pending, 'resolve_team_change_bulletin_channel', new_callable=AsyncMock):
            result = await resolver._send_announcements(
                member=SimpleNamespace(guild=SimpleNamespace(id=1)), assignment=assignment,
                team_role=SimpleNamespace(id=30), staff_roles=(SimpleNamespace(id=31),), added_role_ids={30, 31},
            )
        self.assertEqual(result, (40, 41))
        sender.send_staff_role_change_announcement.assert_awaited_once()

    async def test_staff_signing_keeps_its_staff_announcements(self) -> None:
        with patch.object(visibility, '_collect_team_signing_team_links', new_callable=AsyncMock) as team, \
                patch.object(visibility, '_collect_staff_announcement_links', new_callable=AsyncMock) as staff, \
                patch.object(visibility, '_collect_staff_sync_removal_announcement_links',
                             new_callable=AsyncMock) as removals:
            team.return_value = removals.return_value = ()
            staff.return_value = ('staff-link',)
            links = await visibility.collect_team_signing_visibility_links(
                settings=Mock(), guild=Mock(), bot=Mock(), team_role=Mock(),
                assignment_summary=None, technical_staff_batch=_staff(),
                staff_sync_summary=SimpleNamespace(team_role_assigned_members=()), since=0,
            )
        self.assertEqual(links.staff_links, ('staff-link',))
        staff.assert_awaited_once()


class RegistrationMessageTests(unittest.TestCase):
    def test_registration_heading_and_dm_role_names_preserve_links(self) -> None:
        localizer = _localizer()
        content = build_team_signing_visibility_message(
            localizer=localizer, locale='es-ES', team_role_mention='<@&30>',
            team_links=(TeamSigningTeamAnnouncementLink('https://discord.com/channels/1/2/3'),),
            registration=True,
        )
        self.assertIn('¿Dónde ver mi inscripción?', content)
        message = SimpleNamespace(content=content, guild=SimpleNamespace(
            get_role=lambda role_id: SimpleNamespace(name='Equipo nuevo') if role_id == 30 else None,
        ), embeds=[], attachments=[], stickers=[], message_snapshots=[])
        dm = build_ticket_command_relay_message(localizer=localizer, message=message, command_name='hacer_inscripción')
        self.assertIn('@Equipo nuevo', dm)
        self.assertNotIn('<@&', dm)
        self.assertIn('https://discord.com/channels/1/2/3', dm)
        self.assertIn('<@&30>', content)

    def test_signing_keeps_its_original_heading(self) -> None:
        content = build_team_signing_visibility_message(
            localizer=_localizer(), locale='es-ES', team_role_mention='<@&30>',
            team_links=(TeamSigningTeamAnnouncementLink('https://example.com'),),
        )
        self.assertIn('¿Dónde ver mi fichaje?', content)

    def test_dm_embeds_render_role_names_without_changing_the_source_embed(self) -> None:
        source = discord.Embed(title='<@&30>', description='Equipo <@&30>')
        source.add_field(name='Rol', value='<@&30>')
        message = SimpleNamespace(embeds=[source], guild=SimpleNamespace(
            get_role=lambda _: SimpleNamespace(name='Equipo nuevo'),
        ))
        cloned = clone_message_embeds(message)[0]
        self.assertEqual(cloned.title, '@Equipo nuevo')
        self.assertEqual(cloned.fields[0].value, '@Equipo nuevo')
        self.assertEqual(source.title, '<@&30>')

    def test_registration_command_requires_both_links(self) -> None:
        from bigness_league_bot.presentation.discord.cogs.team_signing import TeamSigningCog
        parameters = {parameter.name: parameter.required for parameter in TeamSigningCog.make_registration.parameters}
        self.assertTrue(parameters['enlace_jugadores'])
        self.assertTrue(parameters['enlace_staff_tecnico'])


if __name__ == '__main__':
    unittest.main()
