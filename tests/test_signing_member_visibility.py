from __future__ import annotations

import unittest
from types import SimpleNamespace

import discord

from bigness_league_bot.infrastructure.discord.team_role_change_delivery import SentTeamChangeAnnouncement
from bigness_league_bot.infrastructure.discord.team_signing_messages import build_team_signing_visibility_message
from bigness_league_bot.infrastructure.discord.team_signing_visibility_links import team_links_from_announcements
from bigness_league_bot.infrastructure.discord.ticket_relay_messages import (
    build_ticket_command_relay_message, clone_message_embeds, dm_mentions_as_text,
)
from test_team_registration_import import _localizer


class SigningMemberVisibilityTests(unittest.TestCase):
    def test_each_announcement_preserves_its_user_and_link_in_forum_and_dm(self) -> None:
        links = team_links_from_announcements(tuple(
            SentTeamChangeAnnouncement(1, member, 30, 'signing', member, 2,
                                       f'https://discord.com/channels/1/2/{member}', 0)
            for member in (10, 11)
        ))
        content = build_team_signing_visibility_message(
            localizer=_localizer(), locale='es-ES', team_role_mention='<@&30>',
            team_links=links, registration=True,
        )
        for member in (10, 11):
            self.assertIn(f'<@{member}>, [es fichado por](https://discord.com/channels/1/2/{member}) <@&30>', content)
        message = SimpleNamespace(
            content=content, embeds=[], attachments=[], stickers=[], message_snapshots=[],
            mentions=[SimpleNamespace(id=10, name='jugador.uno')],
            guild=SimpleNamespace(get_role=lambda _: SimpleNamespace(name='Mi equipo'),
                                  get_member=lambda mid: SimpleNamespace(name='jugador.dos') if mid == 11 else None),
        )
        dm = build_ticket_command_relay_message(localizer=_localizer(), message=message,
                                                command_name='hacer_inscripción')
        self.assertIn('@jugador.uno(10)', dm)
        self.assertIn('@jugador.dos(11)', dm)
        self.assertIn('@Mi equipo', dm)
        self.assertNotIn('<@', dm)
        self.assertIn('https://discord.com/channels/1/2/11', dm)

    def test_dm_legacy_mentions_unknown_users_and_markdown_names(self) -> None:
        message = SimpleNamespace(guild=None, mentions=[SimpleNamespace(id=10, name='player_*')])
        converted = dm_mentions_as_text('<@!10> y <@11> en <@&30>', message=message)
        self.assertEqual(converted, '@player\\_\\*(10) y @11 en @30')

    def test_embed_mentions_are_converted_without_mutating_forum_embed(self) -> None:
        source = discord.Embed(title='<@10>', description='<@!10> fichado por <@&30>')
        source.add_field(name='<@10>', value='<@10>')
        message = SimpleNamespace(embeds=[source], guild=SimpleNamespace(get_role=lambda _: None),
                                  mentions=[SimpleNamespace(id=10, name='jugador')])
        copy = clone_message_embeds(message)[0]
        self.assertEqual(copy.title, '@jugador(10)')
        self.assertEqual(copy.description, '@jugador(10) fichado por @30')
        self.assertEqual(copy.fields[0].value, '@jugador(10)')
        self.assertEqual(source.title, '<@10>')
