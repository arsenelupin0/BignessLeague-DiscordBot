from __future__ import annotations

import hashlib
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from PIL import Image

from bigness_league_bot.infrastructure.images import team_logos as logos


def png_bytes(size: tuple[int, int] = (32, 16), color: tuple[int, int, int, int] = (20, 50, 80, 100)) -> bytes:
    output = BytesIO()
    with Image.new("RGBA", size, color) as image:
        image.save(output, format="PNG")
    return output.getvalue()


class TeamLogoImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name)
        self.url = "https://cdn.discordapp.com/attachments/1/2/Profit.png?backend=b2&ex=111&is=000&hm=first&"
        self.content = png_bytes()
        self.team_key = "guild-1:role-Profit"

    def response(self, content: bytes) -> Mock:
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = content
        return response

    def load(self, url: str | None = None, *, team_key: str | None = None) -> bytes:
        return logos.load_team_logo_png(url or self.url, team_key=team_key or self.team_key,
                                        cache_directory=self.cache)

    def test_signed_discord_url_is_preserved_and_logo_is_cached(self) -> None:
        response = self.response(self.content)
        with patch.object(logos, "urlopen", return_value=response) as fetch:
            first, second = self.load(), self.load()
        self.assertEqual(first, second)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0].full_url, self.url)
        self.assertEqual(fetch.call_args.kwargs["timeout"], logos.LOGO_TIMEOUT_SECONDS)
        response.read.assert_called_once_with(logos.MAX_LOGO_BYTES + 1)
        self.assertEqual(len(tuple(self.cache.glob("*.png"))), 1)

    def test_renewed_signature_uses_same_valid_cached_attachment(self) -> None:
        renewed = self.url.replace("ex=111", "ex=222").replace("hm=first", "hm=second")
        with patch.object(logos, "urlopen", return_value=self.response(self.content)) as fetch:
            self.assertEqual(self.load(), self.load(renewed))
        fetch.assert_called_once()

    def test_url_changes_replace_the_single_team_copy_immediately(self) -> None:
        with patch.object(logos, "urlopen", return_value=self.response(self.content)) as fetch:
            self.load()
            self.load(self.url.replace("/2/", "/3/"))
            self.load("https://example.com/logo?id=1")
            self.load("https://example.com/logo?id=2")
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual(len(tuple(self.cache.glob("*.png"))), 1)

    def test_valid_new_logo_replaces_old_pixels_and_persists_its_source(self) -> None:
        new_url = self.url.replace("/2/", "/3/")
        new_content = png_bytes(color=(200, 20, 30, 255))
        with patch.object(logos, "urlopen", return_value=self.response(self.content)):
            self.load()
        original_path = next(self.cache.glob("*.png"))
        with patch.object(logos, "urlopen", return_value=self.response(new_content)):
            self.load(new_url)
        self.assertEqual(list(self.cache.iterdir()), [original_path])
        with Image.open(original_path) as image:
            self.assertEqual(image.getpixel((0, 0)), (200, 20, 30, 255))
            self.assertEqual(image.info[logos.SOURCE_METADATA_KEY],
                             hashlib.sha256(logos._cache_identity(new_url).encode()).hexdigest())
        # A new call knows the current source from the PNG, even after restart.
        with patch.object(logos, "urlopen", side_effect=AssertionError("unexpected download")):
            self.load(new_url)

    def test_same_source_for_different_teams_does_not_mix_their_cache_records(self) -> None:
        with patch.object(logos, "urlopen", return_value=self.response(self.content)):
            self.load()
            self.load(team_key="guild-1:role-Taifa")
        self.assertEqual(len(tuple(self.cache.glob("team-*.png"))), 2)

    def test_invalid_new_source_deletes_previous_team_logo(self) -> None:
        with patch.object(logos, "urlopen", return_value=self.response(self.content)):
            self.load()
        path = next(self.cache.glob("*.png"))
        with patch.object(logos, "urlopen", return_value=self.response(b"<html>invalid</html>")), \
                self.assertRaisesRegex(logos.TeamLogoLoadError, "invalid_image"):
            self.load(self.url.replace("/2/", "/3/"))
        self.assertFalse(path.exists())
        self.assertEqual(list(self.cache.iterdir()), [])
        with patch.object(logos, "urlopen", return_value=self.response(self.content)) as fetch:
            self.load()
        fetch.assert_called_once()

    def test_failed_cache_write_does_not_leave_previous_logo_or_temporary_files(self) -> None:
        with patch.object(logos, "urlopen", return_value=self.response(self.content)):
            self.load()
        path = next(self.cache.glob("*.png"))
        new_content = png_bytes(color=(200, 20, 30, 255))
        with patch.object(logos, "urlopen", return_value=self.response(new_content)), \
                patch.object(Path, "replace", side_effect=OSError("write denied")), \
                self.assertLogs("bigness_league_bot.activity", level="WARNING"):
            displayed = self.load(self.url.replace("/2/", "/3/"))
        with Image.open(BytesIO(displayed)) as image:
            self.assertEqual(image.getpixel((0, 0)), (200, 20, 30, 255))
        self.assertFalse(path.exists())
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_missing_or_invalid_link_deletes_cached_logo_without_network_request(self) -> None:
        for url in (None, "", " ", "https://", "file:///old.png", "https://user:password@example.com/logo.png"):
            with self.subTest(url=url):
                with patch.object(logos, "urlopen", return_value=self.response(self.content)):
                    self.load()
                with patch.object(logos, "urlopen") as fetch, self.assertRaises(logos.TeamLogoLoadError):
                    logos.load_team_logo_png(url, team_key=self.team_key, cache_directory=self.cache)
                fetch.assert_not_called()
                self.assertEqual(list(self.cache.iterdir()), [])

    def test_failed_new_download_deletes_old_team_and_matching_legacy_copy(self) -> None:
        with patch.object(logos, "urlopen", return_value=self.response(self.content)):
            self.load()
        old_source = hashlib.sha256(logos._cache_identity(self.url).encode()).hexdigest()
        old_legacy = self.cache / f"{old_source}.png"
        old_legacy.write_bytes(self.content)
        error = HTTPError(self.url, 404, "Missing", {}, None)
        with patch.object(logos, "urlopen", side_effect=error), \
                self.assertRaisesRegex(logos.TeamLogoLoadError, "http_404"):
            self.load(self.url.replace("/2/", "/3/"))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_failed_refresh_deletes_expired_legacy_copy(self) -> None:
        source_key = hashlib.sha256(logos._cache_identity(self.url).encode()).hexdigest()
        legacy = self.cache / f"{source_key}.png"
        legacy.write_bytes(self.content)
        old = time.time() - logos.CACHE_REFRESH_SECONDS - 5
        os.utime(legacy, (old, old))
        error = HTTPError(self.url, 403, "Expired", {}, None)
        with patch.object(logos, "urlopen", side_effect=error), \
                self.assertRaisesRegex(logos.TeamLogoLoadError, "http_403"):
            self.load()
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_legacy_source_copy_is_migrated_and_deleted_without_removing_other_files(self) -> None:
        source_key = hashlib.sha256(logos._cache_identity(self.url).encode()).hexdigest()
        legacy = self.cache / f"{source_key}.png"
        legacy.write_bytes(self.content)
        unrelated = self.cache / f"{'f' * 64}.png"
        unrelated.write_bytes(self.content)
        with patch.object(logos, "urlopen", side_effect=AssertionError("unexpected download")):
            self.load()
        self.assertFalse(legacy.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(len(tuple(self.cache.glob("team-*.png"))), 1)

    def test_failed_migration_retains_the_legacy_image(self) -> None:
        source_key = hashlib.sha256(logos._cache_identity(self.url).encode()).hexdigest()
        legacy = self.cache / f"{source_key}.png"
        legacy.write_bytes(self.content)
        with patch.object(Path, "replace", side_effect=OSError("write denied")), \
                self.assertLogs("bigness_league_bot.activity", level="WARNING"):
            self.load()
        self.assertTrue(legacy.exists())
        self.assertEqual(list(self.cache.iterdir()), [legacy])

    def test_overlapping_old_and_new_downloads_leave_only_the_new_source(self) -> None:
        new_url = self.url.replace("/2/", "/3/")
        new_content = png_bytes(color=(200, 20, 30, 255))
        old_started, release_old = Event(), Event()

        def download(url: str) -> bytes:
            if url == self.url:
                old_started.set()
                if not release_old.wait(timeout=2):
                    raise AssertionError("old download timed out")
                return self.content
            return new_content

        with patch.object(logos, "_download_logo_png", side_effect=download), ThreadPoolExecutor(max_workers=2) as pool:
            old = pool.submit(self.load)
            try:
                self.assertTrue(old_started.wait(timeout=1))
                new = pool.submit(self.load, new_url)
            finally:
                release_old.set()
            old.result(timeout=3)
            new.result(timeout=3)
        paths = list(self.cache.iterdir())
        self.assertEqual(len(paths), 1)
        with Image.open(paths[0]) as image:
            self.assertEqual(image.getpixel((0, 0)), (200, 20, 30, 255))

    def test_failed_refresh_deletes_cached_logo_instead_of_serving_previous_pixels(self) -> None:
        with patch.object(logos, "urlopen", return_value=self.response(self.content)):
            self.load()
        for path in self.cache.glob("*.png"):
            old = time.time() - logos.CACHE_REFRESH_SECONDS - 5
            os.utime(path, (old, old))
        error = HTTPError(self.url, 403, "Expired", {}, None)
        with patch.object(logos, "urlopen", side_effect=error), \
                self.assertRaisesRegex(logos.TeamLogoLoadError, "http_403"):
            self.load()
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_expired_url_without_copy_reports_http_failure(self) -> None:
        with patch.object(logos, "urlopen", side_effect=HTTPError(self.url, 404, "Deleted", {}, None)), \
                self.assertRaisesRegex(logos.TeamLogoLoadError, "http_404"):
            self.load()

    def test_html_and_corrupt_image_are_rejected_and_not_cached(self) -> None:
        for content in (b"<!DOCTYPE html><html>Drive viewer</html>", self.content[:30]):
            with self.subTest(content=content), \
                    patch.object(logos, "urlopen", return_value=self.response(content)), \
                    self.assertRaisesRegex(logos.TeamLogoLoadError, "invalid_image"):
                self.load()
        self.assertEqual(tuple(self.cache.glob("*.png")), ())

    def test_oversized_input_and_dimensions_are_rejected(self) -> None:
        with self.assertRaisesRegex(logos.TeamLogoLoadError, "invalid_size"):
            logos._normalize_logo_png(b"x" * (logos.MAX_LOGO_BYTES + 1))
        with patch.object(logos, "MAX_LOGO_PIXELS", 100), \
                self.assertRaisesRegex(logos.TeamLogoLoadError, "invalid_dimensions"):
            logos._normalize_logo_png(self.content)

    def test_logo_is_scaled_and_transparency_is_preserved(self) -> None:
        normalized = logos._normalize_logo_png(png_bytes((512, 256)))
        with Image.open(BytesIO(normalized)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (256, 128))
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 100)

    def test_invalid_urls_are_rejected_before_any_network_request(self) -> None:
        with patch.object(logos, "urlopen") as fetch:
            for url in ("file:///etc/passwd", "https://", "https://user:password@example.com/logo.png"):
                with self.subTest(url=url), self.assertRaises(logos.TeamLogoLoadError):
                    self.load(url)
        fetch.assert_not_called()

    def test_unwritable_cache_does_not_discard_downloaded_logo(self) -> None:
        blocked = self.cache / "file"
        blocked.write_text("not a directory")
        with patch.object(logos, "urlopen", return_value=self.response(self.content)), \
                self.assertLogs("bigness_league_bot.activity", level="WARNING"):
            content = logos.load_team_logo_png(self.url, team_key=self.team_key, cache_directory=blocked)
        with Image.open(BytesIO(content)) as image:
            self.assertEqual(image.format, "PNG")

    def test_corrupt_cache_is_replaced_by_valid_download(self) -> None:
        with patch.object(logos, "urlopen", return_value=self.response(self.content)):
            self.load()
        path = next(self.cache.glob("*.png"))
        path.write_bytes(b"invalid")
        with patch.object(logos, "urlopen", return_value=self.response(self.content)) as fetch, \
                self.assertLogs("bigness_league_bot.activity", level="WARNING"):
            self.load()
        fetch.assert_called_once()
        with Image.open(path) as image:
            self.assertEqual(image.format, "PNG")
