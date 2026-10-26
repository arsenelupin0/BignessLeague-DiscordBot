from __future__ import annotations

import json
import tempfile
import unittest
from functools import partial
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from PIL import Image

from bigness_league_bot.application.services.match_replay_models import MatchReplayDivision, MatchReplayReport
from bigness_league_bot.application.services.match_standings import MatchStandingRow
from bigness_league_bot.infrastructure.discord import match_summary_image_shared as shared
from bigness_league_bot.infrastructure.discord.match_replay_assets import team_logo_url_map
from bigness_league_bot.infrastructure.discord.match_replay_summary_images import build_match_replay_summary_image_file
from bigness_league_bot.infrastructure.discord.match_standings_images import build_match_standings_image_file
from bigness_league_bot.infrastructure.google.match_replay_rosters import list_division_team_logos_from_grids
from bigness_league_bot.infrastructure.google.team_sheets.models import SheetCell
from bigness_league_bot.infrastructure.images import team_logo_sources as sources
from bigness_league_bot.infrastructure.images import team_logos as logos


def png_bytes(color: tuple[int, int, int, int]) -> bytes:
    output = BytesIO()
    with Image.new("RGBA", (32, 32), color) as image:
        image.save(output, format="PNG")
    return output.getvalue()


class MatchSummaryLogoTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.cache = self.directory / "cache"
        self.catalog = self.directory / "sources.json"
        self.attachment_path = "/attachments/123/456/expired.png"
        self.expired_url = f"https://cdn.discordapp.com{self.attachment_path}?ex=old&hm=expired"
        self.drive_url = "https://drive.google.com/uc?export=download&id=drive_logo_file_123"
        self.viewer_url = "https://drive.google.com/file/d/drive_logo_file_456/view?usp=sharing"
        self.second_drive_url = "https://drive.google.com/uc?export=download&id=drive_logo_file_456"
        self.guild_url = "https://cdn.discordapp.com/icons/123/server.png"
        self.red = (220, 30, 40, 255)
        self.blue = (20, 50, 210, 255)
        self.green = (30, 200, 40, 255)
        self.remote = {
            self.drive_url: png_bytes(self.red),
            self.second_drive_url: png_bytes(self.blue),
            self.guild_url: png_bytes(self.green),
        }
        self.catalog.write_text(json.dumps([{
            "discord_attachment_path": self.attachment_path, "drive_file_id": "drive_logo_file_123",
        }]), encoding="utf-8")
        for patcher in (
                patch.object(shared, "load_team_logo_png",
                             partial(logos.load_team_logo_png, cache_directory=self.cache)),
                patch.object(logos, "resolve_team_logo_source", partial(
                    sources.resolve_team_logo_source, catalog_path=self.catalog,
                )),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        fetch_patcher = patch.object(logos, "urlopen", side_effect=self.open_url)
        self.fetch = fetch_patcher.start()
        self.addCleanup(fetch_patcher.stop)

    def open_url(self, request, **_kwargs):
        content = self.remote.get(request.full_url)
        if content is None:
            raise HTTPError(request.full_url, 404, "Not Found", None, None)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = content
        return response

    def load(self, url: str | None = None, *, team_name: str = "Equipo Uno", fallback: str | None = None):
        return shared._load_logo_image(Image, url, fallback, size=64, team_name=team_name)

    def logo_map_from_sheet(self, division_name: str) -> dict[str, str]:
        headers = ("Jugador", "Discord ID", "Platform", "Platform ID", "Epic Name", "MMR")
        grid = {
            0: {0: SheetCell("Equipo Uno", hyperlink=self.expired_url),
                7: SheetCell("Equipo Dos", hyperlink=self.viewer_url)},
            1: {start + i: SheetCell(header) for start in (0, 7) for i, header in enumerate(headers)},
        }
        return team_logo_url_map(list_division_team_logos_from_grids(division_name, ((division_name, grid),)))

    def test_standings_in_both_divisions_render_sheet_logos_instead_of_guild_icon(self) -> None:
        rows = tuple(MatchStandingRow(str(i), name, 0, 0, 0, 0, 0, 0, 0)
                     for i, name in enumerate(("Equipo Uno", "Equipo Dos"), 1))
        for division in MatchReplayDivision:
            with self.subTest(division=division):
                attachment = build_match_standings_image_file(
                    division_name=division.label, rows=rows,
                    team_logo_urls=self.logo_map_from_sheet(division.label), fallback_logo_url=self.guild_url,
                )
                try:
                    with Image.open(attachment.fp) as image:
                        self.assertEqual(image.size, (1600, 900))
                        self.assertEqual(image.getpixel((243, 280)), self.red[:3])
                        self.assertEqual(image.getpixel((243, 344)), self.blue[:3])
                finally:
                    attachment.close()
        self.assertEqual([call.args[0].full_url for call in self.fetch.call_args_list],
                         [self.drive_url, self.second_drive_url])

    def test_replay_summary_renders_both_recovered_logos(self) -> None:
        report = MatchReplayReport(MatchReplayDivision.GOLD, 1, 1, "Equipo Uno", "Equipo Dos", (), 0, 0, ())
        attachment = build_match_replay_summary_image_file(
            report=report, team_logo_urls=self.logo_map_from_sheet(report.division.label),
            fallback_logo_url=self.guild_url,
        )
        try:
            with Image.open(attachment.fp) as image:
                self.assertEqual(image.getpixel((110, 149)), self.red[:3])
                self.assertEqual(image.getpixel((1250, 149)), self.blue[:3])
        finally:
            attachment.close()
        self.assertEqual(self.fetch.call_count, 2)

    def test_same_source_cache_survives_refresh_failure(self) -> None:
        first = self.load(self.expired_url)
        self.remote.clear()
        with patch.object(logos, "CACHE_REFRESH_SECONDS", -1), \
                self.assertLogs("bigness_league_bot.activity", level="WARNING"):
            second = self.load(self.expired_url, fallback=self.guild_url)
        self.assertEqual(second.tobytes(), first.tobytes())
        self.assertEqual([call.args[0].full_url for call in self.fetch.call_args_list], [self.drive_url] * 2)

    def test_changed_source_replaces_cached_team_image(self) -> None:
        self.load(self.expired_url)
        result = self.load(self.viewer_url)
        self.assertEqual(result.getpixel((32, 32)), self.blue)
        self.assertEqual(len(list(self.cache.glob("team-*.png"))), 1)

    def test_failed_new_source_uses_guild_icon_without_previous_team_pixels(self) -> None:
        self.load(self.expired_url)
        with self.assertLogs(shared.LOGGER, level="INFO") as logs:
            result = self.load("https://example.test/missing.png?secret=hidden", fallback=self.guild_url)
        self.assertEqual(result.getpixel((32, 32)), self.green)
        self.assertIn("http_404", " ".join(logs.output))
        self.assertNotIn("secret=hidden", " ".join(logs.output))

    def test_invalid_image_uses_guild_icon(self) -> None:
        self.remote[self.drive_url] = b"<html>not an image</html>"
        with self.assertLogs(shared.LOGGER, level="INFO") as logs:
            result = self.load(self.expired_url, fallback=self.guild_url)
        self.assertEqual(result.getpixel((32, 32)), self.green)
        self.assertIn("invalid_image", " ".join(logs.output))

    def test_missing_link_uses_guild_icon_without_reusing_cached_team_image(self) -> None:
        self.load(self.expired_url)
        result = self.load(fallback=self.guild_url)
        self.assertEqual(result.getpixel((32, 32)), self.green)

    def test_missing_team_and_guild_images_allow_initials_fallback(self) -> None:
        self.remote.clear()
        with self.assertLogs(shared.LOGGER, level="INFO"):
            self.assertIsNone(self.load(self.expired_url, fallback=self.guild_url))
        self.assertIsNone(self.load())

    def test_unmapped_expired_attachment_cannot_inherit_recovered_logo_by_name(self) -> None:
        self.load(self.expired_url)
        new_url = self.expired_url.replace("/456/", "/789/")
        result = self.load(new_url, fallback=self.guild_url)
        self.assertEqual(result.getpixel((32, 32)), self.green)

    def test_regular_url_keeps_its_complete_query_when_downloading(self) -> None:
        url = "https://example.test/logo.png?backend=b2&ex=111&is=000&hm=signature"
        self.remote[url] = png_bytes(self.blue)
        self.assertEqual(self.load(url).getpixel((32, 32)), self.blue)
        self.assertEqual(self.fetch.call_args.args[0].full_url, url)


if __name__ == "__main__":
    unittest.main()
