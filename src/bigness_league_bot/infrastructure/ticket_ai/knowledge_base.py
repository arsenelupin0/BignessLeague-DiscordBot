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
from dataclasses import dataclass
from pathlib import Path

import unicodedata

TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")


@dataclass(frozen=True, slots=True)
class TicketAiKnowledgeEntry:
    entry_id: str
    category: str
    title: str
    question: str
    answer: str
    tags: tuple[str, ...]
    keywords: tuple[str, ...]
    related_commands: tuple[str, ...]
    requires_staff: bool
    searchable_text: str
    searchable_tokens: frozenset[str]

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "TicketAiKnowledgeEntry":
        entry_id = str(payload["id"]).strip()
        category = str(payload.get("category", "general")).strip() or "general"
        title = str(payload["title"]).strip()
        question = str(payload.get("question", "")).strip()
        answer = str(payload["answer"]).strip()
        tags = _read_string_tuple(payload.get("tags"))
        keywords = _read_string_tuple(payload.get("keywords"))
        related_commands = _read_string_tuple(payload.get("related_commands"))
        requires_staff = bool(payload.get("requires_staff", False))
        searchable_text = _build_searchable_text(
            category=category,
            title=title,
            question=question,
            answer=answer,
            tags=tags,
            keywords=keywords,
            related_commands=related_commands,
        )
        return cls(
            entry_id=entry_id,
            category=category,
            title=title,
            question=question,
            answer=answer,
            tags=tags,
            keywords=keywords,
            related_commands=related_commands,
            requires_staff=requires_staff,
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
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_entries = payload.get("entries", [])
        if not isinstance(raw_entries, list):
            raise ValueError(f"La base de conocimiento `{path}` no contiene una lista `entries` valida.")

        entries = tuple(
            TicketAiKnowledgeEntry.from_dict(raw_entry)
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
        return tuple(ranked_matches[:limit])


def _read_string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()

    return tuple(
        str(item).strip()
        for item in value
        if str(item).strip()
    )


def _build_searchable_text(
        *,
        category: str,
        title: str,
        question: str,
        answer: str,
        tags: tuple[str, ...],
        keywords: tuple[str, ...],
        related_commands: tuple[str, ...],
) -> str:
    parts = [
        category,
        title,
        question,
        answer,
        " ".join(tags),
        " ".join(keywords),
        " ".join(related_commands),
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

    return score


def _build_entry_snippet(
        *,
        entry: TicketAiKnowledgeEntry,
        max_characters: int,
) -> str:
    parts = [
        f"ID: {entry.entry_id}",
        f"Categoria: {entry.category}",
        f"Titulo: {entry.title}",
        f"Pregunta: {entry.question}" if entry.question else "",
        f"Respuesta: {entry.answer}",
        f"Tags: {', '.join(entry.tags)}" if entry.tags else "",
        f"Comandos: {', '.join(entry.related_commands)}" if entry.related_commands else "",
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
    return tuple(TOKEN_PATTERN.findall(normalized_value))
