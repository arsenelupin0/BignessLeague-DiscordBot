from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bigness_league_bot.core.environment import load_environment


class EnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def write(self, name: str, content: str) -> None:
        (self.root / name).write_text(content, encoding="utf-8")

    def test_process_selects_production_despite_local_development_selector(self) -> None:
        self.write(".env", "BOT_ENV=development\nDISCORD_TOKEN=local-secret\n")
        self.write(".env.production", "BOT_ENV=production\nSHEETS=OFFICIAL\nCHANNEL=2\n")
        os.environ["BOT_ENV"] = "production"
        self.assertEqual(load_environment(self.root), "production")
        self.assertEqual(os.environ["BOT_ENV"], "production")
        self.assertEqual(os.environ["SHEETS"], "OFFICIAL")
        self.assertEqual(os.environ["CHANNEL"], "2")
        self.assertEqual(os.environ["DISCORD_TOKEN"], "local-secret")

    def test_explicit_process_values_override_both_files(self) -> None:
        self.write(".env", "BOT_ENV=development\nDISCORD_TOKEN=base\n")
        self.write(".env.production", "SHEETS=OFFICIAL\n")
        os.environ.update(BOT_ENV="production", DISCORD_TOKEN="service")
        load_environment(self.root)
        self.assertEqual(os.environ["DISCORD_TOKEN"], "service")
        self.assertEqual(os.environ["SHEETS"], "OFFICIAL")

    def test_local_file_can_select_production_and_override_profile(self) -> None:
        self.write(".env", "BOT_ENV=production\nSHEETS=CUSTOM\nPREFIX=!\n")
        self.write(".env.production", "SHEETS=OFFICIAL\n")
        self.assertEqual(load_environment(self.root), "production")
        self.assertEqual(os.environ["SHEETS"], "CUSTOM")
        self.assertEqual(os.environ["PREFIX"], "!")

    def test_development_uses_its_selected_file(self) -> None:
        self.write(".env", "BOT_ENV=development\nDISCORD_TOKEN=local-secret\n")
        self.write(".env.development", "SHEETS=TEST\n")
        self.write(".env.production", "SHEETS=OFFICIAL\n")
        self.assertEqual(load_environment(self.root), "development")
        self.assertEqual(os.environ["SHEETS"], "TEST")

    def test_no_selector_defaults_to_development(self) -> None:
        self.write(".env.development", "SHEETS=TEST\n")
        self.assertEqual(load_environment(self.root), "development")
        self.assertEqual(os.environ["SHEETS"], "TEST")

    def test_selected_file_cannot_switch_environment(self) -> None:
        os.environ["BOT_ENV"] = " Production "
        self.write(".env.production", "BOT_ENV=development\nSHEETS=OFFICIAL\n")
        self.assertEqual(load_environment(self.root), "production")
        self.assertEqual(os.environ["BOT_ENV"], "production")
        self.assertEqual(os.environ["SHEETS"], "OFFICIAL")

    def test_missing_selected_file_keeps_base_values(self) -> None:
        self.write(".env", "BOT_ENV=production\nSHEETS=OFFICIAL\n")
        load_environment(self.root)
        self.assertEqual(os.environ["SHEETS"], "OFFICIAL")

    def test_production_keeps_all_private_credentials_from_untracked_base(self) -> None:
        self.write(".env", "BOT_ENV=development\nDISCORD_TOKEN=discord-secret\n"
                           "BOT_BALLCHASING_API_TOKEN=ballchasing-secret\nBOT_TICKET_AI_API_KEY=ai-secret\n")
        self.write(".env.production", "BOT_ENV=production\nSHEETS=OFFICIAL\n")
        os.environ["BOT_ENV"] = "production"
        load_environment(self.root)
        self.assertEqual(os.environ["DISCORD_TOKEN"], "discord-secret")
        self.assertEqual(os.environ["BOT_BALLCHASING_API_TOKEN"], "ballchasing-secret")
        self.assertEqual(os.environ["BOT_TICKET_AI_API_KEY"], "ai-secret")
        self.assertEqual(os.environ["SHEETS"], "OFFICIAL")

    def test_versioned_profiles_list_credentials_with_empty_placeholders(self) -> None:
        from dotenv import dotenv_values

        project_root = Path(__file__).resolve().parents[1]
        private_keys = {"DISCORD_TOKEN", "BOT_BALLCHASING_API_TOKEN", "BOT_TICKET_AI_API_KEY"}
        for name in (".env.production", ".env.development"):
            with self.subTest(file=name):
                values = dotenv_values(project_root / name)
                self.assertTrue(private_keys <= values.keys())
                for key in private_keys:
                    self.assertTrue(values[key] == "", msg=f"{name}: {key} debe ser un placeholder vacío")

    def test_local_credentials_override_matching_keys_in_both_profiles(self) -> None:
        self.write(".env", "DISCORD_TOKEN=local-discord\nBOT_BALLCHASING_API_TOKEN=local-ballchasing\n"
                           "BOT_TICKET_AI_API_KEY=local-ai\n")
        self.write(".env.production", "DISCORD_TOKEN=\nBOT_BALLCHASING_API_TOKEN=\nBOT_TICKET_AI_API_KEY=\n")
        self.write(".env.development", "DISCORD_TOKEN=template-discord\n"
                                       "BOT_BALLCHASING_API_TOKEN=template-ballchasing\nBOT_TICKET_AI_API_KEY=template-ai\n")
        for environment in ("production", "development"):
            with self.subTest(environment=environment), patch.dict(os.environ, {"BOT_ENV": environment}, clear=True):
                load_environment(self.root)
                self.assertEqual(os.environ["DISCORD_TOKEN"], "local-discord")
                self.assertEqual(os.environ["BOT_BALLCHASING_API_TOKEN"], "local-ballchasing")
                self.assertEqual(os.environ["BOT_TICKET_AI_API_KEY"], "local-ai")

    def test_explicit_empty_local_value_also_overrides_profile(self) -> None:
        self.write(".env", "BOT_ENV=production\nBOT_TICKET_AI_API_KEY=\n")
        self.write(".env.production", "BOT_TICKET_AI_API_KEY=template-key\n")
        load_environment(self.root)
        self.assertEqual(os.environ["BOT_TICKET_AI_API_KEY"], "")

    def test_systemd_uses_python_loader_with_local_overrides_and_production_profile(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        service = (project_root / "aa_deploy" / "bigness-league.service").read_text(encoding="utf-8")
        self.assertFalse(any(line.startswith("EnvironmentFile=") for line in service.splitlines()))
        self.assertIn("Environment=BOT_ENV=production", service.splitlines())
        self.write(".env", "BOT_ENV=development\nCHANNEL=3\nDISCORD_TOKEN=private-token\n")
        self.write(".env.production", "BOT_ENV=production\nSHEETS=OFFICIAL\nCHANNEL=2\n")
        os.environ["BOT_ENV"] = "production"
        load_environment(self.root)
        self.assertEqual(os.environ["BOT_ENV"], "production")
        self.assertEqual(os.environ["SHEETS"], "OFFICIAL")
        self.assertEqual(os.environ["CHANNEL"], "3")
        self.assertEqual(os.environ["DISCORD_TOKEN"], "private-token")

    def test_local_channel_and_timeout_override_either_profile(self) -> None:
        self.write(".env", "BOT_TEAM_ROLE_REMOVAL_ANNOUNCEMENT_CHANNEL_ID=42\n"
                           "BOT_BALLCHASING_REQUEST_TIMEOUT_SECONDS=15\n")
        self.write(".env.production", "BOT_TEAM_ROLE_REMOVAL_ANNOUNCEMENT_CHANNEL_ID=2\n"
                                      "BOT_BALLCHASING_REQUEST_TIMEOUT_SECONDS=8\n")
        self.write(".env.development", "BOT_TEAM_ROLE_REMOVAL_ANNOUNCEMENT_CHANNEL_ID=1\n"
                                       "BOT_BALLCHASING_REQUEST_TIMEOUT_SECONDS=5\n")
        for environment in ("production", "development"):
            with self.subTest(environment=environment), patch.dict(os.environ, {"BOT_ENV": environment}, clear=True):
                load_environment(self.root)
                self.assertEqual(os.environ["BOT_TEAM_ROLE_REMOVAL_ANNOUNCEMENT_CHANNEL_ID"], "42")
                self.assertEqual(os.environ["BOT_BALLCHASING_REQUEST_TIMEOUT_SECONDS"], "15")

    def test_example_file_is_never_loaded(self) -> None:
        self.write(".env", "DISCORD_TOKEN=private-token\n")
        self.write(".env.development", "CHANNEL=1\n")
        self.write(".env.example", "DISCORD_TOKEN=example-token\nCHANNEL=999\n")
        load_environment(self.root)
        self.assertEqual(os.environ["DISCORD_TOKEN"], "private-token")
        self.assertEqual(os.environ["CHANNEL"], "1")

    def test_local_values_can_reference_selected_profile_defaults(self) -> None:
        self.write(".env.production", "CHANNEL=2\n")
        self.write(".env", "BOT_ENV=production\nCUSTOM_CHANNEL=${CHANNEL}\n")
        load_environment(self.root)
        self.assertEqual(os.environ["CUSTOM_CHANNEL"], "2")
