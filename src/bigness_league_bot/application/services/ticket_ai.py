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

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.ticket_ai.knowledge_base import (
    TicketAiKnowledgeBase,
    TicketAiKnowledgeMatch,
)
from bigness_league_bot.infrastructure.ticket_ai.ollama import OllamaClient
from bigness_league_bot.infrastructure.ticket_ai.ollama import (
    OllamaClientError,
)
from bigness_league_bot.infrastructure.ticket_ai.openai_compatible import (
    OpenAiCompatibleChatMessage,
    OpenAiCompatibleClient,
)

ConversationRole = Literal["user", "staff", "assistant"]


class TicketAiChatClient(Protocol):
    async def chat_json(
            self,
            *,
            messages: tuple[object, ...],
            json_schema: dict[str, object],
    ) -> dict[str, object]:
        ...

    async def ping(self) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class TicketAiConversationTurn:
    role: ConversationRole
    content: str


@dataclass(frozen=True, slots=True)
class TicketAiReply:
    answer: str
    confidence: int
    should_escalate: bool
    reason: str
    used_entry_ids: tuple[str, ...]
    retrieved_matches: tuple[TicketAiKnowledgeMatch, ...]


class TicketAiService:
    def __init__(
            self,
            *,
            settings: Settings,
            ai_client: TicketAiChatClient,
            knowledge_base: TicketAiKnowledgeBase,
            system_prompt: str,
    ) -> None:
        self.settings = settings
        self.ai_client = ai_client
        self.knowledge_base = knowledge_base
        self.system_prompt = system_prompt.strip()

    @classmethod
    def from_settings(cls, settings: Settings) -> "TicketAiService | None":
        if not settings.ticket_ai_enabled:
            return None

        knowledge_base = TicketAiKnowledgeBase.from_file(
            settings.ticket_ai_knowledge_base_file
        )
        system_prompt = _load_prompt(settings.ticket_ai_system_prompt_file)
        ai_client = create_ticket_ai_chat_client(settings)
        return cls(
            settings=settings,
            ai_client=ai_client,
            knowledge_base=knowledge_base,
            system_prompt=system_prompt,
        )

    def can_auto_reply(self, category_key: str) -> bool:
        if not self.settings.ticket_ai_auto_reply_enabled:
            return False

        return category_key in self.settings.ticket_ai_autoreply_categories

    async def generate_reply(
            self,
            *,
            category_key: str,
            latest_user_message: str,
            conversation: tuple[TicketAiConversationTurn, ...],
    ) -> TicketAiReply:
        matches = self.knowledge_base.search(
            query=latest_user_message,
            category=category_key,
            limit=self.settings.ticket_ai_max_knowledge_matches,
            max_characters=self.settings.ticket_ai_max_knowledge_characters,
        )
        prompt_messages = (
            self._build_message(
                role="system",
                content=self.system_prompt,
            ),
            self._build_message(
                role="user",
                content=_build_model_input(
                    category_key=category_key,
                    latest_user_message=latest_user_message,
                    conversation=conversation[-self.settings.ticket_ai_max_context_messages:],
                    matches=matches,
                ),
            ),
        )
        response_payload = await self.ai_client.chat_json(
            messages=prompt_messages,
            json_schema=_ticket_ai_json_schema(),
        )
        return _parse_ticket_ai_reply(
            payload=response_payload,
            retrieved_matches=matches,
            category_key=category_key,
        )

    async def ping(self) -> bool:
        return await self.ai_client.ping()

    def _build_message(
            self,
            *,
            role: str,
            content: str,
    ) -> object:
        if self.settings.ticket_ai_provider == "openai_compatible":
            return OpenAiCompatibleChatMessage(
                role=role,
                content=content,
            )

        from bigness_league_bot.infrastructure.ticket_ai.ollama import OllamaChatMessage

        return OllamaChatMessage(
            role=role,
            content=content,
        )


def create_ticket_ai_chat_client(settings: Settings) -> TicketAiChatClient:
    if settings.ticket_ai_provider == "openai_compatible":
        return OpenAiCompatibleClient(
            base_url=settings.ticket_ai_base_url,
            api_key=settings.ticket_ai_api_key,
            model=settings.ticket_ai_model,
            timeout_seconds=settings.ticket_ai_request_timeout_seconds,
            temperature=settings.ticket_ai_temperature,
            max_output_tokens=settings.ticket_ai_max_output_tokens,
        )

    return OllamaClient(
        base_url=settings.ticket_ai_base_url,
        model=settings.ticket_ai_model,
        timeout_seconds=settings.ticket_ai_request_timeout_seconds,
        keep_alive=settings.ticket_ai_keep_alive,
        temperature=settings.ticket_ai_temperature,
    )


def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _build_model_input(
        *,
        category_key: str,
        latest_user_message: str,
        conversation: tuple[TicketAiConversationTurn, ...],
        matches: tuple[TicketAiKnowledgeMatch, ...],
) -> str:
    conversation_blocks = [
        f"- {turn.role}: {turn.content.strip()}"
        for turn in conversation
        if turn.content.strip()
    ]
    knowledge_blocks = [
        match.snippet
        for match in matches
    ]
    if not knowledge_blocks:
        knowledge_blocks.append("Sin resultados relevantes en la base de conocimiento.")

    return "\n\n".join(
        [
            f"Categoria del ticket: {category_key}",
            f"Ultimo mensaje del usuario:\n{latest_user_message.strip()}",
            (
                "Contexto reciente del ticket:\n"
                + "\n".join(conversation_blocks)
                if conversation_blocks
                else "Contexto reciente del ticket:\n- (sin mensajes previos)"
            ),
            "Base de conocimiento recuperada:\n" + "\n\n".join(knowledge_blocks),
        ]
    )


def _ticket_ai_json_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "confidence": {"type": "integer"},
            "should_escalate": {"type": "boolean"},
            "reason": {"type": "string"},
            "used_entry_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "answer",
            "confidence",
            "should_escalate",
            "reason",
            "used_entry_ids",
        ],
    }


def _parse_ticket_ai_reply(
        *,
        payload: dict[str, object],
        retrieved_matches: tuple[TicketAiKnowledgeMatch, ...],
        category_key: str,
) -> TicketAiReply:
    answer = str(payload.get("answer", "")).strip()
    if not answer:
        raise OllamaClientError("La IA local no ha devuelto un texto de respuesta.")

    confidence_raw = payload.get("confidence", 0)
    try:
        confidence = max(0, min(100, int(confidence_raw)))
    except (TypeError, ValueError) as exc:
        raise OllamaClientError("La IA local ha devuelto una confianza invalida.") from exc

    should_escalate = bool(payload.get("should_escalate", False))
    reason = str(payload.get("reason", "")).strip() or "Sin motivo especificado."
    used_entry_ids_raw = payload.get("used_entry_ids", [])
    if isinstance(used_entry_ids_raw, list):
        used_entry_ids = tuple(
            str(item).strip()
            for item in used_entry_ids_raw
            if str(item).strip()
        )
    else:
        used_entry_ids = ()

    if any(
            match.entry.requires_staff
            and (
                    match.entry.entry_id in used_entry_ids
                    or match.entry.category == category_key
            )
            for match in retrieved_matches
    ):
        should_escalate = True

    return TicketAiReply(
        answer=answer,
        confidence=confidence,
        should_escalate=should_escalate,
        reason=reason,
        used_entry_ids=used_entry_ids,
        retrieved_matches=retrieved_matches,
    )
