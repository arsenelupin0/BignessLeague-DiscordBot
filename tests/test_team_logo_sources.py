from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bigness_league_bot.infrastructure.images import team_logo_sources as sources
from bigness_league_bot.infrastructure.images import team_logos as logos
from tests.test_team_logo_images import png_bytes


class TeamLogoSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.catalog = self.directory / "sources.json"
        self.path = "/attachments/123/456/old-logo.png"
        self.file_id = "drive_logo_file_123"
        self.drive_url = f"https://drive.google.com/uc?export=download&id={self.file_id}"
        self.mapping = {"discord_attachment_path": self.path, "drive_file_id": self.file_id}
        self.catalog.write_text(json.dumps([self.mapping]), encoding="utf-8")

    def resolve(self, url: str) -> str:
        return sources.resolve_team_logo_source(url, catalog_path=self.catalog)

    def test_known_discord_attachment_recovers_from_drive_with_any_signature(self) -> None:
        for host in ("cdn.discordapp.com", "media.discordapp.net"):
            self.assertEqual(self.resolve(f"https://{host}{self.path}?ex=old&hm=expired"), self.drive_url)

    def test_new_attachment_and_unrelated_host_cannot_use_previous_recovery(self) -> None:
        for url in (f"https://cdn.discordapp.com{self.path.replace('/456/', '/789/')}",
                    f"https://example.com{self.path}", f"https://cdn.discordapp.com.evil.example{self.path}"):
            with self.subTest(url=url):
                self.assertEqual(self.resolve(url), url)

    def test_drive_viewer_open_and_download_urls_resolve_to_image_download(self) -> None:
        for url in (f"https://drive.google.com/file/d/{self.file_id}/view?usp=sharing",
                    f"https://drive.google.com/file/d/{self.file_id}/preview",
                    f"https://drive.google.com/open?id={self.file_id}", self.drive_url):
            with self.subTest(url=url):
                self.assertEqual(self.resolve(url), self.drive_url)

    def test_drive_resource_key_is_preserved(self) -> None:
        self.assertEqual(self.resolve(f"https://drive.google.com/file/d/{self.file_id}/view?resourcekey=abc"),
                         self.drive_url + "&resourcekey=abc")

    def test_folder_and_invalid_file_ids_are_not_guessed(self) -> None:
        for url in ("https://drive.google.com/drive/folders/123", "https://drive.google.com/open?id=../bad",
                    "https://drive.google.com.evil.example/file/d/drive_logo_file_123/view"):
            self.assertEqual(self.resolve(url), url)

    def test_missing_catalog_leaves_original_link(self) -> None:
        self.catalog.unlink()
        url = f"https://cdn.discordapp.com{self.path}"
        self.assertEqual(self.resolve(url), url)

    def test_invalid_or_ambiguous_catalog_does_not_select_a_logo(self) -> None:
        url = f"https://cdn.discordapp.com{self.path}"
        for content in ("{broken", "{}", '[null]', json.dumps([self.mapping, self.mapping]),
                        json.dumps([{**self.mapping, "drive_file_id": "../../outside"}])):
            with self.subTest(content=content):
                self.catalog.write_text(content, encoding="utf-8")
                with self.assertLogs("bigness_league_bot.activity", level="WARNING"):
                    self.assertEqual(self.resolve(url), url)

    def test_drive_viewer_download_is_cached_and_survives_outage(self) -> None:
        viewer = f"https://drive.google.com/file/d/{self.file_id}/view"
        content = png_bytes()
        with patch.object(logos, "_download_logo_png", return_value=content) as download:
            logos.load_team_logo_png(viewer, team_key="1:2", cache_directory=self.directory)
        download.assert_called_once_with(self.drive_url)
        with patch.object(logos, "CACHE_REFRESH_SECONDS", -1), \
                patch.object(logos, "_download_logo_png", side_effect=logos.TeamLogoLoadError("http_503")), \
                self.assertLogs("bigness_league_bot.activity", level="WARNING"):
            self.assertEqual(logos.load_team_logo_png(viewer, team_key="1:2", cache_directory=self.directory), content)

    def test_recovery_downloads_drive_instead_of_expired_discord_url_and_replaces_on_change(self) -> None:
        url = f"https://cdn.discordapp.com{self.path}?ex=old&hm=expired"
        content = png_bytes()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = content
        with patch.object(logos, "resolve_team_logo_source", side_effect=self.resolve), \
                patch.object(logos, "urlopen", return_value=response) as fetch:
            first = logos.load_team_logo_png(url, team_key="1:2", cache_directory=self.directory)
            self.assertEqual(first, content)
            self.assertEqual(fetch.call_args.args[0].full_url, self.drive_url)
            self.assertEqual(logos.load_team_logo_png(url, team_key="1:2", cache_directory=self.directory), first)
            fetch.assert_called_once()
            new_url = "https://example.com/replacement.png"
            response.read.return_value = b"not an image"
            with self.assertRaisesRegex(logos.TeamLogoLoadError, "invalid_image"):
                logos.load_team_logo_png(new_url, team_key="1:2", cache_directory=self.directory)
        self.assertEqual(list(self.directory.glob("team-*.png")), [])

    def test_production_catalog_covers_16_distinct_s4_attachments(self) -> None:
        entries = json.loads(sources.SOURCE_CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(len(entries), 16)
        self.assertEqual(len({e["discord_attachment_path"] for e in entries}), 16)
        self.assertEqual(len({e["drive_file_id"] for e in entries}), 16)
        for entry in entries:
            url = "https://cdn.discordapp.com" + entry["discord_attachment_path"]
            self.assertEqual(sources.resolve_team_logo_source(url),
                             f"https://drive.google.com/uc?export=download&id={entry['drive_file_id']}")
