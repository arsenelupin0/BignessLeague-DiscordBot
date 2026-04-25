#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import unicodedata

from bigness_league_bot.application.services.tickets import (
    get_ticket_category,
    normalize_ticket_category_key,
)

TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")
DEFAULT_CATEGORY_KEY = "general"
ENTRY_TEXT_EXCLUDED_KEYS = frozenset(
    {
        "id",
        "category",
        "title",
        "topic",
        "question",
        "question_examples",
        "answer",
        "bullets",
        "tags",
        "keywords",
        "related_commands",
        "requires_staff",
        "escalate_when",
        "audience",
        "confidence",
        "source_refs",
        "public_safe",
    }
)


@dataclass(frozen=True, slots=True)
class TicketAiKnowledgeEntry:
    entry_id: str
    category: str
    category_label: str
    title: str
    question: str
    answer: str
    tags: tuple[str, ...]
    keywords: tuple[str, ...]
    related_commands: tuple[str, ...]
    requires_staff: bool
    question_examples: tuple[str, ...]
    bullets: tuple[str, ...]
    escalate_when: tuple[str, ...]
    audience: tuple[str, ...]
    source_refs: tuple[str, ...]
    confidence_label: str
    public_safe: bool
    extra_text_blocks: tuple[str, ...]
    searchable_text: str
    searchable_tokens: frozenset[str]

    @classmethod
    def from_dict(
            cls,
            payload: dict[str, object],
            *,
            category_routing_hints: tuple[str, ...] = (),
    ) -> "TicketAiKnowledgeEntry":
        entry_id = _read_scalar_text(payload["id"])
        raw_category = _read_scalar_text(payload.get("category", DEFAULT_CATEGORY_KEY))
        category = _normalize_category_key(raw_category)
        category_label = _resolve_category_label(raw_category, category)
        title = _first_non_empty_string(
            payload.get("title"),
            payload.get("topic"),
            _humanize_identifier(entry_id),
        )
        question_examples = _read_string_tuple(payload.get("question_examples"))
        question = _first_non_empty_string(
            payload.get("question"),
            question_examples[0] if question_examples else None,
            "",
        )
        answer = _read_scalar_text(payload["answer"])
        tags = _read_string_tuple(payload.get("tags"))
        keywords = _read_string_tuple(payload.get("keywords"))
        related_commands = _read_string_tuple(payload.get("related_commands"))
        bullets = _read_string_tuple(payload.get("bullets"))
        escalate_when = _read_string_tuple(payload.get("escalate_when"))
        audience = _read_string_tuple(payload.get("audience"))
        source_refs = _read_nested_text_tuple(payload.get("source_refs"))
        confidence_label = _read_scalar_text(payload.get("confidence", "")).lower()
        public_safe = bool(payload.get("public_safe", True))
        requires_staff = _derive_requires_staff(
            payload=payload,
            category_key=category,
            escalate_when=escalate_when,
        )
        extra_text_blocks = _collect_additional_entry_text(payload)
        searchable_text = _build_searchable_text(
            category=category,
            category_label=category_label,
            title=title,
            question=question,
            answer=answer,
            tags=tags,
            keywords=keywords,
            related_commands=related_commands,
            question_examples=question_examples,
            bullets=bullets,
            escalate_when=escalate_when,
            audience=audience,
            source_refs=source_refs,
            confidence_label=confidence_label,
            category_routing_hints=category_routing_hints,
            extra_text_blocks=extra_text_blocks,
        )
        return cls(
            entry_id=entry_id,
            category=category,
            category_label=category_label,
            title=title,
            question=question,
            answer=answer,
            tags=tags,
            keywords=keywords,
            related_commands=related_commands,
            requires_staff=requires_staff,
            question_examples=question_examples,
            bullets=bullets,
            escalate_when=escalate_when,
            audience=audience,
            source_refs=source_refs,
            confidence_label=confidence_label,
            public_safe=public_safe,
            extra_text_blocks=extra_text_blocks,
            searchable_text=searchable_text,
            searchable_tokens=frozenset(_tokenize(searchable_text)),
        )


@dataclass(frozen=True, slots=True)
class TicketAiKnowledgeMatch:
    entry: TicketAiKnowledgeEntry
    score: int
    snippet: str


