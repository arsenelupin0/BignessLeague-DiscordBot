from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass

sys.modules.setdefault("discord", types.ModuleType("discord"))

from bigness_league_bot.application.services.tickets import (
    REGISTRATION_TICKET_CATEGORIES,
    require_ticket_category,
)
from bigness_league_bot.infrastructure.discord.tickets import resolve_forum_tag

EXPECTED_REGISTRATION_TAG_IDS = {
    "registration_league": 1541966369158078464,
    "registration_junior_cup": 1541966446060376104,
    "registration_cup": 1541966538393788486,
    "registration_extras": 1541966573777068092,
}


@dataclass(frozen=True, slots=True)
class _ForumTagStub:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class _ForumChannelStub:
    name: str
    available_tags: tuple[_ForumTagStub, ...]


class RegistrationTicketCategoryTests(unittest.TestCase):
    def test_registration_categories_keep_the_configured_tag_ids(self) -> None:
        configured_tag_ids = {
            category.key: category.forum_tag_id
            for category in REGISTRATION_TICKET_CATEGORIES
        }

        self.assertEqual(configured_tag_ids, EXPECTED_REGISTRATION_TAG_IDS)

    def test_registration_categories_are_available_to_persisted_tickets(self) -> None:
        for category in REGISTRATION_TICKET_CATEGORIES:
            self.assertIs(require_ticket_category(category.key), category)

        self.assertEqual(
            require_ticket_category("Bigness Extras").key,
            "registration_extras",
        )

    def test_registration_forum_tags_are_resolved_by_exact_id(self) -> None:
        forum_tags = tuple(
            _ForumTagStub(id=tag_id, name=f"Etiqueta {index}")
            for index, tag_id in enumerate(
                EXPECTED_REGISTRATION_TAG_IDS.values(),
                start=1,
            )
        )
        forum_channel = _ForumChannelStub(
            name="tickets",
            available_tags=forum_tags,
        )

        for category in REGISTRATION_TICKET_CATEGORIES:
            resolved_tag = resolve_forum_tag(forum_channel, category)
            self.assertEqual(resolved_tag.id, category.forum_tag_id)


if __name__ == "__main__":
    unittest.main()
