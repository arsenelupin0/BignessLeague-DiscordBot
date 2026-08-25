from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.modules.setdefault("discord", types.ModuleType("discord"))

from bigness_league_bot.application.services.tickets import TicketRecord
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore


def _create_ticket(**overrides: object) -> TicketRecord:
    values: dict[str, object] = {
        "ticket_number": 1,
        "user_id": 10,
        "thread_id": 20,
        "forum_channel_id": 30,
        "category_key": "general",
        "created_at": "2026-08-25T08:00:00+00:00",
    }
    values.update(overrides)
    return TicketRecord.create(**values)  # type: ignore[arg-type]


class TicketRecordInactivityTests(unittest.TestCase):
    def test_new_tickets_disable_inactivity_reminders_by_default(self) -> None:
        record = _create_ticket()

        self.assertFalse(record.inactivity_reminders_enabled)
        self.assertFalse(record.to_dict()["inactivity_reminders_enabled"])

    def test_legacy_ticket_payload_keeps_reminders_enabled(self) -> None:
        payload = _create_ticket().to_dict()
        payload.pop("inactivity_reminders_enabled")

        record = TicketRecord.from_dict(payload)

        self.assertTrue(record.inactivity_reminders_enabled)

    def test_enabling_reminders_restarts_inactivity_window_and_counter(self) -> None:
        record = _create_ticket().mark_inactivity_notice(
            sent_at="2026-08-25T09:00:00+00:00"
        )

        updated = record.set_inactivity_reminders_enabled(
            True,
            occurred_at="2026-08-25T10:00:00+00:00",
        )

        self.assertTrue(updated.inactivity_reminders_enabled)
        self.assertEqual(updated.last_activity_at, "2026-08-25T10:00:00+00:00")
        self.assertEqual(updated.inactivity_notice_count, 0)

    def test_ticket_creation_accepts_enabled_default(self) -> None:
        record = _create_ticket(inactivity_reminders_enabled=True)

        self.assertTrue(record.inactivity_reminders_enabled)


class TicketStateStoreDefaultTests(unittest.TestCase):
    def test_default_is_disabled_for_a_new_state_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = TicketStateStore(Path(temporary_directory) / "tickets.json")

            self.assertFalse(store.default_inactivity_reminders_enabled)

    def test_default_setting_is_persisted_and_reloaded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "tickets.json"
            store = TicketStateStore(state_path)
            store.add(_create_ticket())

            changed = store.set_default_inactivity_reminders_enabled(True)
            reloaded_store = TicketStateStore(state_path)
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            existing_record = reloaded_store.active_for_thread(20)

            self.assertTrue(changed)
            self.assertTrue(reloaded_store.default_inactivity_reminders_enabled)
            self.assertTrue(payload["default_inactivity_reminders_enabled"])
            self.assertIsNotNone(existing_record)
            assert existing_record is not None
            self.assertFalse(existing_record.inactivity_reminders_enabled)

    def test_legacy_store_payload_keeps_default_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "tickets.json"
            state_path.write_text(
                json.dumps({"version": 6, "tickets": []}),
                encoding="utf-8",
            )

            store = TicketStateStore(state_path)

            self.assertFalse(store.default_inactivity_reminders_enabled)


if __name__ == "__main__":
    unittest.main()
