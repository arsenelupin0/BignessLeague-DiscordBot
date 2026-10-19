from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bigness_league_bot.infrastructure.replays import runtime
from bigness_league_bot.infrastructure.replays.name_recovery import build_replay_name_reader


class BundledRuntimeTests(unittest.TestCase):
    def setUp(self):
        parent = (Path(__file__).resolve().parents[1] / "out/parser-runtime-tests").resolve()
        parent.mkdir(parents=True, exist_ok=True)
        temporary = TemporaryDirectory(dir=parent)
        self.root = Path(temporary.name).resolve()
        assert self.root.is_relative_to(parent)
        self.addCleanup(temporary.cleanup)
        self.target = self.root / runtime.executable_name()

    def test_fresh_checkout_prepares_parser_without_network(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network must not be used")):
            runtime.ensure_bundled_runtime(self.target)
        manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], runtime.VERSION)
        self.assertEqual(manifest["executable_sha256"], hashlib.sha256(self.target.read_bytes()).hexdigest())
        self.assertTrue((self.root / "LICENSE.txt").is_file())

    def test_current_cache_is_reused_and_changed_versions_are_rebuilt(self):
        runtime.ensure_bundled_runtime(self.target)
        with patch.object(runtime, "executable_from_archive", side_effect=AssertionError("unnecessary extraction")):
            runtime.ensure_bundled_runtime(self.target)
        manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        manifest["version"] = "old"
        (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        runtime.ensure_bundled_runtime(self.target)
        self.assertEqual(json.loads((self.root / "manifest.json").read_text())["version"], runtime.VERSION)

    def test_corrupt_local_executable_is_regenerated(self):
        runtime.ensure_bundled_runtime(self.target)
        expected = self.target.read_bytes()
        self.target.write_bytes(b"corrupted")
        runtime.ensure_bundled_runtime(self.target)
        self.assertEqual(self.target.read_bytes(), expected)

    def test_corrupt_bundle_never_writes_an_executable(self):
        with patch.object(runtime, "_read_bundled", side_effect=runtime.ReplayRuntimeError("bundle_checksum")):
            with self.assertRaises(runtime.ReplayRuntimeError):
                runtime.ensure_bundled_runtime(self.target)
        self.assertFalse(self.target.exists())

    def test_all_shipped_platform_archives_match_their_official_hashes(self):
        for (system, _), (suffix, digest) in runtime.ASSETS.items():
            with self.subTest(asset=suffix):
                data = runtime._read_bundled(f"rrrocket-{runtime.VERSION}-{suffix}", digest)
                binary = runtime.executable_from_archive(data, windows=system == "Windows")
                self.assertGreater(len(binary), 100_000)
        runtime._read_bundled("LICENSE.txt", runtime.LICENSE_SHA256)

    def test_default_reader_prepares_missing_managed_runtime_automatically(self):
        from types import SimpleNamespace
        target = self.root / "aa_var/tools/rrrocket" / runtime.executable_name()
        settings = SimpleNamespace(replay_name_parser_enabled=True, replay_name_parser_path=target,
                                   replay_name_parser_timeout_seconds=10)
        with patch("bigness_league_bot.infrastructure.replays.name_recovery.PROJECT_ROOT", self.root):
            reader = build_replay_name_reader(settings)
        self.assertIsNotNone(reader)
        self.assertTrue(target.is_file())