@dataclass(frozen=True, slots=True)
class TicketAiKnowledgeBase:
    entries: tuple[TicketAiKnowledgeEntry, ...]

    @classmethod
    def from_file(cls, path: Path) -> "TicketAiKnowledgeBase":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        raw_entries = payload.get("entries", [])
        if not isinstance(raw_entries, list):
            raise ValueError(f"La base de conocimiento `{path}` no contiene una lista `entries` válida.")

        category_routing_hints = _read_category_routing_hints(
            payload.get("category_routing_hints")
        )
        entries = tuple(
            TicketAiKnowledgeEntry.from_dict(
                raw_entry,
                category_routing_hints=category_routing_hints.get(
                    _normalize_category_key(
                        _read_scalar_text(raw_entry.get("category", DEFAULT_CATEGORY_KEY))
                    ),
                    (),
                ),
            )
            for raw_entry in raw_entries
            if isinstance(raw_entry, dict)
        )
        return cls(entries=entries)

    def search(
            self,
            *,
            query: str,
            category: str | None,
            limit: int,
            max_characters: int,
    ) -> tuple[TicketAiKnowledgeMatch, ...]:
        normalized_query = _normalize_text(query)
        query_tokens = frozenset(_tokenize(normalized_query))
        ranked_matches: list[TicketAiKnowledgeMatch] = []
        for entry in self.entries:
            score = _score_entry(
                entry=entry,
                normalized_query=normalized_query,
                query_tokens=query_tokens,
                category=category,
            )
            if score <= 0:
                continue

            ranked_matches.append(
                TicketAiKnowledgeMatch(
                    entry=entry,
                    score=score,
                    snippet=_build_entry_snippet(
                        entry=entry,
                        max_characters=max_characters,
                    ),
                )
            )

        ranked_matches.sort(
            key=lambda match: (
                -match.score,
                match.entry.requires_staff,
                match.entry.entry_id,
            )
        )
        return _select_balanced_matches(
            ranked_matches=ranked_matches,
            requested_category=category,
            limit=limit,
        )


def _read_string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()

    return tuple(
        normalized_item
        for item in value
        if (normalized_item := _read_scalar_text(item))
    )


def _read_nested_text_tuple(value: object) -> tuple[str, ...]:
    text_blocks = tuple(
        block
        for block in _collect_text_values(value)
        if block
    )
    return text_blocks


def _read_category_routing_hints(
        payload: object,
) -> dict[str, tuple[str, ...]]:
    if not isinstance(payload, Mapping):
        return {}

    hints_by_category: dict[str, tuple[str, ...]] = {}
    for raw_category, raw_hints in payload.items():
        normalized_category = _normalize_category_key(_read_scalar_text(raw_category))
        hints_by_category[normalized_category] = _read_nested_text_tuple(raw_hints)

    return hints_by_category


def _build_searchable_text(
        *,
        category: str,
        category_label: str,
        title: str,
        question: str,
        answer: str,
        tags: tuple[str, ...],
        keywords: tuple[str, ...],
        related_commands: tuple[str, ...],
        question_examples: tuple[str, ...],
        bullets: tuple[str, ...],
        escalate_when: tuple[str, ...],
        audience: tuple[str, ...],
        source_refs: tuple[str, ...],
        confidence_label: str,
        category_routing_hints: tuple[str, ...],
        extra_text_blocks: tuple[str, ...],
) -> str:
    parts = [
        category,
        category_label,
        title,
        question,
        answer,
        " ".join(tags),
        " ".join(keywords),
        " ".join(related_commands),
        " ".join(question_examples),
        " ".join(bullets),
        " ".join(escalate_when),
        " ".join(audience),
        " ".join(source_refs),
        confidence_label,
        " ".join(category_routing_hints),
        " ".join(extra_text_blocks),
    ]
    return "\n".join(
        part
        for part in parts
        if part
    )


def _score_entry(
        *,
        entry: TicketAiKnowledgeEntry,
        normalized_query: str,
        query_tokens: frozenset[str],
        category: str | None,
) -> int:
    score = 0
    if category is not None and entry.category == category:
        score += 20
    if entry.requires_staff:
        score += 2
    if entry.confidence_label == "high":
        score += 2
    elif entry.confidence_label == "medium":
        score += 1

    token_overlap = len(query_tokens & entry.searchable_tokens)
    score += token_overlap * 4

    for keyword in entry.keywords:
        if _normalize_text(keyword) in normalized_query:
            score += 10

    for tag in entry.tags:
        if _normalize_text(tag) in normalized_query:
            score += 6

    for related_command in entry.related_commands:
        if _normalize_text(related_command) in normalized_query:
            score += 8

    for question_example in entry.question_examples:
        if _normalize_text(question_example) in normalized_query:
            score += 6

    normalized_title = _normalize_text(entry.title)
    if normalized_title and normalized_title in normalized_query:
        score += 10

    return score


