from __future__ import annotations

import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from bigness_league_bot.infrastructure.discord import team_change_logo as logos
from bigness_league_bot.infrastructure.discord import team_role_change_delivery as delivery
from bigness_league_bot.infrastructure.discord.team_change_announcements import TEAM_ROLE_SIGNING_SPEC
from bigness_league_bot.infrastructure.google.team_sheets.models import TeamRoleSheetMetadata
from bigness_league_bot.infrastructure.images.team_logos import TeamLogoLoadError


class TeamChangeLogoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.embed = discord.Embed()
        self.embed.set_thumbnail(url="https://example.com/league.png")
        self.metadata = TeamRoleSheetMetadata("SILVER DIVISION S4", "Profit", "https://example.com/Profit.png")
        self.team_key = "1:30"

    async def test_valid_logo_becomes_an_attachment_thumbnail(self) -> None:
        with patch.object(logos, "load_team_logo_png", return_value=b"validated png") as loader:
            file = await logos.attach_team_change_logo(embed=self.embed, metadata=self.metadata, team_key=self.team_key)
        self.addCleanup(file.close)
        loader.assert_called_once_with(self.metadata.team_image_url, team_key=self.team_key)
        self.assertEqual(self.embed.thumbnail.url, "attachment://team-logo.png")
        self.assertEqual(file.fp.read(), b"validated png")

    async def test_download_failure_preserves_default_and_reports_reason(self) -> None:
        with patch.object(logos, "load_team_logo_png", side_effect=TeamLogoLoadError("http_403")), \
                self.assertLogs("bigness_league_bot.activity", level="WARNING") as logs:
            file = await logos.attach_team_change_logo(embed=self.embed, metadata=self.metadata, team_key=self.team_key)
        self.assertIsNone(file)
        self.assertEqual(self.embed.thumbnail.url, "https://example.com/league.png")
        self.assertIn("Profit", logs.output[0])
        self.assertIn("http_403", logs.output[0])

    async def test_no_link_invalidates_cache_and_preserves_default(self) -> None:
        metadata = TeamRoleSheetMetadata("SILVER DIVISION S4", "Profit", None)
        with patch.object(logos, "load_team_logo_png", side_effect=TeamLogoLoadError("missing_link")) as loader, \
                self.assertLogs("bigness_league_bot.activity", level="WARNING"):
            self.assertIsNone(await logos.attach_team_change_logo(embed=self.embed, metadata=metadata,
                                                                  team_key=self.team_key))
        loader.assert_called_once_with(None, team_key=self.team_key)
        self.assertEqual(self.embed.thumbnail.url, "https://example.com/league.png")

    async def test_sender_publishes_both_card_and_logo_and_closes_files(self) -> None:
        card = discord.File(BytesIO(b"card"), filename="card.png")
        logo = discord.File(BytesIO(b"logo"), filename="team-logo.png")
        sender = delivery.TeamRoleChangeAnnouncementSender(bot=Mock(), deduplicator=Mock())
        channel = SimpleNamespace(send=AsyncMock(return_value="published"))
        with patch.object(delivery, "build_team_change_content", return_value="announcement"), \
                patch.object(delivery, "build_team_change_embed", return_value=(self.embed, card)), \
                patch.object(delivery, "_build_role_removal_description", return_value="description"), \
                patch.object(delivery, "attach_team_change_logo", new=AsyncMock(return_value=logo)) as attach:
            result = await sender._send_announcement(
                member=SimpleNamespace(id=1), team_role=SimpleNamespace(id=2), guild=SimpleNamespace(id=99),
                metadata=self.metadata, spec=TEAM_ROLE_SIGNING_SPEC, channel=channel,
            )
        attach.assert_awaited_once_with(embed=self.embed, metadata=self.metadata, team_key="99:2")
        self.assertEqual(result, "published")
        self.assertEqual(channel.send.await_args.kwargs["files"], [card, logo])
        self.assertNotIn("file", channel.send.await_args.kwargs)
        self.assertTrue(card.fp.closed)
        self.assertTrue(logo.fp.closed)

    async def test_sender_still_sends_logo_when_card_renderer_is_unavailable(self) -> None:
        logo = discord.File(BytesIO(b"logo"), filename="team-logo.png")
        sender = delivery.TeamRoleChangeAnnouncementSender(bot=Mock(), deduplicator=Mock())
        channel = SimpleNamespace(send=AsyncMock())
        with patch.object(delivery, "build_team_change_content", return_value="announcement"), \
                patch.object(delivery, "build_team_change_embed", return_value=(self.embed, None)), \
                patch.object(delivery, "_build_role_removal_description", return_value="description"), \
                patch.object(delivery, "attach_team_change_logo", new=AsyncMock(return_value=logo)):
            await sender._send_announcement(
                member=SimpleNamespace(id=1), team_role=SimpleNamespace(id=2), guild=Mock(),
                metadata=self.metadata, spec=TEAM_ROLE_SIGNING_SPEC, channel=channel,
            )
        self.assertIs(channel.send.await_args.kwargs["file"], logo)
        self.assertTrue(logo.fp.closed)


class AnnouncementDeduplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(delivery._inflight_announcement_keys.clear)

    def test_inflight_download_does_not_expire_announcement_reservation(self) -> None:
        deduplicator = delivery.TeamChangeAnnouncementDeduplicator()
        kwargs = dict(guild=SimpleNamespace(id=1, name="League"), member=SimpleNamespace(id=2),
                      team_role=SimpleNamespace(id=3, name="Profit"), spec=TEAM_ROLE_SIGNING_SPEC)
        with patch.object(delivery, "monotonic", return_value=0):
            key = deduplicator.reserve(**kwargs)
        with patch.object(delivery, "monotonic", return_value=20):
            self.assertIsNone(deduplicator.reserve(**kwargs))
            deduplicator.complete(key)
            self.assertIsNotNone(deduplicator.reserve(**kwargs))

    def test_separate_senders_cannot_duplicate_a_pending_announcement(self) -> None:
        first = delivery.TeamChangeAnnouncementDeduplicator()
        second = delivery.TeamChangeAnnouncementDeduplicator()
        kwargs = dict(guild=SimpleNamespace(id=1, name="League"), member=SimpleNamespace(id=2),
                      team_role=SimpleNamespace(id=3, name="Profit"), spec=TEAM_ROLE_SIGNING_SPEC)
        key = first.reserve(**kwargs)
        self.assertIsNone(second.reserve(**kwargs))
        first.release(key)
        self.assertIsNotNone(second.reserve(**kwargs))
