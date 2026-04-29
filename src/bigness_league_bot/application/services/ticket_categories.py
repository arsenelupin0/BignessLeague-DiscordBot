from __future__ import annotations

from dataclasses import dataclass

import unicodedata


@dataclass(frozen=True, slots=True)
class TicketCategory:
    key: str
    label: str
    tag_name: str
    emoji: str
    thread_prefix: str


TICKET_CATEGORIES: tuple[TicketCategory, ...] = (
    TicketCategory(
        key="general",
        label="Soporte general",
        tag_name="Soporte general",
        emoji="\U0001f6e0\ufe0f",
        thread_prefix="soporte-general",
    ),
    TicketCategory(
        key="competition",
        label="Competici\u00f3n Bigness League",
        tag_name="Competicion",
        emoji="\U0001f4dd",
        thread_prefix="competicion",
    ),
    TicketCategory(
        key="player_market",
        label="Mercado de jugadores",
        tag_name="Mercado",
        emoji="\U0001f680",
        thread_prefix="mercado",
    ),
    TicketCategory(
        key="stream",
        label="\u00bfQuieres hacer stream de tu partido?",
        tag_name="Streaming",
        emoji="\U0001f310",
        thread_prefix="stream",
    ),
    TicketCategory(
        key="appeals",
        label="Apelaciones, problemas con alg\u00fan equipo, jugador, etc",
        tag_name="Apelaciones",
        emoji="\U0001f4dc",
        thread_prefix="apelaciones",
    ),
    TicketCategory(
        key="bot",
        label="Bot de discord",
        tag_name="Bot",
        emoji="\U0001f916",
        thread_prefix="bot",
    ),
    TicketCategory(
        key="social",
        label="Social",
        tag_name="Social",
        emoji="\U0001f4f1",
        thread_prefix="social",
    ),
)
TICKET_CATEGORIES_BY_KEY: dict[str, TicketCategory] = {
    category.key: category
    for category in TICKET_CATEGORIES
}


def get_ticket_category(category_key: str) -> TicketCategory | None:
    return TICKET_CATEGORIES_BY_KEY.get(normalize_ticket_category_key(category_key))


def require_ticket_category(category_key: str) -> TicketCategory:
    category = get_ticket_category(category_key)
    if category is None:
        raise ValueError(f"Categor\u00eda de ticket no soportada: {category_key}")

    return category


def normalize_ticket_category_key(category_key: str) -> str:
    normalized_key = _normalize_ticket_category_lookup_key(category_key)
    return TICKET_CATEGORY_KEYS_BY_ALIAS.get(normalized_key, normalized_key)


def _normalize_ticket_category_lookup_key(value: str) -> str:
    normalized_value = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character
        for character in normalized_value
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.replace("_", " ").split())


TICKET_CATEGORY_KEYS_BY_ALIAS: dict[str, str] = {}
for _category in TICKET_CATEGORIES:
    for _alias in (
            _category.key,
            _category.label,
            _category.tag_name,
            _category.thread_prefix,
    ):
        TICKET_CATEGORY_KEYS_BY_ALIAS[_normalize_ticket_category_lookup_key(_alias)] = _category.key
