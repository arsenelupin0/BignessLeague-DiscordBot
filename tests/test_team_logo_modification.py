from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from bigness_league_bot.application.services.team_logo import normalize_team_logo_url
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.google.team_sheets.config import TeamSheetLookupConfig
from bigness_league_bot.infrastructure.google.team_sheets.errors import (
    TeamSheetDivisionNotFoundError, TeamSheetRowNotFoundError,
)
from bigness_league_bot.infrastructure.google.team_sheets.models import SheetCell, TeamRoleSheetMetadata
from bigness_league_bot.infrastructure.google.team_sheets.team_logo_mutations import update_team_logo_sync
from bigness_league_bot.presentation.discord.cogs import team_roster_modification as cog_module
from bigness_league_bot.presentation.discord.views import team_logo_modification as ui
from test_team_registration_import import _grid, _localizer


class LogoMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Mock()
        self.grid = _grid('Mi "equipo"')
        self.client.fetch_sheet_grids.return_value = ('S4', (('Gold Division S4', self.grid),))
        self.config = TeamSheetLookupConfig('document', ('Gold Division S4',), None)
        self.writer = self.client.build_service.return_value.spreadsheets.return_value.values.return_value.batchUpdate

    def test_updates_only_title_hyperlink_and_preserves_title_and_rest_of_block(self) -> None:
        result = update_team_logo_sync(self.client, self.config, 'Gold Division S4', 'Mi "equipo"',
                                       ' https://example.com/new.png?x=1 ')
        self.assertEqual(result.team_image_url, 'https://example.com/new.png?x=1')
        self.assertEqual(self.writer.call_args.kwargs['body'], {
            'valueInputOption': 'USER_ENTERED',
            'data': [{'range': "'Gold Division S4'!A1:A1", 'values': [[
                '=HYPERLINK("https://example.com/new.png?x=1";"Mi ""equipo""")',
            ]]}],
        })
        self.assertEqual(self.grid[0][0].value, 'Mi "equipo"')
        self.writer.return_value.execute.assert_called_once()

    def test_title_cell_offset_is_respected(self) -> None:
        self.grid[0] = {0: SheetCell(), 2: SheetCell('Mi "equipo"', 'https://example.com/old')}
        update_team_logo_sync(self.client, self.config, 'Gold Division S4', 'Mi "equipo"', 'https://example.com/new')
        self.assertEqual(self.writer.call_args.kwargs['body']['data'][0]['range'], "'Gold Division S4'!C1:C1")

    def test_missing_team_never_uses_a_free_block(self) -> None:
        self.client.fetch_sheet_grids.return_value = ('S4', (('Gold Division S4', _grid()),))
        with self.assertRaises(TeamSheetRowNotFoundError):
            update_team_logo_sync(self.client, self.config, 'Gold Division S4', 'Mi "equipo"',
                                  'https://example.com/new')
        self.writer.assert_not_called()

    def test_different_season_is_not_written(self) -> None:
        with self.assertRaises(TeamSheetDivisionNotFoundError):
            update_team_logo_sync(self.client, self.config, 'Gold Division S3', 'Mi "equipo"',
                                  'https://example.com/new')
        self.writer.assert_not_called()

    def test_invalid_urls_are_rejected_before_sheets_access(self) -> None:
        for url in ('', 'javascript:alert(1)', '=HYPERLINK("x")', 'https://', 'https://host/a b',
                    'https://host/a\nb', 'https://[invalid', 'https://host:bad/logo', 'https://host/' + 'a' * 2000):
            with self.subTest(url=url), self.assertRaises(CommandUserError):
                update_team_logo_sync(self.client, self.config, 'Gold Division S4', 'Mi "equipo"', url)
        self.client.build_service.assert_not_called()

    def test_http_and_cdn_urls_with_query_strings_are_supported(self) -> None:
        for url in ('http://example.com/logo', 'https://cdn.example.com/a?format=png&key=123'):
            self.assertEqual(normalize_team_logo_url(' ' + url + ' '), url)


class LogoModalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.metadata = TeamRoleSheetMetadata('Gold Division S4', 'Mi equipo', 'https://example.com/old.png')
        self.member = Mock(spec=discord.Member)
        self.member.id = 10
        self.member.roles = [SimpleNamespace(name='Staff')]
        self.interaction = SimpleNamespace(
            user=self.member, guild_id=1, locale='es-ES',
            client=SimpleNamespace(settings=Mock(), localizer=_localizer()),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    def modal(self, metadata=None):
        return ui.TeamLogoModificationModal(actor_id=10, guild_id=1, metadata=metadata or self.metadata,
                                            localizer=_localizer(), locale='es-ES')

    async def test_placeholder_is_old_url_and_long_links_fit_discord_limit(self) -> None:
        modal = self.modal()
        self.assertEqual(modal.logo_url.placeholder, self.metadata.team_image_url)
        self.assertTrue(modal.logo_url.required)
        self.assertEqual(
            len(self.modal(replace(self.metadata, team_image_url='https://host/' + 'x' * 150)).logo_url.placeholder),
            100)

    async def test_submission_updates_selected_team_and_confirms_success(self) -> None:
        modal = self.modal()
        modal.logo_url._value = 'https://example.com/new.png'
        repository = SimpleNamespace(
            update_team_logo=AsyncMock(return_value=replace(self.metadata, team_image_url=modal.logo_url.value)))
        with patch.object(ui, 'GoogleSheetsTeamRepository', return_value=repository):
            await modal.on_submit(self.interaction)
        repository.update_team_logo.assert_awaited_once_with('Gold Division S4', 'Mi equipo',
                                                             'https://example.com/new.png')
        self.assertIn('Se ha actualizado el logo', self.interaction.followup.send.call_args.args[0])

    async def test_other_user_or_lost_permission_cannot_submit(self) -> None:
        for user_id, roles in ((11, ['Staff']), (10, ['Jugador'])):
            self.member.id = user_id
            self.member.roles = [SimpleNamespace(name=name) for name in roles]
            with patch.object(ui, 'GoogleSheetsTeamRepository') as repository:
                await self.modal().on_submit(self.interaction)
            repository.assert_not_called()
        self.interaction.response.defer.assert_not_awaited()

    async def test_sheet_failure_is_reported_without_success_message(self) -> None:
        from bigness_league_bot.core.localization import localize
        from bigness_league_bot.infrastructure.i18n.keys import I18N
        repository = SimpleNamespace(update_team_logo=AsyncMock(side_effect=CommandUserError(
            localize(I18N.errors.team_signing.invalid_logo_url),
        )))
        with patch.object(ui, 'GoogleSheetsTeamRepository', return_value=repository):
            await self.modal().on_submit(self.interaction)
        self.assertIn('La URL del logo', self.interaction.followup.send.call_args.args[0])

    async def test_command_exposes_required_team_with_autocomplete(self) -> None:
        from bigness_league_bot.presentation.discord.cogs.team_roster_modification import TeamRosterModificationCog
        command = TeamRosterModificationCog.modify_logo
        self.assertEqual(str(command.name), 'modificar_logo')
        self.assertEqual(
            [(parameter.name, parameter.required, parameter.autocomplete) for parameter in command.parameters],
            [('equipo', True, True)])

    async def test_command_reads_logo_then_button_opens_modal_without_writing(self) -> None:
        self.interaction.guild = SimpleNamespace(id=1)
        self.interaction.response.send_modal = AsyncMock()
        role = SimpleNamespace(id=30, name='Mi equipo')
        metadata = replace(self.metadata, team_image_url='https://example.com/' + 'x' * 1900)
        repository = SimpleNamespace(find_team_sheet_metadata_for_role=AsyncMock(return_value=metadata),
                                     update_team_logo=AsyncMock())
        cog = cog_module.TeamRosterModificationCog(Mock())
        with patch.object(cog_module, 'GoogleSheetsTeamRepository', return_value=repository), \
                patch.object(cog_module, 'resolve_selected_team_role', return_value=role):
            await cog.modify_logo.callback(cog, self.interaction, '30')
        repository.find_team_sheet_metadata_for_role.assert_awaited_once_with(role)
        kwargs = self.interaction.followup.send.call_args.kwargs
        self.assertIn(metadata.team_image_url, kwargs['embed'].description)
        self.assertTrue(kwargs['ephemeral'])
        view = kwargs['view']
        self.assertTrue(await view.interaction_check(self.interaction))
        await view.children[0].callback(self.interaction)
        modal = self.interaction.response.send_modal.call_args.args[0]
        self.assertEqual(modal.metadata.team_name, 'Mi equipo')
        self.assertEqual(modal.logo_url.placeholder, metadata.team_image_url[:100])
        repository.update_team_logo.assert_not_awaited()

    async def test_command_rejects_unauthorized_member_before_reading_sheets(self) -> None:
        from bigness_league_bot.infrastructure.discord.channel_access_management import ChannelManagementError
        self.interaction.guild = SimpleNamespace(id=1)
        self.member.roles = []
        cog = cog_module.TeamRosterModificationCog(Mock())
        with patch.object(cog_module, 'GoogleSheetsTeamRepository') as repository:
            with self.assertRaises(ChannelManagementError):
                await cog.modify_logo.callback(cog, self.interaction, '30')
        repository.assert_not_called()
        self.interaction.response.defer.assert_not_awaited()