def _build_entry_snippet(
        *,
        entry: TicketAiKnowledgeEntry,
        max_characters: int,
) -> str:
    parts = [
        f"ID: {entry.entry_id}",
        f"Categoría: {entry.category_label}",
        f"Título: {entry.title}",
        f"Pregunta: {entry.question}" if entry.question else "",
        f"Respuesta: {entry.answer}",
        (
            "Ejemplos de pregunta:\n- " + "\n- ".join(entry.question_examples)
            if entry.question_examples
            else ""
        ),
        (
            "Puntos clave:\n- " + "\n- ".join(entry.bullets)
            if entry.bullets
            else ""
        ),
        (
            "Escalar cuando:\n- " + "\n- ".join(entry.escalate_when)
            if entry.escalate_when
            else ""
        ),
        f"Tags: {', '.join(entry.tags)}" if entry.tags else "",
        f"Comandos: {', '.join(entry.related_commands)}" if entry.related_commands else "",
        f"Audiencia: {', '.join(entry.audience)}" if entry.audience else "",
        f"Confianza documental: {entry.confidence_label}" if entry.confidence_label else "",
        f"Fuentes: {', '.join(entry.source_refs)}" if entry.source_refs else "",
        f"Requiere staff: {'si' if entry.requires_staff else 'no'}",
    ]
    snippet = "\n".join(
        part
        for part in parts
        if part
    )
    if len(snippet) <= max_characters:
        return snippet

    return f"{snippet[:max_characters].rstrip()}..."


def _normalize_text(value: str) -> str:
    normalized_value = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character
        for character in normalized_value
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.split())


def _tokenize(value: str) -> tuple[str, ...]:
    normalized_value = _normalize_text(value)
    tokens = TOKEN_PATTERN.findall(normalized_value)
    expanded_tokens: list[str] = []
    seen_tokens: set[str] = set()
    for token in tokens:
        if token not in seen_tokens:
            seen_tokens.add(token)
            expanded_tokens.append(token)
        if len(token) >= 7:
            token_stem = token[:6]
            if token_stem not in seen_tokens:
                seen_tokens.add(token_stem)
                expanded_tokens.append(token_stem)

    return tuple(expanded_tokens)


def _normalize_category_key(value: str) -> str:
    normalized_value = normalize_ticket_category_key(value)
    return normalized_value or DEFAULT_CATEGORY_KEY


def _resolve_category_label(
        raw_category: str,
        category_key: str,
) -> str:
    category = get_ticket_category(category_key)
    if category is not None:
        return category.label

    normalized_raw = raw_category.strip()
    if normalized_raw:
        return normalized_raw

    return category_key


def _first_non_empty_string(*values: object) -> str:
    for value in values:
        if normalized_value := _read_scalar_text(value):
            return normalized_value

    return ""


def _humanize_identifier(value: str) -> str:
    normalized_value = value.replace("_", " ").replace("-", " ").strip()
    if not normalized_value:
        return "Entrada de conocimiento"

    return normalized_value[:1].upper() + normalized_value[1:]


def _derive_requires_staff(
        *,
        payload: Mapping[str, object],
        category_key: str,
        escalate_when: tuple[str, ...],
) -> bool:
    if "requires_staff" in payload:
        return bool(payload.get("requires_staff"))

    if category_key == "appeals":
        return True

    return any(
        _normalize_text(rule).startswith("siempre")
        for rule in escalate_when
    )


def _collect_additional_entry_text(payload: Mapping[str, object]) -> tuple[str, ...]:
    blocks: list[str] = []
    for key, value in payload.items():
        if key in ENTRY_TEXT_EXCLUDED_KEYS:
            continue
        blocks.extend(_collect_text_values(value))

    seen: set[str] = set()
    unique_blocks: list[str] = []
    for block in blocks:
        normalized_block = block.strip()
        if not normalized_block or normalized_block in seen:
            continue
        seen.add(normalized_block)
        unique_blocks.append(normalized_block)

    return tuple(unique_blocks)


def _collect_text_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        normalized_value = value.strip()
        return (normalized_value,) if normalized_value else ()
    if isinstance(value, Mapping):
        blocks: list[str] = []
        for nested_value in value.values():
            blocks.extend(_collect_text_values(nested_value))
        return tuple(blocks)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        blocks = []
        for item in value:
            blocks.extend(_collect_text_values(item))
        return tuple(blocks)

    normalized_value = _read_scalar_text(value)
    return (normalized_value,) if normalized_value else ()


def _read_scalar_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    return ""


def _select_balanced_matches(
        *,
        ranked_matches: list[TicketAiKnowledgeMatch],
        requested_category: str | None,
        limit: int,
) -> tuple[TicketAiKnowledgeMatch, ...]:
    selected_matches = ranked_matches[:limit]
    if (
            requested_category is None
            or len(selected_matches) < 2
            or any(match.entry.category != requested_category for match in selected_matches)
    ):
        return tuple(selected_matches)

    alternative_category_match = next(
        (
            match
            for match in ranked_matches[limit:]
            if match.entry.category != requested_category
        ),
        None,
    )
    if alternative_category_match is None:
        return tuple(selected_matches)

    return tuple([*selected_matches[:-1], alternative_category_match])
