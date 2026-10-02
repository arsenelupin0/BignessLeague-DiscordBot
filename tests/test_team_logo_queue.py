from __future__ import annotations

import asyncio
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from bigness_league_bot.infrastructure.images import team_logos as logos


class TeamLogoQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_more_than_ten_seconds_for_a_worker_does_not_discard_logo(self) -> None:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        started = asyncio.Event()
        release = Event()

        def occupy_worker() -> None:
            loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=15):
                raise TimeoutError("test worker was not released")

        busy = asyncio.create_task(asyncio.to_thread(occupy_worker))
        await asyncio.wait_for(started.wait(), timeout=1)
        with patch.object(logos, "load_team_logo_png", return_value=b"validated logo") as loader:
            queued = asyncio.create_task(logos.load_team_logo_png_async(
                "https://example.com/Profit.png", team_key="1:30",
            ))
            try:
                # The old global timeout expired here before the HTTP call began.
                await asyncio.sleep(10.1)
                self.assertFalse(queued.done())
                loader.assert_not_called()
                release.set()
                self.assertEqual(await asyncio.wait_for(queued, timeout=2), b"validated logo")
                loader.assert_called_once_with("https://example.com/Profit.png", team_key="1:30")
            finally:
                release.set()
                await busy
                if not queued.done():
                    queued.cancel()
                    await asyncio.gather(queued, return_exceptions=True)

    async def test_actual_download_failure_is_reported_after_worker_starts(self) -> None:
        with patch.object(logos, "load_team_logo_png", side_effect=logos.TeamLogoLoadError("http_404")):
            with self.assertRaisesRegex(logos.TeamLogoLoadError, "http_404"):
                await logos.load_team_logo_png_async("https://example.com/Profit.png", team_key="1:30")
